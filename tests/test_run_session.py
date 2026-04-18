import logging
from pathlib import Path

import anyio
import httpx

from scripts.run_session import (
    ARENA_WARMUP_SAMPLES,
    MIN_POLL_SLEEP,
    compute_arena_sleep,
    effective_latency,
    configure_logging,
    describe_command_status,
    fetch_arena_once,
    summarize_construction,
    summarize_decision,
    summarize_response_errors,
    update_latency_estimate,
    warmup_complete,
)
from cherviak.models import Arena


class FailingArenaClient:
    def get_arena(self):
        request = httpx.Request("GET", "https://example.test/api/arena")
        response = httpx.Response(503, text="unavailable", request=request)
        raise httpx.HTTPStatusError("boom", request=request, response=response)


def test_update_latency_estimate_initializes_from_first_sample():
    state: dict[str, float] = {}

    mean, jitter = update_latency_estimate(state, observed_latency=0.25)

    assert mean == 0.25
    assert jitter == 0.0
    assert state == {"mean": 0.25, "jitter": 0.0}


def test_update_latency_estimate_smooths_single_spike():
    state: dict[str, float] = {}
    update_latency_estimate(state, observed_latency=0.10)
    update_latency_estimate(state, observed_latency=0.10)

    mean, jitter = update_latency_estimate(state, observed_latency=0.50)

    assert round(mean, 3) == 0.18
    assert round(jitter, 3) == 0.08
    assert round(effective_latency(mean, jitter), 3) == 0.34


def test_warmup_complete_requires_three_samples():
    assert warmup_complete(ARENA_WARMUP_SAMPLES - 1) is False
    assert warmup_complete(ARENA_WARMUP_SAMPLES) is True


def test_compute_arena_sleep_uses_half_latency():
    sleep_for = compute_arena_sleep(next_turn_in=0.95, latency=0.06)

    assert round(sleep_for, 3) == round(0.95 - 0.03, 3)


def test_compute_arena_sleep_respects_min_poll_sleep():
    sleep_for = compute_arena_sleep(next_turn_in=0.01, latency=0.10)

    assert sleep_for == MIN_POLL_SLEEP


def test_fetch_arena_once_logs_error_and_returns_none(tmp_path: Path):
    result = anyio.run(fetch_arena_once, FailingArenaClient(), tmp_path / "turns.jsonl")

    assert result is None
    payload = (tmp_path / "turns.jsonl").read_text(encoding="utf-8")
    assert '"kind": "http_error"' in payload
    assert '"statusCode": 503' in payload


def test_describe_command_status_marks_server_side_errors():
    status = describe_command_status(
        {"command": [{"path": [[1, 1], [1, 1], [1, 2]]}]},
        submit_enabled=True,
        response={"code": 0, "errors": ["command already submitted this turn"]},
    )
    assert status == "sent_with_errors"


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

    root_level_before = root_logger.level
    request_level_before = request_logger.level
    root_handlers_before = list(root_logger.handlers)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    root_logger.setLevel(logging.WARNING)
    request_logger.setLevel(logging.NOTSET)

    try:
        configure_logging()
        assert root_logger.level == logging.INFO
        assert request_logger.level == logging.DEBUG
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in root_handlers_before:
            root_logger.addHandler(handler)
        root_logger.setLevel(root_level_before)
        request_logger.setLevel(request_level_before)


def test_runner_log_message_does_not_include_strategy_name(caplog):
    with caplog.at_level(logging.INFO):
        logging.info(
            "turn=%s decision_time_ms=%.1f plantations=%s cells=%s construction=%s decision=%s command=%s errors=%s",
            42,
            12.3,
            2,
            1,
            "0",
            "actions=0 targets=- relocate=- upgrade=-",
            "planned",
            "-",
        )

    assert "strategy=" not in caplog.text
