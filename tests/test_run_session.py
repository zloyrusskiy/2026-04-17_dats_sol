import json
import logging
from pathlib import Path

import pytest

from scripts.run_session import (
    SessionWriter,
    configure_logging,
    describe_command_status,
    find_hq_id,
    looks_like_active_arena,
    summarize_construction,
    summarize_decision,
    summarize_response_errors,
)
from cherviak.models import Arena


def _make_arena(plantations=None, size=(100, 100)) -> Arena:
    return Arena.model_validate(
        {
            "turnNo": 1,
            "nextTurnIn": 1.0,
            "size": list(size),
            "actionRange": 2,
            "plantations": plantations or [],
            "enemy": [],
            "mountains": [],
            "cells": [],
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


def _hq(hq_id: str, pos=(10, 10)) -> dict:
    return {
        "id": hq_id,
        "position": list(pos),
        "isMain": True,
        "isIsolated": False,
        "immunityUntilTurn": 0,
        "hp": 100,
    }


def test_find_hq_id_returns_main_plantation_id():
    arena = _make_arena(plantations=[_hq("hq-1"), {
        "id": "p2",
        "position": [11, 10],
        "isMain": False,
        "isIsolated": False,
        "immunityUntilTurn": 0,
        "hp": 50,
    }])
    assert find_hq_id(arena) == "hq-1"


def test_find_hq_id_returns_none_when_no_main():
    arena = _make_arena()
    assert find_hq_id(arena) is None


def test_looks_like_active_arena_rejects_zero_size():
    assert looks_like_active_arena(_make_arena(size=(0, 0))) is False
    assert looks_like_active_arena(_make_arena(size=(100, 100))) is True


def test_session_writer_creates_session_dir_and_meta_on_first_hq(tmp_path: Path):
    writer = SessionWriter(
        root=tmp_path,
        strategy_name="lateral",
        submit=True,
        latency_avg=0.12,
        poll_interval=0.4,
        base_url="https://example.test",
    )
    switched = writer.ensure_for_hq("hq-alpha")

    assert switched is True
    assert writer.session_dir == tmp_path / "session_hq-alpha"
    assert writer.turns_path == tmp_path / "session_hq-alpha" / "turns.jsonl"
    assert writer.logs_path == tmp_path / "session_hq-alpha" / "logs.jsonl"

    meta = json.loads((writer.session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["hqId"] == "hq-alpha"
    assert meta["strategy"] == "lateral"
    assert meta["submit"] is True
    assert meta["latencyAvg"] == 0.12
    assert meta["pollInterval"] == 0.4
    assert meta["baseUrl"] == "https://example.test"


def test_session_writer_ensure_is_idempotent_for_same_hq(tmp_path: Path):
    writer = SessionWriter(
        root=tmp_path,
        strategy_name="lateral",
        submit=False,
        latency_avg=0.1,
        poll_interval=0.5,
        base_url="https://example.test",
    )
    writer.ensure_for_hq("hq-1")
    meta_path = writer.session_dir / "meta.json"
    original_meta_text = meta_path.read_text(encoding="utf-8")

    switched = writer.ensure_for_hq("hq-1")

    assert switched is False
    assert meta_path.read_text(encoding="utf-8") == original_meta_text


def test_session_writer_switches_dir_when_hq_changes(tmp_path: Path):
    writer = SessionWriter(
        root=tmp_path,
        strategy_name="lateral",
        submit=False,
        latency_avg=0.1,
        poll_interval=0.5,
        base_url="https://example.test",
    )
    writer.ensure_for_hq("hq-1")
    first_dir = writer.session_dir

    switched = writer.ensure_for_hq("hq-2")

    assert switched is True
    assert writer.session_dir != first_dir
    assert writer.session_dir == tmp_path / "session_hq-2"
    assert first_dir.exists()
    assert (first_dir / "meta.json").exists()


def test_describe_command_status_marks_server_side_errors():
    status = describe_command_status(
        {"command": [{"path": [[1, 1], [1, 1], [1, 2]]}]},
        submit_enabled=True,
        response={"code": 0, "errors": ["command already submitted this turn"]},
    )
    assert status == "sent_with_errors"


def test_describe_command_status_returns_planned_when_submit_disabled():
    status = describe_command_status(
        {"command": [{"path": [[1, 1], [1, 1], [1, 2]]}]},
        submit_enabled=False,
        response=None,
    )
    assert status == "planned"


def test_summarize_construction_lists_progress():
    arena = Arena.model_validate(
        {
            "turnNo": 1,
            "nextTurnIn": 1.0,
            "size": [100, 100],
            "actionRange": 2,
            "plantations": [],
            "enemy": [],
            "mountains": [],
            "cells": [],
            "construction": [{"position": [253, 76], "progress": 5}],
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

    assert summarize_construction(arena) == "1:[253,76]=5"


def test_summarize_decision_includes_targets_relocate_and_upgrade():
    summary = summarize_decision(
        {
            "command": [{"path": [[254, 76], [254, 76], [253, 76]]}],
            "plantationUpgrade": "signal_range",
            "relocateMain": [[254, 76], [253, 76]],
        }
    )

    assert summary == (
        "actions=1 targets=[253,76] relocate=[254,76]->[253,76] upgrade=signal_range"
    )


def test_summarize_response_errors_shows_compact_messages():
    errors = summarize_response_errors(
        {"code": 0, "errors": ["command already submitted this turn", "other issue", "third"]}
    )

    assert errors == "command already submitted this turn | other issue | +1"


def test_configure_logging_enables_debug_for_request_logger():
    root_logger = logging.getLogger()
    request_logger = logging.getLogger("cherviak.client")
    arena_raw_logger = logging.getLogger("cherviak.client.arena_raw")

    root_level_before = root_logger.level
    request_level_before = request_logger.level
    arena_raw_level_before = arena_raw_logger.level
    root_handlers_before = list(root_logger.handlers)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    root_logger.setLevel(logging.WARNING)
    request_logger.setLevel(logging.NOTSET)
    arena_raw_logger.setLevel(logging.NOTSET)

    try:
        configure_logging()
        assert root_logger.level == logging.INFO
        assert request_logger.level == logging.DEBUG
        assert arena_raw_logger.level == logging.INFO
        assert not arena_raw_logger.isEnabledFor(logging.DEBUG)
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in root_handlers_before:
            root_logger.addHandler(handler)
        root_logger.setLevel(root_level_before)
        request_logger.setLevel(request_level_before)
        arena_raw_logger.setLevel(arena_raw_level_before)


def test_runner_log_message_does_not_include_strategy_name(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        logging.info(
            "turn=%s nextTurnIn=%.3f decision_ms=%.1f submit_ms=%.1f plantations=%s cells=%s construction=%s decision=%s command=%s errors=%s",
            42,
            0.5,
            12.3,
            4.1,
            2,
            1,
            "0",
            "actions=0 targets=- relocate=- upgrade=-",
            "planned",
            "-",
        )

    assert "strategy=" not in caplog.text
