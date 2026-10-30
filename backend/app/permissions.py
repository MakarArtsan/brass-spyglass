"""Матрица ролей из ТЗ («Пользователи, роли и доступ») — единственное место, где она описана.

Владелец: видит всё, редактирует всё, загружает, удаляет всё (включая чужое), экспорт.
Режиссёр: видит всё, редактирует всё кроме участников, загружает, удаляет своё и чужое
          (в корзину), экспорт.
Команда:  видит всё, редактирует статусы, комментарии и свои карточки, загружает,
          удаляет только своё, экспорт.
Гость:    видит всё кроме журнала, редактировать ничего нельзя (только комментарии),
          не загружает, не удаляет, экспорта нет.
"""

from dataclasses import dataclass

from app.constants import EntityType, Role


@dataclass(frozen=True, slots=True)
class Actor:
    """Кто действует: id пользователя и его роль на момент запроса."""

    id: int
    role: Role


class PermissionDenied(Exception):  # noqa: N818 — читается лучше, чем PermissionDeniedError
    """Роль не позволяет действие. API превращает это в 403."""


# Поля, которые «Команда» может менять на любой карточке (остальное — только на своих).
TEAM_FREE_FIELDS = frozenset({"status"})


def can_view(actor: Actor) -> bool:
    return True


def can_view_journal(actor: Actor) -> bool:
    return actor.role != Role.GUEST


def can_upload(actor: Actor) -> bool:
    return actor.role != Role.GUEST


def can_export(actor: Actor) -> bool:
    return actor.role != Role.GUEST


def can_create(actor: Actor, entity_type: str) -> bool:
    if entity_type == EntityType.USER:
        return False  # участники появляются только через вход по Telegram
    if entity_type == EntityType.COMMENT:
        return True  # комментировать могут все, включая гостя
    return actor.role != Role.GUEST


def can_edit(actor: Actor, entity_type: str, owner_id: int | None, fields: set[str]) -> bool:
    """`owner_id` — автор карточки (created_by / uploaded_by); `fields` — что меняем."""
    match actor.role:
        case Role.OWNER:
            return True
        case Role.DIRECTOR:
            return entity_type != EntityType.USER
        case Role.TEAM:
            if entity_type == EntityType.USER:
                return False
            if owner_id == actor.id:
                return True
            return bool(fields) and fields <= TEAM_FREE_FIELDS
        case _:
            return False


def can_delete(actor: Actor, owner_id: int | None) -> bool:
    match actor.role:
        case Role.OWNER | Role.DIRECTOR:
            return True
        case Role.TEAM:
            return owner_id == actor.id
        case _:
            return False


def can_restore(actor: Actor) -> bool:
    """Из корзины восстанавливает только владелец."""
    return actor.role == Role.OWNER


def can_manage_users(actor: Actor) -> bool:
    return actor.role == Role.OWNER


def require(allowed: bool, message: str = "Недостаточно прав") -> None:
    if not allowed:
        raise PermissionDenied(message)
