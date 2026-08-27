"""
КОНТЕКСТ · два рівні пам'яті: розмова і те, що її переживає.

Картка вимагає розвести їх, бо плутати дорого: те, що з'ясували в цій розмові,
і те, що знаємо про читача взагалі, живуть різний час і потрібні в різних
місцях.

ПАМ'ЯТЬ РОЗМОВИ (SessionMemory)

Живе, доки живе процес, і складається з двох речей: тема, про яку йдеться
зараз (розділ, який останнім повернув пошук), і факти, які читач назвав про
себе або про те, як йому відповідати. Факти видобуває дешева модель з кожної
репліки читача окремо — не з усієї історії, тож виклик короткий і коштує
десяті частки цента; у більшості реплік вона не знаходить нічого.

Це не те саме, що історія повідомлень, хоч і виводиться з неї. Історію можна
обрізати заради економії, і тоді разом із першою реплікою зникають правила,
які там були названі. Пам'ять розмови лежить окремо від історії і на кожній
репліці додається до вікна коротким рядком, тому обрізання її не зачіпає.
Саме так стиснення перестає означати забування — це і є четвертий чекбокс.

ПАМ'ЯТЬ, ЩО ПЕРЕЖИВАЄ РОЗМОВУ (LongMemory)

Наприкінці розмови факти про читача і перелік обговорених розділів лягають у
сховище, яке переживає процес: у Qdrant, коли сервер піднято і запис у нього
не заборонено, інакше — у файл practice/out/memory.json. Наступна розмова
починається з того, що дістає звідти факти про читача (усі: їх небагато, і
вони потрібні завжди) і кілька обговорених раніше тем, найближчих за змістом
до першого питання, — тут і працює векторний пошук, а не просто перелік.
Файл, на відміну від бази, за змістом не шукає і віддає теми останні за часом;
про це друкується рядок при відкритті.

Записи лягають поверх своїх ідентифікаторів, і повторна розмова з тими самими
фактами базу не роздуває. Теми не прибираються ніколи. Факти про читача живуть,
доки бесіду не закрито: наприкінці розмови dialog питає про це, а незакриті
бесіди прибираються при наступному вході — механіка в context/cleanup.py.

    python -m practice.context.memory --info    # що зараз у пам'яті, $0
"""

import datetime
import json
import pathlib
import re
import sys
import uuid

from practice.challenges import qdrant_store as qs
from practice.common.vectors import MODEL_KEY, embed

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
FILE = OUT / "memory.json"
COLLECTION = f"memory-{MODEL_KEY}"

# Простір імен для ідентифікаторів: той самий факт завжди дає той самий id.
_NS = uuid.UUID("6f1c2a9e-3b4d-4e5f-8a6b-7c8d9e0f1a2b")

EXTRACT_PROMPT = (
    "You keep working notes for an assistant. From ONE message written by the "
    "reader, extract facts worth keeping for the rest of the conversation: what "
    "the reader is working on, rules they asked the assistant to follow, "
    "preferences about the form of answers. Ignore the question itself: do not "
    "record what it is about, that the topic changed, or what the reader is "
    "asking right now. Return JSON of the shape {\"facts\": [\"...\"]}, each "
    "fact one short English sentence, and an empty list when the message states "
    "nothing durable. Return only the JSON.")


def _parse_facts(raw: str) -> list[str]:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    facts = data.get("facts", []) if isinstance(data, dict) else []
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]


