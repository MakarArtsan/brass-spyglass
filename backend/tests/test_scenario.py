"""Импорт сценария: схема 1.0, проверка файла, автопоправки, части, промпт и запись в базу."""

import copy
import json
import re

import pytest
from sqlalchemy import func, select

from app import db as database
from app import models, scope
from app.scenario import check, convert, prompt
from app.scenario import schema as S
from app.scenario.check import Params
from app.services import importing, projects
from app.xlsx_reader import read_workbook
from tests.conftest import SEED_PATH

PARAMS = Params(target_min_sec=5, target_max_sec=20, max_shot_sec=15)


def good() -> dict:
    """Маленький правильный файл: одна сцена, две шота, реплика, сетап, открытый вопрос."""
    return copy.deepcopy(
        {
            "schema_version": "1.0",
            "project": {"title": "Тест", "language": "en", "sides": ["Север", "Юг"]},
            "characters": [
                {
                    "code": "CH-01",
                    "name": "Дозорный",
                    "name_en": "Watchman",
                    "kind": "Персонаж",
                    "side": "Юг",
                    "appearance": "Кривой",
                    "states": [{"name": "дозор"}, {"name": "бег"}],
                }
            ],
            "locations": [{"code": "LC-01", "name": "Стена"}],
            "assets": [{"code": "PR-01", "type": "Реквизит", "name": "Труба"}],
            "scenes": [
                {
                    "number": 1,
                    "title": "Тигр",
                    "location_codes": ["LC-01"],
                    "time_of_day": "Утро",
                    "planned_sec": 9,
                    "intensity": 1,
                    "summary": "Видит тигра",
                    "source_ref": "стр. 1",
                    "side": "Юг",
                    "shots": [
                        {
                            "description": "Щурится в трубу",
                            "size": "Крупный",
                            "duration_sec": 3,
                            "asset_codes": ["CH-01", "PR-01", "LC-01"],
                            "asset_states": {"CH-01": "дозор"},
                        },
                        {
                            "description": "Бежит по городу",
                            "size": "Общий",
                            "duration_sec": 6,
                            "asset_codes": ["CH-01"],
                            "asset_states": {"CH-01": "бег"},
                            "dialogue": [
                                {"character": "CH-01", "text": "Ma lord!", "translation": "Милорд!"}
                            ],
                            "sfx": "Шаги",
                            "notes": "ПРЕДПОЛОЖЕНИЕ: бег по улице",
                        },
                    ],
                }
            ],
            "setups": [{"motif": "Труба", "setup": ["1.1"], "payoff": ["1.2"], "takeaway": "Лжёт"}],
            "open_questions": [{"question": "Кто такой Глашатай?", "related": ["CH-01"]}],
        }
    )


def run(data, **kwargs):
    texts = data if isinstance(data, list) else [data]
    return check.check_texts(
        [t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in texts],
        PARAMS,
        **kwargs,
    )


def texts(result, level="error") -> list[str]:
    return [i.text() for i in result.issues if i.level == level]


def has(result, fragment, level="error") -> bool:
    return any(fragment in line for line in texts(result, level))


# --- эталон: файл фильма ---------------------------------------------------------------------------


def test_the_film_example_passes_the_check_without_errors():
    result = check.check_texts(
        [prompt.example_text()], Params(target_min_sec=300, target_max_sec=420)
    )
    assert result.ok, texts(result)
    assert not result.fixes
    assert texts(result, "warning") == ["Персонаж CH-06: «Глашатай» не встречается ни в одном шоте"]
    assert any(
        "Глашатай" in q.question for q in result.doc.open_questions
    )  # попал в открытые вопросы


