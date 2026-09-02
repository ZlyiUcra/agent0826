"""
Гейт релізу і перевірки набору. БЕЗКОШТОВНО: до моделі не ходить.

    cd module7
    .venv/bin/python -m pytest practice -q

Платні дані сюди приходять файлом: прогін знімається окремо
(`python -m practice.base.run_eval --label baseline`), а тести читають останній
збережений. Тому запускати їх можна на кожен коміт.

Покейсові перевірки навмисно НЕ блокують: одна відповідь моделі гуляє між
прогонами, і зупиняти реліз через один кейс означає зупиняти його випадково.
Блокують два агрегати — частка взятих інструментів і частка кейсів, що пройшли
все. Провалений кейс видно як xfail, і саме за ним потім дивляться трейс.
"""

import pytest

from practice import evaluation as ev

CASES = ev.load_dataset()


@pytest.fixture(scope="session")
def sections_in_corpus() -> dict:
    """Номер розділу -> документи, у яких він трапляється.

    Читається з тих самих файлів, з яких читає сервер знань, і будується один
    раз на сесію: увесь набір розкладається на фрагменти менш ніж за півсекунди,
    а ключів і мережі для цього не треба.
    """
    from practice.common.corpus import load_passages

    where: dict[str, list] = {}
    for p in load_passages():
        if not p.section:
            continue
        docs = where.setdefault(p.section, [])
        if p.doc_id not in docs:
            docs.append(p.doc_id)
    return where


# ── Набір кейсів: перевіряється завжди, прогону не потребує ──

def test_dataset_shape():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "однакові ідентифікатори кейсів"
    assert len(CASES) >= 20, f"кейсів лише {len(CASES)}, картка просить двадцять"
    for c in CASES:
        assert c.get("source") in {"seed", "trace", "manual"}, f"{c['id']}: немає джерела"
        assert len(c.get("criterion", "")) > 30, f"{c['id']}: критерій надто короткий"
        if c["source"] == "trace":
            assert c.get("source_trace"), f"{c['id']}: кейс із трейсу без посилання на трейс"


def test_dataset_tools_are_allowed():
    """Кейс не має права чекати інструмента, якого агентові не дозволено."""
    from practice.base import layers

    for c in CASES:
        assert c["expects_tool"] in layers.ALLOWED_TOOLS, \
            f"{c['id']}: {c['expects_tool']} не в переліку дозволених"


def test_dataset_sections_exist(sections_in_corpus):
    """Кожен очікуваний розділ існує, і саме в названому документі.

    Документ обов'язковий: у корпусі 214 номерів розділів повторюються в різних
    документах. 6.2.2 є в ECMA-262, в ECMA-402 і в UTS #35, а однорівневий 12 —
    аж у п'яти документах. Кейс, який називає лише номер, звірявся б із чужим
    розділом і мовчки проходив.
    """
    for c in CASES:
        if not c["expects_section"]:
            continue
        docs = sections_in_corpus.get(c["expects_section"])
        assert docs, f"{c['id']}: розділу {c['expects_section']} у корпусі немає"
        assert c["expects_document"] in docs, (
            f"{c['id']}: розділ {c['expects_section']} є не в "
            f"{c['expects_document']}, а в {docs}")


def test_section_numbers_repeat_across_documents(sections_in_corpus):
    """Підстава для попередньої перевірки, а не окрема цікавинка.

    Якби номер розділу адресував рівно один текст, документ у кейсі був би
    зайвим полем. Він не зайвий, і ось скільки саме номерів його потребують.
    """
    repeated = {s: d for s, d in sections_in_corpus.items() if len(d) > 1}
    assert len(repeated) == 214, f"повторюваних номерів {len(repeated)}, а не 214"
    assert len(sections_in_corpus["12"]) == 5, "номер 12 мав траплятися в п'ятьох документах"


# ── Гейт над збереженим прогоном ──

