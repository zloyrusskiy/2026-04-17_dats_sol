import json
import os
from pathlib import Path

from scripts import session_viewer


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_list_sessions_uses_lightweight_summary(tmp_path, monkeypatch):
    older = tmp_path / "session_20260417T100000Z"
    latest = tmp_path / "session_20260417T110000Z"
    older.mkdir()
    latest.mkdir()

    write_json(
        older / "meta.json",
        {"startedAt": "2026-04-17T10:00:00Z", "strategy": "passive", "hqId": "hq-old", "latencyAvg": 0.1},
    )
    write_json(
        latest / "meta.json",
        {"startedAt": "2026-04-17T11:00:00Z", "strategy": "lateral", "hqId": "hq-new", "latencyAvg": 0.15},
    )
    write_jsonl(older / "turns.jsonl", [{"kind": "turn", "turnNo": 3}, {"kind": "turn", "turnNo": 4}])
    write_jsonl(latest / "turns.jsonl", [{"kind": "turn", "turnNo": 10}, {"kind": "turn", "turnNo": 11}])
    write_jsonl(older / "logs.jsonl", [{"message": "a"}])
    write_jsonl(latest / "logs.jsonl", [{"message": "a"}, {"message": "b"}])

    monkeypatch.setattr(
        session_viewer,
        "load_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full session load is not expected")),
    )
    monkeypatch.setattr(
        session_viewer,
        "session_dir_created_ts",
        lambda path: {older.resolve(): 100.0, latest.resolve(): 200.0}[path],
    )

    sessions = session_viewer.list_sessions(tmp_path)

    assert [session["id"] for session in sessions] == [latest.name, older.name]
    assert sessions[0]["createdTs"] == 200.0
    assert sessions[0]["frameCount"] == 2
    assert sessions[0]["firstTurn"] == 10
    assert sessions[0]["lastTurn"] == 11
    assert sessions[0]["logCount"] == 2
    assert sessions[0]["hqId"] == "hq-new"
    assert sessions[0]["latencyAvg"] == 0.15


def test_list_sessions_prefers_folder_creation_time_over_started_at(tmp_path, monkeypatch):
    newer_meta = tmp_path / "session_meta_newer"
    newer_dir = tmp_path / "session_dir_newer"
    newer_meta.mkdir()
    newer_dir.mkdir()

    write_json(
        newer_meta / "meta.json",
        {"startedAt": "2026-04-17T12:00:00Z", "strategy": "passive", "hqId": "hq-meta"},
    )
    write_json(
        newer_dir / "meta.json",
        {"startedAt": "2026-04-17T10:00:00Z", "strategy": "lateral", "hqId": "hq-dir"},
    )
    write_jsonl(newer_meta / "turns.jsonl", [{"kind": "turn", "turnNo": 2}])
    write_jsonl(newer_dir / "turns.jsonl", [{"kind": "turn", "turnNo": 3}])

    monkeypatch.setattr(
        session_viewer,
        "session_dir_created_ts",
        lambda path: {newer_meta.resolve(): 100.0, newer_dir.resolve(): 200.0}[path],
    )

    sessions = session_viewer.list_sessions(tmp_path)

    assert [session["id"] for session in sessions] == [newer_dir.name, newer_meta.name]


def test_load_session_exposes_html_legend_separately(tmp_path):
    session_dir = tmp_path / "session_20260417T120000Z"
    session_dir.mkdir()

    write_json(session_dir / "meta.json", {"strategy": "passive"})
    write_jsonl(
        session_dir / "turns.jsonl",
        [
            {
                "kind": "turn",
                "turnNo": 7,
                "arena": {
                    "turnNo": 7,
                    "size": [3, 2],
                    "actionRange": 4,
                    "mountains": [],
                    "cells": [{"position": [0, 0], "terraformationProgress": 55}],
                    "construction": [],
                    "enemy": [],
                    "plantations": [{"id": "hq-42", "position": [1, 1], "isMain": True, "hp": 99}],
                    "beavers": [],
                },
                "capturedAt": "2026-04-17T12:00:00Z",
                "nextTurnIn": 1,
                "strategyElapsedMs": 12.5,
                "submitElapsedMs": 5.0,
                "decision": {"kind": "wait"},
                "response": {"ok": True},
            }
        ],
    )
    write_jsonl(session_dir / "logs.jsonl", [])

    payload = session_viewer.load_session(str(session_dir), cell_size=18)

    frame = payload["frames"][0]
    assert frame["legend"]["title"] == "DatsSol Session Frame"
    assert frame["legend"]["stats"][0] == "turn: 7"
    assert any(item["label"] == "your HQ" for item in frame["legend"]["items"])
    assert 'width="138"' in frame["svg"]
    assert frame["hqId"] == "hq-42"
    assert frame["strategyElapsedMs"] == 12.5
    assert frame["submitElapsedMs"] == 5.0


def test_load_session_refreshes_when_turns_file_changes(tmp_path):
    session_dir = tmp_path / "session_20260417T130000Z"
    session_dir.mkdir()

    turns_path = session_dir / "turns.jsonl"
    write_json(session_dir / "meta.json", {"strategy": "passive"})
    write_jsonl(
        turns_path,
        [
            {
                "kind": "turn",
                "turnNo": 7,
                "arena": {
                    "turnNo": 7,
                    "size": [2, 2],
                    "actionRange": 4,
                    "mountains": [],
                    "cells": [],
                    "construction": [],
                    "enemy": [],
                    "plantations": [{"id": "hq-42", "position": [1, 1], "isMain": True, "hp": 99}],
                    "beavers": [],
                },
            }
        ],
    )
    write_jsonl(session_dir / "logs.jsonl", [])

    payload = session_viewer.load_session(str(session_dir), cell_size=18)
    assert [frame["turnNo"] for frame in payload["frames"]] == [7]

    write_jsonl(
        turns_path,
        [
            {
                "kind": "turn",
                "turnNo": 7,
                "arena": {
                    "turnNo": 7,
                    "size": [2, 2],
                    "actionRange": 4,
                    "mountains": [],
                    "cells": [],
                    "construction": [],
                    "enemy": [],
                    "plantations": [{"id": "hq-42", "position": [1, 1], "isMain": True, "hp": 99}],
                    "beavers": [],
                },
            },
            {
                "kind": "turn",
                "turnNo": 8,
                "arena": {
                    "turnNo": 8,
                    "size": [2, 2],
                    "actionRange": 4,
                    "mountains": [],
                    "cells": [],
                    "construction": [],
                    "enemy": [],
                    "plantations": [{"id": "hq-42", "position": [1, 1], "isMain": True, "hp": 97}],
                    "beavers": [],
                },
            },
        ],
    )
    stat = turns_path.stat()
    os.utime(turns_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    refreshed = session_viewer.load_session(str(session_dir), cell_size=18)
    assert [frame["turnNo"] for frame in refreshed["frames"]] == [7, 8]
