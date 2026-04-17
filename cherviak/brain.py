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
    x_mod = x % 7
    y_mod = y % 7

    # If close to bonus boundary (within 1 cell), target nearest bonus
    # Otherwise, target next bonus cell
    x_outer = x_mod <= 1 or x_mod >= 6
    y_outer = y_mod <= 1 or y_mod >= 6

    if x_outer and y_outer:
        # Near bonus - distance to nearest
        bx = round(x / 7) * 7
        by = round(y / 7) * 7
    else:
        # In middle - distance to next bonus
        bx = ((x // 7) + 1) * 7
        by = ((y // 7) + 1) * 7

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
