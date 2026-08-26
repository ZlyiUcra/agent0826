"""
КОНТЕКСТ · сценарії розмови, зафіксовані до вимірів. $0 сам по собі.

Картка просить розмову на 15–20 реплік і перевірку «чи не почав агент від
стиснення забувати важливе». Перевірка можлива лише тоді, коли відомо, що саме
важливе: тому сценарій складено заздалегідь, а факти, які агент мусить донести
до кінця, закладено в першу репліку навмисно.

ДОВГИЙ СЦЕНАРІЙ, 18 реплік

Читач пише посібник про String.prototype.replace і в першій репліці ставить два
правила на всю розмову: не більше трьох речень у відповіді й завжди називати
номер розділу. Далі розмова відходить від теми — Proxy, обгортка Boolean,
зв'язані функції, звичайні й екзотичні об'єкти — і двічі повертається до неї,
не називаючи метод («the method we started with»). Остання репліка прямо
питає, з якого методу почали і які були два правила.

Стиснення, що відрізало початок, на цій репліці провалюється: фактів у вікні
вже немає. Тому вона і є перевіркою — разом із тим, чи трималися двох правил
усі попередні відповіді.

КОРОТКІ СЦЕНАРІЇ

    short   дві репліки; друга не називає теми — «And what does it receive as
            its arguments?». Доказ пам'яті розмови — рядок пошуку: запит до
            інструмента містить назву методу, якої в репліці немає.
    recall  одна репліка без жодних правил. Потрібен після довгої розмови в
            ОКРЕМОМУ процесі: якщо відповідь вкладається в три речення і
            називає розділ, правила прийшли з пам'яті, що пережила розмову.

Усі репліки в межах вісімнадцяти розділів набору core, щоб сценарій однаково
працював на обох наборах документів.
"""

import re

LONG = {
    "name": "long",
    "turns": [
        "I am writing a beginners' tutorial about String.prototype.replace. Two "
        "rules for this whole conversation: keep every answer to three sentences "
        "at most, and always name the section number you cite. To start: when "
        "the first argument is a plain string rather than a RegExp, how does "
        "replace find what to replace?",
        "What can the second argument be?",
        "When it is a function, what arguments does that function receive?",
        "What do $& and $1 stand for inside a replacement string?",
        "How does replaceAll differ from replace?",
        "A different topic for a while: what does the get trap of a Proxy "
        "receive when a property is read through the proxy?",
        "Which invariant must the get trap respect?",
        "Can a proxy claim that the target has a property it does not actually have?",
        "Back to strings: does replace modify the original string or return a new one?",
        "And if the pattern does not occur in the string at all?",
        "What does new Boolean(false) create, and what does the specification "
        "say its [[BooleanData]] holds?",
        "What does Boolean.prototype.valueOf return for such a wrapper object?",
        "How does a bound function remember the object it was bound to?",
        "Can a bound function be called with new?",
        "What makes an object exotic rather than ordinary?",
        "Which internal method does reading a property go through on an ordinary object?",
        "One more about the method we started with: does it replace every "
        "occurrence or only the first one?",
        "Before I close: which method did we start this conversation with, and "
        "what two rules did I ask you to follow?",
    ],
    # Що закладено в першу репліку і що має дожити до останньої.
    "planted": {"method": "replace", "rules": ("three sentences", "section number")},
}

SHORT = {
    "name": "short",
    "turns": [
        "What does String.prototype.replace do with its second argument when "
        "it is a function?",
        "And what does it receive as its arguments?",
    ],
    "topic_word": "replace",
}

RECALL = {
    "name": "recall",
    "turns": [
        "What does the get trap of a Proxy receive when a property is read "
        "through the proxy?",
    ],
}

SCRIPTS = {"long": LONG, "short": SHORT, "recall": RECALL}

# Кінець речення: крапка, знак оклику чи питання, після яких — пробіл і велика
# літера або кінець тексту. Крапки всередині номера розділу (22.1.3.19) під це
# не підпадають. Міра груба, тому в записі вона названа кількістю речень «за
# розділовими знаками», а не істиною в останній інстанції.
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-ZА-ЯІЇЄҐ\[«\"(]|\s*$)")
_SECTION = re.compile(r"\b\d{1,2}\.\d{1,2}(?:\.\d{1,3})*\b")
_THREE = re.compile(r"\bthree\b|\b3 sentences?\b|\bthree-sentence\b", re.I)


def sentences(text: str) -> int:
    text = text.strip()
    if not text:
        return 0
    return max(1, len(_SENTENCE_END.findall(text)))


def cites_section(text: str) -> bool:
    return bool(_SECTION.search(text))


# Так dialog.py позначає репліку, на якій агент вичерпав ліміт кроків і відповіді
# не дав. Перевірки таку репліку не рахують ні як вкладену у три речення, ні як
# таку, що назвала розділ, — вона рахується окремо.
NO_ANSWER = "(turn limit reached before an answer)"


def check(script: dict, answers: list[str], searches: list[list[str]]) -> dict:
    """Що з важливого дожило до кінця. Усе детерміноване, без моделі."""
    answered = [a for a in answers if a != NO_ANSWER]
    out = {"turns": len(answers), "answered": len(answered),
           "unanswered": len(answers) - len(answered),
           "within_three": sum(sentences(a) <= 3 for a in answered),
           "cited": sum(cites_section(a) for a in answered)}
    if "planted" in script and answers:
        last = answers[-1].lower()
        out["recalled_method"] = script["planted"]["method"] in last
        out["recalled_rules"] = bool(_THREE.search(last)) and "section" in last
    if "topic_word" in script and len(answers) > 1:
        # Тему з розмови видно або в запиті пошуку другої репліки, або в самій
        # відповіді. Перший прогін показав, що пошуку може й не бути зовсім:
        # фрагменти першої репліки вже лежать в історії, і агент відповідає з них.
        word = script["topic_word"]
        via = []
        if any(word in q.lower() for q in searches[1]):
            via.append("у запиті пошуку")
        if word in answers[1].lower():
            via.append("у відповіді")
        out["topic_carried"] = bool(via)
        out["topic_via"] = ", ".join(via)
    return out


def verdict(script: dict, checks: dict) -> list[str]:
    """Рядки для виводу — по одному на перевірку, з відповіддю «так» чи «ні»."""
    yes = lambda b: "так" if b else "НІ"
    lines = [f"у три речення вклалося: {checks['within_three']} з {checks['answered']}",
             f"розділ названо: {checks['cited']} з {checks['answered']}"]
    if checks.get("unanswered"):
        lines.append(f"без відповіді (вичерпано ліміт кроків): {checks['unanswered']} з {checks['turns']}")
    if "recalled_method" in checks:
        lines.insert(0, f"метод, з якого почали, названо: {yes(checks['recalled_method'])}")
        lines.insert(1, f"два правила з першої репліки названо: {yes(checks['recalled_rules'])}")
    if "topic_carried" in checks:
        how = f" ({checks['topic_via']})" if checks["topic_via"] else ""
        lines.insert(0, f"тему другого питання взято з розмови: {yes(checks['topic_carried'])}{how}")
    return lines
