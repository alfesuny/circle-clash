"""Rule tests for game.game.Game (no networking). Time is passed explicitly."""

import math

import pytest

from game.config import GAME_CONFIG, MAP
from game.game import ENDED, LOBBY, RUNNING, Game, GameError

R = GAME_CONFIG["player_radius"]
DT = 1 / GAME_CONFIG["tick_rate"]
PROTECT = GAME_CONFIG["spawn_protection_duration"]


def make_game(*teams):
    """Game with one player per given team, in the lobby. Returns (game, players)."""
    g = Game()
    players = []
    for i, team in enumerate(teams):
        p = g.join(f"p{i}")
        g.choose_team(p.id, team)
        players.append(p)
    return g, players


def run(g, start, seconds):
    """Tick the game from `start` for `seconds`; returns the end time."""
    t = start
    for _ in range(int(seconds / DT)):
        t += DT
        g.tick(DT, t)
    return t


def place(p, x, y):
    p.x, p.y = x, y


def running_duel(team_a="red", team_b="blue", duration=300):
    """Two players in open space, 120 units apart, spawn protection expired."""
    g, (a, b) = make_game(team_a, team_b)
    g.start(duration, now=0)
    place(a, 580, 250)
    place(b, 700, 250)
    return g, a, b, PROTECT + 1  # a time after spawn protection has worn off


def shoot_and_resolve(g, shooter, target, now):
    angle = math.atan2(target.y - shooter.y, target.x - shooter.x)
    bullet = g.shoot(shooter.id, angle, now=now)
    return bullet, run(g, now, 0.5)


# ------------------------------------------------------------------ teams/join
def test_team_capacity_enforced():
    g = Game()
    for i in range(GAME_CONFIG["max_players_per_team"]):
        g.choose_team(g.join(f"r{i}").id, "red")
    extra = g.join("extra")
    with pytest.raises(GameError):
        g.choose_team(extra.id, "red")
    g.choose_team(extra.id, "green")
    assert extra.team == "green"


def test_change_team_in_lobby_but_not_during_match():
    g, (p,) = make_game("red")
    g.choose_team(p.id, "blue")
    assert p.team == "blue"
    g.start(60, now=0)
    with pytest.raises(GameError):
        g.choose_team(p.id, "red")
    assert p.team == "blue"


def test_unknown_team_and_empty_name_rejected():
    g = Game()
    with pytest.raises(GameError):
        g.join("   ")
    p = g.join("ok")
    with pytest.raises(GameError):
        g.choose_team(p.id, "purple")


def test_cannot_join_running_match():
    g, _ = make_game("red")
    g.start(60, now=0)
    with pytest.raises(GameError):
        g.join("late")


def test_player_ids_do_not_depend_on_name():
    g = Game()
    a, b = g.join("Same"), g.join("Same")
    assert a.id != b.id


# ------------------------------------------------------------------ admin/start
def test_start_with_few_players_and_teamless_players_sit_out():
    g, (p,) = make_game("red")
    idle = g.join("idle")
    g.start(60, now=0)
    assert g.state == RUNNING
    assert p.in_match and p.alive
    assert not idle.in_match


def test_cannot_start_without_any_team():
    g = Game()
    g.join("nobody")
    with pytest.raises(GameError):
        g.start(60, now=0)


def test_duration_is_configurable_and_clamped():
    g, _ = make_game("red")
    g.start(90, now=0)
    assert g.time_remaining(now=0) == 90
    g2, _ = make_game("red")
    g2.set_duration(10**9)
    assert g2.duration == GAME_CONFIG["max_game_duration"]


# ------------------------------------------------------------------ movement
def test_cannot_leave_map():
    g, (p,) = make_game("red")
    g.start(60, now=0)
    place(p, 300, 40)
    g.set_keys(p.id, {"w": True})
    run(g, 0, 1)
    assert p.y == pytest.approx(R)


def test_cannot_walk_through_walls():
    g, (p,) = make_game("red")
    g.start(60, now=0)
    wall = MAP["walls"][0]  # x 250..450, y 150..180
    place(p, 350, 100)
    g.set_keys(p.id, {"s": True})
    run(g, 0, 2)
    assert p.y <= wall["y"] - R + 1e-6


def test_diagonal_not_faster():
    g, (p,) = make_game("red")
    g.start(60, now=0)
    place(p, 600, 250)
    g.set_keys(p.id, {"d": True, "s": True})
    g.tick(DT, DT)
    assert math.hypot(p.x - 600, p.y - 250) == pytest.approx(GAME_CONFIG["player_speed"] * DT)


def test_invalid_keys_ignored():
    g, (p,) = make_game("red")
    g.set_keys(p.id, {"w": "yes", "a": 1, "hack": True})
    assert p.keys == {"w": False, "a": False, "s": False, "d": False}


# ------------------------------------------------------------------ shooting
def test_cannot_shoot_before_start_or_after_end():
    g, (p,) = make_game("red")
    assert g.shoot(p.id, 0, now=0) is None
    g.start(60, now=0)
    assert g.shoot(p.id, 0, now=1) is not None
    g.end(now=2)
    assert g.shoot(p.id, 0, now=5) is None


