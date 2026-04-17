from typing import Optional
from cherviak.models import Arena, Plantation


Position = list[int]


def chebyshev(a: Position, b: Position) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def cardinal_neighbors(p: Position) -> list[Position]:
    x, y = p
    return [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]


def is_cardinal_neighbor(a: Position, b: Position) -> bool:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return (dx == 1 and dy == 0) or (dx == 0 and dy == 1)


def nearest_bonus_distance(p: Position) -> int:
    x, y = p
    bx = round(x / 7) * 7
    by = round(y / 7) * 7
    return abs(x - bx) + abs(y - by)


def pick_target(arena: Arena, hq: Plantation) -> Optional[Position]:
    occupied: set[tuple[int, int]] = set()
    for p in arena.plantations:
        occupied.add(tuple(p.position))
    for e in arena.enemy:
        occupied.add(tuple(e.position))
    for c in arena.construction:
        occupied.add(tuple(c.position))
    mountains = {tuple(m) for m in arena.mountains}
    beaver_positions = [b.position for b in arena.beavers]

    def is_safe(c: Position) -> bool:
        ct = (c[0], c[1])
        if ct in occupied or ct in mountains:
            return False
        for bp in beaver_positions:
            if chebyshev(c, bp) <= 2:
                return False
        return True

    safe = [c for c in cardinal_neighbors(hq.position) if is_safe(c)]
    if not safe:
        return None
    return min(safe, key=nearest_bonus_distance)


def build_commands(arena: Arena, target: Position) -> list[list[Position]]:
    """Return list of paths [author, author, target] for every controllable
    plantation within action_range of the target."""
    AR = arena.action_range
    paths: list[list[Position]] = []
    for p in arena.plantations:
        if p.is_isolated:
            continue
        if abs(p.position[0] - target[0]) > AR:
            continue
        if abs(p.position[1] - target[1]) > AR:
            continue
        paths.append([p.position, p.position, target])
    return paths
