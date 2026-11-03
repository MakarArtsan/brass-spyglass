from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class SessionOut(BaseModel):
    """Кто вошёл и какие проекты ему открыты (вне проекта)."""

    user: UserOut
    is_superadmin: bool
    projects: list[ProjectBrief]


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
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


class AuthConfigOut(BaseModel):
    login_available: bool
    bot_username: str


class LoginTokenOut(BaseModel):
    token: str
    bot_url: str
    expires_in: int
