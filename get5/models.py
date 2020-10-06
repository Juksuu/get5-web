from get5 import app, db, cache
import countries
import logos
import util

from flask import url_for, Markup
from collections import OrderedDict
import requests

import datetime
import string
import random
import json
import re

dbKey = app.config['DATABASE_KEY']


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    steam_id = db.Column(db.String(40), unique=True)
    name = db.Column(db.String(40))
    admin = db.Column(db.Boolean, default=False)
    super_admin = db.Column(db.Boolean, default=False)
    servers = db.relationship('GameServer', backref='user', lazy='dynamic')
    teams = db.relationship('Team', backref='user', lazy='dynamic')
    matches = db.relationship('Match', backref='user', lazy='dynamic')
    seasons = db.relationship('Season', backref='user', lazy='dynamic')

    @staticmethod
    def get_or_create(steam_id):
        rv = User.query.filter_by(steam_id=steam_id).first()
        if rv is None:
            rv = User()
            rv.steam_id = steam_id
            db.session.add(rv)
            app.logger.info('Creating user for {}'.format(steam_id))

        rv.admin = ('ADMIN_IDS' in app.config) and (
            steam_id in app.config['ADMIN_IDS'])
        rv.super_admin = ('SUPER_ADMIN_IDS' in app.config) and (
            steam_id in app.config['SUPER_ADMIN_IDS'])
        return rv

    def get_url(self):
        return url_for('user', userid=self.id)

    def get_steam_url(self):
        return 'http://steamcommunity.com/profiles/{}'.format(self.steam_id)

    def get_recent_matches(self, limit=10):
        return self.matches.filter_by(cancelled=False).limit(limit)

    def __repr__(self):
        return 'User(id={}, steam_id={}, name={}, admin={}, super_admin={})'.format(
            self.id, self.steam_id, self.name, self.admin, self.super_admin)


class GameServer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    display_name = db.Column(db.String(32), default='')
    ip_string = db.Column(db.String(32))
    port = db.Column(db.Integer)
    rcon_password = db.Column(db.String(128))
    in_use = db.Column(db.Boolean, default=False)
    public_server = db.Column(db.Boolean, default=False, index=True)

    @staticmethod
    def create(user, display_name, ip_string, port, rcon_password, public_server):
        rv = GameServer()
        rv.user_id = user.id
        rv.display_name = display_name
        rv.ip_string = ip_string
        rv.port = port
        rv.rcon_password = rcon_password
        rv.public_server = public_server
        db.session.add(rv)
        return rv

    def send_rcon_command(self, command, raise_errors=False, num_retries=3, timeout=3.0):
        encRcon = util.decrypt(dbKey, self.rcon_password)
        if encRcon is None:
            encRcon = self.rcon_password
        return util.send_rcon_command(
            self.ip_string, self.port, encRcon,
            command, raise_errors, num_retries, timeout)

    def get_hostport(self):
        return '{}:{}'.format(self.ip_string, self.port)

    def get_display(self):
        if self.display_name:
            return '{} ({})'.format(self.display_name, self.get_hostport())
        else:
            return self.get_hostport()

    def receive_rcon_value(self, command):
        try:
            response = self.send_rcon_command(command, raise_errors=False)
            if response is not None:
                pattern = r'"([A-Za-z0-9_\./\\-]*)"'
                value = re.split(pattern, Markup(
                    response.replace('\n', '<br>')))
            else:
                return None
        except Exception as e:
            app.logger.info(
                "Tried to receive value from server but failed.\n{}".format(e))
            return None
        # Not sure how stable this will be, but send off for the third
        # value of the string split. Most values returned have format
        # "sv_password" = "test" (def. "")
        return value[3]

    def __repr__(self):
        return 'GameServer({})'.format(self.get_hostport())