def test_the_example_creates_exactly_what_the_excel_import_creates(db):
    excel = read_workbook(SEED_PATH)
    result = check.check_texts([prompt.example_text()])
    assert result.ok
    parsed = convert.to_bundle(result.doc)
    assert (len(parsed.scenes), len(parsed.shots), len(parsed.assets), len(parsed.setups)) == (
        12,
        69,
        54,
        13,
    )
    assert sum(s.planned_sec for s in parsed.scenes) == 360
    assert [s.code for s in parsed.shots] == [s.code for s in excel.shots]  # те же коды шотов
    assert sorted((a.code, a.type) for a in parsed.assets) == sorted(
        (a.code, a.type) for a in excel.assets
    )
    assert sum(1 for s in parsed.sounds if s.type == "dialogue") == sum(
        1 for s in excel.sounds if s.type == "dialogue"
    )

    first = projects.get_by_slug(db, "brass-spyglass")
    second = models.Project(**{**projects.DEFAULT_PROJECT, "slug": "from-json", "title": "Из JSON"})
    db.add(second)
    db.commit()
    with scope.project_session(first.id) as session:
        from_excel = importing.apply_bundle(session, first.id, excel)
        session.commit()
    with scope.project_session(second.id) as session:
        from_json = importing.apply_bundle(session, second.id, parsed)
        session.commit()
    for kind in ("scene", "shot", "asset", "asset_state", "shot_asset", "setup_payoff"):
        assert from_json.created[kind] == from_excel.created[kind], kind
    with database.session_factory()() as session:

        def total(model, project_id, *conditions):
            return session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.project_id == project_id, *conditions)
            )

        for project_id in (first.id, second.id):
            assert total(models.Scene, project_id) == 12 and total(models.Shot, project_id) == 69
            assert total(models.SoundCue, project_id, models.SoundCue.type == "dialogue") == 12


# --- разбор текста -----------------------------------------------------------------------------------


def test_json_is_taken_from_a_code_block_with_chatter_around_it():
    text = (
        "Конечно! Вот файл:\n```json\n"
        + json.dumps(good(), ensure_ascii=False)
        + "\n```\nДля продолжения напишите «дальше»"
    )
    result = check.check_texts([text], PARAMS)
    assert result.ok and has(result, "лишний текст", "fix")


def test_the_largest_code_block_wins():
    small = "```\n{}\n```"
    big = "```json\n" + json.dumps(good(), ensure_ascii=False) + "\n```"
    assert check.check_texts([small + "\n" + big], PARAMS).ok


def test_text_without_json_is_refused_with_a_clear_message():
    result = check.check_texts(["Извините, я не могу разобрать этот сценарий."], PARAMS)
    assert result.doc is None and has(result, "нет JSON")
    assert has(check.check_texts(["   \n"], PARAMS), "Файл пуст")
    assert has(check.check_texts([], PARAMS), "Нечего проверять")


def test_trailing_commas_and_smart_quotes_are_fixed_and_reported():
    text = json.dumps(good(), ensure_ascii=False).replace('"Север", "Юг"]}', '"Север", "Юг",],}')
    assert '"Юг",],}' in text  # запятая перед ] и перед }
    result = check.check_texts([text], PARAMS)
    assert result.ok and has(result, "поправили запись JSON", "fix")
    quoted = json.dumps(good(), ensure_ascii=False).replace('"schema_version"', "“schema_version”")
    assert check.check_texts([quoted], PARAMS).ok


def test_a_real_syntax_error_says_where_and_what():
    broken = json.dumps(good(), ensure_ascii=False).replace(
        '"code": "CH-01",', '"code" "CH-01",', 1
    )
    result = check.check_texts([broken], PARAMS)
    message = texts(result)[0]
    assert (
        re.search(r"строка \d+, символ \d+", message)
        and "двоеточие" in message
        and result.doc is None
    )


def test_a_list_instead_of_an_object_is_refused():
    result = check.check_texts(["[ {} ]"], PARAMS)
    assert result.doc is None and result.issues  # список в корне — не пустой ответ
    assert has(check.check_texts(['"просто строка"'], PARAMS), "один объект JSON")


# --- автопоправки -------------------------------------------------------------------------------------


def test_codes_sizes_and_shot_references_are_normalised_and_reported():
    data = good()
    data["characters"][0]["code"] = "ch1"
    data["scenes"][0]["shots"][0]["asset_codes"] = ["CH1", " pr-1", "LC-01"]
    data["scenes"][0]["shots"][0]["asset_states"] = {"ch_1": "дозор"}
    data["scenes"][0]["shots"][1]["asset_codes"] = ["CH-01"]
    data["scenes"][0]["shots"][1]["dialogue"][0]["character"] = "CH 01"
    data["scenes"][0]["shots"][0]["size"] = "  крупный "
    data["scenes"][0]["shots"][1]["size"] = "POV трубы"
    data["setups"][0]["setup"], data["setups"][0]["payoff"] = ["01.01"], ["1,2"]
    data["open_questions"][0]["related"] = ["Ch1"]
    result = run(data)
    assert result.ok, texts(result)
    fixed = " | ".join(texts(result, "fix"))
    for expected in (
        "«ch1» → «CH-01»",
        "«CH1» → «CH-01»",
        "« pr-1» → «PR-01»",
        "«  крупный » → «Крупный»",
        "«POV трубы» → «POV»",
        "«01.01» → «1.1»",
    ):
        assert expected in fixed, expected
    assert (
        result.doc.scenes[0].shots[0].size == "Крупный"
        and result.doc.scenes[0].shots[1].size == "POV"
    )
    assert result.doc.setups[0].setup == ["1.1"] and result.doc.setups[0].payoff == ["1.2"]


