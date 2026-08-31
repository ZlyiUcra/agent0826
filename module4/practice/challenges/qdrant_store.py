"""
ЧЕЛЕНДЖ · ті самі фрагменти, але в Qdrant. Лабораторна 1 з презентації.

Суть вправи в її назві: сховище змінилось, агент — ні. Досі вектори лежали
матрицею в пам'яті процесу і файлом `.npy` на диску (common/vectors.py); тепер
вони лежать у сервері Qdrant, який працює в Docker окремим процесом. Агент,
його промпт, інструмент `search_docs` і всі точки входу лишаються недоторканими:
міняється рівно один рядок оточення — `PRACTICE_RETRIEVER=qdrant`.

ЧОГО ЦЯ ВПРАВА НЕ ДОВОДИТЬ

Вона не доводить, що базу тут треба ставити. У practice/README.md написано, що
для 283 фрагментів матриця в пам'яті достатня, а Chroma чи Qdrant не додали б
нічого, крім залежності, — і це лишається правдою. Вправа доводить інше: що шар
пошуку відв'язаний від сховища настільки, що його можна замінити, не чіпаючи
нічого вище. Саме це знадобиться, коли фрагментів стане не 283, а мільйон.

ЧОМУ БЕЗ БІБЛІОТЕКИ-КЛІЄНТА

Qdrant має офіційний пакет `qdrant-client`, і в ньому немає нічого поганого,
але він тягне за собою grpcio, protobuf і ще кілька залежностей. Тут
використовується HTTP-API самого сервера через `urllib` зі стандартної
бібліотеки: чотири запити — створити колекцію, залити точки, спитати розмір,
пошукати. У `.venv` модуля пакет стоїть з 26 серпня 2026 лише заради
курсового `knowledge_qdrant.py`, який того дня з'явився в курсі; практика його
не імпортує.

ЩО ЛЕЖИТЬ У КОЛЕКЦІЇ

Колекція зветься `spec-e5` — на ім'я моделі ембедингів. Це не прикраса: `e5` і
`bge` дають вектори різної геометрії й різної довжини, і класти їх в одну
колекцію означало б рахувати косинус між непорівнюваними числами. Перемкнули
модель через PRACTICE_EMBED_MODEL — заливаєте в колекцію `spec-bge`, стару
ніхто не чіпає.

Точка в колекції — це фрагмент: вектор плюс увесь текст і паспорт фрагмента
(ідентифікатор, розділ, заголовок, документ, адреса джерела) у полі `payload`.
Тобто після заливання Qdrant містить самодостатню копію того, що потрібно
агентові: і числа для пошуку, і текст для відповіді.

ЗАЛИВАННЯ НІЧОГО НЕ ПЕРЕРАХОВУЄ

Вектори беруться з кеша `practice/index/*.npy`, який уже порахований звичайними
прогонами. Тому заливання не піднімає модель ембедингів і триває секунди, а не
хвилини. Якщо кеша немає, він порахується один раз, як і в звичайному прогоні.

Заливання не видаляє нічого: колекція створюється, лише якщо її ще немає, а
точки записуються поверх своїх номерів. Якщо в колекції виявиться більше точок,
ніж фрагментів у документах, скрипт скаже про це вголос і лишить рішення людині.

    python -m practice.challenges.qdrant_store            # залити фрагменти
    python -m practice.challenges.qdrant_store --info     # що зараз у колекції
    python -m practice.challenges.qdrant_store --check    # звірити з матрицею .npy

Сервер піднімається так (з будь-якої теки):

    docker run -d --name agent0826-qdrant -p 6333:6333 -p 6334:6334 \\
        -v agent0826-qdrant:/qdrant/storage qdrant/qdrant

Іменований том `agent0826-qdrant` — це те, чим ця вправа відрізняється від
режиму `:memory:`, про який каже картка. Без тому дані живуть, доки живий
контейнер; з томом вони переживають і зупинку контейнера, і його видалення.
Адреса сервера береться зі змінної QDRANT_URL, типово http://localhost:6333;
дашборд — на http://localhost:6333/dashboard.
"""

import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

from practice.common.corpus import DOC_SET, Passage, load_passages
from practice.common.vectors import MODEL_KEY, MODEL_NAME, THRESHOLD, VectorIndex

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")