class Team(db.Model):
    MAXPLAYERS = app.config['TEAM_MAXPLAYERS']

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    name = db.Column(db.String(40))
    tag = db.Column(db.String(40), default='')
    flag = db.Column(db.String(4), default='')
    logo = db.Column(db.String(10), default='')
    auths = db.Column(db.PickleType)
    public_team = db.Column(db.Boolean, index=True)
    preferred_names = db.Column(db.PickleType)

    @staticmethod
    def create(user, name, tag, flag, logo, auths, public_team=False, preferred_names=None):
        rv = Team()
        rv.user_id = user.id
        rv.set_data(name, tag, flag, logo, auths,
                    (public_team and user.admin), preferred_names)
        db.session.add(rv)
        return rv

    def set_data(self, name, tag, flag, logo, auths, public_team, preferred_names=None):
        self.name = name
        self.tag = tag
        self.flag = flag.lower() if flag else ''
        self.logo = logo
        self.auths = auths
        self.public_team = public_team
        self.preferred_names = preferred_names

    def can_edit(self, user):
        if not user:
            return False
        if self.user_id == user.id:
            return True
        if user.super_admin:
            return True
        return False

    def get_players(self):
        results = []
        for steam64 in self.auths:
            if steam64:
                name = get_steam_name(steam64)
                if not name:
                    name = ''

                results.append((steam64, name))
        return results

    def can_delete(self, user):
        if not self.can_edit(user):
            return False
        return self.get_recent_matches().count() == 0

    def get_recent_matches(self, limit=10):
        if self.public_team:
            matches = Match.query.order_by(-Match.id).limit(100).from_self()
        else:
            owner = User.query.get_or_404(self.user_id)
            matches = owner.matches

        recent_matches = matches.filter(
            ((Match.team1_id == self.id) | (Match.team2_id == self.id)) & (
                Match.cancelled == False) & (Match.start_time != None)  # noqa: E712
        ).order_by(-Match.id).limit(5)

        if recent_matches is None:
            return []
        else:
            return recent_matches

    def get_vs_match_result(self, match_id):
        other_team = None
        my_score = 0
        other_team_score = 0

        match = Match.query.get(match_id)
        if match.team1_id == self.id:
            my_score = match.team1_score
            other_team_score = match.team2_score
            other_team = Team.query.get(match.team2_id)
        else:
            my_score = match.team2_score
            other_team_score = match.team1_score
            other_team = Team.query.get(match.team1_id)

        # for a bo1 replace series score with the map score
        if match.max_maps == 1:
            mapstat = match.map_stats.first()
            if mapstat:
                if match.team1_id == self.id:
                    my_score = mapstat.team1_score
                    other_team_score = mapstat.team2_score
                else:
                    my_score = mapstat.team2_score
                    other_team_score = mapstat.team1_score

        if match.live():
            return 'Live, {}:{} vs {}'.format(my_score, other_team_score, other_team.name)
        if my_score < other_team_score:
            return 'Lost {}:{} vs {}'.format(my_score, other_team_score, other_team.name)
        elif my_score > other_team_score:
            return 'Won {}:{} vs {}'.format(my_score, other_team_score, other_team.name)
        else:
            return 'Tied {}:{} vs {}'.format(other_team_score, my_score, other_team.name)

    def get_flag_html(self, scale=1.0):
        # flags are expected to be 32x21
        width = int(round(32.0 * scale))
        height = int(round(21.0 * scale))

        html = '<img src="{}"  width="{}" height="{}">'
        output = html.format(
            countries.get_flag_img_path(self.flag), width, height)
        return Markup(output)

    def get_logo_html(self, scale=1.0):
        if logos.has_logo(self.logo):
            width = int(round(32.0 * scale))
            height = int(round(32.0 * scale))
            html = ('<img src="{}"  width="{}" height="{}">')
            return Markup(html.format(logos.get_logo_img(self.logo), width, height))
        else:
            #app.logger.info("Looked for {} but found nothing.".format(self.logo))
            return ''

    def get_url(self):
        return url_for('team.team', teamid=self.id)

    def get_name_url_html(self):
        return Markup('<a href="{}">{}</a>'.format(self.get_url(), self.name))

    def get_logo_or_flag_html(self, scale=1.0, other_team=None):
        if logos.has_logo(self.logo):
            return self.get_logo_html(scale)
        else:
            return self.get_flag_html(scale)

    def __repr__(self):
        return 'Team(id={}, user_id={}, name={}, flag={}, logo={}, public={})'.format(
            self.id, self.user_id, self.name, self.flag, self.logo, self.public_team)