@pytest.fixture(scope="session")
def run():
    try:
        return ev.latest_run()
    except SystemExit as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_case_signals(run, case_id):
    """Сигнальна перевірка кейса: показує, що саме не склалося, але не блокує."""
    row = next((r for r in run["rows"] if r["id"] == case_id), None)
    if row is None:
        pytest.skip(f"кейса {case_id} не було в прогоні «{run['label']}»")
    if not row["pass"]:
        why = []
        if not row["tool_ok"]:
            why.append(f"не взято {row['expects_tool']}")
        if not row["section_ok"]:
            why.append(f"не названо розділ {row['expects_section'] or '(жодного)'}")
        if not row["grounded"]:
            why.append(f"вигадані розділи: {', '.join(row['invented_sections'])}")
        if not row["judge"]["pass"]:
            why.append(f"суддя: {row['judge']['reason']}")
        pytest.xfail(f"{case_id}: " + "; ".join(why))


def test_tool_accuracy(run):
    """Перший блокувальний агрегат: агент перестав брати потрібні інструменти."""
    assert run["tool_accuracy"] >= ev.TOOL_ACCURACY, (
        f"інструменти {run['tool_accuracy']} < {ev.TOOL_ACCURACY} "
        f"(прогін «{run['label']}»)")


def test_release_gate(run):
    """Другий блокувальний агрегат: якість набору просіла — реліз стоїть."""
    assert run["score"] >= ev.THRESHOLD, (
        f"скор {run['score']} < {ev.THRESHOLD}: {run['passed']}/{run['cases']} "
        f"у прогоні «{run['label']}» "
        f"({run.get('corpus') or run.get('instance')}) — реліз зупинено")


def test_run_is_comparable(run):
    """Два прогони можна порівнювати лише за однакового способу пошуку.

    Якщо в одному прогоні вектори піднялися, а в іншому ні, різниця в скорі
    описує не деградацію, а різний ретривер.
    """
    assert run["search_modes"], "прогін не записав жодного способу пошуку"
    assert run["search_modes"] == ["meaning+words"], (
        f"прогін «{run['label']}» шукав як {run['search_modes']} — "
        f"з іншим прогоном його порівнювати не можна")
    # Набір документів — друга умова порівнюваності, і окрема від способу пошуку:
    # прогін на вужчому наборі може мати залиті вектори й пройти перевірку вище,
    # вимірявши при цьому інший корпус.
    assert run.get("docs", "suite") == "suite", (
        f"прогін «{run['label']}» знято на наборі {run.get('docs')}, "
        f"а записані — на suite")


# ── Самі правила перевірки: без прогону і без моделі ──

_HITS = [{"tool": "search_spec", "ok": True, "output": {"passages": [
    {"id": "20-fundamental-objects#20.1.3.6/1",
     "section": "20.1.3.6 Object.prototype.toString ( ) (частина 1 з 2)",
     "text": "..."},
    {"id": "07-abstract-operations#7.2.9", "section": "7.2.9 SameValue ( x , y )",
     "text": "..."}]}}]


def test_grounding_catches_an_invented_section():
    """Головний клас шкоди: правдоподібний номер розділу, якого агент не бачив."""
    ok, invented = ev.grounded("Це описано в розділі 20.1.3.6.", _HITS)
    assert ok and not invented
    ok, invented = ev.grounded("Це описано в розділі 22.1.3.19.", _HITS)
    assert not ok and invented == ["22.1.3.19"]


def test_grounding_allows_a_parent_section():
    """Показали 20.1.3.6 — згадка 20.1.3 законна, це та сама гілка."""
    ok, _ = ev.grounded("Загальні правила — у 20.1.3, конкретика в 20.1.3.6.", _HITS)
    assert ok


def test_grounding_ignores_numbers_that_are_not_sections():
    """Версія «15.0» і крок «4.1» — не розділи, і провалу давати не мусять."""
    ok, invented = ev.grounded("У ES2024 крок 4 розділу 20.1.3.6 робить ToObject.", _HITS)
    assert ok, invented
    ok, invented = ev.grounded("Крок 4.1 розділу 20.1.3.6; версія 15.0.", _HITS)
    assert ok, invented


def test_grounding_sees_a_section_at_the_end_of_a_sentence():
    """Найчастіша позиція номера — кінець речення, і саме там перевірка сліпла."""
    ok, invented = ev.grounded("Це описано в розділі 22.1.3.19.", _HITS)
    assert not ok and invented == ["22.1.3.19"]


