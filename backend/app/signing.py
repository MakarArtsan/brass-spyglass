"""Короткоживущие подписанные ссылки на файлы: `/api/files/<id>/<вариант>?t=<подпись>`.

Подпись привязана к файлу и варианту (оригинал, превью, прокси…) и живёт `file_link_ttl_sec`.
Ссылка работает только вместе с сессией: файлы отдаются исключительно залогиненным.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.session import _fallback_secret
from app.config import Settings, get_settings

_SALT = "brass-spyglass-file-link"
VARIANTS = ("original", "thumb", "preview", "poster", "proxy", "waveform")


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret or _fallback_secret, salt=_SALT)


def sign(file_id: int, variant: str, settings: Settings | None = None) -> str:
    return _serializer(settings or get_settings()).dumps([file_id, variant])


def verify(token: str | None, file_id: int, variant: str, settings: Settings | None = None) -> bool:
    if not token:
        return False
    settings = settings or get_settings()
    try:
        data = _serializer(settings).loads(token, max_age=settings.file_link_ttl_sec)
    except (BadSignature, SignatureExpired):
        return False
    return data == [file_id, variant]


def file_url(file_id: int, variant: str = "original", settings: Settings | None = None) -> str:
    return f"/api/files/{file_id}/{variant}?t={sign(file_id, variant, settings)}"
