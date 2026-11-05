"""Файл импорта ↔ пакет данных (`Bundle`), который уже понимает импортёр Excel.

Один путь записи в базу для Excel и JSON: коды, порядок и идемпотентность те же. Обратное
преобразование (пакет → файл) нужно, чтобы собрать эталонный пример фильма из Excel-трекера и
проверить, что JSON создаёт ровно столько же записей.
"""

from collections import Counter
from typing import Any

from app.constants import (
    AssetType,
    ShotSize,
    Side,
    SoundType,
    Stage,
    Status,
    TaskBlock,
)
from app.scenario import schema as S
from app.xlsx_reader import AssetRow, Bundle, SceneRow, SetupRow, ShotRow, SoundRow, TaskRow

KIND_TO_TYPE = {
    "Персонаж": AssetType.CHARACTER,
    "Массовка": AssetType.CROWD,
    "Животное": AssetType.ANIMAL,
}
ASSET_TO_TYPE = {
    "Реквизит": AssetType.PROP,
    "Бутафория": AssetType.FAUX_PROP,
    "Транспорт": AssetType.SHIP,
    "Эффект / среда": AssetType.EFFECT,
    "Стиль / лук": AssetType.STYLE,
}
SIZE_TO_CONST = {
    "Общий": ShotSize.WIDE,
    "Средний": ShotSize.MEDIUM,
    "Крупный": ShotSize.CLOSE,
    "Деталь": ShotSize.DETAIL,
    "POV": ShotSize.POV_SPYGLASS,
    "Сплит": ShotSize.SPLIT_MIRROR,
}
SIDES = {"север": Side.NORTH, "юг": Side.SOUTH}  # стороны в базе пока только эти две

TYPE_TO_KIND = {v.value: k for k, v in KIND_TO_TYPE.items()}
TYPE_TO_ASSET = {v.value: k for k, v in ASSET_TO_TYPE.items()}
CONST_TO_SIZE = {v.value: k for k, v in SIZE_TO_CONST.items()}

MAX_WHO = 200
NOT_STARTED = Status.NOT_STARTED.value


def shot_code(scene_number: int, position: int) -> str:
    """Код шота выдаёт сайт: «номер сцены.номер шота», как в Excel (01.03)."""
    return f"{scene_number:02d}.{position:02d}"


def _side(label: str | None, where: str, warnings: list[str]) -> str | None:
    if not label:
        return None
    side = SIDES.get(label.strip().casefold())
    if side is None:
        warnings.append(f"{where}: сторона «{label}» пока не поддерживается сайтом, пропущена")
        return None
    return side.value


def _join(*parts: str | None, sep: str = "\n\n") -> str | None:
    text = sep.join(p.strip() for p in parts if p and p.strip())
    return text or None


def _ref_to_code(ref: str) -> str | None:
    head, _, tail = ref.partition(".")
    return shot_code(int(head), int(tail)) if head.isdigit() and tail.isdigit() else None


