"""Seed team registry. Format per line: ``CODE|Full Name|alias;alias|extra codes``.

Aliases are generated automatically from the full name (nickname, unique city, "City X" Kalshi style);
only irregular aliases are listed. Admins can add more aliases at runtime (table ``team_aliases``).
"""

from __future__ import annotations

LEAGUES: dict[str, dict[str, str]] = {
    "nba": {"sport": "basketball", "name": "NBA"},
    "nfl": {"sport": "american_football", "name": "NFL"},
    "nhl": {"sport": "hockey", "name": "NHL"},
    "mlb": {"sport": "baseball", "name": "MLB"},
    "epl": {"sport": "soccer", "name": "English Premier League"},
}

# nickname word count overrides (e.g. "Trail Blazers", "Red Sox")
TEAMS_RAW: dict[str, str] = {
    "nba": """
ATL|Atlanta Hawks||
BOS|Boston Celtics|celts|
BKN|Brooklyn Nets||BRK;BRO
CHA|Charlotte Hornets||CHO
CHI|Chicago Bulls||
CLE|Cleveland Cavaliers|cavs|
DAL|Dallas Mavericks|mavs|
DEN|Denver Nuggets||
DET|Detroit Pistons||
GSW|Golden State Warriors|golden state;gs warriors|GS
HOU|Houston Rockets||
IND|Indiana Pacers||
LAC|Los Angeles Clippers|la clippers;l.a. clippers|
LAL|Los Angeles Lakers|la lakers;l.a. lakers|
MEM|Memphis Grizzlies|grizz|
MIA|Miami Heat||
MIL|Milwaukee Bucks||
MIN|Minnesota Timberwolves|wolves;t-wolves|
NOP|New Orleans Pelicans|pels|NO;NOR
NYK|New York Knicks|ny knicks|NY
OKC|Oklahoma City Thunder|okc thunder|
ORL|Orlando Magic||
PHI|Philadelphia 76ers|sixers;76ers;phila 76ers|
PHX|Phoenix Suns||PHO
POR|Portland Trail Blazers|trail blazers;blazers|
SAC|Sacramento Kings||
SAS|San Antonio Spurs||SA
TOR|Toronto Raptors||
UTA|Utah Jazz||UTAH
WAS|Washington Wizards||WSH
""",
    "nfl": """
ARI|Arizona Cardinals||ARZ
ATL|Atlanta Falcons||
BAL|Baltimore Ravens||
BUF|Buffalo Bills||
CAR|Carolina Panthers||
CHI|Chicago Bears||
CIN|Cincinnati Bengals||
CLE|Cleveland Browns||
DAL|Dallas Cowboys||
DEN|Denver Broncos||
DET|Detroit Lions||
GB|Green Bay Packers|green bay|GNB
HOU|Houston Texans||
IND|Indianapolis Colts||
JAX|Jacksonville Jaguars|jags|JAC
KC|Kansas City Chiefs|kansas city|KAN
LV|Las Vegas Raiders|las vegas|LVR;OAK
LAC|Los Angeles Chargers|la chargers|
LAR|Los Angeles Rams|la rams|LA
MIA|Miami Dolphins||
MIN|Minnesota Vikings||
NE|New England Patriots|pats;new england|NWE
NO|New Orleans Saints|new orleans|NOR
NYG|New York Giants|ny giants|
NYJ|New York Jets|ny jets|
PHI|Philadelphia Eagles||
PIT|Pittsburgh Steelers||
SF|San Francisco 49ers|niners;49ers;san francisco|SFO
SEA|Seattle Seahawks||
TB|Tampa Bay Buccaneers|bucs;tampa bay|TAM
TEN|Tennessee Titans||
WAS|Washington Commanders|washington|WSH
""",
    "nhl": """
ANA|Anaheim Ducks||
BOS|Boston Bruins||
BUF|Buffalo Sabres||
CGY|Calgary Flames||CAL
CAR|Carolina Hurricanes|canes|
CHI|Chicago Blackhawks|hawks|
COL|Colorado Avalanche|avs|
CBJ|Columbus Blue Jackets|blue jackets|CLB
DAL|Dallas Stars||
DET|Detroit Red Wings|red wings|
EDM|Edmonton Oilers||
FLA|Florida Panthers||
LAK|Los Angeles Kings|la kings|LA
MIN|Minnesota Wild||
MTL|Montreal Canadiens|habs;montréal canadiens|MON
NSH|Nashville Predators|preds|NAS
NJD|New Jersey Devils||NJ
NYI|New York Islanders|isles;ny islanders|
NYR|New York Rangers|ny rangers|
OTT|Ottawa Senators|sens|
PHI|Philadelphia Flyers||
PIT|Pittsburgh Penguins|pens|
SJS|San Jose Sharks||SJ
SEA|Seattle Kraken||
STL|St. Louis Blues|st louis blues;saint louis blues|
TBL|Tampa Bay Lightning|bolts|TB
TOR|Toronto Maple Leafs|maple leafs;leafs|
UTA|Utah Mammoth|utah hockey club;utah|UHC
VAN|Vancouver Canucks||
VGK|Vegas Golden Knights|golden knights;vegas|VEG
WSH|Washington Capitals|caps|WAS
WPG|Winnipeg Jets||WIN
""",
    "mlb": """
ARI|Arizona Diamondbacks|d-backs;dbacks|AZ
ATL|Atlanta Braves||
BAL|Baltimore Orioles||
BOS|Boston Red Sox|red sox|
CHC|Chicago Cubs||
CWS|Chicago White Sox|white sox|CHW
CIN|Cincinnati Reds||
CLE|Cleveland Guardians||
COL|Colorado Rockies||
DET|Detroit Tigers||
HOU|Houston Astros||
KC|Kansas City Royals||KCR
LAA|Los Angeles Angels|la angels|ANA
LAD|Los Angeles Dodgers|la dodgers|
MIA|Miami Marlins||
MIL|Milwaukee Brewers||
MIN|Minnesota Twins||
NYM|New York Mets|ny mets|
NYY|New York Yankees|ny yankees|
ATH|Athletics|oakland athletics;sacramento athletics;a's|OAK
PHI|Philadelphia Phillies||
PIT|Pittsburgh Pirates||
SD|San Diego Padres||SDP
SF|San Francisco Giants||SFG
SEA|Seattle Mariners||
STL|St. Louis Cardinals|st louis cardinals;saint louis cardinals|
TB|Tampa Bay Rays||TBR
TEX|Texas Rangers||
TOR|Toronto Blue Jays|blue jays|
WSH|Washington Nationals|nats|WAS
""",
    "epl": """
ARS|Arsenal|arsenal fc|
AVL|Aston Villa|villa|
BOU|Bournemouth|afc bournemouth|
BRE|Brentford||
BHA|Brighton and Hove Albion|brighton;brighton & hove albion|BRI
BUR|Burnley||
CHE|Chelsea||
CRY|Crystal Palace|palace|CPL
EVE|Everton||
FUL|Fulham||
LEE|Leeds United|leeds|LEEDS
LIV|Liverpool||
MCI|Manchester City|man city;man. city|MNC
MUN|Manchester United|man united;man utd;man. united;manchester utd|MNU
NEW|Newcastle United|newcastle|
NFO|Nottingham Forest|nottm forest;nott'm forest;forest|NOT
SUN|Sunderland|sunderland afc|
TOT|Tottenham Hotspur|tottenham;spurs|
WHU|West Ham United|west ham|
WOL|Wolverhampton Wanderers|wolves;wolverhampton|
LEI|Leicester City|leicester|
IPS|Ipswich Town|ipswich|
SOU|Southampton||
""",
}

# multi-word nicknames that must not be split
MULTIWORD_NICKNAMES = {
    "trail blazers",
    "red sox",
    "white sox",
    "blue jays",
    "red wings",
    "blue jackets",
    "maple leafs",
    "golden knights",
}
