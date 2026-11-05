"""Свои проекты: чаты, которыми человек может распоряжаться, и создание проекта.

Вне проектов (`/api/projects/…`): человек ещё не в проекте. Чат проверяет сервер через юзербота:
человек должен состоять в нём администратором, а аккаунт юзербота — быть в чате, иначе чужой чат
можно было бы «занять». Проверку не обойти: без подключённого юзербота проект с чатом не
создаётся (кроме суперадмина).
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import select

from app import approvals, models
from app import db as database
from app.api import access
from app.auth import session
from app.auth.membership import ChatInfo, MembershipUnavailable
from app.config import get_settings
from app.constants import Role
from app.permissions import PermissionDenied
from app.schemas import (
    AvailableChatsOut,
    ChatOut,
    DecisionOut,
    PendingOut,
    ProjectBrief,
    ProjectCreate,
    UserbotOut,
)
from app.services import core, projects

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", dependencies=[Depends(session.same_origin)])

SCAN_TIMEOUT_SEC = (
    90.0  # просмотр чатов юзербота долгий: Telegram отвечает не быстрее 1 запроса в секунду
)
CHECK_TIMEOUT_SEC = 60.0

UserDep = access.UserDep


def _context(user_id: int) -> tuple[int | None, bool, set[int]]:
    """Telegram-id человека, можно ли ему создавать проекты, уже занятые чаты."""
    with database.session_factory()() as db:
        user = db.get(models.User, user_id)
        assert user is not None
        bound = {c for c in db.scalars(select(models.Project.tg_chat_id)) if c is not None}
        return user.tg_id, projects.can_create(db, user), bound


def _create(user_id: int, body: ProjectCreate, chat: ChatInfo | None) -> ProjectBrief:
    with database.session_factory()() as db:
        user = db.get(models.User, user_id)
        assert user is not None
        project = projects.create(
            db,
            user,
            title=body.title,
            title_en=body.title_en,
            deadline=body.deadline,
            chat_id=chat.id if chat else None,
            settings=get_settings(),
        )
        db.commit()
        return ProjectBrief(
            slug=project.slug,
            title=project.title,
            title_en=project.title_en,
            role=Role.OWNER.value,
            archived=False,
            pending=project.approved_at is None,
        )


async def _after_create(app: FastAPI, slug: str, chat_id: int) -> None:
    """Подтверждённому проекту сразу запускает индексатор чата, неподтверждённому — сообщает
    суперадмину о заявке (с кнопками решения). Знакомых по чату впускает в проект при любом
    исходе."""
    with database.session_factory()() as db:
        project = projects.get_by_slug(db, slug)
        if project is None:
            return
        project_id, title, approved = project.id, project.title, project.approved_at is not None
        owner = next(iter(projects.owners(db, project)), None)
        who = (
            f"{owner.name} (@{owner.tg_username})"
            if owner is not None and owner.tg_username
            else (owner.name if owner else "—")
        )
    if approved:
        pool = getattr(app.state, "indexer_pool", None)
        if pool is not None:
            try:
                await pool.ensure(chat_id)
            except Exception:
                log.exception("индексатор чата %s не запущен", chat_id)
    else:
        await app.state.tg.announce_request(project_id, title, who)
    try:
        await app.state.tg.sync_project(project_id, chat_id)
    except Exception:
        log.exception("участники чата %s не прочитаны", chat_id)


def _forbidden() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "Новые проекты вам недоступны")


@router.get("/available-chats", response_model=AvailableChatsOut)
async def available_chats(request: Request, user: UserDep) -> AvailableChatsOut:
    """Чаты, где есть и юзербот, и вы (администратором) и которые ещё не заняты проектом."""
    tg_id, allowed, bound = await asyncio.to_thread(_context, user.id)
    if not allowed:
        raise _forbidden()
    tg = request.app.state.tg
    account = UserbotOut(**tg.userbot_account) if tg.userbot_account else None
    if tg.userbot is None or tg_id is None:
        return AvailableChatsOut(
            ready=False,
            userbot=account,
            chats=[],
            message="Подключение к Telegram сейчас недоступно. Попробуйте позже.",
        )
    try:
        chats = await asyncio.wait_for(
            tg.membership.manageable_chats(tg_id, bound), SCAN_TIMEOUT_SEC
        )
    except (MembershipUnavailable, TimeoutError):
        return AvailableChatsOut(
            ready=False,
            userbot=account,
            chats=[],
            message="Telegram не ответил. Подождите минуту и обновите список.",
        )
    return AvailableChatsOut(
        ready=True,
        userbot=account,
        chats=[ChatOut(id=c.id, title=c.title) for c in chats],
    )


@router.post("", response_model=ProjectBrief, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, request: Request, background: BackgroundTasks, user: UserDep
) -> ProjectBrief:
    tg_id, allowed, _ = await asyncio.to_thread(_context, user.id)
    if not allowed:
        raise _forbidden()
    chat: ChatInfo | None = None
    if body.chat_id is not None:
        tg = request.app.state.tg
        if tg.userbot is None or tg_id is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Подключение к Telegram недоступно: чат проверить нельзя. Попробуйте позже.",
            )
        superadmin = get_settings().is_superadmin(tg_id)
        try:
            chat = await asyncio.wait_for(
                tg.membership.chat_for(tg_id, body.chat_id, require_admin=not superadmin),
                CHECK_TIMEOUT_SEC,
            )
        except (MembershipUnavailable, TimeoutError):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram не ответил. Попробуйте ещё раз."
            ) from None
        if chat is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Вы не администратор этого чата, или аккаунт юзербота не добавлен в него.",
            )
    brief = await asyncio.to_thread(_create, user.id, body, chat)
    if chat is not None:
        background.add_task(_after_create, request.app, brief.slug, chat.id)
    return brief


# --- заявки на подтверждение (только суперадмин) -------------------------------------------


def _require_superadmin(user_id: int) -> None:
    with database.session_factory()() as db:
        user = db.get(models.User, user_id)
        if user is None or not get_settings().is_superadmin(user.tg_id):
            raise PermissionDenied("Заявки видит и решает только владелец сайта")


def _pending(user_id: int) -> list[PendingOut]:
    _require_superadmin(user_id)
    with database.session_factory()() as db:
        out = []
        for project in projects.pending(db):
            owner = next(iter(projects.owners(db, project)), None)
            out.append(
                PendingOut(
                    slug=project.slug,
                    title=project.title,
                    title_en=project.title_en,
                    created_at=project.created_at,
                    owner_name=owner.name if owner else None,
                    owner_username=owner.tg_username if owner else None,
                )
            )
        return out


def _project_id(slug: str) -> int:
    with database.session_factory()() as db:
        project = projects.get_by_slug(db, slug)
        if project is None:
            raise core.NotFoundError("Такого проекта нет")
        return project.id


@router.get("/pending", response_model=list[PendingOut])
async def pending_projects(user: UserDep) -> list[PendingOut]:
    return await asyncio.to_thread(_pending, user.id)


async def _decide(
    request: Request, slug: str, action: approvals.Action, user: UserDep
) -> DecisionOut:
    project_id = await asyncio.to_thread(_project_id, slug)
    outcome = await approvals.decide(request.app, action, project_id, user.id)
    return DecisionOut(slug=outcome.slug, title=outcome.title, status=action)


@router.post("/{slug}/approve", response_model=DecisionOut)
async def approve_project(slug: str, request: Request, user: UserDep) -> DecisionOut:
    return await _decide(request, slug, "approve", user)


@router.post("/{slug}/reject", response_model=DecisionOut)
async def reject_project(slug: str, request: Request, user: UserDep) -> DecisionOut:
    return await _decide(request, slug, "reject", user)
