"""Central game configuration: tuning values, teams and the map.

All balancing numbers live here. World units are abstract "map units";
the client scales them to the browser window.
"""

import os
import secrets

GAME_CONFIG = {
    "max_players_per_team": 5,
    "default_game_duration": 300,     # seconds
    "min_game_duration": 10,          # seconds (admin input is clamped to this range)
    "max_game_duration": 3600,
    "player_health": 4,
    "player_radius": 14,
    "player_speed": 220,              # units / second
    "bullet_speed": 650,              # units / second
    "bullet_radius": 4,
    "bullet_lifetime": 2.0,           # seconds before an unobstructed bullet expires
    "fire_cooldown": 0.35,            # seconds between shots
    "respawn_delay": 3,               # seconds
    "spawn_protection_duration": 3,   # seconds of invulnerability after (re)spawning
    "kill_score": 10,
    "tick_rate": 30,                  # server updates per second
    "max_name_length": 16,
    "kill_feed_size": 5,
}

# Admin password: set LAN_SHOOTER_ADMIN_PASSWORD to choose one, otherwise a
# random one is generated at startup and printed to the server console.
ADMIN_PASSWORD = os.environ.get("LAN_SHOOTER_ADMIN_PASSWORD") or secrets.token_hex(3)

# Teams are data: add an entry here (plus a spawn zone in MAP) to add a team.
TEAMS = [
    {"id": "red", "name": "RED", "color": "#e74c3c"},
    {"id": "green", "name": "GREEN", "color": "#2ecc71"},
    {"id": "blue", "name": "BLUE", "color": "#3498db"},
]

MAP = {
    "width": 1000,
    "height": 700,
    "walls": [
        # upper bars
        {"x": 250, "y": 150, "width": 200, "height": 30},
        {"x": 550, "y": 150, "width": 200, "height": 30},
        # side pillars
        {"x": 150, "y": 330, "width": 30, "height": 160},
        {"x": 820, "y": 330, "width": 30, "height": 160},
        # centre cross
        {"x": 400, "y": 335, "width": 200, "height": 30},
        {"x": 485, "y": 260, "width": 30, "height": 180},
        # lower bars
        {"x": 230, "y": 520, "width": 150, "height": 30},
        {"x": 620, "y": 520, "width": 150, "height": 30},
        # cover next to the bottom spawn
        {"x": 370, "y": 600, "width": 30, "height": 100},
        {"x": 600, "y": 600, "width": 30, "height": 100},
    ],
    "spawn_zones": {
        "red": {"x": 20, "y": 20, "width": 130, "height": 130},
        "green": {"x": 850, "y": 20, "width": 130, "height": 130},
        "blue": {"x": 435, "y": 560, "width": 130, "height": 130},
    },
}


def max_total_players() -> int:
    return GAME_CONFIG["max_players_per_team"] * len(TEAMS)