class SessionMemory:
    """Тема і факти цієї розмови. Вмирає разом із процесом.

    Тема береться не з того, що пошук повернув першим, а з того, на що
    відповідь справді послалася: пошук часто віддає сусідів потрібного розділу,
    і перший прогін записав у «обговорене» Object.prototype.toLocaleString, якого
    ніхто не обговорював. Тому впродовж репліки збираються всі побачені розділи,
    а після відповіді темою стають ті з них, чиї номери вона назвала; якщо не
    назвала жодного — перший побачений.
    """

    def __init__(self):
        self.topic: str | None = None
        self.topics: list[str] = []
        self.facts: list[str] = []
        self._seen: dict[str, str] = {}   # номер розділу → його заголовок, за репліку

    def absorb(self, text: str, ledger) -> list[str]:
        """Факти з однієї репліки читача. Повертає лише нові."""
        new = [f for f in _parse_facts(ledger.ask(EXTRACT_PROMPT, text, kind="memory",
                                                  max_tokens=200))
               if f not in self.facts]
        self.facts.extend(new)
        return new

    def note_hits(self, output: dict) -> None:
        """Запам'ятовує, які розділи бачила модель у цій репліці."""
        for p in output.get("passages") or []:
            number = p["section"].split(" ", 1)[0]
            self._seen.setdefault(number, p["section"])

    def note_answer(self, answer: str) -> list[str]:
        """Після відповіді: темою стають розділи, номери яких вона назвала."""
        cited = [label for number, label in self._seen.items()
                 if re.search(rf"(?<![\d.]){re.escape(number)}(?!\.?\d)", answer)]
        picked = cited or list(self._seen.values())[:1]
        for label in picked:
            self.topic = label
            if label not in self.topics:
                self.topics.append(label)
        self._seen = {}
        return picked

    def note(self) -> str:
        parts = []
        if self.topic:
            parts.append(f"topic under discussion: {self.topic}")
        if self.facts:
            parts.append("the reader asked: " + "; ".join(self.facts))
        return "; ".join(parts)


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def records_from(session: SessionMemory, conversation: str) -> list[dict]:
    """Що з розмови вартує пережити її: факти про читача і обговорені теми."""
    when = _stamp()
    out = []
    for fact in session.facts:
        out.append({"id": str(uuid.uuid5(_NS, "reader:" + fact.lower())),
                    "kind": "reader", "text": fact, "when": when,
                    "conversation": conversation})
    for topic in session.topics:
        out.append({"id": str(uuid.uuid5(_NS, "topic:" + topic)),
                    "kind": "topic", "text": f"Discussed {topic}", "when": when,
                    "conversation": conversation})
    return out


