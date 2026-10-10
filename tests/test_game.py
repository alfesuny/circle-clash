"""Rule tests for game.game.Game (no networking). Time is passed explicitly."""

import math

import pytest

from game.config import GAME_CONFIG, TEAMS
from game.game import ENDED, LOBBY, RUNNING, Game, GameError
from game.maps import build_map

# A small fixed map (1:1 pixel->world) so geometry tests don't depend on the
# real maps in Maps/. Team "a" spawns top-left, team "b" bottom-centre.
TEST_MAP = build_map("Test", {
    "image_size": [1000, 700],
    "walls": [
        [250, 150, 200, 30], [550, 150, 200, 30],        # upper bars
        [150, 330, 30, 160], [820, 330, 30, 160],        # side pillars
        [400, 335, 200, 30], [485, 260, 30, 180],        # centre cross
        [230, 520, 150, 30], [620, 520, 150, 30],        # lower bars
    ],
    "spawn_zones": [[20, 20, 130, 130], [435, 560, 130, 130]],
}, TEAMS)
OTHER_MAP = build_map("Other", {"image_size": [800, 600], "walls": [[300, 300, 50, 50]],
                                "spawn_zones": [[0, 0, 100, 100], [700, 500, 100, 100]]}, TEAMS)

R = GAME_CONFIG["player_radius"]
DT = 1 / GAME_CONFIG["tick_rate"]
PROTECT = GAME_CONFIG["spawn_protection_duration"]


def new_game():
    return Game(maps={"Test": TEST_MAP, "Other": OTHER_MAP})


def make_game(*teams):
    """Game with one player per given team, in the lobby. Returns (game, players)."""
    g = new_game()
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


def running_duel(team_a="a", team_b="b", duration=300):
    """Two players in open space, 120 units apart, spawn protection expired."""
    g, (a, b) = make_game(team_a, team_b)
    g.start(duration, now=0)
    place(a, 580, 250)
    place(b, 700, 250)
    return g, a, b, PROTECT + 1  # a time after spawn protection has worn off


def shoot_and_resolve(g, shooter, target, now):
    angle = math.atan2(target.y - shooter.y, target.x - shooter.x)
    bullet = g.shoot(shooter.id, angle, now=now)
    # resolve the shot and let the gun cool down (+1 tick: run() rounds down to whole ticks)
    return bullet, run(g, now, max(0.5, GAME_CONFIG["fire_cooldown"]) + DT)


# ------------------------------------------------------------------ teams/join
def test_team_capacity_enforced():
    g = new_game()
    for i in range(GAME_CONFIG["max_players_per_team"]):
        g.choose_team(g.join(f"r{i}").id, "a")
    extra = g.join("extra")
    with pytest.raises(GameError):
        g.choose_team(extra.id, "a")
    g.choose_team(extra.id, "b")
    assert extra.team == "b"


def test_change_team_in_lobby_but_not_during_match():
    g, (p,) = make_game("a")
    g.choose_team(p.id, "b")
    assert p.team == "b"
    g.start(60, now=0)
    with pytest.raises(GameError):
        g.choose_team(p.id, "a")
    assert p.team == "b"


def test_unknown_team_and_empty_name_rejected():
    g = new_game()
    with pytest.raises(GameError):
        g.join("   ")
    p = g.join("ok")
    with pytest.raises(GameError):
        g.choose_team(p.id, "purple")


def test_two_teams_of_seven():
    g = new_game()
    assert [t["id"] for t in g.teams] == ["a", "b"]
    assert g.max_total_players() == 14
    for i in range(14):
        g.join(f"p{i}")
    with pytest.raises(GameError, match="full"):
        g.join("fifteenth")


def test_can_join_running_match_and_pick_a_team():
    g, (a,) = make_game("a")
    g.start(60, now=0)
    late = g.join("late")
    assert not late.in_match and late.team is None
    g.choose_team(late.id, "b", now=5)
    assert late.in_match and late.alive and late.team == "b"
    assert g.in_own_spawn(late) and g.is_protected(late, 5)
    assert late.health == GAME_CONFIG["player_health"]
    # once in the match the team is locked
    with pytest.raises(GameError, match="locked"):
        g.choose_team(late.id, "a", now=6)
    # and the joiner shows up as a playing participant
    row = next(p for p in g.snapshot(now=6)["players"] if p["id"] == late.id)
    assert row["in_match"] and row["x"] is not None


