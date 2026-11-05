from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_username: str | None
    name: str
    color: str
    role: str
    has_avatar: bool = False
    last_seen_at: datetime | None


class AbilitiesOut(BaseModel):
    """Что можно текущему пользователю — интерфейс прячет лишнее, но решает сервер."""

    upload: bool
    export: bool
    journal: bool
    manage_users: bool
    restore: bool
    edit_project: bool


class MeOut(BaseModel):
    """Человек в проекте: роль проекта и что она позволяет."""

    user: UserOut
    abilities: AbilitiesOut


class ProjectBrief(BaseModel):
    """Строка списка проектов человека. Чужих проектов здесь нет и названий их не узнать."""

    slug: str
    title: str
    title_en: str
    role: str
    archived: bool
    pending: bool = False  # ждёт подтверждения суперадмина


class SessionOut(BaseModel):
    """Кто вошёл и какие проекты ему открыты (вне проекта)."""

    user: UserOut
    is_superadmin: bool
    projects: list[ProjectBrief]
    can_create_projects: bool = False
    pending_count: int = 0  # сколько заявок ждёт суперадмина (обычным людям 0)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    approved: bool  # подтверждён суперадмином; иначе команда не загружает файлы
    title: str
    title_en: str
    contest: str
    deadline_official: datetime
    deadline_internal: datetime
    fps: int
    width: int
    height: int
    target_min_sec: int
    target_max_sec: int
    storage_limit_gb: float


ProjectTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class ProjectRename(BaseModel):
    """Новое название проекта: по-русски и/или по-английски. Адрес проекта (`slug`) не меняется."""

    model_config = ConfigDict(extra="forbid")

    title: ProjectTitle | None = None
    title_en: ProjectTitle | None = None


class ProjectCreate(BaseModel):
    """Новый проект. Чат обязателен всем, кроме суперадмина; адрес проекта строится из названия."""

    model_config = ConfigDict(extra="forbid")

    title: ProjectTitle
    title_en: ProjectTitle | None = None
    deadline: date | None = None
    chat_id: int | None = None


class ChatOut(BaseModel):
    id: int
    title: str


class UserbotOut(BaseModel):
    """Аккаунт, которого нужно добавить в чат проекта."""

    username: str | None
    name: str | None


class PendingOut(BaseModel):
    """Заявка на проект, которую решает суперадмин."""

    slug: str
    title: str
    title_en: str
    created_at: datetime
    owner_name: str | None
    owner_username: str | None


class DecisionOut(BaseModel):
    slug: str
    title: str
    status: str  # approve | reject


class AvailableChatsOut(BaseModel):
    ready: bool  # False — юзербот недоступен, список выдать нельзя (причина в `message`)
    userbot: UserbotOut | None
    chats: list[ChatOut]
    message: str | None = None


class AuthConfigOut(BaseModel):
    login_available: bool
    bot_username: str


class LoginTokenOut(BaseModel):
    token: str
    bot_url: str
    expires_in: int