class FileMemory:
    where = "файл"

    def __init__(self, path: pathlib.Path = FILE):
        self.path = path
        self.records: list[dict] = []
        if path.exists():
            self.records = json.loads(path.read_text(encoding="utf-8"))

    def recall(self, question: str) -> dict:
        reader = [r["text"] for r in self.records if r["kind"] == "reader"]
        topics = [f"{r['text']} ({r['when']})" for r in self.records
                  if r["kind"] == "topic"][-3:]
        return {"reader": reader, "topics": topics}

    def remember(self, records: list[dict]) -> int:
        by_id = {r["id"]: r for r in self.records}
        by_id.update({r["id"]: r for r in records})
        self.records = list(by_id.values())
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.records, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return len(records)

    def all(self) -> list[dict]:
        return list(self.records)

    def reader_facts(self, conversations: set) -> list[str]:
        return [r["text"] for r in self.records
                if r["kind"] == "reader" and r.get("conversation") in conversations]

    def forget_reader(self, conversation: str) -> int:
        """Прибирає факти про читача, залишені цією бесідою. Теми не чіпає."""
        keep = [r for r in self.records
                if not (r["kind"] == "reader" and r.get("conversation") == conversation)]
        n = len(self.records) - len(keep)
        if n:
            self.records = keep
            self.path.write_text(json.dumps(keep, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        return n


class QdrantMemory:
    where = "Qdrant"

    def _exists(self) -> bool:
        try:
            qs._request("GET", f"/collections/{COLLECTION}")
            return True
        except qs.QdrantUnavailable as e:
            if "404" in str(e):
                return False
            raise

    def _scroll(self, kind: str, limit: int) -> list[dict]:
        body = {"filter": {"must": [{"key": "kind", "match": {"value": kind}}]},
                "limit": limit, "with_payload": True, "with_vector": False}
        found = qs._request("POST", f"/collections/{COLLECTION}/points/scroll",
                            body)["result"]["points"]
        return [p["payload"] for p in found]

    def recall(self, question: str) -> dict:
        if not self._exists():
            return {"reader": [], "topics": []}
        reader = [r["text"] for r in self._scroll("reader", 50)]
        vector = [float(x) for x in embed([question], kind="query")[0]]
        body = {"query": vector, "limit": 3, "with_payload": True,
                "filter": {"must": [{"key": "kind", "match": {"value": "topic"}}]}}
        hits = qs._request("POST", f"/collections/{COLLECTION}/points/query",
                           body)["result"]["points"]
        topics = [f"{h['payload']['text']} ({h['payload']['when']})" for h in hits]
        return {"reader": reader, "topics": topics}

    def remember(self, records: list[dict]) -> int:
        if not records:
            return 0
        vectors = embed([r["text"] for r in records], kind="passage")
        qs._ensure(COLLECTION, len(vectors[0]))
        points = [{"id": r["id"], "vector": [float(x) for x in v], "payload": r}
                  for r, v in zip(records, vectors)]
        qs._request("PUT", f"/collections/{COLLECTION}/points?wait=true",
                    {"points": points})
        return len(points)

    def all(self) -> list[dict]:
        if not self._exists():
            return []
        return self._scroll("reader", 200) + self._scroll("topic", 200)

    def reader_facts(self, conversations: set) -> list[str]:
        if not self._exists():
            return []
        return [r["text"] for r in self._scroll("reader", 200)
                if r.get("conversation") in conversations]

    def forget_reader(self, conversation: str) -> int:
        """Прибирає факти про читача, залишені цією бесідою. Теми не чіпає.

        Факт з однаковим текстом у двох бесідах — одна точка, позначена
        останньою з них; прибирається разом із нею.
        """
        if not self._exists():
            return 0
        mine = [r for r in self._scroll("reader", 200) if r.get("conversation") == conversation]
        if not mine:
            return 0
        qs._request("POST", f"/collections/{COLLECTION}/points/delete?wait=true",
                    {"points": [r["id"] for r in mine]})
        return len(mine)


def open_store():
    """Qdrant, якщо сервер піднято і запис у нього не заборонено; інакше файл.

    QDRANT_AUTO_INGEST=0 означає «у базу не писати» — і пам'ять це шанує так
    само, як заливання фрагментів. Згоди на кожен запис не питає: розмова
    лишає по собі кілька десятків рядків, тобто кілобайти, а не сотні мегабайтів
    фрагментів, заради яких існує питання про місце на диску.
    """
    if qs.consent_mode() == "0":
        return FileMemory(), "QDRANT_AUTO_INGEST=0, у базу не пишемо — файл " + str(FILE)
    if not qs.alive():
        return FileMemory(), f"сервера немає на {qs.QDRANT_URL} — файл {FILE}"
    return QdrantMemory(), f"колекція {COLLECTION} на {qs.QDRANT_URL}"


def block(recalled: dict) -> str:
    """Блок системного промпта з того, що пам'ять віддала для цієї розмови."""
    lines = []
    if recalled["reader"]:
        lines.append("What you already know about this reader from earlier conversations:")
        lines += [f"- {t}" for t in recalled["reader"]]
    if recalled["topics"]:
        lines.append("Topics from earlier conversations that may be relevant:")
        lines += [f"- {t}" for t in recalled["topics"]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    store, where = open_store()
    print(f"── Пам'ять, що переживає розмову · {where} ──")
    records = store.all()
    if not records:
        print("  порожньо")
        return 0
    for kind, title in (("reader", "про читача"), ("topic", "обговорені теми")):
        mine = [r for r in records if r["kind"] == kind]
        if mine:
            print(f"  {title}:")
            for r in mine:
                print(f"    {r['when']}  {r['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