def to_bundle(doc: S.ScenarioDoc) -> Bundle:
    """Файл → пакет для `importing.apply_bundle`. Ссылки уже проверены `check.check_references`."""
    bundle = Bundle()
    warnings = bundle.warnings
    by_code: dict[str, Any] = {}

    def asset_row(
        code: str,
        type_: str,
        name: str,
        description: str | None,
        states: list[S.State],
        side: str | None,
    ) -> AssetRow:
        return AssetRow(
            code=code,
            type=type_,
            name=name,
            description=description,
            states=[s.name for s in states],
            status=NOT_STARTED,
            priority=None,
            due_date=None,
            comment=None,
            side=_side(side, f"{code}", warnings),
        )

    for item in doc.characters:
        by_code[item.code] = item
        description = _join(
            item.description,
            f"Внешность: {item.appearance}" if item.appearance else None,
            f"EN: {item.name_en}" if item.name_en else None,
        )
        bundle.assets.append(
            asset_row(
                item.code,
                KIND_TO_TYPE[item.kind].value,
                item.name,
                description,
                item.states,
                item.side,
            )
        )
    for item in doc.locations:
        by_code[item.code] = item
        bundle.assets.append(
            asset_row(
                item.code, AssetType.LOCATION.value, item.name, item.description, item.states, None
            )
        )
    for item in doc.assets:
        by_code[item.code] = item
        bundle.assets.append(
            asset_row(
                item.code,
                ASSET_TO_TYPE[item.type].value,
                item.name,
                item.description,
                item.states,
                None,
            )
        )

    character_codes = {c.code for c in doc.characters}
    location_codes = {c.code for c in doc.locations}
    sound_n = 0
    for scene in doc.scenes:
        used: list[str] = []
        lines: list[str] = []
        for shot in scene.shots:
            used.extend(c for c in shot.asset_codes if c not in used)
            lines.extend(
                f"{(line.speaker or by_code[line.character].name)}: {line.text}"
                for line in shot.dialogue
            )
        bundle.scenes.append(
            SceneRow(
                number=scene.number,
                title=scene.title,
                location=", ".join(by_code[c].name for c in scene.location_codes) or None,
                time_of_day=scene.time_of_day,
                planned_sec=scene.planned_sec,
                characters=", ".join(by_code[c].name for c in used if c in character_codes) or None,
                key_assets=", ".join(
                    by_code[c].name
                    for c in used
                    if c not in character_codes and c not in location_codes
                )
                or None,
                lines_en="\n".join(lines) or None,
                drum_level=scene.intensity,
                meaning=scene.meaning,
                cut_notes=scene.cut_notes,
                status=NOT_STARTED,
                priority=None,
                due_date=None,
                comment=_join(
                    scene.summary,
                    f"Источник: {scene.source_ref}" if scene.source_ref else None,
                    sep=" · ",
                ),
                side=_side(scene.side, f"Сцена {scene.number}", warnings),
            )
        )
        for position, shot in enumerate(scene.shots, start=1):
            code = shot_code(scene.number, position)
            states = {c: n for c, n in shot.asset_states.items()}
            note_states = [f"{by_code[c].name} — {n}" for c, n in states.items() if c in by_code]
            bundle.shots.append(
                ShotRow(
                    code=code,
                    scene_number=scene.number,
                    description=shot.description,
                    size=SIZE_TO_CONST[shot.size].value if shot.size else None,
                    camera=shot.camera,
                    duration_sec=shot.duration_sec,
                    asset_codes=list(shot.asset_codes),
                    sound_note=shot.sfx,
                    tool=None,
                    stage=Stage.STORYBOARD.value,
                    takes_count=0,
                    status=NOT_STARTED,
                    priority=None,
                    due_date=None,
                    comment=_join(
                        shot.notes,
                        "Состояния: " + "; ".join(note_states) if note_states else None,
                        sep="\n",
                    ),
                    asset_states=states,
                )
            )
            for line in shot.dialogue:
                sound_n += 1
                who = line.speaker or (by_code[line.character].name if line.character else None)
                bundle.sounds.append(
                    SoundRow(
                        code=f"SND-{sound_n:02d}",
                        scene_number=scene.number,
                        shot_code=code,
                        type=SoundType.DIALOGUE.value,
                        who=who[:MAX_WHO] if who else None,
                        text_en=line.text,
                        text_ru=line.translation,
                        rights=None,
                        status=NOT_STARTED,
                        comment=None,
                    )
                )
            if shot.sfx:
                sound_n += 1
                bundle.sounds.append(
                    SoundRow(
                        code=f"SND-{sound_n:02d}",
                        scene_number=scene.number,
                        shot_code=code,
                        type=SoundType.SFX.value,
                        who=shot.sfx[:MAX_WHO],
                        text_en=None,
                        text_ru=None,
                        rights=None,
                        status=NOT_STARTED,
                        comment=None,
                    )
                )
    for number, setup in enumerate(doc.setups, start=1):
        bundle.setups.append(
            SetupRow(
                number=number,
                motif=setup.motif,
                setup_codes=[c for c in map(_ref_to_code, setup.setup) if c],
                payoff_codes=[c for c in map(_ref_to_code, setup.payoff) if c],
                reader_takeaway=setup.takeaway,
                risk=setup.risk,
                status=NOT_STARTED,
                comment=None,
            )
        )
    for number, question in enumerate(doc.open_questions, start=1):
        related = [by_code[c].name for c in question.related if c in by_code]
        title = question.question + (
            f" ({', '.join(question.related)}: {', '.join(related)})" if related else ""
        )
        bundle.tasks.append(
            TaskRow(
                code=f"T-{number:02d}",
                block=TaskBlock.PREPRODUCTION.value,
                title=title,
                due_date=None,
                status=NOT_STARTED,
                priority=None,
                comment=None,
            )
        )
    return bundle


def counts(doc: S.ScenarioDoc) -> Counter[str]:
    """Что будет создано: для шапки предпросмотра."""
    shots = [shot for scene in doc.scenes for shot in scene.shots]
    c: Counter[str] = Counter()
    c["scenes"] = len(doc.scenes)
    c["shots"] = len(shots)
    c["characters"] = len(doc.characters)
    c["locations"] = len(doc.locations)
    c["assets"] = len(doc.assets)
    c["dialogue"] = sum(len(shot.dialogue) for shot in shots)
    c["setups"] = len(doc.setups)
    c["open_questions"] = len(doc.open_questions)
    return c


# --- обратный путь: пакет (Excel) → файл ---------------------------------------------------------


