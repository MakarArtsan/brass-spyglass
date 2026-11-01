"""Аниматик: таймлайн фильма (шоты встык, ширина = длительность, под ними дорожки звука) и
список для «Смотреть фильм». Раскладку считает `metrics.py`, здесь — сборка ответа."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import metrics, models
from app.api import serialize
from app.api.entities import DbDep, UserDep
from app.auth import session
from app.services import finals, projects, versions
from app.services.core import NotFoundError

router = APIRouter(dependencies=[Depends(session.same_origin)])

MIN_CARD_SEC = 1.0


def _scenes(db: Session, project_id: int) -> list[models.Scene]:
    return list(
        db.scalars(
            select(models.Scene)
            .where(models.Scene.project_id == project_id, models.Scene.deleted_at.is_(None))
            .order_by(models.Scene.order, models.Scene.id)
        )
    )


def _shots(db: Session, project_id: int) -> list[models.Shot]:
    return list(
        db.scalars(
            select(models.Shot)
            .where(models.Shot.project_id == project_id, models.Shot.deleted_at.is_(None))
            .order_by(models.Shot.order, models.Shot.id)
        )
    )


def _cues(db: Session, project_id: int) -> list[models.SoundCue]:
    return list(
        db.scalars(
            select(models.SoundCue)
            .where(models.SoundCue.project_id == project_id, models.SoundCue.deleted_at.is_(None))
            .order_by(models.SoundCue.id)
        )
    )


def build(db: Session, project_id: int) -> dict[str, Any]:
    scenes, shots, cues = _scenes(db, project_id), _shots(db, project_id), _cues(db, project_id)
    layout = metrics.film_layout(
        [metrics.SceneIn(s.id, s.order, s.planned_sec, s.status) for s in scenes],
        [metrics.ShotLay(s.id, s.scene_id, s.order, s.duration_sec, s.status) for s in shots],
    )
    scene_by_id = {s.id: s for s in scenes}
    shot_by_id = {s.id: s for s in shots}
    scene_finals = finals.resolve(db, scenes)
    shot_finals = finals.resolve(db, shots)

    out_scenes: list[dict[str, Any]] = []
    playlist: list[dict[str, Any]] = []
    for span in layout:
        scene = scene_by_id[span.scene_id]
        scene_final = serialize.final_info(scene_finals.get(scene.id))
        title = f"Сцена {scene.number} · {scene.title}"
        shot_items = []
        for sp in span.shots:
            shot = shot_by_id[sp.shot_id]
            final = serialize.final_info(shot_finals.get(shot.id))
            shot_items.append(
                {
                    "id": shot.id,
                    "code": shot.code,
                    "description": shot.description,
                    "status": shot.status,
                    "side": shot.side,
                    "duration_sec": shot.duration_sec,
                    "start_sec": sp.start_sec,
                    "end_sec": sp.end_sec,
                    "final": final,
                }
            )
        out_scenes.append(
            {
                "id": scene.id,
                "number": scene.number,
                "title": scene.title,
                "status": scene.status,
                "planned_sec": scene.planned_sec,
                "start_sec": span.start_sec,
                "end_sec": span.end_sec,
                "final": scene_final,
                "shots": shot_items,
            }
        )
        # Что играет: готовая сцена целиком, иначе готовые шоты;
        # где файла нет — карточка с описанием на время шота.
        length = span.end_sec - span.start_sec
        if scene_final is not None:
            playlist.append(
                _item(
                    "file",
                    scene,
                    None,
                    title,
                    scene.meaning,
                    span.start_sec,
                    span.end_sec,
                    scene_final,
                    length,
                )
            )
        elif shot_items:
            for sp, item in zip(span.shots, shot_items, strict=True):
                playlist.append(
                    _item(
                        "file" if item["final"] else "card",
                        scene,
                        item["id"],
                        f"Шот {item['code']}",
                        item["description"],
                        sp.start_sec,
                        sp.end_sec,
                        item["final"],
                        item["duration_sec"],
                    )
                )
        else:
            playlist.append(
                _item(
                    "card",
                    scene,
                    None,
                    title,
                    scene.meaning,
                    span.start_sec,
                    span.end_sec,
                    None,
                    length,
                )
            )

    cue_files = versions.current_many(db, {c.file_id for c in cues if c.file_id})
    sound: list[dict[str, Any]] = []
    for cue in cues:
        lane = metrics.SOUND_LANES.get(cue.type)
        if lane is None:
            continue
        file = cue_files.get(cue.file_id) if cue.file_id else None
        placed = metrics.cue_span(
            metrics.CueIn(
                cue.id,
                cue.scene_id,
                cue.shot_id,
                cue.start_offset_sec,
                file.duration_sec if file else None,
            ),
            layout,
        )
        if placed is None:
            continue
        sound.append(
            {
                "id": cue.id,
                "code": cue.code,
                "type": cue.type,
                "lane": lane,
                "who": cue.who,
                "text_en": cue.text_en,
                "start_sec": placed[0],
                "end_sec": placed[1],
                "has_file": file is not None,
                "shot_id": cue.shot_id,
                "scene_id": cue.scene_id,
            }
        )
    total = layout[-1].end_sec if layout else 0.0
    return {
        "total_sec": total,
        "scenes": out_scenes,
        "sound": sound,
        "playlist": playlist,
        "ready_count": sum(1 for p in playlist if p["kind"] == "file"),
    }


def _item(
    kind: str,
    scene: models.Scene,
    shot_id: int | None,
    title: str,
    description: str | None,
    start: float,
    end: float,
    file: dict[str, Any] | None,
    length: float,
) -> dict[str, Any]:
    playing = (file or {}).get("duration_sec") or length
    return {
        "kind": kind,
        "scene_id": scene.id,
        "shot_id": shot_id,
        "title": title,
        "description": description,
        "start_sec": start,
        "end_sec": end,
        "duration_sec": max(MIN_CARD_SEC, float(playing)),
        "file": file,
    }


@router.get("/animatic")
def animatic(db: DbDep, _: UserDep) -> dict[str, Any]:
    project = projects.get_project(db)
    if project is None:
        raise NotFoundError("Проект не создан")
    return build(db, project.id)