def test_late_joiner_cannot_pick_full_team_mid_match():
    g = new_game()
    for i in range(GAME_CONFIG["max_players_per_team"]):
        g.choose_team(g.join(f"a{i}").id, "a")
    g.start(60, now=0)
    late = g.join("late")
    with pytest.raises(GameError, match="full"):
        g.choose_team(late.id, "a", now=1)
    assert not late.in_match
    g.choose_team(late.id, "b", now=1)
    assert late.in_match


def test_late_joiner_who_waits_sits_out():
    g, _ = make_game("a")
    g.start(60, now=0)
    waiter = g.join("waiter")
    run(g, 0, 1)
    assert not waiter.in_match and not waiter.alive
    g.end(now=2)
    g.back_to_lobby()
    g.choose_team(waiter.id, "b")
    g.start(60, now=3)
    assert waiter.in_match


def test_player_ids_do_not_depend_on_name():
    g = new_game()
    a, b = g.join("Same"), g.join("Same")
    assert a.id != b.id


# ------------------------------------------------------------------ admin/start
def test_start_with_few_players_and_teamless_players_sit_out():
    g, (p,) = make_game("a")
    idle = g.join("idle")
    g.start(60, now=0)
    assert g.state == RUNNING
    assert p.in_match and p.alive
    assert not idle.in_match


def test_cannot_start_without_any_team():
    g = new_game()
    g.join("nobody")
    with pytest.raises(GameError):
        g.start(60, now=0)


def test_duration_is_configurable_and_clamped():
    g, _ = make_game("a")
    g.start(90, now=0)
    assert g.time_remaining(now=0) == 90
    g2, _ = make_game("a")
    g2.set_duration(10**9)
    assert g2.duration == GAME_CONFIG["max_game_duration"]


# ------------------------------------------------------------------ movement
def test_cannot_leave_map():
    g, (p,) = make_game("a")
    g.start(60, now=0)
    place(p, 300, 40)
    g.set_keys(p.id, {"w": True}, now=0)
    run(g, 0, 1)
    assert p.y == pytest.approx(R)


def test_keys_released_when_input_stops():
    g, (p,) = make_game("a")
    g.start(60, now=0)
    place(p, 600, 250)
    g.set_keys(p.id, {"d": True}, now=0)
    t = run(g, 0, GAME_CONFIG["input_timeout"] + 0.5)
    x_after_timeout = p.x
    assert x_after_timeout > 600
    run(g, t, 1)
    assert p.x == x_after_timeout  # stopped once the client went quiet
    assert not any(p.keys.values())


def test_key_heartbeat_keeps_player_moving():
    g, (p,) = make_game("a")
    g.start(60, now=0)
    place(p, 900, 30)  # open column on the right edge
    t = 0.0
    for _ in range(int(2 * GAME_CONFIG["tick_rate"])):  # 2 s with a heartbeat every tick
        g.set_keys(p.id, {"s": True}, now=t)
        t += DT
        g.tick(DT, t)
    # moved for longer than input_timeout would allow without the heartbeat
    assert p.keys["s"] and p.y > 30 + GAME_CONFIG["player_speed"] * (GAME_CONFIG["input_timeout"] + 0.5)


def test_cannot_walk_through_walls():
    g, (p,) = make_game("a")
    g.start(60, now=0)
    wall = TEST_MAP["walls"][0]  # x 250..450, y 150..180
    place(p, 350, 100)
    g.set_keys(p.id, {"s": True}, now=0)
    run(g, 0, 2)
    assert p.y <= wall["y"] - R + 1e-6


def test_diagonal_not_faster():
    g, (p,) = make_game("a")
    g.start(60, now=0)
    place(p, 600, 250)
    g.set_keys(p.id, {"d": True, "s": True}, now=0)
    g.tick(DT, DT)
    assert math.hypot(p.x - 600, p.y - 250) == pytest.approx(GAME_CONFIG["player_speed"] * DT)


def test_invalid_keys_ignored():
    g, (p,) = make_game("a")
    g.set_keys(p.id, {"w": "yes", "a": 1, "hack": True})
    assert p.keys == {"w": False, "a": False, "s": False, "d": False}


