import logging

import httpx

from scripts.run_session import (
    configure_logging,
    compute_logs_backoff_seconds,
    compute_retry_after_seconds,
    describe_command_status,
    summarize_construction,
    summarize_decision,
    summarize_response_errors,
)
from cherviak.models import Arena


def make_status_error(status_code: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/api/logs")
    response = httpx.Response(status_code, headers=headers, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_compute_logs_backoff_uses_retry_after_header():
    exc = make_status_error(429, headers={"Retry-After": "7"})
    assert compute_logs_backoff_seconds(exc, default=5.0) == 7.0


def test_compute_logs_backoff_falls_back_to_default():
    exc = make_status_error(429)
    assert compute_logs_backoff_seconds(exc, default=5.0) == 5.0


def test_compute_retry_after_seconds_uses_default_floor():
    exc = make_status_error(429, headers={"Retry-After": "0.2"})
    assert compute_retry_after_seconds(exc, default=1.0) == 1.0


def test_describe_command_status_marks_backoff():
    status = describe_command_status(
        {"command": [{"path": [[1, 1], [1, 1], [1, 2]]}]},
        submit_enabled=True,
        response={"skipped": "rate_limit_backoff", "retryInSeconds": 1.5},
    )
    assert status == "rate_limit_backoff"


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
