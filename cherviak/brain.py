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


def primary_direction(arena: Arena, hq: Plantation) -> tuple[int, int]:
    """Pick one cardinal direction to commit to for chain expansion.

    Prefer direction from oldest-living plantation to current HQ (chain forward).
    When the chain has not formed yet, pick whichever cardinal has most room on
    the map. Falls back to (1, 0) if HQ is on an unusual spot."""
    non_main = [p for p in arena.plantations if not p.is_main and not p.is_isolated]
    if non_main:
        oldest = min(non_main, key=lambda p: p.immunity_until_turn)
        direction = forward_direction(oldest.position, hq.position)
        if direction != (0, 0):
            return direction
    x, y = hq.position
    w, h = arena.size
    room = {
        (1, 0): w - x - 1,
        (-1, 0): x,
        (0, 1): h - y - 1,
        (0, -1): y,
    }
    return max(room, key=lambda d: room[d])


def next_bonus_target(
    arena: Arena,
    origin: Position,
    direction: tuple[int, int],
) -> Optional[Position]:
    """Closest unclaimed bonus cell (coords multiple of 7) in the given direction."""
    dx, dy = direction
    ox, oy = origin
    w, h = arena.size
    if w <= 0 or h <= 0:
        return None
    plantations = {tuple(p.position) for p in arena.plantations}
    construction = {tuple(c.position) for c in arena.construction}
    mountains = {tuple(m) for m in arena.mountains}
    completed = {
        tuple(c.position) for c in arena.cells if c.terraformation_progress >= 100
    }
    claimed = plantations | construction | completed

    best: Optional[tuple[int, int, Position]] = None
    for bx in range(0, w, 7):
        for by in range(0, h, 7):
            pos = (bx, by)
            if pos in mountains or pos in claimed:
                continue
            px, py = bx - ox, by - oy
            if dx != 0 and px * dx <= 0:
                continue
            if dy != 0 and py * dy <= 0:
                continue
            primary = abs(px) if dx != 0 else abs(py)
            perpendicular = abs(py) if dx != 0 else abs(px)
            candidate = (primary + perpendicular, perpendicular, [bx, by])
            if best is None or candidate < best:
                best = candidate
    if best is None:
        return None
    return best[2]


def pick_target(arena: Arena, hq: Plantation) -> Optional[Position]:
    occupied: set[tuple[int, int]] = set()
    for p in arena.plantations:
        occupied.add(tuple(p.position))
    for e in arena.enemy:
        occupied.add(tuple(e.position))
    construction_progress: dict[tuple[int, int], int] = {
        (c.position[0], c.position[1]): c.progress for c in arena.construction
    }
    mountains = {tuple(m) for m in arena.mountains}
    beaver_positions = [b.position for b in arena.beavers]
    haz = hazardous_positions(arena)

    def is_safe(c: Position, allow_construction: bool = False, ignore_haz: bool = False) -> bool:
        if c[0] < 0 or c[1] < 0 or c[0] >= arena.size[0] or c[1] >= arena.size[1]:
            return False
        ct = (c[0], c[1])
        if ct in occupied or ct in mountains:
            return False
        if not allow_construction and ct in construction_progress:
            return False
        if not ignore_haz and ct in haz:
            return False
        for bp in beaver_positions:
            if chebyshev(c, bp) <= 2:
                return False
        return True

    neighbors = cardinal_neighbors(hq.position)
    in_progress = [
        c for c in neighbors
        if (c[0], c[1]) in construction_progress
        and is_safe(c, allow_construction=True, ignore_haz=True)
    ]
    if in_progress:
        return max(in_progress, key=lambda c: construction_progress[(c[0], c[1])])

    safe = [c for c in neighbors if is_safe(c)]
    if not safe:
        return None

    direction = primary_direction(arena, hq)
    bonus = next_bonus_target(arena, hq.position, direction)

    def directional_key(c: Position) -> tuple[int, int, int]:
        dx, dy = direction
        projection = (c[0] - hq.position[0]) * dx + (c[1] - hq.position[1]) * dy
        bonus_dist = (
            max(abs(c[0] - bonus[0]), abs(c[1] - bonus[1]))
            if bonus is not None
            else nearest_bonus_distance(c)
        )
        return (-projection, bonus_dist, nearest_bonus_distance(c))

    return min(safe, key=directional_key)


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
HQ_RELOCATE_THRESHOLD = 70


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
    construction_set = {(c.position[0], c.position[1]) for c in arena.construction}
    mountains = {tuple(m) for m in arena.mountains}
    beaver_positions = [b.position for b in arena.beavers]
    haz = hazardous_positions(arena)

    def is_safe(c: Position, ignore_haz: bool = False) -> bool:
        if c[0] < 0 or c[1] < 0 or c[0] >= arena.size[0] or c[1] >= arena.size[1]:
            return False
        ct = (c[0], c[1])
        if ct in occupied or ct in mountains:
            return False
        if not ignore_haz and ct in haz:
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
        in_progress = [
            c for c in cands
            if (c[0], c[1]) in construction_set and is_safe(c, ignore_haz=True)
        ]
        if in_progress:
            out.append((p, in_progress[0]))
            continue
        safe = [c for c in cands if is_safe(c)]
        if not safe:
            continue
        out.append((p, min(safe, key=nearest_bonus_distance)))
    return out


def check_relocate(arena: Arena) -> Optional[list[Position]]:
    """Return [hq.position, candidate.position] for a safe adjacent HQ move.

    We relocate aggressively once the HQ cell is close to completion, because
    losing a main plantation on a 95% cell is much more common than losing a
    branch. Fresh adjacent plantations remain the top priority. Ties break in
    favor of moving forward along the primary expansion direction so HQ keeps
    marching onto fresh ground rather than doubling back.
    """
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    haz = hazardous_positions(arena)
    cell_progress = {
        (cell.position[0], cell.position[1]): cell.terraformation_progress for cell in arena.cells
    }
    hq_progress = cell_progress.get((hq.position[0], hq.position[1]), 0)
    direction = primary_direction(arena, hq)
    dx, dy = direction

    candidates: list[tuple[tuple[int, int, int, int, int], Plantation]] = []
    for p in arena.plantations:
        if p.is_main or p.is_isolated:
            continue
        if not is_cardinal_neighbor(p.position, hq.position):
            continue
        if is_hazardous(p.position, haz, arena.beavers, beaver_buffer=3):
            continue
        freshness = p.immunity_until_turn - arena.turn_no
        if freshness < 2 and hq_progress < HQ_RELOCATE_THRESHOLD:
            continue
        candidate_progress = cell_progress.get((p.position[0], p.position[1]), 0)
        projection = (p.position[0] - hq.position[0]) * dx + (p.position[1] - hq.position[1]) * dy
        priority = (
            0 if freshness >= 2 else 1,
            candidate_progress,
            -projection,
            -freshness,
            -p.hp,
        )
        candidates.append((priority, p))
    if not candidates:
        return None
    _, best = min(candidates, key=lambda item: item[0])
    return [hq.position, best.position]


UPGRADE_ORDER = [
    "settlement_limit",
    "max_hp",
    "earthquake_mitigation",
    "signal_range",
    "decay_mitigation",
    "beaver_damage_mitigation",
    "vision_range",
    "repair_power",
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


def decide_turn_lateral(arena: Arena) -> Optional[dict]:
    """Compose all decisions into a request body. Returns None if there is
    nothing useful to send (server requires at least one of command/upgrade/
    relocateMain). Includes lateral-branch builds."""
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