# ------------------------------------------------------------------ shooting
def test_cannot_shoot_before_start_or_after_end():
    g, (p,) = make_game("a")
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
    g, a, b, t = running_duel("a", "a")
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]


def test_hitbox_covers_head_and_feet():
    """Players are drawn standing upright, so the hitbox is a vertical capsule:
    taller than the movement circle, same width."""
    reach = R + GAME_CONFIG["bullet_radius"] + GAME_CONFIG["hitbox_half_height"]
    for dy, hit in ((-(reach - 2), True), (reach - 2, True), (-(reach + 2), False), (reach + 2, False)):
        g, a, b, t = running_duel()
        place(a, 580, b.y + dy)
        g.shoot(a.id, 0.0, now=t)  # straight right, passing b at vertical offset dy
        run(g, t, 0.5)
        assert (b.health < GAME_CONFIG["player_health"]) == hit, dy


def test_hitbox_is_no_wider_than_the_circle():
    g, a, b, t = running_duel()
    side = R + GAME_CONFIG["bullet_radius"] + 2
    place(a, b.x + side, b.y - 150)
    g.shoot(a.id, math.pi / 2, now=t)  # straight down, just beside b
    run(g, t, 0.5)
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
    assert g.team_kills["a"] == 1
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
    zone = TEST_MAP["spawn_zones"]["b"]
    assert zone["x"] <= b.x <= zone["x"] + zone["width"]
    assert zone["y"] <= b.y <= zone["y"] + zone["height"]
    assert g.is_protected(b, t)


def test_spawn_protection_after_respawn():
    g, (a, b) = make_game("a", "b")
    g.start(300, now=0)
    place(a, 580, 250)
    place(b, 700, 250)  # out of spawn zone, but within post-spawn invulnerability
    shoot_and_resolve(g, a, b, 0.5)
    assert b.health == GAME_CONFIG["player_health"]


def test_spawn_zone_prevents_damage():
    g, a, b, t = running_duel()
    zone = TEST_MAP["spawn_zones"]["b"]
    place(b, zone["x"] + zone["width"] / 2, zone["y"] + 20)
    place(a, b.x, b.y - 150)
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]


def test_bullets_fired_from_spawn_do_not_leave_it():
    g, a, b, t = running_duel()
    zone = TEST_MAP["spawn_zones"]["a"]  # x 20..150, y 20..150
    place(a, zone["x"] + 100, zone["y"] + 65)   # inside own spawn
    place(b, zone["x"] + zone["width"] + R, a.y)  # pressed against the zone edge, in the line of fire
    bullet, t = shoot_and_resolve(g, a, b, t)
    assert bullet.confine is not None
    assert b.health == GAME_CONFIG["player_health"]
    assert not g.bullets


def test_spawn_bullets_cannot_reach_enemy_head_below_the_zone():
    """The taller hitbox reaches into the spawn zone from an enemy standing
    right below it; a bullet fired from inside must still not hit them."""
    g, a, b, t = running_duel()
    zone = TEST_MAP["spawn_zones"]["a"]
    place(b, zone["x"] + 60, zone["y"] + zone["height"] + R)  # pressed against the bottom edge
    place(a, b.x, b.y - 60)                                     # inside own spawn, straight above b
    assert g.in_own_spawn(a)
    bullet, t = shoot_and_resolve(g, a, b, t)
    assert bullet.confine is not None
    assert b.health == GAME_CONFIG["player_health"]


def test_bullets_fired_outside_spawn_travel_normally():
    g, a, b, t = running_duel()
    zone = TEST_MAP["spawn_zones"]["a"]
    place(a, zone["x"] + zone["width"] + 5, zone["y"] + 65)  # just outside own spawn
    place(b, a.x + 100, a.y)
    bullet, _ = shoot_and_resolve(g, a, b, t)
    assert bullet.confine is None
    assert b.health == GAME_CONFIG["player_health"] - 1


def test_cannot_enter_enemy_spawn():
    g, a, b, t = running_duel()
    zone = TEST_MAP["spawn_zones"]["a"]
    place(b, zone["x"] + zone["width"] + 40, zone["y"] + 65)  # blue, right of RED spawn
    g.set_keys(b.id, {"a": True}, now=t)
    run(g, t, 2)
    assert b.x >= zone["x"] + zone["width"] + R - 1e-6


