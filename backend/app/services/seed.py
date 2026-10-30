"""Стартовые данные: на пустой базе сайт сразу открывается заполненным из Excel-трекера."""

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services.importing import ImportReport, apply_bundle
from app.xlsx_reader import read_workbook

log = logging.getLogger(__name__)


def seed_if_empty(db: Session, project_id: int, path: Path | None) -> ImportReport | None:
    """Импортирует Excel, только если в проекте ещё не было ни одной сцены (в том числе
    удалённой). Так перезапуск не затрёт правки; повторный импорт — явным скриптом."""
    if path is None or not path.is_file():
        return None
    if db.scalar(select(func.count()).select_from(models.Scene)):
        return None
    report = apply_bundle(db, project_id, read_workbook(path))
    log.info("стартовые данные из %s: создано %s", path.name, dict(report.created))
    return report
