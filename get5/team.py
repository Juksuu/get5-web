from get5 import app, db, flash_errors, config_setting, BadRequestError
from models import User, Team, TeamAuthNames

import itertools
import countries
import logos
import steamid
import util
import os
import io
import re
import xml.etree.ElementTree as ET

from werkzeug.utils import secure_filename
from PIL import Image

from flask import Blueprint, request, render_template, flash, g, redirect, jsonify

from wtforms import (
    validators,
    StringField, BooleanField,
    SelectField, ValidationError)

from flask_wtf.file import FileField
from flask_wtf import FlaskForm
team_blueprint = Blueprint('team', __name__)


def valid_auth(form, field):
    # Ignore empty data fields
    if field.data is None or field.data == '':
        return

    # Otherwise validate and coerce to steam64
    suc, newauth = steamid.auth_to_steam64(field.data)
    if suc:
        field.data = newauth
    else:
        raise ValidationError('Invalid Steam ID')


def valid_file(form, field):
    if not field.data:
        return
    mock = config_setting("TESTING")
    if mock:
        return
    elif not g.user.admin:
        return
    filename = secure_filename(field.data.filename)
    # Safe method.
    if filename == '':
        return

    index_of_dot = filename.index('.')
    file_name_without_extension = filename[:index_of_dot]
    extension = filename.rsplit('.', 1)[1].lower()
    exists = os.path.isfile(
        app.config['LOGO_FOLDER'] + "/" + secure_filename(filename))
    existsSVG = os.path.isfile(
        app.config['PANO_LOGO_FOLDER'] + "/" + secure_filename(filename))

    if '.' not in filename:
        raise ValidationError('Image MUST be PNG or SVG.')
    elif extension not in {'svg', 'png'}:
        raise ValidationError('Image MUST be PNG or SVG.')
    elif len(filename.rsplit('.', 1)[0]) > 3:
        raise ValidationError('Image name can only be 3 characters long.')
    elif exists:
        raise ValidationError('Image already exists in PNG.')
    elif existsSVG:
        raise ValidationError('Image name already exists for SVG.')

    if extension == 'png':
        file = request.files['upload_logo']
        img = Image.open(file)
        width, height = img.size
        out = io.BytesIO()
        if width != 64 or height != 64:
            app.logger.info("Resizing image as it is not 64x64.")
            img = img.resize((64, 64), Image.ANTIALIAS)
            img.save(out, format=extension)
            # check once more for size.
            if out.tell() > 16384:
                app.logger.info("Size: {}".format(out.tell()))
                raise ValidationError(
                    'Image is too large, must be 10kB or less.')
            img.save(os.path.join(
                app.config['LOGO_FOLDER'], filename), optimize=True)
        elif out.tell() > 16384:
            raise ValidationError('Image is too large, must be 10kB or less.')
        else:
            img.save(os.path.join(
                app.config['LOGO_FOLDER'], filename), optimize=True)
    else:
        file = request.files['upload_logo']
        # Limited - attempt to find width and height. If nothing then deny
        # upload.
        tree = ET.parse(file)
        root = tree.getroot()
        try:
            width = root.attrib['width']
            height = root.attrib['height']
        except:
            raise ValidationError('SVG is not properly formatted.')
        if (width in {'64', '64px'}) and (height in {'64', '64px'}):
            tree.write(app.config['PANO_LOGO_FOLDER'] +
                       "/" + secure_filename(filename))
        else:
            raise ValidationError("Error in saving SVG to folder.")


class TeamForm(FlaskForm):
    mock = config_setting("TESTING")
    name = StringField('Team Name', validators=[
        validators.required(),
        validators.Length(min=-1, max=Team.name.type.length)])

    tag = StringField('Team Tag', validators=[
        validators.required(), validators.Length(min=-1, max=Team.tag.type.length)])

    flag_choices = [('', 'None')] + countries.country_choices
    country_flag = SelectField(
        'Country Flag', choices=flag_choices, default='')
    if mock:
        logo_choices = logos.get_logo_choices()
        logo = SelectField('Logo Name', choices=logo_choices, default='')
    else:
        logo = SelectField('Logo Name', default='')

    upload_logo = FileField(validators=[valid_file])

    public_team = BooleanField('Public Team')

    def get_auth_list(self):
        auths = []
        for i in range(1, Team.MAXPLAYERS + 1):
            key = 'auth{}'.format(i)
            auths.append(self.data[key])

        return auths

    def get_pref_list(self):
        prefs = []
        for i in range(1, Team.MAXPLAYERS + 1):
            key = 'pref_name{}'.format(i)
            prefs.append(self.data[key])

        return prefs