def test_can_walk_back_into_own_spawn():
    g, a, b, t = running_duel()
    zone = TEST_MAP["spawn_zones"]["a"]
    place(a, zone["x"] + zone["width"] + 40, zone["y"] + 65)
    g.set_keys(a.id, {"a": True}, now=t)
    run(g, t, 0.4)  # ~88 units: well inside the 130-wide zone
    assert g.in_own_spawn(a)


# ------------------------------------------------------------------ maps
def test_map_selection_only_outside_a_match():
    g, (a, b) = make_game("a", "b")
    assert g.map_id == "Test"
    g.set_map("Other")
    assert g.map is OTHER_MAP and g.snapshot()["map_id"] == "Other"
    with pytest.raises(GameError):
        g.set_map("Nope")
    g.start(60, now=0)
    assert g.in_own_spawn(a) and g.in_own_spawn(b)  # spawned on the selected map
    with pytest.raises(GameError):
        g.set_map("Test")
    g.end(now=1)
    g.set_map("Test")
    assert g.map is TEST_MAP


def test_enemy_spawn_blockers_follow_the_map():
    g = new_game()
    g.set_map("Other")
    assert OTHER_MAP["spawn_zones"]["b"] in g.blockers["a"]
    assert OTHER_MAP["spawn_zones"]["a"] not in g.blockers["a"]


# ------------------------------------------------------------------ timer/results
def test_match_ends_automatically_and_results_remain():
    g, a, b, t = running_duel(duration=20)
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    run(g, t, 20)
    assert g.state == ENDED
    assert g.results["winners"] == ["a"]
    assert g.results["players"][0]["id"] == a.id
    assert g.results["players"][0]["kills"] == 1
    assert g.snapshot()["results"] is not None


def test_draw_when_tied():
    g, _ = make_game("a", "b")
    g.start(60, now=0)
    g.end(now=1)
    assert set(g.results["winners"]) == {"a", "b"}


def test_new_game_resets_stats():
    g, a, b, t = running_duel()
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    g.end(now=t)
    g.start(60, now=t + 1)
    assert a.kills == 0 and b.deaths == 0 and g.team_kills["a"] == 0
    g.end(now=t + 2)
    g.back_to_lobby()
    assert g.state == LOBBY and a.team == "a"


# ------------------------------------------------------------------ connections
def test_disconnect_in_lobby_removes_player():
    g, (p,) = make_game("a")
    g.disconnect(p.id)
    assert p.id not in g.players
    assert g.team_count("a") == 0


def test_disconnect_mid_match_removes_from_play_but_keeps_stats():
    g, a, b, t = running_duel()
    for _ in range(GAME_CONFIG["player_health"]):
        _, t = shoot_and_resolve(g, a, b, t)
    g.disconnect(a.id)
    assert not a.alive
    assert all(p["id"] != a.id for p in g.snapshot()["players"])
    g.end(now=t)
    assert g.team_kills["a"] == 1
    assert any(p["id"] == a.id and p["kills"] == 1 for p in g.results["players"])


def test_disconnected_player_is_not_hit():
    g, a, b, t = running_duel()
    g.disconnect(b.id)
    shoot_and_resolve(g, a, b, t)
    assert b.health == GAME_CONFIG["player_health"]


def test_resume_takes_over_a_still_connected_session():
    """Wi-Fi blip: the browser reconnects before the server saw the old socket die."""
    g, a, b, t = running_duel()
    g.set_keys(a.id, {"d": True}, now=t)
    x, kills = a.x, a.kills
    p = g.resume(a.id, a.resume_token, now=t)
    assert p is a and a.connected and a.alive and a.x == x and a.kills == kills
    assert not any(a.keys.values())  # held keys from the dead connection are dropped
    with pytest.raises(GameError):
        g.resume(a.id, "wrong-token", now=t)


def test_resume_after_refresh():
    g, a, b, t = running_duel()
    g.disconnect(a.id)
    with pytest.raises(GameError):
        g.resume(a.id, "wrong-token", now=t)
    p = g.resume(a.id, a.resume_token, now=t)
    assert p is a and a.connected and a.team == "a"
    run(g, t, GAME_CONFIG["respawn_delay"] + 0.1)
    assert a.alive
