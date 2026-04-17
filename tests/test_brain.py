from cherviak.brain import (
    cardinal_neighbors,
    chebyshev,
    is_cardinal_neighbor,
    nearest_bonus_distance,
    pick_target,
)
from cherviak.models import Arena


def make_arena(plantations=None, mountains=None, beavers=None,
                construction=None, enemy=None) -> Arena:
    return Arena.model_validate({
        "turnNo": 1,
        "nextTurnIn": 1.0,
        "size": [100, 100],
        "actionRange": 2,
        "plantations": plantations or [],
        "enemy": enemy or [],
        "mountains": mountains or [],
        "cells": [],
        "construction": construction or [],
        "beavers": beavers or [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    })


def make_plant(pos, is_main=False, is_isolated=False, hp=50, immunity=0, pid="p1"):
    return {
        "id": pid, "position": pos, "isMain": is_main,
        "isIsolated": is_isolated, "immunityUntilTurn": immunity, "hp": hp,
    }


def test_chebyshev_distance():
    assert chebyshev([0, 0], [3, 4]) == 4
    assert chebyshev([5, 5], [5, 5]) == 0


def test_cardinal_neighbors_returns_4_orthogonal_cells():
    assert sorted(cardinal_neighbors([10, 10])) == sorted([
        [11, 10], [9, 10], [10, 11], [10, 9],
    ])


def test_is_cardinal_neighbor():
    assert is_cardinal_neighbor([5, 5], [5, 6]) is True
    assert is_cardinal_neighbor([5, 5], [6, 5]) is True
    assert is_cardinal_neighbor([5, 5], [6, 6]) is False  # diagonal
    assert is_cardinal_neighbor([5, 5], [7, 5]) is False  # too far
    assert is_cardinal_neighbor([5, 5], [5, 5]) is False  # same


def test_nearest_bonus_distance():
    assert nearest_bonus_distance([7, 7]) == 0          # on bonus
    assert nearest_bonus_distance([8, 7]) == 1          # one cell away
    assert nearest_bonus_distance([10, 10]) == 6        # nearest is [7,7]: 3+3
    assert nearest_bonus_distance([11, 11]) == 6        # nearest is [14,14]: 3+3
    assert nearest_bonus_distance([14, 14]) == 0        # on bonus


def test_pick_target_chooses_neighbor_closest_to_bonus():
    hq = make_plant([6, 6], is_main=True)
    arena = make_arena(plantations=[hq])
    target = pick_target(arena, arena.plantations[0])
    # candidates: [7,6], [5,6], [6,7], [6,5]
    # distances to [7,7]: [7,6]=1, [5,6]=3, [6,7]=1, [6,5]=3
    # tie between [7,6] and [6,7] — both equally close to bonus
    assert target in ([7, 6], [6, 7])


def test_pick_target_skips_mountains():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(plantations=[hq], mountains=[[7, 7]])
    target = pick_target(arena, arena.plantations[0])
    # [7,7] is a bonus cell BUT a mountain — must skip
    assert target != [7, 7]


def test_pick_target_skips_occupied_cells():
    hq = make_plant([7, 6], is_main=True, pid="hq")
    other = make_plant([7, 7], pid="p2")
    arena = make_arena(plantations=[hq, other])
    target = pick_target(arena, arena.plantations[0])
    assert target != [7, 7]


def test_pick_target_prefers_adjacent_construction_in_progress():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(
        plantations=[hq],
        construction=[{"position": [7, 7], "progress": 20}],
    )
    target = pick_target(arena, arena.plantations[0])
    assert target == [7, 7]


def test_pick_target_skips_cells_within_2_of_beaver():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(
        plantations=[hq],
        beavers=[{"id": "b1", "position": [8, 8], "hp": 100}],
    )
    target = pick_target(arena, arena.plantations[0])
    # [7,7] is within chebyshev radius 2 of [8,8] -> skip
    assert target != [7, 7]


def test_pick_target_skips_out_of_bounds_positions():
    hq = make_plant([0, 7], is_main=True)
    arena = make_arena(plantations=[hq], mountains=[[1, 7]])
    target = pick_target(arena, arena.plantations[0])
    assert target != [-1, 7]


def test_pick_target_returns_none_when_all_blocked():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(
        plantations=[hq],
        mountains=[[6, 5], [4, 5], [5, 6], [5, 4]],
    )
    target = pick_target(arena, arena.plantations[0])
    assert target is None


from cherviak.brain import build_commands


def test_build_commands_includes_plantations_in_action_range():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    near = make_plant([6, 5], pid="near")  # within AR=2 of [7,5]
    far = make_plant([20, 20], pid="far")  # outside AR=2 of [7,5]
    arena = make_arena(plantations=[hq, near, far])
    target = [7, 5]

    commands = build_commands(arena, target)
    builder_positions = sorted([c[0] for c in commands])
    assert builder_positions == sorted([[5, 5], [6, 5]])


def test_build_commands_uses_author_as_relay_to_avoid_penalty():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(plantations=[hq])
    target = [6, 5]
    commands = build_commands(arena, target)
    # path is [author, author, target]
    assert commands == [[[5, 5], [5, 5], [6, 5]]]


def test_build_commands_excludes_isolated_plantations():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    isolated = make_plant([6, 5], is_isolated=True, pid="iso")
    arena = make_arena(plantations=[hq, isolated])
    target = [7, 5]
    commands = build_commands(arena, target)
    builders = [c[0] for c in commands]
    assert [6, 5] not in builders


def test_build_commands_empty_when_no_plantations_in_range():
    hq = make_plant([0, 0], is_main=True)
    arena = make_arena(plantations=[hq])
    target = [50, 50]  # way outside AR
    commands = build_commands(arena, target)
    assert commands == []


from cherviak.brain import LATERAL_THRESHOLD, lateral_targets


def make_cell(pos, progress=0, ttd=80):
    return {"position": pos, "terraformationProgress": progress,
            "turnsUntilDegradation": ttd}


def test_lateral_targets_skips_below_threshold():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = make_arena(
        plantations=[hq, rib_parent],
    )
    # inject cell with low progress
    arena.cells.append(__import__("cherviak.models", fromlist=["Cell"]).Cell.model_validate(
        make_cell([7, 5], progress=LATERAL_THRESHOLD - 1)))
    assert lateral_targets(arena) == []


def test_lateral_targets_picks_perpendicular_when_threshold_reached():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")  # forward = (+1, 0) so perpendicular = Y axis
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=LATERAL_THRESHOLD)))

    result = lateral_targets(arena)
    assert len(result) == 1
    builder, target = result[0]
    assert builder.id == "r1"
    assert target in ([7, 6], [7, 4])  # perpendicular to forward X


