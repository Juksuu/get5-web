from flask import Blueprint, request, render_template, flash, g, redirect, jsonify, Markup, json

import steamid
import get5
from get5 import app, db, BadRequestError, config_setting
from models import User, Team, Match, GameServer, MapStats, Season
from collections import OrderedDict, defaultdict
from datetime import datetime
import util
import re
from copy import deepcopy

# Since we use the same logic for getting a leaderboard based on total
# and on season, just wrap it in one function to avoid code reuse.


def getLeaderboard(seasonid=None):
    if seasonid is None:
        totalMatches = Match.query.order_by(-Match.id).filter(
            Match.cancelled == False, Match.end_time.isnot(None), Match.winner.isnot(None))
        seasonsBoard = False
    else:
        totalMatches = Match.query.order_by(-Match.id).filter(
            Match.cancelled == False, Match.end_time.isnot(None), 
            Match.season_id == seasonid, Match.winner.isnot(None))
        seasonsBoard = True
        season = Season.query.get_or_404(seasonid)
    allTeams = Team.query.order_by(-Team.id)
    # Shoutouts to n3rds.
    dTeamStandings = defaultdict(lambda: {'teamid': 0, 'wins': 0, 'losses': 0, 'rounddiff': 0})
    # Build our own object with team and links, rank, and round diff?
    # Building our own object requires matches, map_stats for each match.
    # Just build a dictionary with each match and stats?
    for match in totalMatches:     
        map_stats = MapStats.query.filter_by(
            match_id=match.id)
        # Get the losing team, and scores for round difference.
        for all_stats in map_stats:
            winningRounds = 0
            losingRounds = 0
            # Get each winner ID and create a list that returns the Team Name, amount of wins for now.
            winningTeam = Team.query.filter_by(id=all_stats.winner).first()
            if all_stats.winner == match.team1_id:
                losingTeam = Team.query.filter_by(id=match.team2_id).first()
                winningRounds = winningRounds + all_stats.team1_score
                losingRounds = losingRounds + all_stats.team2_score
            else:
                losingTeam = Team.query.filter_by(id=match.team1_id).first()
                losingRounds = losingRounds + all_stats.team1_score
                winningRounds = winningRounds + all_stats.team2_score

            # Update winning and losing teams.
            dTeamStandings[winningTeam.name]['teamid'] = winningTeam.id
            dTeamStandings[winningTeam.name]['wins'] += 1
            dTeamStandings[winningTeam.name]['rounddiff'] += (winningRounds - losingRounds)
            dTeamStandings[losingTeam.name]['teamid'] = losingTeam.id
            dTeamStandings[losingTeam.name]['losses'] += 1
            dTeamStandings[losingTeam.name]['rounddiff'] += (losingRounds - winningRounds)

            
            
    # Sort teams via lexigraphical sort, very inefficient but it works for now.
    dTeamStandings = OrderedDict(
        sorted(dTeamStandings.items(), key=lambda x: (x[1].get('wins'), x[1].get('losses'), x[1].get('rounddiff')), reverse=True))
    # app.logger.info('Currently in dTeamStandings: \n{}'.format(dTeamStandings))
    if seasonsBoard:
        return render_template('leaderboard.html', standings=dTeamStandings, user=g.user, seasonsBoard=seasonsBoard, seasonName=season.name)
    else:
        return render_template('leaderboard.html', standings=dTeamStandings, user=g.user, seasonsBoard=seasonsBoard)


leaderboard_blueprint = Blueprint('leaderboard', __name__)


@leaderboard_blueprint.route('/leaderboard')
def leaderboard():
    return getLeaderboard()


@leaderboard_blueprint.route('/leaderboard/season/<int:seasonid>/')
def seasonal_leaderboard(seasonid):
    return getLeaderboard(seasonid)
