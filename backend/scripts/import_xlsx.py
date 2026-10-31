"""Импорт Excel-трекера в базу (идемпотентный).

    DATA_DIR=/data python scripts/import_xlsx.py seed/Krivoe_zerkalo_tracker.xlsx [--dry-run]
                                                 [--overwrite-work-fields]

Записи ищутся по коду и обновляются, а не дублируются. Без --overwrite-work-fields статусы,
приоритеты, дедлайны, комментарии и порядок уже существующих записей не трогаются.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as database  # noqa: E402
from app import metrics  # noqa: E402
from app.migrate import upgrade_to_head  # noqa: E402
from app.services import projects  # noqa: E402
from app.services.importing import apply_bundle  # noqa: E402
from app.xlsx_reader import read_workbook  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="показать отчёт и откатить")
    parser.add_argument("--overwrite-work-fields", action="store_true")
    args = parser.parse_args()

    bundle = read_workbook(args.xlsx)
    database.init_engine()
    upgrade_to_head()
    with database.session_factory()() as db:
        project = projects.ensure_default_project(db)
        report = apply_bundle(
            db, project.id, bundle, overwrite_work_fields=args.overwrite_work_fields
        )
        checks = metrics.consistency_checks(db, project.id)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    print("Создано:", dict(report.created) or "—")
    print("Обновлено:", dict(report.updated) or "—")
    print("Восстановлено:", dict(report.restored) or "—")
    print("\nПроверки:")
    for check in checks:
        print(f"  {'✓' if check.ok else '✗'} {check.name}: {check.detail}")
    if report.warnings:
        print(f"\nПредупреждения ({len(report.warnings)}):")
        for warning in report.warnings:
            print("  -", warning)
    if args.dry_run:
        print("\n(пробный запуск: ничего не записано)")
    if not all(c.ok for c in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
