from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .build_dataset import read_tsv, write_tsv


def row_key(row: dict[str, Any]) -> str:
    return str(
        row.get("tweet_id")
        or row.get("rid")
        or row.get("notice_id")
        or row.get("reported_weibo_url")
        or row.get("uid")
        or row.get("page")
        or ""
    ).strip()


def merge_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in existing + incoming:
        key = row_key(row)
        if not key:
            continue
        base = merged.get(key, {})
        merged[key] = {**base, **{k: v for k, v in row.items() if str(v) != ""}}
    return list(merged.values())


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return read_tsv(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    write_tsv(path, rows, columns)
