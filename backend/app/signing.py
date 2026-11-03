"""Короткоживущие подписанные ссылки на файлы: `/api/p/<slug>/files/<id>/<вариант>?t=<подпись>`.

Подпись привязана к проекту, файлу и варианту (оригинал, превью, прокси…) и живёт
`file_link_ttl_sec`. Ссылка работает только вместе с сессией и членством в проекте: файлы отдаются
исключительно участникам проекта, и подпись чужого проекта не подходит.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app import scope
from app.auth.session import _fallback_secret
from app.config import Settings, get_settings

_SALT = "brass-spyglass-file-link"
VARIANTS = ("original", "thumb", "preview", "poster", "proxy", "waveform")


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret or _fallback_secret, salt=_SALT)


def sign(file_id: int, variant: str, project_id: int, settings: Settings | None = None) -> str:
    return _serializer(settings or get_settings()).dumps([file_id, variant, project_id])


def verify(
    token: str | None,
    file_id: int,
    variant: str,
    project_id: int,
    settings: Settings | None = None,
) -> bool:
    if not token:
        return False
    settings = settings or get_settings()
    try:
        data = _serializer(settings).loads(token, max_age=settings.file_link_ttl_sec)
    except (BadSignature, SignatureExpired):
        return False
    return data == [file_id, variant, project_id]


def file_url(
    db: Session, file_id: int, variant: str = "original", settings: Settings | None = None
) -> str:
    """Ссылка на файл проекта, в котором работает сессия."""
    project_id, slug = scope.current_project_id(db), db.info[scope.PROJECT_SLUG]
    token = sign(file_id, variant, project_id, settings)
    return f"/api/p/{slug}/files/{file_id}/{variant}?t={token}"
