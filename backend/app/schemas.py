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
    user: UserOut
    abilities: AbilitiesOut


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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