# В імені колекції — і набір документів, і модель ембедингів. Обидва змінюють
# вміст: набір — те, які фрагменти всередині, модель — довжину і геометрію
# векторів. Одна колекція на все означала б косинуси між непорівнюваними
# числами, тому їх чотири: spec-core-e5, spec-core-bge, spec-full-e5, spec-full-bge.
COLLECTION = f"spec-{DOC_SET}-{MODEL_KEY}"

# Налаштування підняття сервера. Практика ними не користується сама — вони
# потрібні команді --up, яка запускає контейнер тими самими іменами, що й .env.
CONTAINER = os.getenv("QDRANT_CONTAINER", "agent0826-qdrant")
VOLUME = os.getenv("QDRANT_VOLUME", "agent0826-qdrant")
IMAGE = os.getenv("QDRANT_IMAGE", "qdrant/qdrant")

BATCH = 128
TIMEOUT_SEC = 30


class QdrantUnavailable(SystemExit):
    """Сервера немає або він відповів помилкою. Успадкований від SystemExit,
    щоб прогін завершувався поясненням, а не трасуванням стека."""


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    """Один запит до HTTP-API Qdrant. Повертає розібране тіло відповіді."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{QDRANT_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        raise QdrantUnavailable(
            f"Qdrant відповів {e.code} на {method} {path}:\n  {body}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        # Сюди потрапляє все, що не є відповіддю сервера: відмова у з'єднанні,
        # обірване з'єднання (ConnectionResetError — саме так виглядає щойно
        # зупинений контейнер), вичерпаний час очікування, порожнє тіло замість
        # JSON у контейнера, який ще піднімається. Усі ці випадки означають для
        # практики одне й те саме — сервера зараз немає, працюємо з документами.
        reason = getattr(e, "reason", e)
        raise QdrantUnavailable(
            f"Немає зв'язку з Qdrant за адресою {QDRANT_URL}: {reason}\n"
            "Підніміть сервер:\n"
            "  docker run -d --name agent0826-qdrant -p 6333:6333 -p 6334:6334 \\\n"
            "      -v agent0826-qdrant:/qdrant/storage qdrant/qdrant\n"
            "Уже піднімали раніше — досить запустити наявний контейнер:\n"
            "  docker start agent0826-qdrant")


def collection_info() -> dict | None:
    """Опис колекції або None, якщо її ще немає."""
    try:
        return _request("GET", f"/collections/{COLLECTION}")["result"]
    except QdrantUnavailable as e:
        if "404" in str(e):
            return None
        raise


def ensure_collection(dim: int) -> bool:
    """Створює колекцію, якщо її немає. Наявну не чіпає. True — щойно створено.

    Розбіжність довжини вектора не виправляється мовчки: така колекція
    залишається на місці, а людина вирішує, що з нею робити.
    """
    info = collection_info()
    if info is not None:
        have = info["config"]["params"]["vectors"]["size"]
        if have != dim:
            raise QdrantUnavailable(
                f"Колекція {COLLECTION} тримає вектори довжини {have}, а модель "
                f"{MODEL_NAME} дає {dim}. Нічого не змінюю: приберіть стару "
                f"колекцію самі або залийте під іншим іменем.")
        return False
    _request("PUT", f"/collections/{COLLECTION}",
             {"vectors": {"size": dim, "distance": "Cosine"}})
    return True


def _doc_no(doc_id: str) -> int:
    """Номер документа з його імені: «07-array-exotic-objects» → 7."""
    head = doc_id[:2]
    return int(head) if head.isdigit() else 0


# Стійкий номер точки й сума її тексту — те саме, що в практиках модулів 5 і 6.
# Номер зроблено з pid фрагмента (uuid5), а не з його позиції у списку: правка
# документа в середині набору більше не збиває номери решти, і оновлюється лише
# той фрагмент, чия сума змінилася. Пошук фрагмент і так шукав за payload.pid, а
# не за номером точки, тож на видачу ця зміна не впливає.
_NAMESPACE = uuid.UUID("6d0d1f6e-2b8a-4a1e-9f3c-6ec0ffee6006")


def _stable_id(pid: str) -> str:
    """Стійкий номер точки з ідентифікатора фрагмента. Не залежить від позиції."""
    return str(uuid.uuid5(_NAMESPACE, pid))


def _digest(text: str) -> str:
    """Сума тексту фрагмента: за нею відрізняємо змінений від незмінного."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fetch_digests(ids: list, collection: str) -> dict:
    """Суми, що вже лежать у названих точках. Порожньо для тих, кого немає."""
    out: dict = {}
    for start in range(0, len(ids), BATCH):
        res = _request("POST", f"/collections/{collection}/points",
                       {"ids": ids[start:start + BATCH],
                        "with_payload": ["digest"]})["result"]
        for r in res:
            out[r["id"]] = (r.get("payload") or {}).get("digest")
    return out


