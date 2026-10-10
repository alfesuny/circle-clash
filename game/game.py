"""Authoritative game state and rules.

Nothing in here does I/O. The networking layer calls the public methods
(join, choose_team, set_keys, shoot, start, tick, ...) and broadcasts
snapshot(). Every method takes an optional `now` (monotonic seconds) so the
rules can be tested deterministically.
"""

import math
import random
import secrets
import time
import uuid

from . import collision
from .config import GAME_CONFIG, MAPS_DIR, TEAMS
from .entities import MOVE_KEYS, Bullet, Player
from .maps import load_maps

LOBBY, RUNNING, ENDED = "LOBBY", "RUNNING", "ENDED"


class GameError(Exception):
    """A request that the rules refuse; the message is shown to the player/admin."""


def _clean_name(raw) -> str:
    name = "".join(ch for ch in str(raw or "") if ch.isprintable()).strip()
    return name[: GAME_CONFIG["max_name_length"]]


class Game:
    def __init__(self, config: dict = GAME_CONFIG, teams: list = TEAMS, maps: dict | None = None):
        self.cfg = config
        self.teams = teams
        self.team_ids = [t["id"] for t in teams]
        self.maps = load_maps(MAPS_DIR, teams) if maps is None else maps
        if not self.maps:
            raise RuntimeError(f"No valid maps found in {MAPS_DIR}")
        default = config.get("default_map")
        self._use_map(default if default in self.maps else next(iter(self.maps)))
        self.state = LOBBY
        self.players: dict[str, Player] = {}
        self.bullets: list[Bullet] = []
        self._next_bullet_id = 1
        self.duration = config["default_game_duration"]
        self.ends_at: float | None = None
        self.time_left_at_end = 0.0
        # Team kills are counted separately so a player who disconnects
        # mid-match doesn't take their team's points with them.
        self.team_kills = {tid: 0 for tid in self.team_ids}
        self.kill_feed: list[dict] = []
        self.results: dict | None = None

    # ------------------------------------------------------------------ helpers
    def now(self) -> float:
        return time.monotonic()

    def _use_map(self, map_id: str) -> None:
        self.map_id = map_id
        self.map = self.maps[map_id]
        # What blocks each team's movement: all walls plus every *other* team's
        # spawn zone (players can't enter enemy spawns).
        self.blockers = {
            tid: self.map["walls"] + [z for zt, z in self.map["spawn_zones"].items() if zt != tid]
            for tid in self.team_ids
        }

    def max_total_players(self) -> int:
        return self.cfg["max_players_per_team"] * len(self.teams)

    def team_count(self, team_id: str) -> int:
        return sum(1 for p in self.players.values() if p.team == team_id and p.connected)

    def active_players(self):
        """Players currently taking part in the match (connected and in it)."""
        return (p for p in self.players.values() if p.in_match and p.connected)

    def in_own_spawn(self, p: Player) -> bool:
        zone = self.map["spawn_zones"].get(p.team)
        return zone is not None and collision.point_in_rect(p.x, p.y, zone)

    def is_protected(self, p: Player, now: float) -> bool:
        return now < p.invulnerable_until or self.in_own_spawn(p)

    def time_remaining(self, now: float | None = None) -> float:
        if self.state == RUNNING and self.ends_at is not None:
            return max(0.0, self.ends_at - (self.now() if now is None else now))
        if self.state == ENDED:
            return self.time_left_at_end
        return float(self.duration)

    # ------------------------------------------------------------ joining/teams
    def join(self, name) -> Player:
        name = _clean_name(name)
        if not name:
            raise GameError("Please enter a name.")
        if sum(1 for p in self.players.values() if p.connected) >= self.max_total_players():
            raise GameError("The server is full.")
        player = Player(id=uuid.uuid4().hex[:8], name=name)
        self.players[player.id] = player
        return player

    def resume(self, player_id: str, token: str, now: float | None = None) -> Player:
        """Reattach a player after a browser refresh or a dropped connection.

        The player may still be marked connected: after a Wi-Fi blip the
        browser reconnects before the server notices the old socket is dead.
        The token proves it's the same browser, so it takes over the player
        (the networking layer closes the stale socket)."""
        now = self.now() if now is None else now
        p = self.players.get(player_id)
        if p is None or not secrets.compare_digest(p.resume_token, str(token)):
            raise GameError("Session expired.")
        p.keys = {k: False for k in MOVE_KEYS}
        if p.connected:
            return p  # live takeover: keep position/health as they are
        p.connected = True
        if self.state == RUNNING and p.in_match:
            p.respawn_at = now + self.cfg["respawn_delay"]
        return p

    def disconnect(self, player_id: str, now: float | None = None) -> None:
        p = self.players.get(player_id)
        if p is None:
            return
        if self.state == LOBBY or not p.in_match:
            del self.players[player_id]
            return
        # Mid-match / results: keep stats but remove from gameplay entirely.
        p.connected = False
        p.alive = False
        p.respawn_at = None
        p.keys = {k: False for k in MOVE_KEYS}

    def choose_team(self, player_id: str, team_id, now: float | None = None) -> None:
        """Pick/change team. In LOBBY/ENDED anyone may; during a match only
        players not yet in it may, and doing so drops them straight in."""
        now = self.now() if now is None else now
        p = self.players.get(player_id)
        if p is None:
            raise GameError("Unknown player.")
        if self.state == RUNNING and p.in_match:
            raise GameError("Teams are locked during a match.")
        if team_id not in self.team_ids:
            raise GameError("Unknown team.")
        if p.team != team_id and self.team_count(team_id) >= self.cfg["max_players_per_team"]:
            raise GameError("That team is full.")
        p.team = team_id
        if self.state == RUNNING:
            p.reset_match_stats()
            p.in_match = True
            self._spawn(p, now)

    # ------------------------------------------------------------- admin/match
    def start(self, duration=None, now: float | None = None) -> None:
        now = self.now() if now is None else now
        if self.state == RUNNING:
            raise GameError("A match is already running.")
        if duration is not None:
            self.set_duration(duration)
        self._purge_disconnected()
        if not any(p.team for p in self.players.values()):
            raise GameError("No players have chosen a team yet.")
        self.bullets.clear()
        self.kill_feed.clear()
        self.results = None
        self.team_kills = {tid: 0 for tid in self.team_ids}
        for p in self.players.values():
            p.reset_match_stats()
            p.in_match = p.team is not None
            if p.in_match:
                self._spawn(p, now)
        self.state = RUNNING
        self.ends_at = now + self.duration

    def set_map(self, map_id) -> None:
        if self.state == RUNNING:
            raise GameError("The map can't be changed during a match.")
        if map_id not in self.maps:
            raise GameError("Unknown map.")
        self._use_map(map_id)

    def set_duration(self, duration) -> None:
        try:
            d = int(duration)
        except (TypeError, ValueError):
            raise GameError("Invalid duration.")
        self.duration = int(collision.clamp(d, self.cfg["min_game_duration"], self.cfg["max_game_duration"]))

    def end(self, now: float | None = None) -> None:
        if self.state != RUNNING:
            raise GameError("No match is running.")
        self.time_left_at_end = self.time_remaining(now)
        self.state = ENDED
        self.bullets.clear()
        for p in self.players.values():
            p.keys = {k: False for k in MOVE_KEYS}
        self.results = self._build_results()

    def back_to_lobby(self) -> None:
        if self.state == RUNNING:
            raise GameError("End the match first.")
        self.state = LOBBY
        self.results = None
        self.bullets.clear()
        self.kill_feed.clear()
        self._purge_disconnected()
        for p in self.players.values():
            p.reset_match_stats()
            p.in_match = False

    def _purge_disconnected(self) -> None:
        for pid in [pid for pid, p in self.players.items() if not p.connected]:
            del self.players[pid]

    # ------------------------------------------------------------------- input
    def set_keys(self, player_id: str, keys, now: float | None = None) -> None:
        p = self.players.get(player_id)
        if p is None or not isinstance(keys, dict):
            return
        p.keys = {k: keys.get(k) is True for k in MOVE_KEYS}
        p.last_input_at = self.now() if now is None else now

    def set_aim(self, player_id: str, angle) -> None:
        p = self.players.get(player_id)
        if p is not None and isinstance(angle, (int, float)) and math.isfinite(angle):
            p.angle = float(angle)

    def shoot(self, player_id: str, angle=None, now: float | None = None) -> Bullet | None:
        """Fire a bullet if the rules allow it. Returns the bullet or None."""
        now = self.now() if now is None else now
        p = self.players.get(player_id)
        if self.state != RUNNING or p is None or not (p.in_match and p.connected and p.alive):
            return None
        if now - p.last_shot_at < self.cfg["fire_cooldown"] - 1e-9:  # tolerate float rounding
            return None
        self.set_aim(player_id, angle)
        p.last_shot_at = now
        speed = self.cfg["bullet_speed"]
        # Bullets start at the shooter's centre; they never hit teammates, so
        # the shooter is ignored, and the first tick's sweep catches a wall the
        # shooter is pressed against.
        b = Bullet(
            id=self._next_bullet_id, owner_id=p.id, team=p.team, x=p.x, y=p.y,
            vx=math.cos(p.angle) * speed, vy=math.sin(p.angle) * speed,
            expires_at=now + self.cfg["bullet_lifetime"],
            confine=self._bullet_confine_zone(p.team) if self.in_own_spawn(p) else None,
        )
        self._next_bullet_id += 1
        self.bullets.append(b)
        return b

    def _bullet_confine_zone(self, team: str) -> dict:
        """The team's spawn zone shrunk so a confined bullet can't reach an
        enemy pressed against the outside of the zone. Enemies can't enter the
        zone, but their hitbox reaches hitbox_half_height further up/down than
        their movement circle, hence the larger vertical margin."""
        z = self.map["spawn_zones"][team]
        mx = self.cfg["bullet_radius"] + 1
        my = mx + self.cfg["hitbox_half_height"]
        return {"x": z["x"] + mx, "y": z["y"] + my,
                "width": max(0, z["width"] - 2 * mx), "height": max(0, z["height"] - 2 * my)}

    # -------------------------------------------------------------------- tick
    def tick(self, dt: float, now: float | None = None) -> None:
        """Advance the simulation by dt seconds (called at a fixed rate)."""
        now = self.now() if now is None else now
        if self.state != RUNNING:
            return
        self._move_players(dt, now)
        self._move_bullets(dt, now)
        self._process_respawns(now)
        if now >= self.ends_at:
            self.end(now)

    def _move_players(self, dt: float, now: float) -> None:
        r, speed = self.cfg["player_radius"], self.cfg["player_speed"]
        for p in self.active_players():
            if not p.alive:
                continue
            # Clients re-send their key state several times a second. If that
            # stops (frozen tab, dead connection, lost key-up) release the keys
            # instead of letting the player run on forever.
            if now - p.last_input_at > self.cfg["input_timeout"]:
                p.keys = {k: False for k in MOVE_KEYS}
            dx = (1 if p.keys["d"] else 0) - (1 if p.keys["a"] else 0)
            dy = (1 if p.keys["s"] else 0) - (1 if p.keys["w"] else 0)
            if dx == 0 and dy == 0:
                continue
            length = math.hypot(dx, dy)  # normalise so diagonals aren't faster
            nx = p.x + dx / length * speed * dt
            ny = p.y + dy / length * speed * dt
            p.x, p.y = collision.resolve_circle_walls(
                nx, ny, r, self.blockers[p.team], self.map["width"], self.map["height"])

    def _move_bullets(self, dt: float, now: float) -> None:
        br = self.cfg["bullet_radius"]
        hit_r = self.cfg["player_radius"] + br
        half_h = self.cfg["hitbox_half_height"]
        targets = [p for p in self.active_players() if p.alive]
        survivors = []
        for b in self.bullets:
            if now >= b.expires_at:
                continue
            x1, y1 = b.x + b.vx * dt, b.y + b.vy * dt
            # A bullet fired from spawn is cut off at the zone edge *before* hit
            # checks, so it can't reach anyone standing just outside.
            leaves_spawn = b.confine is not None and not collision.point_in_rect(x1, y1, b.confine)
            if leaves_spawn:
                t = collision.segment_rect_exit(b.x, b.y, x1, y1, b.confine)
                x1, y1 = b.x + (x1 - b.x) * t, b.y + (y1 - b.y) * t
            # Find the earliest thing along this tick's path: a wall or an enemy.
            first_t, victim = None, None
            for wall in self.map["walls"]:
                t = collision.segment_rect_hit(b.x, b.y, x1, y1, wall, br)
                if t is not None and (first_t is None or t < first_t):
                    first_t, victim = t, None
            for p in targets:
                if p.team == b.team:
                    continue  # friendly fire disabled: bullets pass through teammates
                # players are drawn standing upright: hit a capsule from head to feet
                t = collision.segment_capsule_hit(b.x, b.y, x1, y1, p.x, p.y, half_h, hit_r)
                if t is not None and (first_t is None or t < first_t):
                    first_t, victim = t, p
            if first_t is not None:
                if victim is not None and victim.alive:
                    self._apply_hit(b, victim, now)
                continue  # bullet is consumed by the wall or player
            if leaves_spawn:
                continue
            if not (0 <= x1 <= self.map["width"] and 0 <= y1 <= self.map["height"]):
                continue
            b.x, b.y = x1, y1
            survivors.append(b)
        self.bullets = survivors

    def _apply_hit(self, bullet: Bullet, victim: Player, now: float) -> None:
        if self.is_protected(victim, now):
            return  # spawn protection: the bullet is absorbed, no damage
        victim.health -= 1
        if victim.health > 0:
            return
        victim.alive = False
        victim.deaths += 1
        victim.respawn_at = now + self.cfg["respawn_delay"]
        killer = self.players.get(bullet.owner_id)
        if killer is not None:
            killer.kills += 1
        self.team_kills[bullet.team] = self.team_kills.get(bullet.team, 0) + 1
        self.kill_feed.append({
            "killer": killer.name if killer else "?", "killer_team": bullet.team,
            "victim": victim.name, "victim_team": victim.team,
        })
        del self.kill_feed[: -self.cfg["kill_feed_size"]]

    def _process_respawns(self, now: float) -> None:
        for p in self.active_players():
            if not p.alive and p.respawn_at is not None and now >= p.respawn_at:
                self._spawn(p, now)

    def _spawn(self, p: Player, now: float) -> None:
        """Place p in its team's spawn zone, as far from other players as possible."""
        zone = self.map["spawn_zones"][p.team]
        r = self.cfg["player_radius"]
        others = [(o.x, o.y) for o in self.active_players() if o.alive and o is not p]
        best, best_dist = None, -1.0
        for _ in range(12):
            x = random.uniform(zone["x"] + r, zone["x"] + zone["width"] - r)
            y = random.uniform(zone["y"] + r, zone["y"] + zone["height"] - r)
            if any(collision.circle_rect_overlap(x, y, r, w) for w in self.map["walls"]):
                continue
            dist = min((math.hypot(x - ox, y - oy) for ox, oy in others), default=math.inf)
            if dist > best_dist:
                best, best_dist = (x, y), dist
            if dist > 3 * r:
                break
        if best is None:
            best = (zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] / 2)
        p.x, p.y = best
        p.health = self.cfg["player_health"]
        p.alive = True
        p.respawn_at = None
        p.invulnerable_until = now + self.cfg["spawn_protection_duration"]

    # ----------------------------------------------------------------- scoring
    def score(self, p: Player) -> int:
        return p.kills * self.cfg["kill_score"]

    def _team_rows(self) -> list[dict]:
        return [{
            "id": t["id"], "name": t["name"], "color": t["color"],
            "count": self.team_count(t["id"]), "max": self.cfg["max_players_per_team"],
            "kills": self.team_kills.get(t["id"], 0),
        } for t in self.teams]

    def _build_results(self) -> dict:
        teams = sorted(
            (t for t in self._team_rows() if any(p.team == t["id"] and p.in_match for p in self.players.values())),
            key=lambda t: -t["kills"])
        winners = [t["id"] for t in teams if teams and t["kills"] == teams[0]["kills"]]
        players = sorted(
            (p for p in self.players.values() if p.in_match),
            key=lambda p: (-p.kills, p.deaths, p.name.lower()))
        return {
            "winners": winners,  # more than one entry means a draw
            "teams": teams,
            "players": [{
                "id": p.id, "name": p.name, "team": p.team, "kills": p.kills,
                "deaths": p.deaths, "score": self.score(p), "connected": p.connected,
            } for p in players],
        }

    # ---------------------------------------------------------------- snapshot
    def snapshot(self, now: float | None = None) -> dict:
        """Everything clients need to render, sent every tick."""
        now = self.now() if now is None else now
        players = []
        for p in self.players.values():
            if not p.connected:
                continue
            row = {"id": p.id, "name": p.name, "team": p.team, "in_match": p.in_match,
                   "alive": p.alive, "kills": p.kills, "deaths": p.deaths}
            if self.state != LOBBY and p.in_match:
                row.update({
                    "x": round(p.x, 1), "y": round(p.y, 1), "angle": round(p.angle, 3),
                    "health": p.health, "protected": p.alive and self.is_protected(p, now),
                    "invulnerable": p.alive and now < p.invulnerable_until,
                    "respawn_in": round(max(0.0, p.respawn_at - now), 1) if p.respawn_at else None,
                })
            players.append(row)
        return {
            "type": "state",
            "game_state": self.state,
            "map_id": self.map_id,
            "time_remaining": round(self.time_remaining(now), 1),
            "duration": self.duration,
            "teams": self._team_rows(),
            "players": players,
            "bullets": [{"id": b.id, "x": round(b.x, 1), "y": round(b.y, 1), "team": b.team} for b in self.bullets],
            "kill_feed": self.kill_feed,
            "results": self.results,
        }