def test_the_original_answer_is_not_changed_by_the_fixes():
    data = good()
    data["characters"][0]["code"] = "CH1"
    raw = copy.deepcopy(data)
    fixed, _ = check.normalize(data)
    assert data == raw and fixed["characters"][0]["code"] == "CH-01"


def test_extra_fields_are_ignored_with_a_warning():
    data = good()
    data["scenes"][0]["shots"][0]["mood"] = "тревога"
    data["comments"] = "лишнее"
    result = run(data)
    assert result.ok
    warnings = " | ".join(texts(result, "warning"))
    assert "mood" in warnings and "comments" in warnings


# --- ошибки схемы по-русски, с адресом -------------------------------------------------------------------


def _drop(data, *path):
    node = data
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]


BROKEN: list[tuple[str, object, str]] = [
    (
        "нет названия проекта",
        lambda d: _drop(d, "project", "title"),
        "Проект: не заполнено обязательное поле «title»",
    ),
    (
        "чужая крупность",
        lambda d: d["scenes"][0]["shots"][0].update(size="Огромный"),
        "Сцена 1, шот 1: недопустимое значение «Огромный» в поле «size»; допустимо: Общий, Средний, Крупный, Деталь, POV, Сплит",
    ),
    (
        "чужой вид ассета",
        lambda d: d["assets"][0].update(type="Мебель"),
        "Ассет PR-01: недопустимое значение «Мебель» в поле «type»",
    ),
    (
        "нулевая длительность",
        lambda d: d["scenes"][0]["shots"][0].update(duration_sec=0),
        "Сцена 1, шот 1: поле «duration_sec» должно быть больше 0",
    ),
    (
        "число словом",
        lambda d: d["scenes"][0].update(planned_sec="много"),
        "Сцена 1: в поле «planned_sec» нужно число, а там «много»",
    ),
    (
        "накал вне 0–5",
        lambda d: d["scenes"][0].update(intensity=9),
        "Сцена 1: поле «intensity» не может быть больше 5",
    ),
    (
        "другая версия схемы",
        lambda d: d.update(schema_version="2.0"),
        "Версия схемы «2.0» не поддерживается: нужна 1.0",
    ),
    ("нет версии схемы", lambda d: _drop(d, "schema_version"), "Версия схемы не указана"),
    ("нет ни одной сцены", lambda d: d.update(scenes=[]), "нет ни одной сцены"),
    (
        "необъявленный ассет",
        lambda d: d["scenes"][0]["shots"][0]["asset_codes"].append("PR-21"),
        "Сцена 1, шот 1: неизвестный ассет PR-21",
    ),
    (
        "неизвестная локация",
        lambda d: d["scenes"][0]["location_codes"].append("LC-09"),
        "Сцена 1: неизвестная локация LC-09",
    ),
    (
        "локация, которая не локация",
        lambda d: d["scenes"][0]["location_codes"].append("PR-01"),
        "PR-01 объявлен не как локация",
    ),
    (
        "дубль кода",
        lambda d: d["assets"].append({"code": "CH-01", "type": "Реквизит", "name": "Двойник"}),
        "код CH-01 объявлен дважды",
    ),
    (
        "код не в формате",
        lambda d: d["assets"].append({"code": "ПРОП-1", "type": "Реквизит", "name": "Х"}),
        "не в формате XX-01",
    ),
    (
        "неизвестное состояние",
        lambda d: d["scenes"][0]["shots"][0]["asset_states"].update({"CH-01": "летит"}),
        "у ассета CH-01 нет состояния «летит»; есть: «бег», «дозор»",
    ),
    (
        "реплика неизвестного персонажа",
        lambda d: d["scenes"][0]["shots"][1]["dialogue"][0].update(character="CH-77"),
        "Сцена 1, шот 2, реплика 1: неизвестный персонаж CH-77",
    ),
    (
        "реплика без говорящего",
        lambda d: d["scenes"][0]["shots"][1]["dialogue"][0].update(character=None),
        "нет ни character, ни speaker",
    ),
    (
        "сетап на несуществующий шот",
        lambda d: d["setups"][0]["payoff"].append("1.7"),
        "Сетап 1 «Труба»: шот 1.7 не найден: в сцене 1 шотов 2",
    ),
    (
        "сетап на несуществующую сцену",
        lambda d: d["setups"][0]["payoff"].append("5.1"),
        "шот 5.1 не найден: сцены 5 нет",
    ),
    (
        "кривая ссылка на шот",
        lambda d: d["setups"][0]["setup"].append("третий"),
        "ссылка «третий» на шот должна быть вида 3.3",
    ),
    (
        "вопрос про неизвестный код",
        lambda d: d["open_questions"][0]["related"].append("CH-55"),
        "Открытый вопрос 1: неизвестный код CH-55",
    ),
    (
        "две сцены с одним номером",
        lambda d: d["scenes"].append(copy.deepcopy(d["scenes"][0])),
        "номер сцены 1 встречается 2 раза",
    ),
]