def _all_ids(collection: str) -> set:
    """Номери всіх точок колекції. Лише читання (scroll), нічого не видаляє."""
    ids: set = set()
    offset = None
    while True:
        body = {"limit": 1024, "with_payload": False, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        res = _request("POST", f"/collections/{collection}/points/scroll",
                       body)["result"]
        for point in res["points"]:
            ids.add(point["id"])
        offset = res.get("next_page_offset")
        if offset is None:
            return ids


def _plan(collection: str, passages: list):
    """Розкладає фрагменти, не заливаючи нічого: todo — нові й змінені (список
    (позиція, фрагмент, сума)), unchanged — скільки вже актуальних, orphans —
    номери точок, яких немає серед поточних фрагментів, recognized — чи впізнано
    в колекції бодай один фрагмент цієї схеми номерів.

    Перерваний Ctrl+C запуск не втрачає залитого: уже записані точки мають
    правильну суму, тож наступний план бачить їх у unchanged і дозаливає лише
    todo — тобто видно, з якого місця продовжувати."""
    want = [(i, p, _stable_id(p.pid), _digest(p.text))
            for i, p in enumerate(passages)]
    want_ids = {sid for _, _, sid, _ in want}
    stored = _fetch_digests([sid for _, _, sid, _ in want], collection)
    todo, unchanged = [], 0
    for i, p, sid, digest in want:
        if stored.get(sid) == digest:
            unchanged += 1
        else:
            todo.append((i, p, digest))
    orphans = [sid for sid in _all_ids(collection) if sid not in want_ids]
    return todo, unchanged, orphans, bool(stored)


def _point(p: Passage, vector, digest: str) -> dict:
    """Фрагмент як точка Qdrant. Номер — стійкий (зі стабільного pid), поряд із
    текстом лежить сума, за якою заливання впізнає зміну."""
    return {
        "id": _stable_id(p.pid),
        "vector": [float(x) for x in vector],
        # doc_no — номер документа числом («07-array-exotic-objects» → 7).
        # Саме по ньому звужується пошук, коли індекс просять не по всьому
        # набору, а по частині документів: у Qdrant це фільтр на боці сервера,
        # а не відсіювання вже знайденого.
        "payload": {"pid": p.pid, "digest": digest, "doc_id": p.doc_id,
                    "doc_no": _doc_no(p.doc_id), "doc_title": p.doc_title,
                    "section": p.section, "heading": p.heading, "label": p.label,
                    "url": p.url, "part": p.part, "parts": p.parts,
                    "text": p.text},
    }


def _upsert(collection: str, todo: list, matrix, verbose: bool = True) -> int:
    """Заливає точки пачками. `todo` — список (позиція, фрагмент, сума) з _plan:
    рівно нові й змінені. Пачками, щоб перерваний запуск не втратив уже залите —
    кожна пачка чекає підтвердження Qdrant (wait=true), тож у разі розриву
    втрачається щонайбільше пачка в польоті, а не весь прогін; наступний запуск
    за сумами продовжить із того місця, де спинився."""
    sent = 0
    total = len(todo)
    for start in range(0, total, BATCH):
        chunk = [_point(p, matrix[i], digest)
                 for i, p, digest in todo[start:start + BATCH]]
        _request("PUT", f"/collections/{collection}/points?wait=true",
                 {"points": chunk})
        sent += len(chunk)
        if verbose:
            print(f"  залито:       {sent} з {total}")
    return sent


def _ensure(collection: str, dim: int) -> None:
    """Створює колекцію на випадок, якщо її ще немає."""
    try:
        _request("GET", f"/collections/{collection}")
    except QdrantUnavailable:
        _request("PUT", f"/collections/{collection}",
                 {"vectors": {"size": dim, "distance": "Cosine"}})


def ingest(verbose: bool = True) -> dict:
    """Заливає у Qdrant лише нові й змінені фрагменти. Вектори — з кеша .npy."""
    index = VectorIndex()
    dim = int(index.matrix.shape[1])
    if verbose:
        src = "з кеша" if index.from_cache else "порахований щойно"
        print(f"  фрагментів:   {len(index.passages)}, вектор {dim} чисел, {src}")

    created = ensure_collection(dim)
    if verbose:
        print(f"  колекція:     {COLLECTION} — "
              f"{'створена' if created else 'уже була, лишаю як є'}")

    have = collection_info()["points_count"]
    todo, unchanged, orphans, recognized = _plan(COLLECTION, index.passages)

    # Точки в колекції є, але жодну не впізнано під нашою схемою номерів: це
    # стара, позиційна схема з попередньої версії практики (або чужий корпус).
    # Заливати поверх не можна — стійкі номери лягли б поряд зі старими, і пошук
    # за pid діставав би той самий фрагмент двічі. Знести й залити наново
    # вирішує людина.
    if have and not recognized:
        print(f"\n  У колекції {have} точок під старою схемою номерів (позиційною).\n"
              f"  Долити поверх не можна — вийдуть дублі. Перехід на стійкі номери —\n"
              f"  через одноразове знесення й заливання наново (видаляєте ви самі):\n"
              f"    curl -X DELETE {QDRANT_URL}/collections/{COLLECTION}\n"
              f"    python -m practice.challenges.qdrant_store")
        return {"sent": 0, "stored": have, "dim": dim, "created": created,
                "todo": 0, "unchanged": 0, "orphans": len(orphans),
                "blocked": True}

    if verbose:
        print(f"  розклад:      нових/змінених {len(todo)}, "
              f"без змін {unchanged}, зайвих {len(orphans)}")
    sent = _upsert(COLLECTION, todo, index.matrix, verbose)

    stored = collection_info()["points_count"]
    if verbose:
        if not todo:
            print(f"  у колекції:   {stored} точок — усе вже актуальне, "
                  f"заливати нічого")
        else:
            print(f"  у колекції:   {stored} точок")
        if orphans:
            print(f"  УВАГА: {len(orphans)} точок описують текст, якого в "
                  f"документах уже\n         немає. Пошук їх не показує "
                  f"(мапиться за pid); прибрати фізично\n         можна лише "
                  f"знесенням колекції — робите це ви самі:\n"
                  f"           curl -X DELETE {QDRANT_URL}/collections/"
                  f"{COLLECTION}\n"
                  f"           python -m practice.challenges.qdrant_store")
    return {"sent": sent, "stored": stored, "dim": dim, "created": created,
            "todo": len(todo), "unchanged": unchanged, "orphans": len(orphans)}


class QdrantIndex:
    """Той самий інтерфейс, що у VectorIndex, але за числами ходить у Qdrant.

    Саме через однаковість інтерфейсу агент і не помічає підміни: `scores` і
    `retrieve` приймають і повертають те саме, а `common/tools.py` просто бере
    інший клас зі свого реєстру.
    """

    def __init__(self, passages: list[Passage] | None = None):
        self.passages = passages if passages is not None else load_passages()
        self._by_pid = {p.pid: p for p in self.passages}

        info = collection_info()
        if info is None:
            raise QdrantUnavailable(
                f"У Qdrant немає колекції {COLLECTION}. Залийте фрагменти:\n"
                "  python -m practice.challenges.qdrant_store")
        self.stored = info["points_count"]
        if self.stored < len(self.passages):
            raise QdrantUnavailable(
                f"У колекції {COLLECTION} лише {self.stored} точок на "
                f"{len(self.passages)} фрагментів. Залийте фрагменти ще раз:\n"
                "  python -m practice.challenges.qdrant_store")

        # Індекс могли попросити не по всьому набору, а по частині документів —
        # так робить практика модуля 4, де в кожного спеціаліста своя родина.
        # Тоді пошук звужується фільтром на боці сервера: інакше Qdrant віддав
        # би три найкращі точки з усієї колекції, а після відсіювання чужих у
        # руках лишилося б менше, ніж просили, а часом і нічого.
        self.doc_nos = sorted({_doc_no(p.doc_id) for p in self.passages})
        self.subset = self.stored > len(self.passages)

    def scores(self, query: str, k: int = 3) -> list[tuple[float, Passage]]:
        """Перші k за косинусом, БЕЗ відсікання за межею — як у VectorIndex."""
        from practice.common.vectors import embed

        vector = [float(x) for x in embed([query], kind="query")[0]]
        body = {"query": vector, "limit": k, "with_payload": ["pid"]}
        if self.subset:
            body["filter"] = {"must": [{"key": "doc_no",
                                        "match": {"any": self.doc_nos}}]}
        found = _request("POST", f"/collections/{COLLECTION}/points/query",
                         body)["result"]["points"]
        out = []
        for hit in found:
            passage = self._by_pid.get(hit["payload"]["pid"])
            if passage is not None:
                out.append((float(hit["score"]), passage))
        return out

    def retrieve(self, query: str, k: int = 3) -> list[Passage]:
        """Перші k з відсіканням за нижньою межею. Межа та сама, що в пам'яті:
        косинус рахує Qdrant, але число, з яким його порівнюють, спільне."""
        return [p for s, p in self.scores(query, k) if s >= THRESHOLD]


# ── згода на заливання ───────────────────────────────────────
# База не наповнюється за спиною в того, хто працює за машиною. Перед першим
# заливанням практика рахує, скільки місця займуть дані, дивиться, скільки його
# лишилось, і питає. Мовчки заливати можна лише тоді, коли згоду вже дано
# наперед змінною QDRANT_AUTO_INGEST=1.

# Скільки байтів на точку понад вектор і текст: службові поля, ідентифікатори,
# структури пошуку. Число грубе і навмисно завищене — краще попередити про
# більший обсяг, ніж про менший.
_OVERHEAD_PER_POINT = 400
_INDEX_FACTOR = 1.3


def estimate_bytes(passages: list, dim: int) -> int:
    """Скільки місця приблизно займуть ці фрагменти в базі."""
    vectors = len(passages) * dim * 4                     # float32
    payload = sum(len(p.text.encode("utf-8")) for p in passages)
    overhead = len(passages) * _OVERHEAD_PER_POINT
    return int((vectors + payload + overhead) * _INDEX_FACTOR)


def _human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(n) < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024


def storage_root() -> tuple[str, int | None]:
    """Тека, де Docker тримає дані, і скільки на ній вільно.

    Тека належить root, тож дізнатися вільне місце вдається не завжди; коли не
    вдається, міряємо кореневу файлову систему і кажемо про це чесно.
    """
    import shutil
    import subprocess

    path = "/var/lib/docker"
    try:
        got = subprocess.run(["docker", "info", "--format", "{{.DockerRootDir}}"],
                             capture_output=True, text=True, timeout=15)
        if got.returncode == 0 and got.stdout.strip():
            path = got.stdout.strip()
    except Exception:
        pass
    for candidate in (path, "/"):
        try:
            return candidate, shutil.disk_usage(candidate).free
        except OSError:
            continue
    return path, None


def consent_mode() -> str:
    """ask — питати (типово), 1 — згоду дано наперед, 0 — не заливати."""
    raw = os.getenv("QDRANT_AUTO_INGEST", "ask").strip().lower()
    if raw in ("1", "yes", "true"):
        return "1"
    if raw in ("0", "no", "false"):
        return "0"
    return "ask"


def ask_consent(passages: list, dim: int, what: str) -> tuple[bool, str]:
    """Питає дозволу залити дані в базу. Повертає рішення і його причину.

    Питає лише тоді, коли є в кого: у прогоні без термінала (з конвеєра, з
    планувальника) відповіді чекати нема від кого, тому там відповідь — «ні»
    плюс команда, якою це робиться свідомо.
    """
    need = estimate_bytes(passages, dim)
    where, free = storage_root()

    print(f"  У базі даних ще немає {what}.")
    print(f"  Залити туди {len(passages)} фрагментів — це приблизно {_human(need)}.")
    if free is None:
        print(f"  Скільки вільно на {where}, дізнатися не вдалося.")
    else:
        print(f"  Вільно на {where}: {_human(free)}.")
        if free < need * 3:
            print("  Місця обмаль: раджу відмовитися і лишитися на документах.")

    mode = consent_mode()
    if mode == "1":
        return True, "згоду дано наперед (QDRANT_AUTO_INGEST=1)"
    if mode == "0":
        return False, "заливання вимкнено (QDRANT_AUTO_INGEST=0)"

    if not sys.stdin.isatty():
        print("  Прогін без термінала — питати нема в кого, лишаюся на документах.")
        print("  Залити свідомо: python -m practice.challenges.qdrant_store")
        return False, "немає термінала, щоб спитати згоди"

    try:
        answer = input("  Залити? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, "згоди не отримано"
    if answer in ("y", "yes", "т", "так"):
        return True, "згоду отримано"
    return False, "власник відмовив"


def _dim_of(passages: list) -> int:
    """Довжина вектора моделі. Береться з кеша, якщо він є, інакше з самої моделі."""
    try:
        return int(VectorIndex(passages=passages).matrix.shape[1])
    except Exception:
        return 384


def alive() -> bool:
    """Чи відповідає сервер. Жодних винятків назовні — лише так або ні."""
    try:
        _request("GET", "/collections")
        return True
    except QdrantUnavailable:
        return False
    except Exception:
        # Доступність сервера ніколи не має валити прогін: будь-яка несподіванка
        # тут означає «сервера немає», а не «зупиняємось».
        return False


def try_open(passages: list[Passage] | None = None):
    """Індекс на Qdrant, якщо його вдається дати, і пояснення в обох випадках.

    Повертає пару (індекс або None, рядок-причина). Саме тут живе правило, за
    яким практика вибирає сховище: сервер є і потрібні фрагменти в ньому —
    працюємо з сервером; сервера немає — працюємо з документами; сервер є, а
    фрагментів у ньому ще немає — заливаємо їх туди з документів і далі
    працюємо з сервером. Останнє вимикається змінною QDRANT_AUTO_INGEST=0.
    """
    if not alive():
        return None, f"сервера немає за адресою {QDRANT_URL}"

    passages = passages if passages is not None else load_passages()
    need = len(passages)
    info = collection_info()
    if info is None or info["points_count"] < need:
        ok, why = ask_consent(passages, _dim_of(passages), f"колекції {COLLECTION}")
        if not ok:
            return None, why
        result = ingest(verbose=False)
        return (QdrantIndex(passages=passages),
                f"залито {result['sent']} фрагментів у {COLLECTION}")

    return QdrantIndex(passages=passages), f"колекція {COLLECTION}"


def up() -> int:
    """Піднімає сервер тими самими іменами, що записані в .env."""
    import subprocess

    if alive():
        print(f"  Qdrant уже відповідає на {QDRANT_URL}")
        return 0

    existing = subprocess.run(
        ["docker", "ps", "-aq", "-f", f"name=^{CONTAINER}$"],
        capture_output=True, text=True)
    if existing.returncode != 0:
        print("  Docker недоступний — підніміть його або працюйте на документах:")
        print(f"    {existing.stderr.strip()[:200]}")
        return 1

    if existing.stdout.strip():
        print(f"  контейнер {CONTAINER} уже створено, запускаю")
        cmd = ["docker", "start", CONTAINER]
    else:
        print(f"  створюю контейнер {CONTAINER} на томі {VOLUME}")
        cmd = ["docker", "run", "-d", "--name", CONTAINER,
               "-p", "6333:6333", "-p", "6334:6334",
               "-v", f"{VOLUME}:/qdrant/storage", IMAGE]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        print(f"  не вдалося: {done.stderr.strip()[:300]}")
        return 1

    for _ in range(60):
        if alive():
            print(f"  сервер піднято: {QDRANT_URL}, дашборд {QDRANT_URL}/dashboard")
            return 0
        time.sleep(0.5)
    print("  контейнер запущено, але сервер не відповів за 30 секунд")
    return 1


def down() -> int:
    """Зупиняє контейнер. Ані контейнера, ані тому не видаляє: дані лишаються
    на місці, і наступний --up підніме їх такими, якими вони були."""
    import subprocess

    done = subprocess.run(["docker", "stop", CONTAINER],
                          capture_output=True, text=True)
    if done.returncode != 0:
        print(f"  не вдалося зупинити {CONTAINER}: {done.stderr.strip()[:200]}")
        return 1
    print(f"  контейнер {CONTAINER} зупинено; дані лишилися в томі {VOLUME}")
    return 0


# ── документація практики як окрема колекція ─────────────────
# «Перенести все» означає не лише документи специфікації, а й те, що написано
# про саму практику: README, чеклісти, опис сховища. Вони лежать окремою
# колекцією, бо це інший рід тексту — не джерело відповідей про ECMAScript, а
# опис того, як влаштована робота.
NOTES_COLLECTION = f"notes-{MODEL_KEY}"

_NOTES_MAX_CHARS = 1400
_NOTES_MIN_CHARS = 120


class _MarkdownDoc:
    """Мінімальний носій полів, яких Passage чекає від документа."""

    def __init__(self, doc_id: str, title: str):
        self.doc_id = doc_id
        self.title = title
        self.url = ""


def notes_passages() -> list:
    """Фрагменти markdown-документації практики: по розділу на фрагмент.

    Межа фрагмента — заголовок рівня «##», так само як у документах
    специфікації межею є пронумерований підзаголовок. Задовгий розділ ділиться
    далі по порожніх рядках, і кожна частина зберігає свій заголовок.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    out = []
    for md in sorted(root.glob("*.md")):
        lines = md.read_text(encoding="utf-8").splitlines()
        doc = _MarkdownDoc(md.stem, lines[0].lstrip("# ").strip() if lines else md.stem)
        heading, buffer = doc.title, []

        def flush(heading, buffer):
            text = "\n".join(buffer).strip()
            if len(text) < _NOTES_MIN_CHARS:
                return
            chunks, current, size = [], [], 0
            for para in text.split("\n\n"):
                if size and size + len(para) > _NOTES_MAX_CHARS:
                    chunks.append("\n\n".join(current))
                    current, size = [], 0
                current.append(para)
                size += len(para) + 2
            if current:
                chunks.append("\n\n".join(current))
            for i, chunk in enumerate(chunks):
                out.append(Passage(doc, _slug(heading), heading, chunk,
                                   i + 1, len(chunks)))

        for line in lines:
            if line.startswith("## "):
                flush(heading, buffer)
                heading, buffer = line[3:].strip(), []
                continue
            buffer.append(line)
        flush(heading, buffer)
    return out


def _slug(heading: str) -> str:
    """Короткий ідентифікатор розділу з його заголовка."""
    keep = [c.lower() if c.isalnum() else "-" for c in heading]
    return "".join(keep).strip("-").replace("--", "-")[:40] or "head"

def ingest_notes(verbose: bool = True) -> dict:
    """Заливає документацію практики в окрему колекцію."""
    passages = notes_passages()
    if not passages:
        print("  markdown-документації поруч не знайдено")
        return {"sent": 0}
    index = VectorIndex(passages=passages)
    dim = int(index.matrix.shape[1])
    ok, why = ask_consent(passages, dim, f"колекції {NOTES_COLLECTION} "
                                         f"(документація практики)")
    if not ok:
        print(f"  пропускаю: {why}")
        return {"sent": 0}
    _ensure(NOTES_COLLECTION, dim)
    todo, unchanged, orphans, recognized = _plan(NOTES_COLLECTION, passages)
    if orphans and not recognized:
        print(f"  у {NOTES_COLLECTION} {len(orphans)} точок під старою схемою "
              f"номерів — знесіть і залийте наново:\n"
              f"    curl -X DELETE {QDRANT_URL}/collections/{NOTES_COLLECTION}\n"
              f"    python -m practice.challenges.qdrant_store --notes")
        return {"sent": 0}
    sent = _upsert(NOTES_COLLECTION, todo, index.matrix, verbose)
    if verbose:
        print(f"  залито {sent} нових/змінених фрагментів документації "
              f"у {NOTES_COLLECTION} (без змін {unchanged})")
    return {"sent": sent}


def migrate() -> int:
    """Переносить у базу все, що є: усі три набори документів і документацію.

    Кожен крок — окремий процес, бо набір документів обирається під час
    імпорту, і в одному процесі їх не поміняти. Згоду кожен крок питає сам,
    показуючи свій обсяг: так видно, за що саме платиться місцем, і будь-який
    крок можна пропустити, не скасовуючи решти.
    """
    import subprocess

    steps = [
        ("вісімнадцять розділів навколо sec-object-type", {"PRACTICE_DOCS": "core"}, []),
        ("уся специфікація", {"PRACTICE_DOCS": "full"}, []),
        ("уся специфікація з ECMA-402/404/414 і посиланнями 402", {"PRACTICE_DOCS": "suite"}, []),
        ("документація практики", {}, ["--notes"]),
    ]
    print(f"── Перенесення в базу {QDRANT_URL} ──")
    if not alive():
        print("  сервера немає. Підніміть його і повторіть:")
        print("    docker compose up -d   або   "
              "python -m practice.challenges.qdrant_store --up")
        return 1

    failed = 0
    for title, env_extra, args in steps:
        print(f"\n── {title} ──")
        env = dict(os.environ, **env_extra)
        done = subprocess.run(
            [sys.executable, "-m", "practice.challenges.qdrant_store", *args],
            env=env)
        failed += done.returncode != 0
    print("\n── Стан колекцій ──")
    for name in _collections():
        info = _request("GET", f"/collections/{name}")["result"]
        print(f"  {name:20} {info['points_count']} точок")
    return 1 if failed else 0


def _collections() -> list:
    return [c["name"] for c in _request("GET", "/collections")["result"]["collections"]]


def show_info() -> int:
    info = collection_info()
    print(f"── Qdrant {QDRANT_URL} · колекція {COLLECTION} ──")
    if info is None:
        print("  колекції немає — залийте фрагменти:")
        print("    python -m practice.challenges.qdrant_store")
        return 1
    params = info["config"]["params"]["vectors"]
    print(f"  точок:        {info['points_count']}")
    print(f"  вектор:       {params['size']} чисел, відстань {params['distance']}")
    print(f"  стан:         {info['status']}")
    print(f"  модель:       {MODEL_NAME}")
    return 0


def check_parity() -> int:
    """Звіряє видачу Qdrant із видачею матриці .npy на запитах порівняння.

    Це і є доказ того, що підміна сховища нічого не змінила: ті самі фрагменти
    в тому самому порядку, а косинуси збігаються до тисячних.
    """
    from practice.base.queries import QUERIES

    CASES = [(q["query"], q["expected_route"]) for q in QUERIES.values()]

    memory = VectorIndex()
    server = QdrantIndex(passages=memory.passages)
    print(f"── Звірка: матриця .npy проти Qdrant · {len(CASES)} запитів ──")

    mismatched = 0
    for query, _ in CASES:
        in_memory = memory.scores(query, 3)
        in_qdrant = server.scores(query, 3)
        same_order = ([p.pid for _, p in in_memory] == [p.pid for _, p in in_qdrant])
        gap = max((abs(a - b) for (a, _), (b, _) in zip(in_memory, in_qdrant)),
                  default=0.0)
        ok = same_order and gap < 1e-3
        mismatched += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  «{query[:52]}{'…' if len(query) > 52 else ''}»")
        print(f"        порядок {'той самий' if same_order else 'РІЗНИЙ'}, "
              f"найбільша розбіжність косинуса {gap:.5f}")
        for (s_mem, p), (s_srv, _) in zip(in_memory, in_qdrant):
            print(f"          {s_mem:.4f} / {s_srv:.4f}  {p.pid}")

    print()
    if mismatched:
        print(f"РОЗБІЖНОСТЕЙ: {mismatched} з {len(CASES)}")
        return 1
    print(f"Усі {len(CASES)} запитів дали однакову видачу з обох сховищ.")
    return 0


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--up" in argv:
        return up()
    if "--migrate" in argv:
        return migrate()
    if "--notes" in argv:
        print(f"── Документація практики у {QDRANT_URL} ──")
        ingest_notes()
        return 0
    if "--down" in argv:
        return down()
    if "--info" in argv:
        return show_info()
    if "--check" in argv:
        return check_parity()

    print(f"── Заливання фрагментів у Qdrant {QDRANT_URL} ──")
    ingest()
    print(f"  дашборд:      {QDRANT_URL}/dashboard")
    print("  агент на цьому сховищі:")
    print("    python -m practice.base.system \"свій запит\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
