"""Validate every real map in Maps/: it loads, its geometry is sane and every
open area is reachable for both teams."""

import json
from collections import deque

import pytest

from game import collision
from game.config import GAME_CONFIG, MAPS_DIR, TEAMS
from game.game import Game
from game.maps import MapError, build_map, load_maps

R = GAME_CONFIG["player_radius"]
MAPS = load_maps(MAPS_DIR, TEAMS)


def test_every_map_folder_loads():
    folders = sorted(p.name for p in MAPS_DIR.iterdir() if p.is_dir())
    assert folders and sorted(MAPS) == folders
    assert GAME_CONFIG["default_map"] in MAPS


def test_map_json_scales_pixels_to_world():
    m = build_map("T", {"image_size": [200, 100], "world_size": [400, 400],
                        "walls": [[10, 10, 20, 20]], "spawn_zones": [[0, 0, 10, 10], [190, 90, 10, 10]]}, TEAMS)
    assert m["walls"][0] == {"x": 20, "y": 40, "width": 40, "height": 80}
    assert m["spawn_zones"]["b"] == {"x": 380, "y": 360, "width": 20, "height": 40}


def test_map_needs_one_spawn_per_team():
    with pytest.raises(MapError):
        build_map("T", {"image_size": [10, 10], "walls": [], "spawn_zones": [[0, 0, 5, 5]]}, TEAMS)


def test_broken_map_folder_is_skipped(tmp_path):
    (tmp_path / "Broken").mkdir()
    (tmp_path / "Broken" / "map.json").write_text("{not json")
    (tmp_path / "NoImage").mkdir()
    (tmp_path / "NoImage" / "map.json").write_text(json.dumps(
        {"image": "x.jpg", "image_size": [10, 10], "walls": [], "spawn_zones": [[0, 0, 1, 1], [2, 2, 1, 1]]}))
    assert load_maps(tmp_path, TEAMS) == {}


@pytest.mark.parametrize("map_id", sorted(MAPS))
def test_spawn_zones_are_open_and_inside(map_id):
    m = MAPS[map_id]
    for zone in m["spawn_zones"].values():
        assert 0 <= zone["x"] and zone["x"] + zone["width"] <= m["width"]
        assert 0 <= zone["y"] and zone["y"] + zone["height"] <= m["height"]
        cx, cy = zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] / 2
        assert not any(collision.point_in_rect(cx, cy, w) for w in m["walls"])
    zones = list(m["spawn_zones"].values())
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            assert collision.segment_rect_hit(a["x"], a["y"], a["x"] + a["width"], a["y"] + a["height"], b) is None


@pytest.mark.parametrize("map_id", sorted(MAPS))
def test_full_team_spawns_without_overlap(map_id):
    g = Game(maps={map_id: MAPS[map_id]})
    for team in g.team_ids:
        for i in range(GAME_CONFIG["max_players_per_team"]):
            g.choose_team(g.join(f"{team}{i}").id, team)
    g.start(60, now=0)
    players = list(g.players.values())
    for p in players:
        assert g.in_own_spawn(p)
        assert not any(collision.circle_rect_overlap(p.x, p.y, R, w) for w in g.map["walls"])


def _reachable(m, team, start, step=6.0):
    """Grid flood fill of the positions a player of `team` can stand on."""
    blockers = m["walls"] + [z for t, z in m["spawn_zones"].items() if t != team]
    cols, rows = int(m["width"] // step), int(m["height"] // step)

    def free(c, r):
        x, y = (c + 0.5) * step, (r + 0.5) * step
        if not (R <= x <= m["width"] - R and R <= y <= m["height"] - R):
            return False
        return not any(collision.circle_rect_overlap(x, y, R, w) for w in blockers)

    grid = [[free(c, r) for r in range(rows)] for c in range(cols)]
    total = sum(map(sum, grid))
    sc, sr = int(start[0] // step), int(start[1] // step)
    assert grid[sc][sr], "spawn centre is blocked"
    seen = {(sc, sr)}
    todo = deque(seen)
    while todo:
        c, r = todo.popleft()
        for nc, nr in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
            if 0 <= nc < cols and 0 <= nr < rows and grid[nc][nr] and (nc, nr) not in seen:
                seen.add((nc, nr))
                todo.append((nc, nr))
    return len(seen), total, seen, step


@pytest.mark.parametrize("map_id", sorted(MAPS))
def test_whole_map_reachable_from_each_spawn(map_id):
    m = MAPS[map_id]
    for team, zone in m["spawn_zones"].items():
        centre = (zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] / 2)
        reached, total, seen, step = _reachable(m, team, centre)
        # No sealed-off pockets: (almost) every open cell is reachable. A
        # tolerance absorbs grid-edge cells in tight corners.
        assert reached >= 0.99 * total, f"team {team}: only {reached}/{total} cells reachable"
        # ...including the area right outside every enemy spawn.
        for other, z in m["spawn_zones"].items():
            if other == team:
                continue
            near = [(c, r) for c, r in seen
                    if collision.circle_rect_overlap((c + 0.5) * step, (r + 0.5) * step, R + 2 * step, z)]
            assert near, f"team {team} can't get near spawn {other}"