def test_tool_ok_ignores_a_rejected_call():
    """Відхилений шаром виклик не рахується за взятий інструмент."""
    case = {"expects_tool": "read_section"}
    assert not ev.tool_ok(case, [{"tool": "read_section", "ok": False}])
    assert ev.tool_ok(case, [{"tool": "read_section", "ok": True, "output": {}}])


def test_section_ok_for_a_case_without_grounding():
    """Кейсові «цього немає в специфікації» немає чого називати.

    Раніше тут стояла інверсія — будь-яка згадка розділу означала провал. Точка
    відліку показала, чого вона варта: агент правильно сказав, що fetch не
    визначений в ECMA-262, і принагідно згадав, що Promise визначений у 27.2.
    Відповідь правильна, а перевірка валила її за зайву обізнаність.
    """
    empty = {"expects_section": ""}
    assert ev.section_ok(empty, "Специфікація ECMAScript цього не описує.")
    assert ev.section_ok(empty, "Цього тут немає, хоча Promise описано в 27.2.")


def test_section_ok_finds_a_top_level_number():
    """«Section 12» — теж розділ, хоч у ньому й немає крапки."""
    assert ev.section_ok({"expects_section": "12"}, "Дивіться Section 12 про лексику.")
    assert not ev.section_ok({"expects_section": "12"}, "Дивіться розділ 5.1.2.")


def test_grounding_ignores_numbers_inside_code():
    """Приклад `"3.14" == 3.14` — не посилання на розділ 3.14."""
    ok, invented = ev.grounded('Наприклад, `"3.14" == 3.14` дає true; див. 20.1.3.6.', _HITS)
    assert ok, invented


def test_score_and_gate_rules():
    """Самі правила гейта, без прогону: де саме проходить межа.

    Прогін для цього не потрібен і не мусить бути потрібен — інакше правила
    гейта можна було б перевірити лише за гроші. Ряди тут зібрані руками.
    """
    def rows(passed: int, total: int, tools_ok: int):
        return [{"pass": i < passed, "tool_ok": i < tools_ok} for i in range(total)]

    green = ev.score(rows(17, 20, 20))
    assert green["score"] == 0.85 and green["gate"] == "PASS"
    assert green["tool_accuracy"] == 1.0

    # Рівно на порозі гейт ще зелений, на кейс нижче — уже червоний.
    assert ev.score(rows(16, 20, 20))["gate"] == "PASS"
    assert ev.score(rows(15, 20, 20))["gate"] == "FAIL"

    # Друга частка блокує окремо: кейси проходять, а інструменти загублено.
    strayed = ev.score(rows(17, 20, 17))
    assert strayed["score"] >= ev.THRESHOLD
    assert strayed["tool_accuracy"] < ev.TOOL_ACCURACY
    assert strayed["gate"] == "FAIL", "друга частка мусить зупиняти реліз сама собою"


def test_layer2_remembers_ids_from_a_real_search_result():
    """Стик між сервером і шаром 2, і саме на справжній видачі, а не на макеті.

    Шар 2 пускає read_section лише на ідентифікатор, який агент справді дістав
    із попереднього пошуку, і бере ці ідентифікатори з відповіді search_spec.
    Варто серверові назвати список інакше — і шар 2 не запам'ятає нічого, після
    чого КОЖЕН read_section дістане відмову, а прогін опише агента, який жодного
    разу не дочитує розділ. Саме це одного разу й сталося, і коштувало цілої
    точки відліку. Тому перевірка кличе сервер по-справжньому: макет повторив би
    ту саму помилку в імені поля й нічого не спіймав.
    """
    from practice.base import layers, spec_server

    found = spec_server.search_spec("Object.prototype.toString tag", k=2)
    assert found["found"] == 2, found

    sess = layers.Session()
    sess.remember(found)
    known = found["passages"][0]["id"]
    assert layers.deny_before("read_section", {"id": known}, sess) is None
    assert layers.deny_before("read_section", {"id": "вигаданий#1.2.3"}, sess)


def test_judge_rejects_an_answer_that_dictates_its_own_verdict():
    """Суддя отримує відповідь як дані; схема відповіді судді строга."""
    calls = []
    verdict = ev.judge({"criterion": "Називає 7.2.9."}, "текст", calls,
                       ask_json=lambda *a, **k: {"pass": "так", "reason": "…"})
    assert verdict["pass"] is False
    assert "схем" in verdict["reason"]
