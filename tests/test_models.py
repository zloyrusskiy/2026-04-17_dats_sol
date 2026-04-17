from cherviak.models import Arena


SAMPLE_ARENA = {
    "turnNo": 42,
    "nextTurnIn": 0.85,
    "size": [100, 100],
    "actionRange": 2,
    "plantations": [
        {
            "id": "p1",
            "position": [50, 50],
            "isMain": True,
            "isIsolated": False,
            "immunityUntilTurn": 45,
            "hp": 50,
        },
        {
            "id": "p2",
            "position": [50, 51],
            "isMain": False,
            "isIsolated": False,
            "immunityUntilTurn": 0,
            "hp": 50,
        },
    ],
    "enemy": [],
    "mountains": [[10, 10], [11, 10]],
    "cells": [
        {"position": [50, 50], "terraformationProgress": 25, "turnsUntilDegradation": 80}
    ],
    "construction": [{"position": [50, 52], "progress": 30}],
    "beavers": [{"id": "b1", "position": [70, 70], "hp": 100}],
    "plantationUpgrades": {
        "points": 1,
        "intervalTurns": 30,
        "turnsUntilPoints": 18,
        "maxPoints": 15,
        "tiers": [
            {"name": "repair_power", "current": 0, "max": 3},
            {"name": "settlement_limit", "current": 0, "max": 10},
        ],
    },
    "meteoForecasts": [
        {"kind": "earthquake", "turnsUntil": 5}
    ],
}


def test_arena_parses_camelcase_fields():
    arena = Arena.model_validate(SAMPLE_ARENA)
    assert arena.turn_no == 42
    assert arena.next_turn_in == 0.85
    assert arena.action_range == 2
    assert arena.size == [100, 100]


def test_arena_parses_plantations():
    arena = Arena.model_validate(SAMPLE_ARENA)
    assert len(arena.plantations) == 2
    hq = arena.plantations[0]
    assert hq.is_main is True
    assert hq.is_isolated is False
    assert hq.immunity_until_turn == 45
    assert hq.position == [50, 50]


def test_arena_parses_upgrades():
    arena = Arena.model_validate(SAMPLE_ARENA)
    pu = arena.plantation_upgrades
    assert pu.points == 1
    assert pu.max_points == 15
    assert len(pu.tiers) == 2
    assert pu.tiers[0].name == "repair_power"


def test_arena_parses_meteo_with_optional_fields():
    arena = Arena.model_validate(SAMPLE_ARENA)
    assert len(arena.meteo_forecasts) == 1
    eq = arena.meteo_forecasts[0]
    assert eq.kind == "earthquake"
    assert eq.turns_until == 5
    assert eq.position is None
    assert eq.radius is None


def test_arena_handles_missing_optional_lists():
    minimal = {
        "turnNo": 1,
        "nextTurnIn": 1.0,
        "size": [100, 100],
        "actionRange": 2,
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    }
    arena = Arena.model_validate(minimal)
    assert arena.plantations == []
    assert arena.beavers == []
    assert arena.meteo_forecasts == []
