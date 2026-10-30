"""Схема данных. Сущности повторяют листы Excel-трекера плюс пользователи, файлы,
индекс медиа из Telegram, комментарии и журнал (см. ТЗ, «Модель данных»).

Вычисляемое (таймкоды сцен, суммы, % готовности) здесь не хранится — оно считается в metrics.py.
Прямых записей в БД в обход сервисного слоя нет (app/services).
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.constants import (
    DRUM_LEVEL_RANGE,
    FPS_CHOICES,
    AssetType,
    EntityType,
    ExportTarget,
    FileKind,
    FileSource,
    JobStatus,
    JobType,
    Priority,
    Purpose,
    Role,
    ShotSize,
    Side,
    SoundType,
    Stage,
    Status,
    Tool,
    check_in,
)
from app.db import UTCDateTime, utcnow

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _check_nullable_in(column: str, enum_cls: type) -> str:
    return f"{column} IS NULL OR {check_in(column, enum_cls)}"  # type: ignore[arg-type]


def _alive(table_index: str, *columns: str) -> Index:
    """Уникальность среди неудалённых строк: код можно использовать повторно после корзины."""
    return Index(
        table_index,
        *columns,
        unique=True,
        sqlite_where=text("deleted_at IS NULL"),
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class WorkMixin(Timestamps):
    """Общий набор полей рабочих сущностей (ТЗ, «Модель данных»)."""

    status: Mapped[str] = mapped_column(String(16), default=Status.NOT_STARTED.value)
    priority: Mapped[str | None] = mapped_column(String(16), default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    @declared_attr
    def assignee_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("user.id"), default=None, index=True)

    @declared_attr
    def created_by(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("user.id"), default=None)

    @declared_attr
    def updated_by(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("user.id"), default=None)


def work_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(check_in("status", Status), name="status"),
        CheckConstraint(_check_nullable_in("priority", Priority), name="priority"),
    )


class Project(Timestamps, Base):
    __tablename__ = "project"
    __table_args__ = (CheckConstraint(f"fps IN ({', '.join(map(str, FPS_CHOICES))})", name="fps"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    title_en: Mapped[str] = mapped_column(String(200))
    contest: Mapped[str] = mapped_column(String(200))
    deadline_official: Mapped[datetime] = mapped_column(UTCDateTime)  # Asia/Dubai, хранится в UTC
    deadline_internal: Mapped[datetime] = mapped_column(UTCDateTime)
    fps: Mapped[int] = mapped_column(Integer, default=24)
    width: Mapped[int] = mapped_column(Integer, default=1920)
    height: Mapped[int] = mapped_column(Integer, default=1080)
    target_min_sec: Mapped[int] = mapped_column(Integer, default=300)
    target_max_sec: Mapped[int] = mapped_column(Integer, default=420)
    storage_limit_gb: Mapped[float] = mapped_column(Float, default=10.0)


class User(Timestamps, Base):
    __tablename__ = "user"
    __table_args__ = (CheckConstraint(check_in("role", Role), name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)  # у гостя нет
    tg_username: Mapped[str | None] = mapped_column(String(64), default=None)
    name: Mapped[str] = mapped_column(String(200))
    avatar_path: Mapped[str | None] = mapped_column(String(500), default=None)
    color: Mapped[str] = mapped_column(String(9))
    role: Mapped[str] = mapped_column(String(16), default=Role.TEAM.value)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    membership_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    access_revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class Scene(WorkMixin, Base):
    __tablename__ = "scene"
    __table_args__ = (
        *work_checks(),
        CheckConstraint(
            "drum_level IS NULL OR drum_level BETWEEN "
            f"{DRUM_LEVEL_RANGE[0]} AND {DRUM_LEVEL_RANGE[1]}",
            name="drum_level",
        ),
        CheckConstraint(_check_nullable_in("side", Side), name="side"),
        _alive("uq_scene_number", "project_id", "number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    order: Mapped[int] = mapped_column(
        "order", Integer
    )  # порядок в трекере, меняется перетаскиванием
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300), default=None)
    time_of_day: Mapped[str | None] = mapped_column(String(100), default=None)
    planned_sec: Mapped[float] = mapped_column(Float, default=0)
    drum_level: Mapped[int | None] = mapped_column(Integer, default=None)
    meaning: Mapped[str | None] = mapped_column(Text, default=None)
    cut_notes: Mapped[str | None] = mapped_column(Text, default=None)
    side: Mapped[str | None] = mapped_column(String(8), default=None)
    final_file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"), default=None)


class Shot(WorkMixin, Base):
    __tablename__ = "shot"
    __table_args__ = (
        *work_checks(),
        CheckConstraint(_check_nullable_in("size", ShotSize), name="size"),
        CheckConstraint(_check_nullable_in("tool", Tool), name="tool"),
        CheckConstraint(_check_nullable_in("stage", Stage), name="stage"),
        CheckConstraint(_check_nullable_in("side", Side), name="side"),
        _alive("uq_shot_code", "project_id", "code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scene.id"), index=True)
    code: Mapped[str] = mapped_column(String(16))  # 01.03
    order: Mapped[int] = mapped_column("order", Integer)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    size: Mapped[str | None] = mapped_column(String(16), default=None)
    camera: Mapped[str | None] = mapped_column(String(300), default=None)
    duration_sec: Mapped[float] = mapped_column(Float, default=0)
    tool: Mapped[str | None] = mapped_column(String(16), default=None)
    stage: Mapped[str | None] = mapped_column(String(16), default=None)
    takes_count: Mapped[int] = mapped_column(Integer, default=0)
    side: Mapped[str | None] = mapped_column(String(8), default=None)
    final_file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"), default=None)


class Asset(WorkMixin, Base):
    __tablename__ = "asset"
    __table_args__ = (
        *work_checks(),
        CheckConstraint(check_in("type", AssetType), name="type"),
        CheckConstraint(_check_nullable_in("side", Side), name="side"),
        _alive("uq_asset_code", "project_id", "code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    code: Mapped[str] = mapped_column(String(16))  # CH-01
    type: Mapped[str] = mapped_column(String(16), default=AssetType.CHARACTER.value)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    side: Mapped[str | None] = mapped_column(String(8), default=None)


class AssetState(Timestamps, Base):
    """Состояние ассета: «полосатая», «смытая». У каждого свои референсы."""

    __tablename__ = "asset_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    order: Mapped[int] = mapped_column("order", Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class ShotAsset(Base):
    """Континьюити: какое состояние ассета в каком шоте."""

    __tablename__ = "shot_asset"
    __table_args__ = (UniqueConstraint("shot_id", "asset_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shot.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    asset_state_id: Mapped[int | None] = mapped_column(ForeignKey("asset_state.id"), default=None)


class SetupPayoff(WorkMixin, Base):
    __tablename__ = "setup_payoff"
    __table_args__ = work_checks()

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    motif: Mapped[str] = mapped_column(String(300))
    setup_shot_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    payoff_shot_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    reader_takeaway: Mapped[str | None] = mapped_column(Text, default=None)
    risk: Mapped[str | None] = mapped_column(Text, default=None)


class SoundCue(WorkMixin, Base):
    __tablename__ = "sound_cue"
    __table_args__ = (
        *work_checks(),
        CheckConstraint(check_in("type", SoundType), name="type"),
        _alive("uq_sound_cue_code", "project_id", "code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    code: Mapped[str] = mapped_column(String(16))  # SND-01
    type: Mapped[str] = mapped_column(String(16), default=SoundType.DIALOGUE.value)
    who: Mapped[str | None] = mapped_column(String(200), default=None)
    text_en: Mapped[str | None] = mapped_column(Text, default=None)
    text_ru: Mapped[str | None] = mapped_column(Text, default=None)
    rights: Mapped[str | None] = mapped_column(Text, default=None)
    start_offset_sec: Mapped[float] = mapped_column(Float, default=0)
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scene.id"), default=None)
    shot_id: Mapped[int | None] = mapped_column(ForeignKey("shot.id"), default=None)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"), default=None)


class Task(WorkMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        *work_checks(),
        CheckConstraint("(entity_type IS NULL) = (entity_id IS NULL)", name="entity_pair"),
        _alive("uq_task_code", "project_id", "code"),
        Index("ix_task_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    code: Mapped[str] = mapped_column(String(16))  # T-01
    block: Mapped[str | None] = mapped_column(String(200), default=None)
    title: Mapped[str] = mapped_column(String(500))
    entity_type: Mapped[str | None] = mapped_column(String(16), default=None)
    entity_id: Mapped[int | None] = mapped_column(Integer, default=None)


class File(Base):
    __tablename__ = "file"
    __table_args__ = (
        CheckConstraint(check_in("kind", FileKind), name="kind"),
        CheckConstraint(check_in("source", FileSource), name="source"),
        # Повторный выбор того же сообщения Telegram не создаёт дубль.
        Index(
            "uq_file_tg_message",
            "tg_chat_id",
            "tg_message_id",
            unique=True,
            sqlite_where=text("tg_message_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_file_sha256", "sha256"),
        Index("ix_file_version_group", "version_group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(String(1000), default=None)
    original_name: Mapped[str | None] = mapped_column(String(500), default=None)
    mime: Mapped[str | None] = mapped_column(String(200), default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    duration_sec: Mapped[float | None] = mapped_column(Float, default=None)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    fps: Mapped[float | None] = mapped_column(Float, default=None)
    thumb_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    proxy_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    waveform_json: Mapped[Any | None] = mapped_column(JSON, default=None)
    url: Mapped[str | None] = mapped_column(String(2000), default=None)
    link_title: Mapped[str | None] = mapped_column(String(500), default=None)
    version_group_id: Mapped[int | None] = mapped_column(Integer, default=None)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(default=True)
    ai_tool: Mapped[str | None] = mapped_column(String(100), default=None)
    ai_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    ai_seed: Mapped[str | None] = mapped_column(String(100), default=None)
    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    tg_topic_id: Mapped[int | None] = mapped_column(Integer, default=None)
    tg_message_id: Mapped[int | None] = mapped_column(Integer, default=None)
    tg_author: Mapped[str | None] = mapped_column(String(200), default=None)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class Attachment(Base):
    """Файл ↔ сущность. Снятие привязки — жёсткое, пишется в журнал."""

    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint(check_in("purpose", Purpose), name="purpose"),
        UniqueConstraint("file_id", "entity_type", "entity_id", "purpose"),
        Index("ix_attachment_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("file.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16), default=Purpose.REFERENCE.value)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TgTopic(Base):
    __tablename__ = "tg_topic"
    __table_args__ = (UniqueConstraint("chat_id", "topic_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    topic_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    icon_emoji: Mapped[str | None] = mapped_column(String(16), default=None)
    media_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class TgMedia(Base):
    """Индекс медиа из тем чата. Сам файл скачивается только при выборе."""

    __tablename__ = "tg_media"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id"),
        Index("ix_tg_media_topic_posted", "topic_id", "posted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    topic_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int] = mapped_column(Integer)
    grouped_id: Mapped[int | None] = mapped_column(BigInteger, default=None)  # альбом
    kind: Mapped[str] = mapped_column(String(16))
    mime: Mapped[str | None] = mapped_column(String(200), default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    duration_sec: Mapped[float | None] = mapped_column(Float, default=None)
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    author_name: Mapped[str | None] = mapped_column(String(200), default=None)
    author_tg_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    thumb_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    imported_file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"), default=None)


class Comment(Timestamps, Base):
    __tablename__ = "comment"
    __table_args__ = (Index("ix_comment_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[int]] = mapped_column(JSON, default=list)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"), default=None)
    at_time_sec: Mapped[float | None] = mapped_column(Float, default=None)  # комментарий к кадру
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class Activity(Base):
    """Журнал и источник графиков активности."""

    __tablename__ = "activity"
    __table_args__ = (
        Index("ix_activity_at", "at"),
        Index("ix_activity_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), default=None)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    action: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[int | None] = mapped_column(Integer, default=None)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Job(Base):
    """Фоновая очередь в той же базе."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(check_in("type", JobType), name="type"),
        CheckConstraint(check_in("status", JobStatus), name="status"),
        Index("ix_job_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED.value)
    progress: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class ExportJob(Base):
    """История экспортов в Resolve и Premiere."""

    __tablename__ = "export_job"
    __table_args__ = (CheckConstraint(check_in("target", ExportTarget), name="target"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job.id"), default=None)
    target: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(16), default="scenes")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# Сущности, поддерживающие привязку файлов, комментариев и задач.
ENTITY_TABLES: dict[str, type[Base]] = {
    EntityType.PROJECT.value: Project,
    EntityType.USER.value: User,
    EntityType.SCENE.value: Scene,
    EntityType.SHOT.value: Shot,
    EntityType.ASSET.value: Asset,
    EntityType.ASSET_STATE.value: AssetState,
    EntityType.SETUP_PAYOFF.value: SetupPayoff,
    EntityType.SOUND_CUE.value: SoundCue,
    EntityType.TASK.value: Task,
    EntityType.FILE.value: File,
    EntityType.COMMENT.value: Comment,
}
