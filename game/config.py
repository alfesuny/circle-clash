"""Central game configuration: tuning values and teams.

All balancing numbers live here. World units are abstract "map units";
the client scales them to the browser window. Maps are loaded from the
Maps/ folder (see game/maps.py).
"""

import os
import secrets
from pathlib import Path

GAME_CONFIG = {
    "max_players_per_team": 7,
    "default_game_duration": 300,     # seconds
    "min_game_duration": 10,          # seconds (admin input is clamped to this range)
    "max_game_duration": 3600,
    "player_health": 4,               # hits to kill ("lives" shown as hearts)
    "player_radius": 14,
    "player_speed": 180,              # units / second
    "bullet_speed": 650,              # units / second
    "bullet_radius": 4,
    "bullet_lifetime": 2.0,           # seconds before an unobstructed bullet expires
    "fire_cooldown": 0.75,            # seconds between shots
    "respawn_delay": 3,               # seconds
    "spawn_protection_duration": 3,   # seconds of invulnerability after (re)spawning
    "kill_score": 10,
    "tick_rate": 30,                  # server updates per second
    "input_timeout": 1.0,             # seconds without a move message before keys are released
    "max_name_length": 16,
    "kill_feed_size": 5,
    "default_map": "Galadriel",
}

# Admin password: set LAN_SHOOTER_ADMIN_PASSWORD to choose one, otherwise a
# random one is generated at startup and printed to the server console.
ADMIN_PASSWORD = os.environ.get("LAN_SHOOTER_ADMIN_PASSWORD") or secrets.token_hex(3)

# Teams are data. Every map lists one spawn zone per team, in this order.
TEAMS = [
    {"id": "a", "name": "TEAM A", "color": "#e74c3c"},
    {"id": "b", "name": "TEAM B", "color": "#3498db"},
]

# Each sub-folder with a map.json is a map (see game/maps.py for the format).
MAPS_DIR = Path(__file__).resolve().parent.parent / "Maps"