def test_lateral_targets_skips_hq():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    arena = make_arena(plantations=[hq])
    arena.cells.append(Cell.model_validate(make_cell([5, 5], progress=99)))
    assert lateral_targets(arena) == []


def test_lateral_targets_skips_isolated():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    iso = make_plant([7, 5], is_isolated=True, pid="iso")
    arena = make_arena(plantations=[hq, iso])
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=99)))
    assert lateral_targets(arena) == []


def test_lateral_targets_filters_unsafe_candidates():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    # block one perpendicular with mountain, the other with another plantation
    blocker = make_plant([7, 4], pid="b")
    arena = make_arena(
        plantations=[hq, rib_parent, blocker],
        mountains=[[7, 6]],
    )
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=80)))
    assert lateral_targets(arena) == []


def test_lateral_targets_skips_when_no_cell_data():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = make_arena(plantations=[hq, rib_parent])
    # no cell entry for [7,5]
    assert lateral_targets(arena) == []


def test_lateral_targets_picks_bonus_neighbor_when_two_safe():
    from cherviak.models import Cell
    # forward axis Y so perpendiculars are X. [7, 6] is closer to bonus [7,7].
    hq = make_plant([7, 4], is_main=True, pid="hq")
    rib_parent = make_plant([7, 6], pid="r1")  # forward (0, +1), perpendiculars X
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([7, 6], progress=80)))
    result = lateral_targets(arena)
    assert len(result) == 1
    _, target = result[0]
    # candidates: [8,6] dist to nearest bonus [7,7]=1+1=2; [6,6] dist to [7,7]=1+1=2 — tie
    # both equally good — accept either
    assert target in ([8, 6], [6, 6])


from cherviak.brain import check_relocate


