"""Пересобирает эталонный пример импорта «Битва при кривом зеркале» из Excel-трекера.

    cd backend && .venv/bin/python scripts/make_scenario_example.py

Файл `app/scenario/example-brass-spyglass.json` лежит в репозитории и отдаётся на сайте как «пример
готового файла»; тест сверяет, что он создаёт ровно столько же записей, сколько Excel-импорт.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.scenario.check import Params, check_texts  # noqa: E402
from app.scenario.convert import bundle_to_document  # noqa: E402
from app.xlsx_reader import read_workbook  # noqa: E402

SOURCE = ROOT / "seed" / "Krivoe_zerkalo_tracker.xlsx"
TARGET = ROOT / "app" / "scenario" / "example-brass-spyglass.json"


def main() -> None:
    bundle = read_workbook(SOURCE)
    doc = bundle_to_document(
        bundle,
        title="Битва при кривом зеркале",
        title_en="The Brass Spyglass",
        sides=["Север", "Юг"],
    )
    text = doc.model_dump_json(indent=1)
    result = check_texts([text], Params(target_min_sec=300, target_max_sec=420))
    if not result.ok:
        sys.exit("пример не проходит проверку:\n" + "\n".join(i.text() for i in result.errors))
    TARGET.write_text(text + "\n", encoding="utf-8")
    print(f"{TARGET.relative_to(ROOT)}: {len(text)} байт, предупреждений {len(result.warnings)}")


if __name__ == "__main__":
    main()