# Now can create a max player count based on your needs.
for num in range(Team.MAXPLAYERS):
    setattr(TeamForm, "auth" + str(num + 1),
            StringField('Player ' + str(num + 1), validators=[valid_auth]))
    setattr(TeamForm, "pref_name" + str(num + 1),
            StringField("Player " + str(num + 1) + "'s Name"))


@team_blueprint.route('/team/create', methods=['GET', 'POST'])
def team_create():
    mock = config_setting("TESTING")
    customNames = config_setting("CUSTOM_PLAYER_NAMES")
    if not g.user:
        return redirect('/login')
    form = TeamForm()
    # We wish to query this every time, since we can now upload photos.
    if not mock:
        form.logo.choices = logos.get_logo_choices()
    if request.method == 'POST':
        num_teams = g.user.teams.count()
        max_teams = config_setting('USER_MAX_TEAMS')
        if max_teams >= 0 and num_teams >= max_teams and not (g.user.admin or g.user.super_admin):
            flash(
                'You already have the maximum number of teams ({}) stored'.format(num_teams))

        elif form.validate():
            data = form.data
            auths = form.get_auth_list()
            pref_names = form.get_pref_list()
            name = data['name'].strip()
            tag = data['tag'].strip()
            flag = data['country_flag']
            logo = data['logo']

            # Update the logo. Passing validation we have the filename in the
            # list now.
            if not mock and (g.user.admin or g.user.super_admin) and form.upload_logo.data:
                filename = secure_filename(form.upload_logo.data.filename)
                index_of_dot = filename.index('.')
                newLogoDetail = filename[:index_of_dot]
                # Reinit our logos.
                logos.add_new_logo(newLogoDetail)
                app.logger.info("Added new logo id {}".format(newLogoDetail))
                data['logo'] = newLogoDetail

            team = Team.create(g.user, name, tag, flag, logo,
                               auths, data['public_team'] and (g.user.admin or g.user.super_admin), pref_names)
            db.session.commit()

            for auth,name in itertools.izip_longest(auths,pref_names):
                if auth:
                    TeamAuthNames.set_or_create(team.id, auth, name)

            db.session.commit()
            app.logger.info(
                'User {} created team {}'.format(g.user.id, team.id))

            return redirect('/teams/{}'.format(team.user_id))

        else:
            flash_errors(form)

    return render_template('team_create.html', user=g.user, form=form,
                           edit=False, is_admin=(g.user.admin or g.user.super_admin), MAXPLAYER=Team.MAXPLAYERS, customNames=customNames)


@team_blueprint.route('/team/<int:teamid>', methods=['GET'])
def team(teamid):
    team = Team.query.get_or_404(teamid)
    return render_template('team.html', user=g.user, team=team)