def test_fire_rate_limit():
    g, a, b, t = running_duel()
    assert g.shoot(a.id, 0, now=t) is not None
    assert g.shoot(a.id, 0, now=t + GAME_CONFIG["fire_cooldown"] / 2) is None
    assert g.shoot(a.id, 0, now=t + GAME_CONFIG["fire_cooldown"]) is not None


def test_dead_players_cannot_shoot():
    g, a, b, t = running_duel()
    a.alive = False
    assert g.shoot(a.id, 0, now=t) is None


def test_hit_enemy_reduces_health_by_one():
    g, a, b, t = running_duel()
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"] - 1
    assert not g.bullets


def test_no_friendly_fire():
    g, a, b, t = running_duel("red", "red")
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]


def test_walls_block_bullets():
    g, a, b, t = running_duel()
    # centre vertical wall is x 485..515, y 260..440
    place(a, 440, 300)
    place(b, 570, 300)
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]
    assert not g.bullets


def test_bullet_leaves_map_and_is_removed():
    g, a, b, t = running_duel()
    g.shoot(a.id, -math.pi / 2, now=t)  # straight up into open space, then off the map
    run(g, t, 1)
    assert not g.bullets


# ------------------------------------------------------------------ damage/death
def test_four_hits_kill_and_credit_killer():
    g, a, b, t = running_duel()
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    assert not b.alive
    assert b.deaths == 1
    assert a.kills == 1 and a.deaths == 0
    assert g.team_kills["red"] == 1
    assert g.score(a) == GAME_CONFIG["kill_score"]
    assert g.kill_feed[-1]["killer"] == a.name


def test_respawn_after_delay_in_own_zone_with_protection():
    g, a, b, t = running_duel()
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    died_at = b.respawn_at - GAME_CONFIG["respawn_delay"]
    t = run(g, t, died_at + GAME_CONFIG["respawn_delay"] - t - 0.1)
    assert not b.alive
    t = run(g, t, 0.2)
    assert b.alive and b.health == GAME_CONFIG["player_health"]
    zone = MAP["spawn_zones"]["blue"]
    assert zone["x"] <= b.x <= zone["x"] + zone["width"]
    assert zone["y"] <= b.y <= zone["y"] + zone["height"]
    assert g.is_protected(b, t)


def test_spawn_protection_after_respawn():
    g, (a, b) = make_game("red", "blue")
    g.start(300, now=0)
    place(a, 580, 250)
    place(b, 700, 250)  # out of spawn zone, but within post-spawn invulnerability
    shoot_and_resolve(g, a, b, 0.5)
    assert b.health == GAME_CONFIG["player_health"]


def test_spawn_zone_prevents_damage():
    g, a, b, t = running_duel()
    zone = MAP["spawn_zones"]["blue"]
    place(b, zone["x"] + zone["width"] / 2, zone["y"] + 20)
    place(a, b.x, b.y - 150)
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]


def test_enemy_spawn_zone_does_not_protect_intruder():
    g, a, b, t = running_duel()
    zone = MAP["spawn_zones"]["red"]  # blue player standing in RED's spawn
    place(b, zone["x"] + 60, zone["y"] + 60)
    place(a, zone["x"] + 60, zone["y"] + 180)
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"] - 1


# ------------------------------------------------------------------ timer/results
def test_match_ends_automatically_and_results_remain():
    g, a, b, t = running_duel(duration=20)
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    run(g, t, 20)
    assert g.state == ENDED
    assert g.results["winners"] == ["red"]
    assert g.results["players"][0]["id"] == a.id
    assert g.results["players"][0]["kills"] == 1
    assert g.snapshot()["results"] is not None


def test_draw_when_tied():
    g, _ = make_game("red", "blue")
    g.start(60, now=0)
    g.end(now=1)
    assert set(g.results["winners"]) == {"red", "blue"}


def test_new_game_resets_stats():
    g, a, b, t = running_duel()
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    g.end(now=t)
    g.start(60, now=t + 1)
    assert a.kills == 0 and b.deaths == 0 and g.team_kills["red"] == 0
    g.end(now=t + 2)
    g.back_to_lobby()
    assert g.state == LOBBY and a.team == "red"


# ------------------------------------------------------------------ connections
def test_disconnect_in_lobby_removes_player():
    g, (p,) = make_game("red")
    g.disconnect(p.id)
    assert p.id not in g.players
    assert g.team_count("red") == 0


def test_disconnect_mid_match_removes_from_play_but_keeps_stats():
    g, a, b, t = running_duel()
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    g.disconnect(a.id)
    assert not a.alive
    assert all(p["id"] != a.id for p in g.snapshot()["players"])
    g.end(now=t)
    assert g.team_kills["red"] == 1
    assert any(p["id"] == a.id and p["kills"] == 1 for p in g.results["players"])


def test_disconnected_player_is_not_hit():
    g, a, b, t = running_duel()
    g.disconnect(b.id)
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]


def test_resume_after_refresh():
    g, a, b, t = running_duel()
    g.disconnect(a.id)
    with pytest.raises(GameError):
        g.resume(a.id, "wrong-token", now=t)
    p = g.resume(a.id, a.resume_token, now=t)
    assert p is a and a.connected and a.team == "red"
    run(g, t, GAME_CONFIG["respawn_delay"] + 0.1)
    assert a.alive