class TeamAuthNames(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    auth = db.Column(db.String(17))
    name = db.Column(db.String(40))

    @staticmethod
    def set_or_create(team_id, auth, name):
        rv = TeamAuthNames.query.filter_by(team_id=team_id,auth=auth).first()
        if rv is None:
            rv = TeamAuthNames()
            rv.set_data(team_id, auth, name)
            db.session.add(rv)
        else:
            rv.set_data(team_id, auth, name)
        return rv

    def set_data(self, team_id, auth, name):
        self.team_id = team_id
        self.auth = auth
        self.name = name if name else ''



class Season(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    name = db.Column(db.String(60), default='')
    start_date = db.Column(db.DateTime, default=datetime.datetime.utcnow())
    end_date = db.Column(db.DateTime)
    matches = db.relationship('Match', backref='season', lazy='dynamic')

    @staticmethod
    def create(user, name, start_date, end_date):
        rv = Season()
        rv.user_id = user.id
        rv.name = name
        rv.start_date = start_date
        rv.end_date = end_date
        db.session.add(rv)
        return rv

    def get_season_name(self):
        return self.name

    def set_data(self, user, name, start_date, end_date):
        self.user_id = self.user_id
        self.name = name
        self.start_date = start_date
        self.end_date = end_date

    def can_edit(self, user):
        if not user:
            return False
        if self.user_id == user.id:
            return True
        if user.super_admin:
            return True
        return False

    def can_delete(self, user):
        if not self.can_edit(user):
            return False
        return self.get_recent_matches().count() == 0

    def get_recent_matches(self, limit=10):
        season = Season.query.get_or_404(self.id)
        matches = season.matches

        recent_matches = matches.filter(
            (Match.season_id == self.id) & (
                Match.cancelled == False) & (Match.start_time != None)  # noqa: E712
        ).order_by(-Match.id).limit(5)

        if recent_matches is None:
            return []
        else:
            return recent_matches

    def get_url(self):
        return url_for('season.seasons', seasonid=self.id)

    def __repr__(self):
        return 'Season(id={}, user_id={}, name={}, start_date={}, end_date={})'.format(
            self.id, self.user_id, self.name, self.start_date, self.end_date)


class match_audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    match_id = db.Column(db.Integer)
    timeaffected = db.Column(db.DateTime)
    cmd_used = db.Column(db.String(4000))

    @staticmethod
    def create(user_id, match_id, timeaffected, cmd_used):
        rv = match_audit()
        rv.user_id = user_id
        rv.match_id = match_id
        rv.timeaffected = timeaffected
        rv.cmd_used = cmd_used
        db.session.add(rv)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    server_id = db.Column(db.Integer, db.ForeignKey(
        'game_server.id'), index=True)
    team1_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    team2_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'))

    team1_string = db.Column(db.String(32), default='')
    team2_string = db.Column(db.String(32), default='')
    winner = db.Column(db.Integer, db.ForeignKey('team.id'))
    plugin_version = db.Column(db.String(32), default='unknown')

    forfeit = db.Column(db.Boolean, default=False)
    cancelled = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    max_maps = db.Column(db.Integer)
    title = db.Column(db.String(60), default='')
    skip_veto = db.Column(db.Boolean)
    api_key = db.Column(db.String(32))
    veto_first = db.Column(db.String(5))
    veto_mappool = db.Column(db.String(500))
    map_stats = db.relationship('MapStats', backref='match', lazy='dynamic')

    side_type = db.Column(db.String(32))
    team1_score = db.Column(db.Integer, default=0)
    team2_score = db.Column(db.Integer, default=0)
    team1_series_score = db.Column(db.Integer, default=0)
    team2_series_score = db.Column(db.Integer, default=0)
    spectator_auths = db.Column(db.PickleType)
    private_match = db.Column(db.Boolean)
    enforce_teams = db.Column(db.Boolean, default=True)
    min_player_ready = db.Column(db.Integer, default=5)
    @staticmethod
    def create(user, team1_id, team2_id, team1_string, team2_string,
               max_maps, skip_veto, title, veto_mappool, season_id,
               side_type, veto_first, server_id=None,
               team1_series_score=None, team2_series_score=None,
               spectator_auths=None, private_match=False, enforce_teams=True, min_player_ready=5):
        rv = Match()
        rv.user_id = user.id
        rv.team1_id = team1_id
        rv.team2_id = team2_id
        rv.season_id = season_id
        rv.side_type = side_type
        rv.skip_veto = skip_veto
        rv.title = title
        rv.veto_mappool = ' '.join(veto_mappool)
        rv.server_id = server_id
        rv.max_maps = max_maps
        if veto_first == "CT":
            rv.veto_first = "team1"
        elif veto_first == "T":
            rv.veto_first = "team2"
        else:
            rv.veto_first = None
        rv.api_key = ''.join(random.SystemRandom().choice(
            string.ascii_uppercase + string.digits) for _ in range(24))
        rv.team1_series_score = team1_series_score
        rv.team2_series_score = team2_series_score
        rv.spectator_auths = spectator_auths
        rv.private_match = private_match
        rv.enforce_teams = enforce_teams
        rv.min_player_ready = min_player_ready
        db.session.add(rv)
        return rv

    def get_status_string(self, show_winner=True):
        if self.pending():
            return 'Pending'
        elif self.live():
            team1_score, team2_score = self.get_current_score()
            return 'Live, {}:{}'.format(team1_score, team2_score)
        elif self.finished():
            t1score, t2score = self.get_current_score()
            min_score = min(t1score, t2score)
            max_score = max(t1score, t2score)
            score_string = '{}:{}'.format(max_score, min_score)

            if not show_winner:
                return 'Finished'
            elif self.winner == self.team1_id:
                return 'Won {} by {}'.format(score_string, self.get_team1().name)
            elif self.winner == self.team2_id:
                return 'Won {} by {}'.format(score_string, self.get_team2().name)
            else:
                return 'Tied {}'.format(score_string)

        else:
            return 'Cancelled'

    def is_private_match(self):
        return self.private_match

    def get_vs_string(self):
        team1 = self.get_team1()
        team2 = self.get_team2()
        scores = self.get_current_score()

        str = '{} vs {} ({}:{})'.format(
            team1.get_name_url_html(), team2.get_name_url_html(), scores[0], scores[1])

        return Markup(str)

    def finalized(self):
        return self.cancelled or self.finished()

    def pending(self):
        return self.start_time is None and not self.cancelled

    def finished(self):
        return self.end_time is not None and not self.cancelled

    def live(self):
        return self.start_time is not None and self.end_time is None and not self.cancelled

    def get_server(self):
        return GameServer.query.filter_by(id=self.server_id).first()

    def get_start_time(self):
        return self.start_time if self.start_time is not None else ''

    def get_end_time(self):
        return self.end_time if self.end_time is not None else ''

    def get_season(self):
        if self.season_id:
            return Season.query.get(self.season_id)
        else:
            return None
            
    def get_season_id(self):
        return self.season_id

    def get_current_score(self):
        if self.max_maps == 1:
            mapstat = self.map_stats.first()
            if not mapstat:
                return (0, 0)
            else:
                return (mapstat.team1_score, mapstat.team2_score)

        else:
            return (self.team1_score, self.team2_score)

    def send_to_server(self):
        server = GameServer.query.get(self.server_id)
        if not server:
            return False

        url = url_for('match.match_config', matchid=self.id,
                      _external=True, _scheme='http')
        # Remove http protocal since the get5 plugin can't parse args with the
        # : in them.
        url = url.replace("http://", "")
        url = url.replace("https://", "")

        loadmatch_response = server.send_rcon_command(
            'get5_loadmatch_url ' + url)

        server.send_rcon_command(
            'get5_web_api_key ' + self.api_key)

        # ***HACK FIX TO ENSURE CHECK_AUTHS WORKS AS INTENDED***
        server.send_rcon_command('map de_dust2')

        if loadmatch_response:  # There should be no response
            return False

        return True

    def get_team1(self):
        return Team.query.get(self.team1_id)

    def get_team2(self):
        return Team.query.get(self.team2_id)

    def get_user(self):
        return User.query.get(self.user_id)

    def get_winner(self):
        if self.team1_score > self.team2_score:
            return self.get_team1()
        elif self.team2_score > self.team1_score:
            return self.get_team2()
        else:
            return None

    def get_loser(self):
        if self.team1_score > self.team2_score:
            return self.get_team2()
        elif self.team2_score > self.team1_score:
            return self.get_team1()
        else:
            return None

    def build_match_dict(self):
        d = {}
        d['matchid'] = str(self.id)
        d['match_title'] = self.title
        d['side_type'] = self.side_type
        d['veto_first'] = self.veto_first
        d['skip_veto'] = self.skip_veto
        if self.max_maps == 2:
            d['bo2_series'] = True
        else:
            d['maps_to_win'] = self.max_maps / 2 + 1

        try:
            d['min_players_to_ready'] = self.min_player_ready
            d['players_per_team'] = self.min_player_ready
        except:
            d['min_players_to_ready'] = 5
            d['players_per_team'] = 5
            
        def add_team_data(teamkey, teamid, matchtext):
            team = Team.query.get(teamid)
            if not team:
                return
            d[teamkey] = {}

            # Add entries if they have values.
            def add_if(key, value):
                if value:
                    d[teamkey][key] = value
            add_if('name', team.name)
            add_if('name', team.name)
            add_if('tag', team.tag)
            add_if('flag', team.flag.upper())
            add_if('logo', team.logo)
            add_if('matchtext', matchtext)
            # Add new series score.
            if teamkey == 'team1':
                add_if('series_score', self.team1_series_score)
            else:
                add_if('series_score', self.team2_series_score)
            # Attempt to send in KV Pairs of preferred names.
            # If none, or error, send in the regular list.
            try:
                d[teamkey]['players'] = OrderedDict()
                for uid, name in zip(team.auths, team.preferred_names):
                    if uid:
                        d[teamkey]['players'][uid] = name
            except:
                d[teamkey]['players'] = filter(lambda x: x != '', team.auths)

        add_team_data('team1', self.team1_id, self.team1_string)
        add_team_data('team2', self.team2_id, self.team2_string)

        d['cvars'] = {}
        d['cvars']['get5_web_api_url'] = url_for(
            'home', _external=True, _scheme='http')    
        d['cvars']['get5_check_auths'] = "1" if self.enforce_teams else "0"
        # Add in for spectators modification.
        d['min_spectators_to_ready'] = 0

        # Perm spectators will go within config, then can add more from match
        # screen.
        d['spectators'] = {"players": app.config['SPECTATOR_IDS']}

        # If we don't have any perm spectators, create the new list.
        if not d['spectators']:
            d['spectators'] = {"players": []}
        # Append auths from match page if we have any.
        if self.spectator_auths:
            for spectator in self.spectator_auths:
                d['spectators']["players"].append(spectator)

        if not d['spectators']['players']:
            d['spectators'] = None

        if self.veto_mappool:
            d['maplist'] = []
            for map in self.veto_mappool.split():
                d['maplist'].append(map)

        return d

    def __repr__(self):
        return 'Match(id={})'.format(self.id)


class MatchSpectator(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    auth = db.Column(db.String(17))

    @staticmethod
    def set_or_create(match_id, auth):
        rv = MatchSpectator.query.filter_by(match_id=match_id,auth=auth).first()
        if rv is None:
            rv = MatchSpectator()
            rv.set_data(match_id, auth)
            db.session.add(rv)
        else:
            rv.set_data(match_id, auth)
        return rv

    def set_data(self, match_id, auth):
        self.match_id = match_id
        self.auth = auth

class MapStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    map_number = db.Column(db.Integer)
    map_name = db.Column(db.String(64))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    winner = db.Column(db.Integer, db.ForeignKey('team.id'))
    team1_score = db.Column(db.Integer, default=0)
    team2_score = db.Column(db.Integer, default=0)
    player_stats = db.relationship(
        'PlayerStats', backref='mapstats', lazy='dynamic')
    demoFile = db.Column(db.String(256))

    @staticmethod
    def get_or_create(match_id, map_number, map_name='', demoFile=None):
        match = Match.query.get(match_id)
        if match is None or map_number >= match.max_maps:
            return None

        rv = MapStats.query.filter_by(
            match_id=match_id, map_number=map_number).first()
        if rv is None:
            rv = MapStats()
            rv.match_id = match_id
            rv.map_number = map_number
            rv.map_name = map_name
            rv.start_time = datetime.datetime.utcnow()
            rv.team1_score = 0
            rv.team2_score = 0
            rv.demoFile = demoFile
            db.session.add(rv)
        return rv

    def __repr__(self):
        return 'MapStats(' + str(self.id) + ',' + str(self.map_name) + ')'


class PlayerStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    map_id = db.Column(db.Integer, db.ForeignKey('map_stats.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    steam_id = db.Column(db.String(40))
    name = db.Column(db.String(40))
    kills = db.Column(db.Integer, default=0)
    deaths = db.Column(db.Integer, default=0)
    roundsplayed = db.Column(db.Integer, default=0)
    assists = db.Column(db.Integer, default=0)
    flashbang_assists = db.Column(db.Integer, default=0)
    teamkills = db.Column(db.Integer, default=0)
    suicides = db.Column(db.Integer, default=0)
    headshot_kills = db.Column(db.Integer, default=0)
    damage = db.Column(db.Integer, default=0)
    bomb_plants = db.Column(db.Integer, default=0)
    bomb_defuses = db.Column(db.Integer, default=0)
    v1 = db.Column(db.Integer, default=0)
    v2 = db.Column(db.Integer, default=0)
    v3 = db.Column(db.Integer, default=0)
    v4 = db.Column(db.Integer, default=0)
    v5 = db.Column(db.Integer, default=0)
    k1 = db.Column(db.Integer, default=0)
    k2 = db.Column(db.Integer, default=0)
    k3 = db.Column(db.Integer, default=0)
    k4 = db.Column(db.Integer, default=0)
    k5 = db.Column(db.Integer, default=0)
    firstkill_t = db.Column(db.Integer, default=0)
    firstkill_ct = db.Column(db.Integer, default=0)
    firstdeath_t = db.Column(db.Integer, default=0)
    firstdeath_Ct = db.Column(db.Integer, default=0)

    def get_steam_id(self):
        return self.steam_id

    def get_steam_url(self):
        return 'http://steamcommunity.com/profiles/{}'.format(self.steam_id)

    def get_player_name(self):
        return get_steam_name(self.steam_id)

    def get_rating(self):
        try:
            AverageKPR = 0.679
            AverageSPR = 0.317
            AverageRMK = 1.277
            KillRating = float(self.kills) / float(self.roundsplayed) / AverageKPR
            SurvivalRating = float(self.roundsplayed -
                                self.deaths) / self.roundsplayed / AverageSPR
            killcount = float(self.k1 + 4 * self.k2 + 9 *
                            self.k3 + 16 * self.k4 + 25 * self.k5)
            RoundsWithMultipleKillsRating = killcount / \
                self.roundsplayed / AverageRMK
            rating = (KillRating + 0.7 * SurvivalRating +
                    RoundsWithMultipleKillsRating) / 2.7
            return rating
        except ZeroDivisionError:
            return 0
    def get_kdr(self):
        if self.deaths == 0:
            return float(self.kills)
        else:
            return float(self.kills) / self.deaths

    def get_hsp(self):
        if self.kills == 0:
            return 0.0
        else:
            return float(self.headshot_kills) / self.kills

    def get_adr(self):
        if self.roundsplayed == 0:
            return 0.0
        else:
            return float(self.damage) / self.roundsplayed

    def get_fpr(self):
        if self.roundsplayed == 0:
            return 0.0
        else:
            return float(self.kills) / self.roundsplayed

    """ Custom made individual scoreboard to work with VMIX and an Excel file.
        The values will be automagically updated and put straight into a broadcast (neat!)"""

    def get_ind_scoreboard(self, map_number):
        d = {}
        map_stats = MapStats.query.filter_by(
            match_id=self.match_id, map_number=map_number).first()
        team = Team.query.get(self.team_id)
        d['map'] = map_stats.map_name
        d[team.name] = {}
        d[team.name][self.steam_id] = {}
        d[team.name][self.steam_id]['Player'] = get_steam_name(self.steam_id)
        d[team.name][self.steam_id]['kills'] = round(float(self.kills), 1)
        d[team.name][self.steam_id]['deaths'] = round(float(self.deaths), 1)
        d[team.name][self.steam_id]['assists'] = round(float(self.assists), 1)
        d[team.name][self.steam_id]['rating'] = round(
            float(self.get_rating()), 2)
        d[team.name][self.steam_id]['hsp'] = round(float(self.get_hsp()), 2)
        d[team.name][self.steam_id]['firstkill'] = round(
            float(self.firstkill_ct + self.firstkill_t), 1)
        d[team.name][self.steam_id]['k2'] = round(float(self.k2), 1)
        d[team.name][self.steam_id]['k3'] = round(float(self.k3), 1)
        d[team.name][self.steam_id]['k4'] = round(float(self.k4), 1)
        d[team.name][self.steam_id]['k5'] = round(float(self.k5), 1)
        d[team.name][self.steam_id]['ADR'] = round(float(self.get_adr()), 1)
        return d

    def get_deaths(self):
        return float(self.deaths)

    @staticmethod
    def get_or_create(matchid, mapnumber, steam_id):
        mapstats = MapStats.get_or_create(matchid, mapnumber)
        if len(mapstats.player_stats.all()) >= 40:  # Cap on players per map
            return None

        rv = mapstats.player_stats.filter_by(steam_id=steam_id).first()

        if rv is None:
            rv = PlayerStats()
            rv.match_id = matchid
            rv.map_number = mapstats.id
            rv.steam_id = steam_id
            rv.map_id = mapstats.id
            db.session.add(rv)

        return rv

    def statsToCSVRow(self):
        team = Team.query.get(self.team_id)
        ourCSVText = [team.name,
                      self.steam_id, get_steam_name(self.steam_id),
                      round(float(self.kills), 1), round(
                          float(self.deaths), 1),
                      round(float(self.assists), 1), round(
                          float(self.get_rating() * 100), 2),
                      round(float(self.get_hsp() * 100),
                            2), round(float(self.firstkill_ct + self.firstkill_t), 1),
                      round(float(self.k2), 1), round(float(self.k3), 1),
                      round(float(self.k4), 1), round(float(self.k5), 1),
                      round(float(self.get_adr()), 1)]
        return (ourCSVText)


class Veto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    team_name = db.Column(db.String(64), default='')
    map = db.Column(db.String(32), default='')
    pick_or_veto = db.Column(db.String(4), default='veto')

    @staticmethod
    def create(match_id, team_name, map_name, p_v):
        rv = Veto()
        rv.match_id = match_id
        rv.team_name = team_name
        rv.map = map_name
        rv.pick_or_veto = p_v
        db.session.add(rv)
        return rv

    def __repr__(self):
        return 'Veto(id={})'.format(self.id)


@cache.memoize(timeout=60 * 60 * 24)  # 1 day timeout
def get_steam_name(steam64):
    url = 'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={}&steamids={}'
    url = url.format(app.config['STEAM_API_KEY'], steam64)
    response = requests.get(url)
    if response.status_code == 200:
        try:
            player_list = response.json()['response']['players']
            return player_list[0]['personaname']
        except (KeyError, IndexError):
            return None

    return None
