"""
Гейт релізу і перевірки набору. БЕЗКОШТОВНО: до моделі не ходить.

    cd module7
    <venv примірника>/bin/python -m pytest practice -q

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
    from server import layers
    for c in CASES:
        assert c["expects_tool"] in layers.ALLOWED_TOOLS, \
            f"{c['id']}: {c['expects_tool']} не в переліку дозволених"


def test_dataset_sections_exist():
    """Кожен очікуваний розділ існує, і саме в названому документі.

    Документ обов'язковий: у наборі 216 номерів розділів повторюються в різних
    документах — 6.2.2 це і «The List and Record Specification Types» з ECMA-262,
    і «CanonicalizeUnicodeLocaleId» з ECMA-402.
    """
    from server import spec_mcp
    for c in CASES:
        if not c["expects_section"]:
            continue
        found = [p for p in spec_mcp._INDEX.passages
                 if p.label.startswith(c["expects_section"] + " ")
                 and getattr(p, "doc_id", "") == c["expects_document"]]
        assert found, (f"{c['id']}: розділу {c['expects_section']} немає в документі "
                       f"{c['expects_document']}")


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
        f"у прогоні «{run['label']}» ({run['instance']}) — реліз зупинено")


def test_run_is_comparable(run):
    """Два прогони можна порівнювати лише за однакового способу пошуку.

    Якщо в одному прогоні вектори піднялися, а в іншому ні, різниця в скорі
    описує не деградацію, а різний ретривер.
    """
    assert run["search_modes"], "прогін не записав жодного способу пошуку"
    assert run["search_modes"] == ["meaning+words"], (
        f"прогін «{run['label']}» шукав як {run['search_modes']} — "
        f"з іншим прогоном його порівнювати не можна")


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


def test_section_ok_inverts_for_a_case_without_grounding():
    """Кейс «цього немає в специфікації»: назвати розділ — це провал."""
    empty = {"expects_section": ""}
    assert ev.section_ok(empty, "Специфікація ECMAScript цього не описує.")
    assert not ev.section_ok(empty, "Дивіться розділ 27.5.4.1.")


def test_judge_rejects_an_answer_that_dictates_its_own_verdict():
    """Суддя отримує відповідь як дані; схема відповіді судді строга."""
    calls = []
    verdict = ev.judge({"criterion": "Називає 7.2.9."}, "текст", calls,
                       ask_json=lambda *a, **k: {"pass": "так", "reason": "…"})
    assert verdict["pass"] is False
    assert "схем" in verdict["reason"]
