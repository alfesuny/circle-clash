"""Plain data objects for players and bullets."""

import secrets
from dataclasses import dataclass, field

MOVE_KEYS = ("w", "a", "s", "d")


@dataclass
class Player:
    id: str
    name: str
    # Secret the browser keeps so a refresh can reclaim this player mid-match.
    resume_token: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    team: str | None = None
    connected: bool = True
    in_match: bool = False          # had a team when the current match started

    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    keys: dict = field(default_factory=lambda: {k: False for k in MOVE_KEYS})

    health: int = 0
    alive: bool = False
    respawn_at: float | None = None
    invulnerable_until: float = 0.0
    last_shot_at: float = float("-inf")

    kills: int = 0
    deaths: int = 0

    def reset_match_stats(self) -> None:
        self.kills = 0
        self.deaths = 0
        self.alive = False
        self.health = 0
        self.respawn_at = None
        self.invulnerable_until = 0.0
        self.last_shot_at = float("-inf")
        self.keys = {k: False for k in MOVE_KEYS}


@dataclass
class Bullet:
    id: int
    owner_id: str
    team: str
    x: float
    y: float
    vx: float
    vy: float
    expires_at: float