def test_check_relocate_returns_path_when_fresh_neighbor_exists():
    hq = make_plant([5, 5], is_main=True, immunity=0, pid="hq")
    # Freshly built: immunityUntilTurn = current_turn + 3 (turn_no=1 here, so >= 3)
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = make_arena(plantations=[hq, fresh])

    result = check_relocate(arena)
    assert result == [[5, 5], [5, 6]]


def test_check_relocate_returns_none_when_no_neighbor_is_fresh():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    old_neighbor = make_plant([5, 6], immunity=0, pid="old")
    arena = make_arena(plantations=[hq, old_neighbor])
    assert check_relocate(arena) is None


def test_check_relocate_skips_diagonal_neighbors():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    diag = make_plant([6, 6], immunity=4, pid="diag")
    arena = make_arena(plantations=[hq, diag])
    assert check_relocate(arena) is None


def test_check_relocate_skips_isolated_plantations():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    iso = make_plant([5, 6], immunity=4, is_isolated=True, pid="iso")
    arena = make_arena(plantations=[hq, iso])
    assert check_relocate(arena) is None


def test_check_relocate_returns_none_when_no_hq():
    arena = make_arena(plantations=[])
    assert check_relocate(arena) is None


from cherviak.brain import UPGRADE_ORDER, pick_upgrade


def make_upgrades(points: int, tiers: list[dict]) -> dict:
    return {
        "points": points, "intervalTurns": 30, "turnsUntilPoints": 30,
        "maxPoints": 15, "tiers": tiers,
    }


def test_pick_upgrade_returns_empty_when_no_points():
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(0, [
            {"name": "repair_power", "current": 0, "max": 3},
        ]),
    })
    assert pick_upgrade(arena) == ""


def test_pick_upgrade_returns_first_in_priority_order():
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(1, [
            {"name": "max_hp", "current": 0, "max": 5},
            {"name": "repair_power", "current": 0, "max": 3},
        ]),
    })
    assert pick_upgrade(arena) == "max_hp"


def test_pick_upgrade_skips_maxed_tiers():
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(1, [
            {"name": "repair_power", "current": 3, "max": 3},  # maxed
            {"name": "signal_range", "current": 0, "max": 5},
        ]),
    })
    assert pick_upgrade(arena) == "signal_range"


def test_pick_upgrade_returns_empty_when_all_known_maxed():
    tiers = [{"name": name, "current": 99, "max": 99} for name in UPGRADE_ORDER]
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(1, tiers),
    })
    assert pick_upgrade(arena) == ""


from cherviak.brain import forward_direction


def test_forward_direction_pure_x():
    assert forward_direction([5, 5], [8, 5]) == (1, 0)
    assert forward_direction([5, 5], [2, 5]) == (-1, 0)


def test_forward_direction_pure_y():
    assert forward_direction([5, 5], [5, 9]) == (0, 1)
    assert forward_direction([5, 5], [5, 1]) == (0, -1)


def test_forward_direction_diagonal_returns_x_component():
    # diagonal червяк — prefer X axis as the "forward" we treat as primary
    assert forward_direction([5, 5], [8, 8]) == (1, 0)
    assert forward_direction([5, 5], [2, 2]) == (-1, 0)


def test_forward_direction_same_position_returns_zero():
    assert forward_direction([5, 5], [5, 5]) == (0, 0)


from cherviak.brain import decide_turn_lateral


def test_decide_turn_returns_none_when_no_hq():
    arena = make_arena(plantations=[])
    assert decide_turn_lateral(arena) is None


def test_decide_turn_returns_build_command_for_normal_state():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(plantations=[hq])
    body = decide_turn_lateral(arena)
    assert body is not None
    assert len(body["command"]) >= 1
    first_cmd = body["command"][0]
    assert first_cmd["path"][0] == [5, 5]


def test_decide_turn_includes_relocate_when_fresh_neighbor_exists():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = make_arena(plantations=[hq, fresh])
    body = decide_turn_lateral(arena)
    assert body["relocateMain"] == [[5, 5], [5, 6]]