@team_blueprint.route('/team/<int:teamid>/edit', methods=['GET', 'POST'])
def team_edit(teamid):
    mock = config_setting("TESTING")
    customNames = config_setting("CUSTOM_PLAYER_NAMES")
    team = Team.query.get_or_404(teamid)
    if not team.can_edit(g.user):
        raise BadRequestError("Not your team.")
    form = TeamForm()
    # We wish to query this every time, since we can now upload photos.
    if not mock:
        form.logo.choices = logos.get_logo_choices()
    if request.method == 'GET':
        # Set values here, as per new FlaskForms.
        form.name.data = team.name
        form.tag.data = team.tag
        form.country_flag.data = team.flag
        form.logo.data = team.logo
        for field in form:
            if "auth" in field.name:
                try:
                    field.data = team.auths[
                        int(re.search(r'\d+', field.name).group()) - 1]
                except:
                    field.data = None
            if "pref_name" in field.name:
                try:
                    field.data = team.preferred_names[
                        int(re.search(r'\d+', field.name).group()) - 1]
                except:
                    field.data = None
        form.public_team.data = team.public_team
        return render_template('team_create.html', user=g.user, form=form,
                               edit=True, is_admin=(g.user.admin or g.user.super_admin), MAXPLAYER=Team.MAXPLAYERS, customNames=customNames)

    elif request.method == 'POST':
        if form.validate():
            data = form.data
            public_team = team.public_team
            if (g.user.admin or g.user.super_admin):
                public_team = data['public_team']

            # Update the logo. Passing validation we have the filename in the
            # list now.
            if not mock and (g.user.admin or g.user.super_admin) and form.upload_logo.data:
                filename = secure_filename(form.upload_logo.data.filename)
                index_of_dot = filename.index('.')
                newLogoDetail = filename[:index_of_dot]
                # Reinit our logos.
                logos.add_new_logo(newLogoDetail)
                data['logo'] = newLogoDetail
            allAuths = form.get_auth_list()
            allNames = form.get_pref_list()
            team.set_data(data['name'], data['tag'], data['country_flag'],
                          data['logo'], allAuths,
                          public_team, allNames)
            for auth,name in itertools.izip_longest(allAuths,allNames):
                if auth:
                    teamNames = TeamAuthNames.set_or_create(teamid, auth, name)


            db.session.commit()
            return redirect('/teams/{}'.format(team.user_id))
        else:
            flash_errors(form)

    return render_template(
        'team_create.html', user=g.user, form=form, edit=True,
        is_admin=g.user.admin, MAXPLAYER=Team.MAXPLAYERS)


@team_blueprint.route('/team/<int:teamid>/delete')
def team_delete(teamid):
    team = Team.query.get_or_404(teamid)
    if not team.can_delete(g.user):
        raise BadRequestError("Cannot delete this team.")

    if TeamAuthNames.query.filter_by(team_id=teamid).delete():
        db.session.commit()
    if Team.query.filter_by(id=teamid).delete():
        db.session.commit()
    

    return redirect('/myteams')


@team_blueprint.route('/teams/<int:userid>', methods=['GET'])
def teams_user(userid):
    user = User.query.get_or_404(userid)
    page = util.as_int(request.values.get('page'), on_fail=1)
    json_data = util.as_int(request.values.get('json'), on_fail=0)

    teams = user.teams
    if g.user is not None and g.user.super_admin:
        teams = Team.query.order_by(-Team.id)

    if json_data:
        teams_dict = {}
        for team in teams:
            team_dict = {}
            team_dict['name'] = team.name
            team_dict['tag'] = team.tag
            team_dict['flag'] = team.flag
            team_dict['logo'] = team.logo
            team_dict['players'] = filter(lambda x: bool(x), team.auths)
            team_dict['players_pref_names'] = filter(
                lambda x: bool(x), team.preferred_names)
            teams_dict[team.id] = team_dict
        return jsonify(teams_dict)

    else:
        # Render teams page
        my_teams = (g.user is not None and ((userid == g.user.id) or g.user.super_admin))
        teams_paginated = teams.paginate(page, 20)
        return render_template(
            'teams.html', user=g.user, teams=teams_paginated, my_teams=my_teams,
            page=page, owner=user)


@team_blueprint.route('/teams', methods=['GET'])
def all_teams():
    all_public_teams = Team.query.filter_by(public_team=True)
    page = util.as_int(request.values.get('page'), on_fail=1)
    json_data = util.as_int(request.values.get('json'), on_fail=0)

    if json_data:
        teams_dict = {}
        for team in all_public_teams:
            team_dict = {}
            team_dict['name'] = team.name
            team_dict['tag'] = team.tag
            team_dict['flag'] = team.flag
            team_dict['logo'] = team.logo
            team_dict['players'] = filter(lambda x: bool(x), team.auths)
            team_dict['players_pref_names'] = filter(
                lambda x: bool(x), team.preferred_names)
            teams_dict[team.id] = team_dict
        return jsonify(teams_dict)

    else:
        # Render teams page
        teams = all_public_teams.paginate(page, 20)
        editable = g.user is not None and g.user.super_admin
        return render_template(
            'teams.html', user=g.user, teams=teams, my_teams=editable,
            page=page, owner=None)


@team_blueprint.route('/myteams', methods=['GET'])
def myteams():
    if not g.user:
        return redirect('/login')

    return redirect('/teams/' + str(g.user.id))
