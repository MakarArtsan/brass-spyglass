"""SSE: `/api/p/<slug>/events` — одна подписка на вкладку и проект. События приходят только тем, кто
состоит в проекте (включая гостя), и только по этому проекту."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app import db as database
from app import events, models
from app.api.access import not_found, role_in
from app.auth import session
from app.services import projects

router = APIRouter()


def stream_project(slug: str, bs_session: Annotated[str | None, Cookie()] = None) -> int:
    """Проверяет вход и членство короткой сессией БД: на время потока соединение с базой занимать
    нельзя. Возвращает id проекта."""
    uid = session.read(bs_session)
    with database.session_factory()() as db:
        user = db.get(models.User, uid) if uid is not None else None
        if user is None or user.access_revoked_at is not None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
        project = projects.get_by_slug(db, slug)
        if project is None or role_in(db, project, user) is None:
            raise not_found()
        return project.id


@router.get("/events")
async def event_stream(project_id: Annotated[int, Depends(stream_project)]) -> StreamingResponse:
    if events.bus.subscribers >= events.MAX_SUBSCRIBERS:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Слишком много подключений")
    return StreamingResponse(
        events.sse_stream(events.bus, project_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