def test_decide_turn_includes_relocate_when_hq_cell_near_completion():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    neighbor = make_plant([5, 6], pid="neighbor")
    arena = Arena.model_validate(
        {
            "turnNo": 10,
            "nextTurnIn": 1.0,
            "size": [100, 100],
            "actionRange": 2,
            "plantations": [hq, neighbor],
            "enemy": [],
            "mountains": [],
            "cells": [
                {"position": [5, 5], "terraformationProgress": 70, "turnsUntilDegradation": 10},
                {"position": [5, 6], "terraformationProgress": 10, "turnsUntilDegradation": 50},
            ],
            "construction": [],
            "beavers": [],
            "plantationUpgrades": {
                "points": 0,
                "intervalTurns": 30,
                "turnsUntilPoints": 30,
                "maxPoints": 15,
                "tiers": [],
            },
        }
    )
    body = decide_turn_lateral(arena)
    assert body["relocateMain"] == [[5, 5], [5, 6]]


def test_decide_turn_includes_upgrade_when_points_available():
    arena_dict = {
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [make_plant([5, 5], is_main=True)],
        "enemy": [], "mountains": [], "cells": [], "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 1, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15,
            "tiers": [
                {"name": "repair_power", "current": 0, "max": 3},
                {"name": "settlement_limit", "current": 0, "max": 10},
            ],
        },
    }
    arena = Arena.model_validate(arena_dict)
    body = decide_turn_lateral(arena)
    assert body["plantationUpgrade"] == "settlement_limit"


def test_decide_turn_returns_none_when_all_blocked_and_no_upgrade():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(
        plantations=[hq],
        mountains=[[6, 5], [4, 5], [5, 6], [5, 4]],
    )
    assert decide_turn_lateral(arena) is None


def test_decide_turn_lateral_includes_lateral_command():
    from cherviak.models import Cell
    # rib_parent at [9,5] is OUT of AR=2 of any HQ-neighbor forward target
    # (closest is [6,5], dx=3 > 2), so it's not consumed by the forward command
    # and the lateral build appears.
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([9, 5], pid="r1")
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([9, 5], progress=80)))

    body = decide_turn_lateral(arena)
    assert body is not None
    paths = [c["path"] for c in body["command"]]
    lateral_paths = [
        p for p in paths
        if p[0] == [9, 5] and p[2] in ([9, 6], [9, 4])
    ]
    assert len(lateral_paths) >= 1


def test_decide_turn_lateral_does_not_double_command_same_builder():
    # rib_parent is in AR of forward target AND has lateral. Only one command.
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([6, 5], pid="r1")  # forward (+1,0), in AR of [7,5]
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([6, 5], progress=80)))

    body = decide_turn_lateral(arena)
    assert body is not None
    builders = [c["path"][0] for c in body["command"]]
    # rib_parent appears exactly once across all commands
    assert builders.count([6, 5]) == 1


def test_decide_turn_lateral_returns_none_when_nothing_to_do():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(
        plantations=[hq],
        mountains=[[6, 5], [4, 5], [5, 6], [5, 4]],
    )
    assert decide_turn_lateral(arena) is None


from cherviak.brain import STORM_LOOKAHEAD, hazardous_positions


def make_meteo(kind="sandstorm", position=None, next_position=None,
               radius=None, turns_until=None, forming=False, mid="m1"):
    out = {"kind": kind, "id": mid, "forming": forming}
    if position is not None:
        out["position"] = position
    if next_position is not None:
        out["nextPosition"] = next_position
    if radius is not None:
        out["radius"] = radius
    if turns_until is not None:
        out["turnsUntil"] = turns_until
    return out


def make_arena_with_meteo(meteo_list):
    return Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [], "enemy": [], "mountains": [], "cells": [],
        "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": meteo_list,
    })


def test_hazardous_positions_stationary_storm_marks_chebyshev_radius():
    arena = make_arena_with_meteo([
        make_meteo(position=[10, 10], radius=1, turns_until=1),
    ])
    haz = hazardous_positions(arena)
    # 3x3 around [10,10]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            assert (10 + dx, 10 + dy) in haz
    assert (12, 10) not in haz
    assert (10, 12) not in haz


def test_hazardous_positions_skips_meteo_without_position_or_radius():
    arena = make_arena_with_meteo([
        make_meteo(kind="solar_flare", position=None, radius=None, turns_until=2),
        make_meteo(position=[5, 5], radius=None, turns_until=1),
        make_meteo(position=None, radius=2, turns_until=1),
    ])
    assert hazardous_positions(arena) == set()


def test_hazardous_positions_empty_when_no_meteo():
    arena = make_arena_with_meteo([])
    assert hazardous_positions(arena) == set()


