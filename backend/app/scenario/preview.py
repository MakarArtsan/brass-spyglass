"""Предпросмотр импорта: что будет создано, до записи в базу (чистая функция, без базы).

Отдаёт готовые для экрана данные: шапка со счётчиками, полоса фильма (сцены пропорционально
длительности, в них шоты и реплики), списки персонажей, локаций и ассетов с числом шотов,
открытые вопросы LLM — они станут задачами.
"""

from typing import Any

from app.scenario import schema as S
from app.scenario.check import Params
from app.scenario.convert import counts


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 2)


def _entries(
    items: list[Any], doc: S.ScenarioDoc, *, kind: str | None = None
) -> list[dict[str, Any]]:
    """Список для вкладки: код, название, состояния, сколько шотов и сцен."""
    out = []
    for item in items:
        shots = [
            (scene.number, position)
            for scene in doc.scenes
            for position, shot in enumerate(scene.shots, start=1)
            if item.code in shot.asset_codes
        ]
        scenes = {number for number, _ in shots} | {
            scene.number for scene in doc.scenes if item.code in scene.location_codes
        }
        entry: dict[str, Any] = {
            "code": item.code,
            "name": item.name,
            "kind": kind or getattr(item, "kind", None) or getattr(item, "type", None),
            "description": item.description if hasattr(item, "description") else None,
            "states": [s.name for s in item.states],
            "shots": len(shots),
            "scenes": len(scenes),
        }
        out.append(entry)
    return out


def build(doc: S.ScenarioDoc, params: Params) -> dict[str, Any]:
    names = {c.code: c.name for c in (*doc.characters, *doc.locations, *doc.assets)}
    total = sum(scene.planned_sec for scene in doc.scenes)
    shots_total = sum(shot.duration_sec for scene in doc.scenes for shot in scene.shots)
    scenes = []
    for scene in doc.scenes:
        scenes.append(
            {
                "number": scene.number,
                "title": scene.title,
                "summary": scene.summary,
                "planned_sec": _number(scene.planned_sec),
                "shots_sec": _number(sum(shot.duration_sec for shot in scene.shots)),
                "location": ", ".join(names[c] for c in scene.location_codes if c in names) or None,
                "shots": [
                    {
                        "position": position,
                        "description": shot.description,
                        "size": shot.size,
                        "duration_sec": _number(shot.duration_sec),
                        "dialogue": [
                            {
                                "who": line.speaker
                                or (names.get(line.character or "") if line.character else None),
                                "text": line.text,
                            }
                            for line in shot.dialogue
                        ],
                    }
                    for position, shot in enumerate(scene.shots, start=1)
                ],
            }
        )
    return {
        "title": doc.project.title,
        "title_en": doc.project.title_en,
        "logline": doc.project.logline,
        "language": doc.project.language,
        "schema_version": S.SCHEMA_VERSION,
        "counts": dict(counts(doc)),
        "total_sec": _number(total),
        "shots_sec": _number(shots_total),
        "target_min_sec": params.target_min_sec,
        "target_max_sec": params.target_max_sec,
        "in_target": None
        if params.target_min_sec is None or params.target_max_sec is None
        else params.target_min_sec <= total <= params.target_max_sec,
        "scenes": scenes,
        "characters": _entries(doc.characters, doc),
        "locations": _entries(doc.locations, doc, kind="Локация"),
        "assets": _entries(doc.assets, doc),
        "open_questions": [
            {"question": q.question, "related": [names.get(c, c) for c in q.related]}
            for q in doc.open_questions
        ],
    }