def bundle_to_document(
    bundle: Bundle,
    *,
    title: str,
    title_en: str,
    language: str = "en",
    sides: list[str] | None = None,
) -> S.ScenarioDoc:
    """Эталонный файл из Excel-трекера: то же содержимое в формате схемы 1.0."""
    names = {a.name: a.code for a in bundle.assets}
    character_types = {AssetType.CHARACTER.value, AssetType.CROWD.value, AssetType.ANIMAL.value}
    characters, locations, assets = [], [], []
    for row in bundle.assets:
        states = [S.State(name=n) for n in row.states]
        if row.type in character_types:
            characters.append(
                S.Character(
                    code=row.code,
                    name=row.name,
                    kind=TYPE_TO_KIND[row.type],
                    description=row.description,
                    states=states,
                )  # fmt: skip
            )
        elif row.type == AssetType.LOCATION.value:
            locations.append(
                S.Location(code=row.code, name=row.name, description=row.description, states=states)
            )
        else:
            assets.append(
                S.Asset(
                    code=row.code,
                    type=TYPE_TO_ASSET[row.type],
                    name=row.name,
                    description=row.description,
                    states=states,
                )
            )
    location_codes = {loc.code for loc in locations}
    sounds_by_shot: dict[str, list[SoundRow]] = {}
    for sound in bundle.sounds:
        if sound.shot_code and sound.type == SoundType.DIALOGUE.value:
            sounds_by_shot.setdefault(sound.shot_code, []).append(sound)
    position_of: dict[str, tuple[int, int]] = {}
    scenes = []
    for scene in sorted(bundle.scenes, key=lambda s: s.number):
        shots = []
        in_scene = [shot for shot in bundle.shots if shot.scene_number == scene.number]
        for position, shot in enumerate(in_scene, start=1):
            position_of[shot.code] = (scene.number, position)
            dialogue = []
            for line in sounds_by_shot.get(shot.code, []):
                character = names.get(line.who or "")
                dialogue.append(
                    S.DialogueLine(
                        character=character,
                        speaker=None if character else line.who,
                        text=line.text_en or "…",
                        translation=line.text_ru,
                    )
                )
            shots.append(
                S.Shot(
                    description=shot.description or "—",
                    size=CONST_TO_SIZE.get(shot.size or ""),
                    camera=shot.camera,
                    duration_sec=shot.duration_sec or 1,
                    asset_codes=list(shot.asset_codes),
                    dialogue=dialogue,
                    sfx=shot.sound_note,
                    notes=shot.comment,
                )
            )
        used_locations = [c for shot in in_scene for c in shot.asset_codes if c in location_codes]
        scenes.append(
            S.Scene(
                number=scene.number,
                title=scene.title,
                location_codes=list(dict.fromkeys(used_locations)),
                time_of_day=scene.time_of_day,
                planned_sec=scene.planned_sec,
                meaning=scene.meaning,
                intensity=scene.drum_level,
                cut_notes=scene.cut_notes,
                shots=shots,
            )
        )

    def ref(code: str) -> str | None:
        found = position_of.get(code)
        return f"{found[0]}.{found[1]}" if found else None

    setups = [
        S.Setup(
            motif=row.motif,
            setup=[r for r in map(ref, row.setup_codes) if r],
            payoff=[r for r in map(ref, row.payoff_codes) if r],
            takeaway=row.reader_takeaway,
            risk=row.risk,
        )
        for row in bundle.setups
    ]
    in_shots = {c for scene in scenes for shot in scene.shots for c in shot.asset_codes}
    questions = [
        S.OpenQuestion(
            question=f"«{item.name}» есть в списке, но не появляется ни в одной сцене",
            related=[item.code],
        )
        for item in characters
        if item.code not in in_shots
    ]
    return S.ScenarioDoc(
        schema_version="1.0",
        project=S.Project(
            title=title,
            title_en=title_en,
            language=language,
            target_duration_sec=round(sum(s.planned_sec for s in bundle.scenes)),
            sides=sides or [],
            motifs=[S.Motif(name=m) for m in dict.fromkeys(row.motif for row in bundle.setups)],
        ),
        characters=characters,
        locations=locations,
        assets=assets,
        scenes=scenes,
        setups=setups,
        open_questions=questions,
    )


def example_fragment(doc: S.ScenarioDoc, scenes: int = 2) -> S.ScenarioDoc:
    """Короткий самодостаточный пример для промпта: первые сцены и то, на что они ссылаются."""
    chosen = doc.scenes[:scenes]
    refs = {c for scene in chosen for c in scene.location_codes}
    refs |= {c for scene in chosen for shot in scene.shots for c in shot.asset_codes}
    refs |= {
        line.character
        for scene in chosen
        for shot in scene.shots
        for line in shot.dialogue
        if line.character
    }
    available = {scene.number: len(scene.shots) for scene in chosen}

    def exists(ref: str) -> bool:
        scene_no, _, shot_no = ref.partition(".")
        return int(scene_no) in available and 1 <= int(shot_no) <= available[int(scene_no)]

    setups = [
        setup
        for setup in doc.setups
        if (setup.setup or setup.payoff) and all(exists(r) for r in (*setup.setup, *setup.payoff))
    ]
    return S.ScenarioDoc(
        schema_version="1.0",
        project=doc.project,
        characters=[c for c in doc.characters if c.code in refs],
        locations=[c for c in doc.locations if c.code in refs],
        assets=[c for c in doc.assets if c.code in refs],
        scenes=chosen,
        setups=setups,
        open_questions=[],
    )