def test_hazardous_positions_moving_storm_marks_path_cells():
    # storm at [10,10], moving to [13,10], turns_until=3, radius=0
    # lookahead=3: centres at t=0 [10,10], t=1 [11,10], t=2 [12,10], t=3 [13,10]
    arena = make_arena_with_meteo([
        make_meteo(position=[10, 10], next_position=[13, 10], radius=0, turns_until=3),
    ])
    haz = hazardous_positions(arena, lookahead=3)
    assert (10, 10) in haz
    assert (11, 10) in haz
    assert (12, 10) in haz
    assert (13, 10) in haz
    assert (14, 10) not in haz


def test_hazardous_positions_moving_storm_with_radius_marks_swept_band():
    arena = make_arena_with_meteo([
        make_meteo(position=[5, 5], next_position=[7, 5], radius=1, turns_until=2),
    ])
    haz = hazardous_positions(arena, lookahead=2)
    # at t=0: 3x3 around [5,5]; at t=1: around [6,5]; at t=2: around [7,5]
    for cx in (5, 6, 7):
        for dy in (-1, 0, 1):
            assert (cx, 5 + dy) in haz
    assert (8, 5) in haz  # right edge of t=2 radius
    assert (4, 5) in haz  # left edge of t=0 radius
    assert (9, 5) not in haz


from cherviak.brain import is_hazardous
from cherviak.models import Beaver


def test_is_hazardous_true_when_in_hazard_set():
    assert is_hazardous([5, 5], {(5, 5)}, []) is True


def test_is_hazardous_true_when_within_beaver_buffer():
    b = Beaver.model_validate({"id": "b1", "position": [10, 10], "hp": 100})
    assert is_hazardous([12, 11], set(), [b], beaver_buffer=3) is True
    assert is_hazardous([13, 13], set(), [b], beaver_buffer=3) is True


def test_is_hazardous_false_outside_buffer_and_hazards():
    b = Beaver.model_validate({"id": "b1", "position": [0, 0], "hp": 100})
    assert is_hazardous([10, 10], {(99, 99)}, [b], beaver_buffer=3) is False


def test_check_relocate_skips_fresh_neighbor_in_storm():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, fresh], "enemy": [], "mountains": [], "cells": [],
        "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": [
            {"kind": "sandstorm", "id": "m1", "forming": False,
             "position": [5, 6], "radius": 0, "turnsUntil": 1},
        ],
    })
    assert check_relocate(arena) is None


def test_check_relocate_skips_fresh_neighbor_near_beaver():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, fresh], "enemy": [], "mountains": [], "cells": [],
        "construction": [],
        "beavers": [{"id": "b1", "position": [7, 7], "hp": 100}],  # cheb([5,6],[7,7])=2 ≤ 3
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    })
    assert check_relocate(arena) is None


def test_check_relocate_prefers_lowest_progress_neighbor_when_hq_is_risky():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    safer = make_plant([5, 6], pid="safer")
    riskier = make_plant([6, 5], pid="riskier")
    arena = Arena.model_validate({
        "turnNo": 10, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, safer, riskier], "enemy": [], "mountains": [], "construction": [],
        "beavers": [],
        "cells": [
            {"position": [5, 5], "terraformationProgress": 95, "turnsUntilDegradation": 10},
            {"position": [5, 6], "terraformationProgress": 5, "turnsUntilDegradation": 50},
            {"position": [6, 5], "terraformationProgress": 40, "turnsUntilDegradation": 40},
        ],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    })
    assert check_relocate(arena) == [[5, 5], [5, 6]]


def test_pick_target_skips_cells_in_storm_path():
    hq = make_plant([7, 6], is_main=True)
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq], "enemy": [], "mountains": [], "cells": [],
        "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": [
            {"kind": "sandstorm", "id": "m1", "forming": False,
             "position": [7, 7], "radius": 0, "turnsUntil": 1},
        ],
    })
    target = pick_target(arena, arena.plantations[0])
    assert target != [7, 7]


def test_lateral_targets_skips_hazardous_perpendicular():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, rib_parent], "enemy": [], "mountains": [],
        "cells": [], "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": [
            # cover both [7,6] and [7,4]
            {"kind": "sandstorm", "id": "m1", "forming": False,
             "position": [7, 5], "radius": 1, "turnsUntil": 1},
        ],
    })
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=80)))
    assert lateral_targets(arena) == []
