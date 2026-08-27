"""
ОСНОВА · перевірка посилань і критик чернетки.

Тут два механізми різної ціни, і межа між ними проведена свідомо.

ПЕРЕВІРКА ПОСИЛАНЬ — детермінована і безкоштовна, застосовується до відповіді
БУДЬ-ЯКОГО маршруту. Вона відповідає на одне питання: чи кожен ідентифікатор
фрагмента, процитований у відповіді, справді повертався інструментами цього ж
прогону. Ідентифікатор, якого в trace немає, — це вигадане джерело: відповідь
виглядає підкріпленою, а перевірити її нічим. Що перевірка НЕ вміє: звірити
саме твердження з текстом фрагмента. Правильний ідентифікатор поруч із чужим
твердженням крізь неї пройде — це відома межа, вона записана в README.

КРИТИК — курсовий патерн «петля з критиком» (critic_memory.py), застосовується
лише до маршруту WRAPPERS. Дешева модель читає чернетку і каже, чи кожне
суттєве твердження спирається на процитований фрагмент; якщо ні, або якщо
детермінована перевірка знайшла вигадане джерело, дорога модель ОДИН раз
переробляє чернетку, і перевірка посилань проганяється знову. Другого кола
немає: критик, який ганяє модель по колу, коштує дорожче за власну користь.

Чому критик саме у WRAPPERS: у цій родині найбільший обсяг тексту і найдовші
перелічувальні розділи, тобто найлегше процитувати те, чого пошук не повертав.
"""

import re

# Ідентифікатор фрагмента у квадратних дужках: [18-string-objects#22.1.3.19],
# з можливим хвостом частини [.../2] і службовим якорем [...#head].
# Окремо — посилання на живий сайт: [live:sec-array-exotic-objects].
_CITE = re.compile(r"\[(\d{2}-[a-z-]+#[\w.\-/]+)\]")
_LIVE_CITE = re.compile(r"\[live:([\w-]+)\]")


def cited_pids(text: str) -> set:
    return set(_CITE.findall(text))


def cited_anchors(text: str) -> set:
    return set(_LIVE_CITE.findall(text))


def trace_pids(trace: list) -> set:
    """Усі ідентифікатори, які інструменти справді повертали в цьому прогоні.

    Три джерела: списки фрагментів у видачі пошуку; підсумки субагента, де
    ідентифікатори стоять у тексті; живі сторінки, де ідентифікатором служить
    якір адреси з префіксом live:.
    """
    known = set()
    for step in trace:
        out = step.get("output", {})
        for p in out.get("passages", []):
            known.add(p["id"])
        if "summary" in out:
            known |= cited_pids(out["summary"])
        if out.get("anchor"):
            known.add(f"live:{out['anchor']}")
    return known


def check_citations(answer: str, trace: list) -> dict:
    """Детермінована звірка посилань відповіді з trace. Нуль звернень до моделей.

    fabricated — процитовані ідентифікатори, яких інструменти не повертали.
    uncited    — інструменти щось знайшли, а відповідь не цитує нічого; для
                 відмови це нормально (відмові нема на що посилатися), тому
                 ознака записується, але сама по собі маршрут не завершує.
    """
    cited = cited_pids(answer) | {f"live:{a}" for a in cited_anchors(answer)}
    known = trace_pids(trace)
    # Підрозділ, що повернувся частинами (…#27.5.4.1.2/1 і /2), процитований
    # без суфікса частини, — не вигадка: його текст агент бачив. Частина, якої
    # не повертали (/3), вигадкою лишається.
    sections = {k.split("/", 1)[0] for k in known if "/" in k}
    found_anything = any(
        step.get("output", {}).get("found") or
        step.get("output", {}).get("found_anything")
        for step in trace)
    return {"cited": sorted(cited),
            "fabricated": sorted(c for c in cited - known if c not in sections),
            "uncited": bool(found_anything and not cited),
            "found_anything": found_anything}


CRITIC_PROMPT = (
    "Ти — критик відповідей довідника специфікації ECMAScript. Перед тобою "
    "чернетка відповіді. Перевір одне: чи кожне суттєве твердження про "
    "специфікацію спирається на процитований у квадратних дужках ідентифікатор "
    "фрагмента. Відмова відповідати цитат не потребує. "
    'Поверни JSON: {"ok": bool, "remarks": "що виправити, коротко"}. '
    "ok=false лише якщо є твердження без посилання або посилання виглядає "
    "приліпленим до твердження, якого фрагмент не містить."
)


def run_critic(result: dict, system: str, query: str) -> dict:
    """Петля з критиком для WRAPPERS: перевірка → щонайбільше одне доопрацювання.

    Мутує result: додає ключі citations, critic і, якщо було доопрацювання, draft.
    Підсумкова ознака result["critic"]["ok"] детермінована: після доопрацювання
    вирішує повторна звірка посилань, а не думка моделі.
    """
    from core.agent import ask, ask_json

    checks = check_citations(result["answer"], result["trace"])
    verdict = ask_json(
        CRITIC_PROMPT,
        f"Питання: {query}\n\nЧернетка:\n{result['answer']}",
        fallback={"ok": True, "remarks": "не розпарсено"},
        fast=True,
    )

    needs_rework = bool(checks["fabricated"]) or checks["uncited"] \
        or not verdict.get("ok")
    if not needs_rework:
        result["citations"] = checks
        result["critic"] = {"verdict": verdict, "revised": False, "ok": True}
        return result

    remarks = []
    if checks["fabricated"]:
        remarks.append("цитовано ідентифікатори, яких пошук не повертав: "
                       + ", ".join(checks["fabricated"]))
    if checks["uncited"]:
        remarks.append("пошук щось знайшов, а відповідь не цитує жодного фрагмента")
    if not verdict.get("ok"):
        remarks.append(str(verdict.get("remarks", "")))

    # Переробіток бачить видачу пошуку: без неї модель не може додати
    # посилання, якого не було в чернетці, — лише викинути твердження.
    digest = "\n\n".join(
        f"[{p['id']}] {p['section']}\n{p['text']}"
        for step in result["trace"]
        for p in step.get("output", {}).get("passages", []))
    result["draft"] = result["answer"]
    result["answer"] = ask(
        system + "\nREWORK: fix the draft according to the critic's remarks. "
                 "Cite only ids from the excerpts below; if nothing below "
                 "supports a claim, drop the claim.",
        f"Question: {query}\n\nExcerpts returned by search:\n{digest}\n\n"
        f"Draft:\n{result['draft']}\nRemarks: {'; '.join(remarks)}",
        max_tokens=800, fast=False,
    )

    checks_after = check_citations(result["answer"], result["trace"])
    ok = not checks_after["fabricated"] and not checks_after["uncited"]
    result["citations"] = checks_after
    result["critic"] = {"verdict": verdict, "revised": True, "ok": ok,
                        "remarks": remarks}
    return result