@pytest.mark.parametrize(("name", "mutate", "expected"), BROKEN, ids=[b[0] for b in BROKEN])
def test_a_broken_file_gets_a_clear_russian_error_with_an_address_and_no_document(
    name, mutate, expected
):
    data = good()
    mutate(data)
    result = run(data)
    assert result.doc is None and not result.ok, name
    assert has(result, expected), (name, texts(result))


def test_errors_are_not_buried_under_a_flood_of_them():
    data = good()
    data["scenes"] = [copy.deepcopy(data["scenes"][0]) for _ in range(5)]
    for number, scene in enumerate(data["scenes"], start=1):
        scene["number"] = number
        scene["shots"][0]["asset_codes"] = [f"PR-{n:02d}" for n in range(50, 70)]
    result = run(data)
    assert len(result.issues) <= check.MAX_ISSUES + 1 and has(result, "и ещё", "warning")


# --- смысл: предупреждения не мешают создать проект -------------------------------------------------------


def test_meaning_problems_are_warnings_and_do_not_block():
    data = good()
    scene = data["scenes"][0]
    scene["planned_sec"] = 20  # шоты дают 9 с
    scene["shots"][0]["duration_sec"] = 18  # длиннее лимита 15 с
    data["scenes"].append({"number": 4, "title": "Пустая", "planned_sec": 3, "shots": []})
    data["assets"].append({"code": "PR-05", "type": "Реквизит", "name": "Забытая вещь"})
    data["characters"].append({"code": "VH-01", "name": "Лодка", "kind": "Персонаж"})
    result = run(data)
    assert result.ok, texts(result)
    warnings = " | ".join(texts(result, "warning"))
    for expected in (
        "хронометраж 23 с вне цели 5–20 с",
        "пропущены номера сцен: 2, 3",
        "Сцена 1: сумма шотов 24 с, а в плане сцены 20 с",
        "Сцена 1, шот 1: шот 18 с длиннее лимита 15 с",
        "Сцена 4: в сцене нет шотов",
        "Ассет PR-05: «Забытая вещь» не встречается ни в одном шоте",
        "Сцена 1, шот 2: догадка LLM, проверьте: ПРЕДПОЛОЖЕНИЕ: бег по улице",
        "Персонаж VH-01: у типа «Персонаж» код обычно CH-NN",
    ):
        assert expected in warnings, expected


def test_a_side_not_listed_in_the_project_is_a_warning():
    data = good()
    data["scenes"][0]["side"] = "Запад"
    assert has(run(data), "сторона «Запад» не названа в project.sides", "warning")


# --- части --------------------------------------------------------------------------------------------


def part(index: int, total: int, scene_numbers: list[int]) -> dict:
    data = good()
    base = data["scenes"][0]
    data["scenes"] = []
    for number in scene_numbers:
        scene = copy.deepcopy(base)
        scene["number"] = number
        data["scenes"].append(scene)
    data["setups"], data["open_questions"] = [], []
    data["part"] = {
        "index": index,
        "total": total,
        "scenes_from": scene_numbers[0],
        "scenes_to": scene_numbers[-1],
    }
    return data


