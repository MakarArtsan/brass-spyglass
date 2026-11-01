"""SSE: `/api/events` — одна подписка на вкладку, события приходят всем вошедшим (включая гостя)."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app import db as database
from app import events, models
from app.auth import session

router = APIRouter()


def stream_user(bs_session: Annotated[str | None, Cookie()] = None) -> int:
    """Проверяет вход короткой сессией БД: на время потока соединение с базой занимать нельзя."""
    uid = session.read(bs_session)
    with database.session_factory()() as db:
        user = db.get(models.User, uid) if uid is not None else None
        if user is None or user.access_revoked_at is not None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
        return user.id


@router.get("/events")
async def event_stream(_: Annotated[int, Depends(stream_user)]) -> StreamingResponse:
    if events.bus.subscribers >= events.MAX_SUBSCRIBERS:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Слишком много подключений")
    return StreamingResponse(
        events.sse_stream(events.bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
