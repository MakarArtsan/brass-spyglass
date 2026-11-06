"""Проекты: у каждого адрес `/p/<slug>` и свой закрытый чат команды."""

import re
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, permissions, scope
from app.config import Settings, get_settings
from app.constants import Collector, Role
from app.permissions import Actor, PermissionDenied
from app.services import members
from app.services.core import ConflictError, ValidationError, log_activity

# Дубай: UTC+4 круглый год, без перехода на летнее время, поэтому tzdata не нужен.
DUBAI = timezone(timedelta(hours=4))

DEFAULT_SLUG = "brass-spyglass"

DEFAULT_PROJECT = {
    "slug": DEFAULT_SLUG,
    "title": "Битва при кривом зеркале",
    "title_en": "The Brass Spyglass",
    "contest": "1 Billion AI Film Award 2027",
    # Подача до 20.11.2026 по времени Дубая (UTC+4), до конца суток; это 22:59:59 по Москве (UTC+3).
    # Час закрытия приёма организаторы нигде не публикуют — конец суток это допущение.
    # Внутренний срок 18.11.2026 — тоже до конца суток.
    "deadline_official": datetime(2026, 11, 20, 23, 59, 59, tzinfo=DUBAI).astimezone(UTC),
    "deadline_internal": datetime(2026, 11, 18, 23, 59, 59, tzinfo=DUBAI).astimezone(UTC),
    "fps": 24,
    "width": 1920,
    "height": 1080,
    "target_min_sec": 300,
    "target_max_sec": 420,
    "storage_limit_gb": 5.0,  # тариф Amvera
}


def get_project(db: Session) -> models.Project | None:
    return db.scalar(select(models.Project).order_by(models.Project.id).limit(1))


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip


def slugify(text: str, fallback: str = "project") -> str:
    """Адрес из названия: латиница, цифры и дефисы (кириллица транслитом); пусто — запасное имя."""
    latin = "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    base = re.sub(r"[^a-z0-9]+", "-", latin).strip("-")[:60].strip("-")
    return base or fallback


def unique_slug(db: Session, wanted: str) -> str:
    slug, n = wanted, 2
    while db.scalar(select(models.Project.id).where(models.Project.slug == slug)) is not None:
        slug, n = f"{wanted}-{n}", n + 1
    return slug


def rename(
    db: Session,
    actor: Actor,
    *,
    title: str | None = None,
    title_en: str | None = None,
) -> models.Project:
    """Меняет название проекта (рус. и/или англ.). Адрес `/p/<slug>` остаётся прежним: ссылки,
    закладки и подписанные ссылки не ломаются. Пишет в журнал пары «было → стало»."""
    permissions.require(permissions.can_edit_project(actor), "Переименовать проект может владелец")
    project = current(db)
    diff: dict[str, list[str]] = {}
    for field, value in (("title", title), ("title_en", title_en)):
        value = None if value is None else value.strip()
        if value and value != getattr(project, field):
            diff[field] = [getattr(project, field), value]
            setattr(project, field, value)
    if diff:
        log_activity(db, actor.id, "update", "project", project.id, diff, project_id=project.id)
    return project


def current(db: Session) -> models.Project:
    """Проект, в котором работает сессия (выбран `access.project_access`)."""
    project = db.get(models.Project, scope.current_project_id(db))
    if project is None:
        raise scope.ProjectScopeError("Проекта нет")
    return project


def get_by_slug(db: Session, slug: str) -> models.Project | None:
    return db.scalar(select(models.Project).where(models.Project.slug == slug))


def get_by_chat(db: Session, chat_id: int) -> models.Project | None:
    return db.scalar(select(models.Project).where(models.Project.tg_chat_id == chat_id))


def ensure_default_project(db: Session, settings: Settings | None = None) -> models.Project:
    """Первый запуск: создаёт проект фильма. Дальше настройки правят в интерфейсе.

    Чат, который до мультипроектности задавался переменной `TG_CHAT_ID`, становится чатом этого
    проекта (если у него своего чата ещё нет и чат не занят другим проектом)."""
    settings = settings or get_settings()
    project = get_project(db)
    if project is None:
        # Проект фильма создаёт сама система, подтверждать его некому: он активен сразу.
        project = models.Project(**DEFAULT_PROJECT, approved_at=datetime.now(UTC))
        db.add(project)
        db.flush()
        log_activity(db, None, "create", "project", project.id, project_id=project.id)
    chat = settings.tg_chat_id
    if chat is not None and project.tg_chat_id is None and get_by_chat(db, chat) is None:
        project.tg_chat_id = chat
        db.flush()
    return project


MOSCOW = timezone(timedelta(hours=3))
DEFAULT_DEADLINE_DAYS = 60
NOT_A_CONTEST = "—"  # у своего проекта конкурса нет; поле показывается на дашборде


def owned_count(db: Session, user: models.User) -> int:
    """В скольких живых проектах человек владелец (лимит на создание своих проектов)."""
    return (
        db.scalar(
            select(func.count())
            .select_from(models.ProjectMember)
            .join(models.Project, models.Project.id == models.ProjectMember.project_id)
            .where(
                models.ProjectMember.user_id == user.id,
                models.ProjectMember.active.is_(True),
                models.ProjectMember.role == Role.OWNER.value,
                models.Project.archived_at.is_(None),
            )
        )
        or 0
    )


