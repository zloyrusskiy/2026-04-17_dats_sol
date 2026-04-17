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


def test_pick_target_skips_construction_in_progress():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(
        plantations=[hq],
        construction=[{"position": [7, 7], "progress": 20}],
    )
    target = pick_target(arena, arena.plantations[0])
    assert target != [7, 7]


def test_pick_target_skips_cells_within_2_of_beaver():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(
        plantations=[hq],
        beavers=[{"id": "b1", "position": [8, 8], "hp": 100}],
    )
    target = pick_target(arena, arena.plantations[0])
    # [7,7] is within chebyshev radius 2 of [8,8] -> skip
    assert target != [7, 7]


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
