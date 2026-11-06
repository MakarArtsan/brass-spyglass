"""Чаты, подключённые боту (`/connect`). Бот собирает медиа новых проектов, но сам в чат его никто
не «назначает»: человек добавляет бота в закрытый чат команды и присылает ему команду — так чат
попадает в список при создании проекта. Вся запись в базу по этим чатам — здесь."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import utcnow
from app.services import projects
from app.services.core import ConflictError, ValidationError

MAX_TITLE = 200


def get(db: Session, chat_id: int) -> models.BotChat | None:
    return db.scalar(select(models.BotChat).where(models.BotChat.chat_id == chat_id))


def connect(
    db: Session,
    *,
    chat_id: int,
    title: str,
    tg_id: int,
    bot_admin: bool,
    forum: bool,
    now: datetime | None = None,
) -> models.BotChat:
    """Запоминает чат за администратором, приславшим команду (проверку прав делает бот: Telegram
    знает это, мы — нет). Повторная команда обновляет название и права бота, а подключившим считает
    того, кто прислал её последним: любой администратор чата вправе его занять. Чат, у которого уже
    есть проект, не подключается."""
    project = projects.get_by_chat(db, chat_id)
    if project is not None:
        raise ConflictError(f"Этот чат уже подключён к проекту «{project.title}»")
    title = title.strip()[:MAX_TITLE]
    if not title:
        raise ValidationError("У чата нет названия")
    row = get(db, chat_id)
    if row is None:
        row = models.BotChat(chat_id=chat_id, connected_at=now or utcnow())
        db.add(row)
    row.title = title
    row.connected_by_tg_id = tg_id
    row.bot_admin = bot_admin
    row.forum = forum
    db.flush()
    return row


def available(
    db: Session, tg_id: int, *, superadmin: bool, exclude: set[int] | frozenset[int] = frozenset()
) -> list[models.BotChat]:
    """Чаты, из которых этот человек может создать проект: подключённые им самим (владелец сайта
    видит все), и ещё не занятые проектом."""
    query = select(models.BotChat).order_by(models.BotChat.title, models.BotChat.id)
    if not superadmin:
        query = query.where(models.BotChat.connected_by_tg_id == tg_id)
    taken = set(exclude)
    return [c for c in db.scalars(query) if c.chat_id not in taken]


def usable_by(db: Session, tg_id: int, chat_id: int, *, superadmin: bool) -> models.BotChat | None:
    """Чат, подключённый этим человеком (или любой — владельцу сайта); иначе None."""
    row = get(db, chat_id)
    if row is None or not (superadmin or row.connected_by_tg_id == tg_id):
        return None
    return row