def test_parts_are_glued_in_order_and_shared_lists_are_merged_by_code():
    first, second = part(1, 2, [1, 2]), part(2, 2, [3])
    second["characters"].append({"code": "CH-02", "name": "Второй", "kind": "Персонаж"})
    result = run([second, first])  # порядок загрузки не важен
    assert result.ok, texts(result)
    assert [s.number for s in result.doc.scenes] == [1, 2, 3] and result.parts == 2
    assert [c.code for c in result.doc.characters] == ["CH-01", "CH-02"]
    assert result.doc.part is None


def test_missing_duplicate_and_lonely_parts_are_errors():
    assert has(run([part(1, 3, [1]), part(3, 3, [3])]), "не хватает части 2 из 3")
    assert has(run([part(1, 2, [1]), part(1, 2, [2])]), "часть 1 загружена дважды")
    assert has(run([part(2, 2, [2])]), "это часть 2 из 2")
    assert has(run([part(1, 2, [1]), good()]), "нет поля part")
    assert has(run([part(1, 2, [1]), part(2, 3, [2])]), "разное число частей")


def test_the_same_scene_in_two_parts_is_an_error_and_other_problems_name_the_file():
    both = run([part(1, 2, [1, 2]), part(2, 2, [2, 3])])
    assert has(both, "номер сцены 2 встречается 2 раза")
    broken = part(2, 2, [3])
    broken["scenes"][0]["shots"][0]["size"] = "Огромный"
    assert has(run([part(1, 2, [1, 2]), broken]), "Файл 2, Сцена 3, шот 1")


def test_conflicting_names_between_parts_are_a_warning_with_the_first_one_kept():
    first, second = part(1, 2, [1]), part(2, 2, [2])
    second["characters"][0]["name"] = "Другое имя"
    second["project"]["title"] = "Другое название"
    result = run([first, second])
    assert result.ok and result.doc.characters[0].name == "Дозорный"
    assert has(result, "в частях назван по-разному", "warning") and has(
        result, "название проекта в частях разное", "warning"
    )


# --- промпт ------------------------------------------------------------------------------------------------


def test_the_prompt_carries_the_project_parameters_the_schema_and_a_valid_example():
    text = prompt.render(prompt.PromptParams("Мой фильм", 120, 180, 10, "ru"))
    assert not re.search(r"\{\{\w+\}\}", text)  # все подстановки сделаны
    for expected in (
        "Рабочее название: Мой фильм",
        "120–180 сек",
        "не длиннее 10 сек",
        "Язык реплик в фильме: русский",
        "версия 1.0",
    ):
        assert expected in text, expected
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    assert len(blocks) == 2  # схема и пример
    schema = json.loads(blocks[0])
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert "Общий" in json.dumps(schema, ensure_ascii=False)
    fragment = check.check_texts([blocks[1]], PARAMS)
    assert fragment.ok, texts(fragment)  # пример в промпте сам проходит проверку
    assert len(text) < 40_000


def test_the_prompt_is_built_from_the_same_models_the_file_is_checked_with():
    names = set(S.Shot.model_fields)
    schema = json.loads(prompt.schema_text())
    assert set(schema["$defs"]["Shot"]["properties"]) == names
    assert "asset_states" in prompt.render(prompt.PromptParams("X"))


# --- преобразование в пакет данных -----------------------------------------------------------------------------