def can_create(db: Session, user: models.User, settings: Settings | None = None) -> bool:
    """Суперадмин создаёт без ограничений. Остальные — если включено самообслуживание и они ещё не
    владеют предельным числом проектов (`MAX_PROJECTS_PER_USER`)."""
    settings = settings or get_settings()
    if settings.is_superadmin(user.tg_id):
        return True
    return settings.self_service_projects and owned_count(db, user) < settings.max_projects_per_user


def create(
    db: Session,
    user: models.User,
    *,
    title: str,
    title_en: str | None = None,
    deadline: date | None = None,
    chat_id: int | None = None,
    collector: Collector = Collector.USERBOT,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> models.Project:
    """Новый проект: создатель — его владелец. Чат проверяет вызывающий (через юзербота):
    сюда он приходит уже проверенным, а без чата проект создаёт только суперадмин.

    Срок сдачи по умолчанию — через 60 дней; внутренний срок — за два дня до него. Формат кадра и
    целевой хронометраж берутся из значений по умолчанию; лимит места — `NEW_PROJECT_STORAGE_GB`.
    """
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    if not can_create(db, user, settings):
        raise PermissionDenied(
            "Создать ещё один проект нельзя: достигнут предел или функция выключена"
        )
    title = title.strip()
    if not title:
        raise ValidationError("Назовите проект")
    if chat_id is None and not settings.is_superadmin(user.tg_id):
        raise ValidationError("Привяжите закрытый чат команды: проект живёт в чате Telegram")
    if chat_id is not None and get_by_chat(db, chat_id) is not None:
        raise ConflictError("Этот чат уже привязан к другому проекту")
    if deadline is not None and deadline < now.astimezone(MOSCOW).date():
        raise ValidationError("Срок сдачи уже прошёл")
    due = deadline or (now.astimezone(MOSCOW) + timedelta(days=DEFAULT_DEADLINE_DAYS)).date()
    official = datetime(due.year, due.month, due.day, 23, 59, 59, tzinfo=MOSCOW).astimezone(UTC)
    internal = official - timedelta(days=2)
    if internal <= now:
        internal = official  # срок близко: внутреннего «раньше» уже нет
    english = (title_en or "").strip() or title
    approved = settings.is_superadmin(user.tg_id) or not settings.project_approval
    project = models.Project(
        **{
            **DEFAULT_PROJECT,
            "slug": unique_slug(db, slugify(english, fallback=slugify(title))),
            "title": title,
            "title_en": english,
            "contest": NOT_A_CONTEST,
            "deadline_official": official,
            "deadline_internal": internal,
            "storage_limit_gb": settings.new_project_storage_gb,
            "tg_chat_id": chat_id,
            "collector": collector.value,
            # Свой проект суперадмина активен сразу; остальные ждут его подтверждения.
            "approved_at": now if approved else None,
            "approved_by": user.id if approved else None,
        }
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:  # два запроса на один чат одновременно: выигрывает один
        db.rollback()
        raise ConflictError("Этот чат уже привязан к другому проекту") from exc
    members.ensure(db, project, user, role=Role.OWNER, settings=settings)
    log_activity(
        db, user.id, "create", "project", project.id, {"chat_id": chat_id}, project_id=project.id
    )
    return project


def pending(db: Session) -> list[models.Project]:
    """Проекты, ждущие подтверждения суперадмина (отклонённые уходят в архив и сюда не попадают)."""
    return list(
        db.scalars(
            select(models.Project)
            .where(models.Project.approved_at.is_(None), models.Project.archived_at.is_(None))
            .order_by(models.Project.id)
        )
    )


def _require_superadmin(user: models.User, settings: Settings) -> None:
    if not settings.is_superadmin(user.tg_id):
        raise PermissionDenied("Подтверждает проекты только владелец сайта")


def approve(
    db: Session, user: models.User, project: models.Project, settings: Settings | None = None
) -> models.Project:
    """Подтверждение: команда получает право загружать файлы. Повторное — без последствий."""
    settings = settings or get_settings()
    _require_superadmin(user, settings)
    if project.approved_at is None:
        project.approved_at = datetime.now(UTC)
        project.approved_by = user.id
        db.flush()
        log_activity(db, user.id, "approve", "project", project.id, project_id=project.id)
    return project


def reject(
    db: Session, user: models.User, project: models.Project, settings: Settings | None = None
) -> int | None:
    """Отказ: проект уходит в архив, а чат освобождается — его можно привязать к другому проекту.
    Возвращает чат, который был у проекта (чтобы остановить его индексатор). Подтверждённый проект
    отклонить нельзя: его архивируют обычным способом."""
    settings = settings or get_settings()
    _require_superadmin(user, settings)
    if project.approved_at is not None:
        raise ConflictError("Проект уже подтверждён")
    chat = project.tg_chat_id
    project.archived_at = datetime.now(UTC)
    project.tg_chat_id = None
    db.flush()
    log_activity(
        db, user.id, "reject", "project", project.id, {"chat_id": chat}, project_id=project.id
    )
    return chat


def owners(db: Session, project: models.Project) -> list[models.User]:
    """Владельцы проекта (при заявке это тот, кто её подал): им сообщают о решении."""
    return list(
        db.scalars(
            select(models.User)
            .join(models.ProjectMember, models.ProjectMember.user_id == models.User.id)
            .where(
                models.ProjectMember.project_id == project.id,
                models.ProjectMember.role == Role.OWNER.value,
                models.ProjectMember.active.is_(True),
            )
            .order_by(models.User.id)
        )
    )
