# get5-web

### Development Build
[![Build Status](https://travis-ci.org/PhlexPlexico/get5-web.svg?branch=development)](https://travis-ci.org/PhlexPlexico/get5-web)

### Master Build
[![Build Status](https://travis-ci.org/PhlexPlexico/get5-web.svg?branch=master)](https://travis-ci.org/PhlexPlexico/get5-web)

---

**Status: Third Party Supported**

[![GitHub Downloads](https://img.shields.io/github/downloads/phlexplexico/get5-web/total.svg?label=Downloads)](https://github.com/phlexplexico/get5-web/releases/latest)

This is an _**experimental**_ web panel meant to be used in conjunction with the [get5](https://github.com/splewis/get5) CS:GO server plugin. It provides a more convenient way of managing matches and match servers.

This fork of get5-web will probably be updated as more features are required for my use case (running a small league). Bugs will be fixed as I come across them, or based on priority (i.e. does it break everything for me). If you have any bugs you'd like to report, please create an issue. I'll try my best to help solve the issue, but I am still new to learning flask as well.

**WARNING: THIS BUILD OF THE WEB-PANEL IS _UNDER DEVELOPMENT_ AND IS STARTING TO USE MODIFIED GET5 MATERIAL, SUCH AS THE API_STATS PLUGIN. I DO NOT TAKE RESPONSIBILITY FOR ANY DATA LOSS, MISUSE, ETC. THAT THIS WEBAPP MAY INCUR.**

_IF YOU HAVE ANY ISSUES, **PLEASE REPORT IT HERE.**_

## How to use it:

1. Create your game servers on the "Add a server" page by giving their ip, port, and rcon password
2. Create teams on the "Create a Team" page by listing the steamids for each of the players
3. Go to the "Create a Match" page, selecting the teams, server, and rules for the match
4. Optional - Create a season with a given date range to keep track for a subset of matches.

Once you do this, the site will send an rcon command to the game server `get5_loadmatch_url <webserver>/match/<matchid>/config`, which will load the match config onto the gameserver automatically for you. Stats and game status will automatically be updated on the webpage.

As the match owner, you will be able to cancel the match. Additionally, on its matchpage there is a dropdown to run admin commands: add players to the teams if a ringer is needed, pause the match, load a match backup, list match backups, and run any rcon command.

Note: when using this web panel, the CS:GO game servers **must** be have both the core get5 plugin and the get5_apistats plugin. They are [released](https://github.com/splewis/get5/releases) together. This means the server must also be running the [Steamworks](https://forums.alliedmods.net/showthread.php?t=229556) and [SMJansson](https://forums.alliedmods.net/showthread.php?t=184604) extensions.

## Screenshots

![Match Creation Page](/screenshots/create_match.png?raw=true "Match Creation Page")

![Match Stats Page](/screenshots/match_stats.png?raw=true "Match Stats Page")

![Teams Page](/screenshots/teams.png?raw=true "Teams Page")

![Team Creation Page](/screenshots/team_edit.png?raw=true "Team Creation Page")

![Season Creation Page](/screenshots/season_create.png?raw=true "Season creation Page")

## Requirements:

- python2.7
- MySQL (other databases will likely work, but aren't guaranteed to, [example for MariaDB](https://github.com/splewis/get5-web/issues/146#issuecomment-480908372))
- a linux web server capable of running Flask applications ([see deployment options](http://flask.pocoo.org/docs/0.11/deploying/))

## Installation

Please see the [installation instructions](INSTALL.md) for Ubuntu 16.04 with apache2. You can use other distributions or web servers, but you will likely have to figure out how to install a python flask app yourself.

## How do the game server and web panel communicate?

1. When a server is added the web server will send `get5_web_avaliable` command through rcon that will check for the appropriate get5 plugins to be installed on the server
2. When a match is assigned to a server, the `get5_loadmatch_url` command is used through rcon to tell the websever a file to download the get5 match config from
3. When stats begin to update (map start, round end, map end, series end), the game server plugins will send HTTP requests to the web server, using a per-match API token set in the `get5_web_api_key` cvar when the match was assigned to the server

## Other useful commands:

Autoformatting:

```sh
cd get5
autopep8 -r get5 --in-place
autopep8 -r get5 --diff # should have no output
```

Linting errors:

```sh
cd get5
pyflakes *.py
```

Testing:
You must also setup a `test_config.py` file in the `instance` directory.

```sh
./test.sh
```

Manually running a test instance: (for development purposes)

```sh
python2.7 main.py
```
