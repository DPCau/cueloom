"""JSONL stage artifacts: one JSON object per line, UTF-8, no BOM."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def write_jsonl(path: Path, records: Iterable[BaseModel | dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            obj = record.model_dump(mode="json") if isinstance(record, BaseModel) else record
            handle.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def read_jsonl(path: Path, model: type[T] | None = None) -> list[T] | list[dict]:
    if not path.exists():
        return []
    records: list[T] | list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            records.append(model.model_validate(obj) if model else obj)  # type: ignore[arg-type]
    return records
