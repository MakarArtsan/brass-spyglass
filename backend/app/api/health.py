from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import backup
from app.config import Settings, get_settings
from app.db import get_db

router = APIRouter()


def _backup_state(settings: Settings) -> dict[str, object] | None:
    """Когда сделана последняя ночная копия и дошла ли она владельцу (деталей и путей не отдаём)."""
    last = backup.read_status(settings)
    if last is None:
        return None
    return {"at": last.get("at"), "sent": last.get("sent"), "ok": last.get("error") is None}


@router.get("/health")
def health(request: Request, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    """Состояние для проверки деплоя. Секретов и данных не отдаёт."""
    settings = get_settings()
    db.execute(text("SELECT 1"))
    tg = request.app.state.tg
    return {
        "status": "ok",
        "database": "ok",
        "telegram": {
            "bot": tg.bot is not None,
            "userbot": tg.userbot is not None,
            "chat_configured": settings.tg_chat_id is not None,
        },
        "backup": _backup_state(settings),
        "session_secret_configured": bool(settings.session_secret),
        "owner_configured": settings.owner_tg_id is not None,
    }