def test_the_file_becomes_a_bundle_with_codes_texts_and_links():
    result = run(good())
    assert result.ok
    bundle = convert.to_bundle(result.doc)
    (scene,) = bundle.scenes
    assert (scene.number, scene.location, scene.characters, scene.key_assets) == (
        1,
        "Стена",
        "Дозорный",
        "Труба",
    )
    assert (
        scene.lines_en == "Дозорный: Ma lord!" and scene.drum_level == 1 and scene.side == "south"
    )
    assert scene.comment == "Видит тигра · Источник: стр. 1"
    first, second = bundle.shots
    assert (
        (first.code, second.code) == ("01.01", "01.02")
        and first.size == "close"
        and second.size == "wide"
    )
    assert (
        first.stage == "storyboard"
        and first.status == "not_started"
        and first.asset_states == {"CH-01": "дозор"}
    )
    assert "Состояния: Дозорный — бег" in second.comment and second.comment.startswith(
        "ПРЕДПОЛОЖЕНИЕ"
    )
    kinds = {a.code: (a.type, a.states, a.side) for a in bundle.assets}
    assert (
        kinds["CH-01"] == ("character", ["дозор", "бег"], "south")
        and kinds["LC-01"][0] == "location"
    )
    assert "Внешность: Кривой" in next(a for a in bundle.assets if a.code == "CH-01").description
    dialogue, sfx = bundle.sounds
    assert (
        dialogue.type,
        dialogue.who,
        dialogue.text_en,
        dialogue.text_ru,
        dialogue.shot_code,
    ) == ("dialogue", "Дозорный", "Ma lord!", "Милорд!", "01.02")
    assert (sfx.type, sfx.who) == ("sfx", "Шаги")
    (setup,) = bundle.setups
    assert (setup.setup_codes, setup.payoff_codes) == (["01.01"], ["01.02"])
    (task,) = bundle.tasks
    assert (
        task.block == "preproduction"
        and "Кто такой Глашатай?" in task.title
        and "Дозорный" in task.title
    )


def test_a_side_the_site_does_not_know_is_dropped_with_a_warning():
    data = good()
    data["scenes"][0]["side"] = "Запад"
    data["project"]["sides"].append("Запад")
    bundle = convert.to_bundle(run(data).doc)
    assert bundle.scenes[0].side is None and any("Запад" in w for w in bundle.warnings)


def test_a_group_speaker_without_a_single_character_is_kept():
    data = good()
    line = data["scenes"][0]["shots"][1]["dialogue"][0]
    line.update(character=None, speaker="Оба дозорных")
    bundle = convert.to_bundle(run(data).doc)
    assert next(s for s in bundle.sounds if s.type == "dialogue").who == "Оба дозорных"
    assert bundle.scenes[0].lines_en == "Оба дозорных: Ma lord!"


def test_shot_continuity_states_reach_the_database(db):
    bundle = convert.to_bundle(run(good()).doc)
    project = projects.get_by_slug(db, "brass-spyglass")
    with scope.project_session(project.id) as session:
        importing.apply_bundle(session, project.id, bundle)
        session.commit()
        links = session.execute(
            select(models.Shot.code, models.Asset.code, models.AssetState.name)
            .select_from(models.ShotAsset)
            .join(models.Shot, models.Shot.id == models.ShotAsset.shot_id)
            .join(models.Asset, models.Asset.id == models.ShotAsset.asset_id)
            .outerjoin(models.AssetState, models.AssetState.id == models.ShotAsset.asset_state_id)
            .where(models.Asset.code == "CH-01")
            .order_by(models.Shot.code)
        ).all()
        assert links == [("01.01", "CH-01", "дозор"), ("01.02", "CH-01", "бег")]
        scene = session.scalar(select(models.Scene))
        assert scene.side == "south"


def test_importing_the_same_file_twice_creates_nothing_new(db):
    bundle = convert.to_bundle(run(good()).doc)
    project = projects.get_by_slug(db, "brass-spyglass")
    with scope.project_session(project.id) as session:
        first = importing.apply_bundle(session, project.id, bundle)
        second = importing.apply_bundle(session, project.id, bundle)
        session.commit()
    assert first.created["shot"] == 2 and not second.created


def test_reimporting_an_excel_without_sides_keeps_the_side_set_on_the_site(db):
    """В Excel стороны нет: повторный импорт не должен стирать то, что поставили на сайте."""
    project = projects.get_by_slug(db, "brass-spyglass")
    scenario = convert.to_bundle(run(good()).doc)
    excel_like = convert.to_bundle(run(good()).doc)
    excel_like.scenes[0].side = None
    for asset in excel_like.assets:
        asset.side = None
    with scope.project_session(project.id) as session:
        importing.apply_bundle(session, project.id, scenario)
        session.commit()
        importing.apply_bundle(session, project.id, excel_like)
        session.commit()
        assert session.scalar(select(models.Scene.side)) == "south"
        assert (
            session.scalar(select(models.Asset.side).where(models.Asset.code == "CH-01")) == "south"
        )
