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


STORM_LOOKAHEAD = 3


def hazardous_positions(arena: Arena, lookahead: int = STORM_LOOKAHEAD) -> set[tuple[int, int]]:
    """Cells expected to be inside a storm in the next `lookahead` turns."""
    haz: set[tuple[int, int]] = set()
    for f in arena.meteo_forecasts:
        if f.position is None or f.radius is None:
            continue
        x0, y0 = f.position
        if f.next_position is not None and f.turns_until and f.turns_until > 0:
            x1, y1 = f.next_position
            steps = min(lookahead, f.turns_until)
        else:
            x1, y1 = x0, y0
            steps = lookahead
        denom = max(steps, 1)
        for t in range(steps + 1):
            cx = x0 + round((x1 - x0) * t / denom)
            cy = y0 + round((y1 - y0) * t / denom)
            r = f.radius
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    haz.add((cx + dx, cy + dy))
    return haz


def is_hazardous(
    pos: Position,
    hazardous: set[tuple[int, int]],
    beavers,
    beaver_buffer: int = 3,
) -> bool:
    if (pos[0], pos[1]) in hazardous:
        return True
    for b in beavers:
        if chebyshev(pos, b.position) <= beaver_buffer:
            return True
    return False


def forward_direction(hq: Position, p: Position) -> tuple[int, int]:
    """Unit-vector direction from hq to p. For diagonal, return X-axis component."""
    dx = p[0] - hq[0]
    dy = p[1] - hq[1]
    if dx == 0 and dy == 0:
        return (0, 0)
    sx = (dx > 0) - (dx < 0)
    sy = (dy > 0) - (dy < 0)
    if sx != 0:
        return (sx, 0)
    return (0, sy)


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
        if c[0] < 0 or c[1] < 0 or c[0] >= arena.size[0] or c[1] >= arena.size[1]:
            return False
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


LATERAL_THRESHOLD = 70


def lateral_targets(arena: Arena) -> list[tuple[Plantation, Position]]:
    """For each plantation whose cell is near completion, suggest a perpendicular
    side-build to keep a survivor after the cell completes."""
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return []

    cell_by_pos = {tuple(c.position): c for c in arena.cells}

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
        if c[0] < 0 or c[1] < 0 or c[0] >= arena.size[0] or c[1] >= arena.size[1]:
            return False
        ct = (c[0], c[1])
        if ct in occupied or ct in mountains:
            return False
        for bp in beaver_positions:
            if chebyshev(c, bp) <= 2:
                return False
        return True

    out: list[tuple[Plantation, Position]] = []
    for p in arena.plantations:
        if p.is_main or p.is_isolated:
            continue
        cell = cell_by_pos.get(tuple(p.position))
        if cell is None:
            continue
        if cell.terraformation_progress < LATERAL_THRESHOLD:
            continue
        fx, fy = forward_direction(hq.position, p.position)
        if fx == 0 and fy == 0:
            continue
        if fx != 0:
            cands = [[p.position[0], p.position[1] + 1], [p.position[0], p.position[1] - 1]]
        else:
            cands = [[p.position[0] + 1, p.position[1]], [p.position[0] - 1, p.position[1]]]
        safe = [c for c in cands if is_safe(c)]
        if not safe:
            continue
        out.append((p, min(safe, key=nearest_bonus_distance)))
    return out


def check_relocate(arena: Arena) -> Optional[list[Position]]:
    """If a freshly built plantation is cardinally adjacent to HQ,
    return [hq.position, fresh.position] for relocateMain. Else None.

    'Freshly built' = immunityUntilTurn - turn_no >= 2 (built this turn,
    has remaining 3-turn immunity).
    """
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    haz = hazardous_positions(arena)
    for p in arena.plantations:
        if p.is_main or p.is_isolated:
            continue
        if not is_cardinal_neighbor(p.position, hq.position):
            continue
        if p.immunity_until_turn - arena.turn_no < 2:
            continue
        if is_hazardous(p.position, haz, arena.beavers, beaver_buffer=3):
            continue
        return [hq.position, p.position]
    return None


UPGRADE_ORDER = [
    "repair_power",
    "signal_range",
    "settlement_limit",
    "decay_mitigation",
    "max_hp",
    "vision_range",
    "earthquake_mitigation",
    "beaver_damage_mitigation",
]


def pick_upgrade(arena: Arena) -> str:
    if arena.plantation_upgrades.points < 1:
        return ""
    by_name = {t.name: t for t in arena.plantation_upgrades.tiers}
    for name in UPGRADE_ORDER:
        tier = by_name.get(name)
        if tier is not None and tier.current < tier.max:
            return name
    return ""


def decide_turn(arena: Arena) -> Optional[dict]:
    """Compose all decisions into a request body. Returns None if there is
    nothing useful to send (server requires at least one of command/upgrade/
    relocateMain)."""
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    target = pick_target(arena, hq)
    commands: list[list[Position]] = []
    if target is not None:
        commands = build_commands(arena, target)

    relocate = check_relocate(arena)
    upgrade = pick_upgrade(arena)

    if not commands and not relocate and not upgrade:
        return None

    body: dict = {
        "command": [{"path": c} for c in commands],
        "plantationUpgrade": upgrade,
    }
    if relocate is not None:
        body["relocateMain"] = relocate
    return body


def decide_turn_lateral(arena: Arena) -> Optional[dict]:
    """Composer that extends decide_turn with lateral-branch builds."""
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    target = pick_target(arena, hq)
    commands: list[list[Position]] = []
    if target is not None:
        commands = build_commands(arena, target)

    used_builders: set[tuple[int, int]] = {tuple(c[0]) for c in commands}
    used_targets: set[tuple[int, int]] = {tuple(c[2]) for c in commands}

    for builder, lat_target in lateral_targets(arena):
        bp = (builder.position[0], builder.position[1])
        tp = (lat_target[0], lat_target[1])
        if bp in used_builders:
            continue
        if tp in used_targets:
            continue
        commands.append([builder.position, builder.position, lat_target])
        used_builders.add(bp)
        used_targets.add(tp)

    relocate = check_relocate(arena)
    upgrade = pick_upgrade(arena)

    if not commands and not relocate and not upgrade:
        return None

    body: dict = {
        "command": [{"path": c} for c in commands],
        "plantationUpgrade": upgrade,
    }
    if relocate is not None:
        body["relocateMain"] = relocate
    return body
