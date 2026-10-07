"""Pure geometry helpers. Rects are dicts with x, y, width, height."""

import math


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def point_in_rect(px: float, py: float, rect: dict) -> bool:
    return (rect["x"] <= px <= rect["x"] + rect["width"]
            and rect["y"] <= py <= rect["y"] + rect["height"])


def circle_rect_overlap(cx: float, cy: float, r: float, rect: dict) -> bool:
    nx = clamp(cx, rect["x"], rect["x"] + rect["width"])
    ny = clamp(cy, rect["y"], rect["y"] + rect["height"])
    return (cx - nx) ** 2 + (cy - ny) ** 2 < r * r


def push_circle_out_of_rect(cx: float, cy: float, r: float, rect: dict) -> tuple[float, float]:
    """Return the circle centre moved the minimum distance so it no longer overlaps rect.

    Pushing along the contact normal (rather than undoing the move) lets players
    slide along walls instead of sticking to them.
    """
    x0, y0 = rect["x"], rect["y"]
    x1, y1 = x0 + rect["width"], y0 + rect["height"]
    nx, ny = clamp(cx, x0, x1), clamp(cy, y0, y1)
    dx, dy = cx - nx, cy - ny
    d2 = dx * dx + dy * dy
    if d2 >= r * r:
        return cx, cy
    if d2 > 0:
        d = math.sqrt(d2)
        return nx + dx / d * r, ny + dy / d * r
    # Centre is inside the rect: push out through the nearest edge.
    exits = [(cx - x0 + r, -1, 0), (x1 - cx + r, 1, 0), (cy - y0 + r, 0, -1), (y1 - cy + r, 0, 1)]
    dist, sx, sy = min(exits)
    return cx + sx * dist, cy + sy * dist


def resolve_circle_walls(cx: float, cy: float, r: float, walls: list[dict],
                         width: float, height: float) -> tuple[float, float]:
    """Keep a circle inside the map bounds and outside every wall."""
    for _ in range(3):  # a few passes handle corners where two walls meet
        for wall in walls:
            cx, cy = push_circle_out_of_rect(cx, cy, r, wall)
        cx, cy = clamp(cx, r, width - r), clamp(cy, r, height - r)
    return cx, cy


def segment_rect_hit(x0: float, y0: float, x1: float, y1: float, rect: dict,
                     pad: float = 0.0) -> float | None:
    """Fraction t in [0, 1] where segment (x0,y0)->(x1,y1) first enters rect
    (expanded by pad on every side), or None if it misses. Slab method."""
    t_min, t_max = 0.0, 1.0
    for p0, d, lo, hi in (
        (x0, x1 - x0, rect["x"] - pad, rect["x"] + rect["width"] + pad),
        (y0, y1 - y0, rect["y"] - pad, rect["y"] + rect["height"] + pad),
    ):
        if abs(d) < 1e-12:
            if p0 < lo or p0 > hi:
                return None
            continue
        ta, tb = (lo - p0) / d, (hi - p0) / d
        if ta > tb:
            ta, tb = tb, ta
        t_min, t_max = max(t_min, ta), min(t_max, tb)
        if t_min > t_max:
            return None
    return t_min


def segment_circle_hit(x0: float, y0: float, x1: float, y1: float,
                       cx: float, cy: float, r: float) -> float | None:
    """Fraction t in [0, 1] where the segment first touches the circle, or None."""
    dx, dy = x1 - x0, y1 - y0
    fx, fy = x0 - cx, y0 - cy
    c = fx * fx + fy * fy - r * r
    if c <= 0:
        return 0.0  # starts inside
    a = dx * dx + dy * dy
    if a < 1e-12:
        return None
    b = 2 * (fx * dx + fy * dy)
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - math.sqrt(disc)) / (2 * a)
    return t if 0.0 <= t <= 1.0 else None
