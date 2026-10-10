"""Load maps from Maps/<Name>/map.json.

A map folder holds the background image and a map.json whose geometry is
written in *image pixel* coordinates (so it can be measured straight off the
artwork) and scaled here to world coordinates:

    {
      "name": "Galadriel",
      "image": "Map.jpg",
      "image_size": [2048, 2048],          # pixel size of the image
      "world_size": [1600, 900],           # world units the image is stretched to
      "walls": [[x, y, w, h], ...],        # solid rectangles (outer border included)
      "spawn_zones": [[x, y, w, h], ...]   # one per team, in TEAMS order
    }

The world size may have a different aspect ratio from the image: the image is
simply stretched to fill it, and since all geometry is axis-aligned rectangles
the collision shapes stay exact.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger("lanshooter")


class MapError(ValueError):
    pass


def _rect(raw, sx: float, sy: float) -> dict:
    if not (isinstance(raw, list) and len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw)):
        raise MapError(f"bad rectangle {raw!r}")
    x, y, w, h = raw
    if w <= 0 or h <= 0:
        raise MapError(f"rectangle with no area {raw!r}")
    return {"x": x * sx, "y": y * sy, "width": w * sx, "height": h * sy}


def build_map(map_id: str, data: dict, teams: list, image_path: Path | None = None) -> dict:
    """Turn a map.json dict into a world-coordinate map. Raises MapError."""
    try:
        img_w, img_h = data["image_size"]
        width, height = data.get("world_size", data["image_size"])
        sx, sy = width / img_w, height / img_h
        walls = [_rect(r, sx, sy) for r in data["walls"]]
        zones = [_rect(r, sx, sy) for r in data["spawn_zones"]]
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise MapError(f"invalid map.json ({e})") from e
    if len(zones) != len(teams):
        raise MapError(f"has {len(zones)} spawn zones but there are {len(teams)} teams")
    return {
        "id": map_id,
        "name": str(data.get("name") or map_id),
        "width": width,
        "height": height,
        "walls": walls,
        "spawn_zones": {t["id"]: z for t, z in zip(teams, zones)},
        "image_path": image_path,
    }


def load_maps(maps_dir: Path, teams: list) -> dict[str, dict]:
    """All valid maps under maps_dir, keyed by folder name (sorted). Invalid
    folders are skipped with a warning so one bad map can't stop the server."""
    maps = {}
    for folder in sorted(p for p in Path(maps_dir).iterdir() if p.is_dir()):
        spec = folder / "map.json"
        if not spec.is_file():
            log.warning("Map folder %s has no map.json; skipped", folder.name)
            continue
        try:
            data = json.loads(spec.read_text(encoding="utf-8"))
            image = folder / str(data.get("image", ""))
            if not image.is_file():
                raise MapError(f"image {data.get('image')!r} not found")
            maps[folder.name] = build_map(folder.name, data, teams, image)
        except (OSError, ValueError) as e:  # MapError and JSONDecodeError are ValueErrors
            log.warning("Map %s skipped: %s", folder.name, e)
    return maps
