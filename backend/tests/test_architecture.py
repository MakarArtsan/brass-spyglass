"""Договорённость из ТЗ: записей в базу в обход сервисного слоя нет."""

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
WRITE = re.compile(
    r"\b(?:db|session)\.(?:add|add_all|delete|merge|execute\(\s*(?:insert|update|delete))\b"
)


def test_no_direct_writes_outside_services():
    offenders = []
    for path in APP.rglob("*.py"):
        if "services" in path.parts:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if WRITE.search(line):
                offenders.append(f"{path.relative_to(APP)}:{number}: {line.strip()}")
    assert offenders == []
