#!/usr/bin/env python3
"""Minimal arena poller: prints turnNo, nextTurnIn, and request timings."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cherviak.client import GameClient
from cherviak.config import load_config


POLL_INTERVAL = 0.5


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def main() -> int:
    config = load_config()
    with GameClient(config, log_requests=False) as client:
        while True:
            t_send = time.time()
            try:
                arena = client.get_arena()
            except Exception as exc:
                t_recv = time.time()
                print(
                    f"sent={fmt_ts(t_send)} recv={fmt_ts(t_recv)} "
                    f"rtt={(t_recv - t_send) * 1000:.1f}ms error={type(exc).__name__}: {exc}"
                )
            else:
                t_recv = time.time()
                print(
                    f"sent={fmt_ts(t_send)} recv={fmt_ts(t_recv)} "
                    f"rtt={(t_recv - t_send) * 1000:.1f}ms "
                    f"turnNo={arena.turn_no} nextTurnIn={arena.next_turn_in}"
                )
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
