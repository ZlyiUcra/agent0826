"""
КОНТЕКСТ · що з історії їде в модель.

Повна історія лишається в записі прогону завжди. Стратегія вирішує лише те,
яку її частину побачить модель на цьому виклику, — і в цьому весь третій
чекбокс картки: та сама розмова, різна ціна, і дивимося, що втрачено.

    full     усе як є — точка відліку
    cut      обрізання: лише останні KEEP_TURNS реплік; початок розмови зникає
             разом із правилами, які там були названі
    prune    прибирання знайденого: у репліках старших за KEEP_FOUND тіла
             tool_result замінено коротким рядком; репліки читача й відповіді
             лишаються всі
    summary  підсумовування: коли незгорнута частина переростає FOLD_ABOVE
             токенів, старші репліки дешева модель переказує одним абзацом;
             останні KEEP_UNFOLDED реплік не згортаються ніколи

Чому prune не «обрізання»: знайдене — це те, що в довгій розмові росте швидше
за все (вимір у dialog.py), і водночас те, чого читач не казав. Прибрати його
означає викинути важке й чуже, а сказане читачем лишити повністю. Обрізання ж
викидає підряд усе старе, і читачеві доводиться повторювати сказане.

Репліка тут — повідомлення читача разом з усім, що йшло за ним до наступного
повідомлення читача: відповіді, виклики інструментів, їхні результати. Межі
реплік важливі, бо tool_use і tool_result мусять їхати в модель парою.
"""

import copy

KEEP_TURNS = 6
KEEP_FOUND = 2
FOLD_ABOVE = 5000
KEEP_UNFOLDED = 3
PRUNED = "(older search results removed to save context)"

SUMMARY_PROMPT = (
    "You write a running summary of a conversation for the assistant that will "
    "continue it. Keep, in this order: what the reader is working on; every rule "
    "or preference the reader stated about how answers should look; which "
    "methods and specification sections were discussed, with their numbers; "
    "anything still unresolved. Plain English, under 150 words, no preamble.")


def turns(messages: list) -> list[list]:
    """Ділить історію на репліки: нова починається з текстового повідомлення читача."""
    out: list[list] = []
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], str):
            out.append([m])
        elif out:
            out[-1].append(m)
    return out


def flatten(chunks: list[list]) -> list:
    return [m for chunk in chunks for m in chunk]


def transcript(chunks: list[list]) -> str:
    """Текст реплік без знайденого — те, що дістає модель-підсумовувач."""
    lines = []
    for chunk in chunks:
        for m in chunk:
            if isinstance(m["content"], str):
                lines.append(f"Reader: {m['content']}")
                continue
            for block in m["content"]:
                if block.get("type") == "text" and m["role"] == "assistant":
                    lines.append(f"Assistant: {block['text']}")
                elif block.get("type") == "tool_use":
                    lines.append(f"Assistant searched for: {block['input'].get('query', '')}")
    return "\n".join(lines)


class Full:
    name = "full"

    def shape(self, messages: list, last_total: int) -> list:
        return messages


class Cut:
    name = "cut"

    def shape(self, messages: list, last_total: int) -> list:
        return flatten(turns(messages)[-KEEP_TURNS:])


class Prune:
    name = "prune"

    def shape(self, messages: list, last_total: int) -> list:
        chunks = turns(messages)
        old, recent = chunks[:-KEEP_FOUND], chunks[-KEEP_FOUND:]
        pruned = copy.deepcopy(old)
        for chunk in pruned:
            for m in chunk:
                if m["role"] == "user" and isinstance(m["content"], list):
                    for block in m["content"]:
                        if block.get("type") == "tool_result":
                            block["content"] = PRUNED
        return flatten(pruned + recent)


class Summary:
    name = "summary"

    def __init__(self, ledger):
        self.ledger = ledger
        self.summary = ""
        self.folded = 0       # скільки реплік уже згорнуто в підсумок
        self.folds = 0        # скільки разів підсумовували

    def shape(self, messages: list, last_total: int) -> list:
        chunks = turns(messages)
        unfolded = chunks[self.folded:]
        if last_total > FOLD_ABOVE and len(unfolded) > KEEP_UNFOLDED:
            to_fold = unfolded[:-KEEP_UNFOLDED]
            self._fold(to_fold)
            self.folded += len(to_fold)
        head = []
        if self.summary:
            head = [{"role": "user", "content": "Summary of the earlier part of "
                                                f"this conversation:\n{self.summary}"},
                    {"role": "assistant", "content": [
                        {"type": "text", "text": "Understood. Continuing from there."}]}]
        return head + flatten(chunks[self.folded:])

    def _fold(self, chunks: list[list]) -> None:
        user = ""
        if self.summary:
            user += f"Summary so far:\n{self.summary}\n\nNew part of the conversation:\n"
        user += transcript(chunks)
        self.summary = self.ledger.ask(SUMMARY_PROMPT, user, kind="summary", max_tokens=300)
        self.folds += 1


def make(name: str, ledger):
    if name == "summary":
        return Summary(ledger)
    return {"full": Full, "cut": Cut, "prune": Prune}[name]()


NAMES = ("full", "cut", "prune", "summary")
