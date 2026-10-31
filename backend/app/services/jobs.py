"""Фоновая очередь в той же базе (таблица `job`). Статусы и прогресс пишутся здесь."""

from collections.abc import Collection
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.constants import JobStatus, JobType
from app.db import utcnow
from app.events import queue_event

MAX_ERROR_LEN = 500
PROGRESS_STEP = 0.05  # прогресс ffmpeg меняется чаще, чем нужно клиенту: шлём не чаще чем раз в 5%


def _announce(db: Session, job: models.Job) -> None:
    """Сообщает клиентам о смене задачи: статус, прогресс и файл, к которому она относится."""
    queue_event(
        db,
        {
            "type": "job",
            "id": job.id,
            "job_type": job.type,
            "status": job.status,
            "progress": round(job.progress or 0, 2),
            "file_id": (job.payload or {}).get("file_id"),
            "created_by": job.created_by,
        },
    )


def enqueue(
    db: Session, job_type: JobType, payload: dict[str, Any], created_by: int | None = None
) -> models.Job:
    job = models.Job(type=job_type.value, payload=payload, created_by=created_by)
    db.add(job)
    db.flush()
    _announce(db, job)
    return job


def claim_next(db: Session, skip: Collection[str] = ()) -> models.Job | None:
    """Берёт самую старую задачу из очереди и помечает её выполняемой. Типы из `skip` не берутся."""
    stmt = select(models.Job).where(models.Job.status == JobStatus.QUEUED.value)
    if skip:
        stmt = stmt.where(models.Job.type.not_in(list(skip)))
    job = db.scalar(stmt.order_by(models.Job.id).limit(1))
    if job is None:
        return None
    job.status = JobStatus.RUNNING.value
    job.started_at = utcnow()
    job.progress = 0
    db.flush()
    _announce(db, job)
    return job


def set_progress(db: Session, job_id: int, progress: float) -> None:
    job = db.get(models.Job, job_id)
    if job is not None:
        new = max(0.0, min(1.0, progress))
        moved = abs(new - (job.progress or 0)) >= PROGRESS_STEP
        job.progress = new
        if moved:
            _announce(db, job)


def finish(db: Session, job_id: int) -> None:
    job = db.get(models.Job, job_id)
    if job is not None:
        job.status = JobStatus.DONE.value
        job.progress = 1.0
        job.finished_at = utcnow()
        _announce(db, job)


def fail(db: Session, job_id: int, error: str) -> None:
    job = db.get(models.Job, job_id)
    if job is not None:
        job.status = JobStatus.FAILED.value
        job.error = error[:MAX_ERROR_LEN]
        job.finished_at = utcnow()
        _announce(db, job)


def requeue_interrupted(db: Session) -> int:
    """После перезапуска незавершённые задачи возвращаются в очередь (ТЗ)."""
    rows = list(db.scalars(select(models.Job).where(models.Job.status == JobStatus.RUNNING.value)))
    for job in rows:
        job.status = JobStatus.QUEUED.value
        job.progress = 0
        job.started_at = None
    return len(rows)


def file_activity(db: Session, file_ids: list[int]) -> tuple[set[int], dict[int, str]]:
    """Какие файлы ещё обрабатываются и у каких последняя задача упала (id → ошибка)."""
    if not file_ids:
        return set(), {}
    wanted = set(file_ids)
    active: set[int] = set()
    failed: dict[int, str] = {}
    rows = db.scalars(
        select(models.Job)
        .where(
            models.Job.type.in_(
                [JobType.PREVIEW.value, JobType.PROXY.value, JobType.WAVEFORM.value]
            )
        )
        .order_by(models.Job.id)
    )
    for job in rows:
        file_id = job.payload.get("file_id")
        if file_id not in wanted:
            continue
        if job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
            active.add(file_id)
            failed.pop(file_id, None)
        elif job.status == JobStatus.FAILED.value:
            failed[file_id] = job.error or "ошибка обработки"
        elif job.status == JobStatus.DONE.value:
            failed.pop(file_id, None)
    return active, failed
