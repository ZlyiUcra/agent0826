"""
ОСНОВА · підготовка сервера: одне питання, і далі все автоматично.

Сервер уміє шукати двома способами. По словах — завжди: усе потрібне лежить
текстовими файлами поруч, ставити нічого не треба. За змістом — коли поруч
працює Qdrant: тоді запит «how to find out the type of a value» має шанс
привести до Object.prototype.toString, у якому цих слів немає.

Другий спосіб потребує Docker, бо Qdrant працює окремим процесом у контейнері.
Це єдине рішення, яке за людину ухвалити не можна, тому воно ставиться питанням
рівно один раз — тут. Відповідь лягає у файл `practice/out/mode.json`, і далі
сервер лише читає її: нічого не питає, нічого не встановлює без дозволу і
нічого не вимагає від того, хто потім користується інструментами в Claude Code.

Саме питання і його підказки написані англійською, а відповідь — одна літера:
`y` піднімає, `n` лишає пошук по словах, `q` виходить, не змінивши нічого.
Типова відповідь — `n`, і порожній рядок означає саме її; на це вказує велика
літера в `[y/N/q]`. Будь-яка інша відповідь не вгадується, а перепитується.

    python -m practice.base.setup              # спитати і зробити
    python -m practice.base.setup --vectors    # без питань: з Qdrant
    python -m practice.base.setup --no-vectors # без питань: лише пошук по словах
    python -m practice.base.setup --stop       # вимкнути і зупинити контейнер
    python -m practice.base.setup --status     # що вирішено і що зараз працює

`--no-vectors` лише записує рішення, `--stop` ще й зупиняє контейнер. Різниця
має значення: після `--no-vectors` контейнер працює далі, просто ним ніхто не
користується; після `--stop` він зупинений і ресурсів не їсть. Дані в обох
випадках лишаються — видалення тому робить людина, не ця команда.

Відмова від Qdrant нічого не ламає: сервер працюватиме по словах над найповнішим
набором документів, який є. Передумати можна будь-коли — просто запустіть цю
команду ще раз.

Рахунок векторів для повного набору триває хвилини, тому він іде пачками і друкує
поступ, а перервана робота не пропадає: наступний запуск дораховує з того місця,
де зупинився попередній. `--vectors --refill` рахує все наново, поверх наявних
точок; наявні точки при цьому не видаляються, а перезаписуються тими самими
номерами.
"""

import sys
import time

from practice.common.mode import PATH as MODE_PATH, read as read_mode, write as write_mode


# Скільки триває рахунок вектора для одного фрагмента. Заміряно на цій машині:
# 256 справжніх фрагментів пачками по 32 за 163 секунди. Число тут потрібне лише
# для попередження людині — з нього рахується очікуваний час.
SEC_PER_PASSAGE = 0.635

YES = {"y", "yes"}
NO = {"n", "no"}
QUIT = {"q", "quit"}


def _ask() -> bool | None:
    """Єдине питання цієї практики. Повертає True, False або None — «вийти».

    Ставиться воно один раз, і воно не риторичне: «y» означає, що на машині
    з'явиться контейнер, том і завантажена модель. Тому питання називає все, що
    буде зроблено, і скільки це триватиме, — згода без цього переліку згодою не
    є. «n» не є поразкою: сервер працює і без Qdrant, і про це сказано тут же,
    щоб відмова не виглядала відмовою від сервера. «q» — вихід без рішення: файл
    рішення лишається такий, який був, і жодного разу не переписується.

    Текст самого питання англійською на прохання власника, і відповідь — літера,
    а не слово: це єдине місце практики, де людина відповідає машині, і воно має
    читатися так само в будь-якому терміналі, без розкладки і без здогадів про
    кодування. Велика «N» у [y/N/q] означає типову відповідь: порожній рядок —
    це «n», тобто не встановлювати нічого.
    """
    from practice.common import embed, vectorstore
    from practice.common.corpus import DOC_SET, load_passages

    n = len(load_passages())
    have_docker = vectorstore.docker_available()

    # Скільки лишилося рахувати насправді. Попередження про сорок хвилин там, де
    # база вже залита і робота займе секунди, — не обережність, а неправда, і
    # людина після одного такого перестає читати попередження взагалі.
    done = vectorstore.count() if vectorstore.alive() else 0
    left = max(0, n - done)
    minutes = max(1, round(left * SEC_PER_PASSAGE / 60))
    if not left:
        cost = (f"Nothing to compute: all {n} are already in the database, so this\n"
                f"        only records the decision.")
    elif done:
        cost = (f"Computes the {left} vectors missing from the database (out of\n"
                f"        {n}): about {minutes} min on this machine.")
    else:
        cost = (f"Computes vectors for all {n} excerpts of the \"{DOC_SET}\" set and\n"
                f"        loads them into the database: about {minutes} min, once. An\n"
                f"        interrupted run is not lost -- the next one resumes where it\n"
                f"        stopped.")

    print(f"""
Meaning search needs Docker with Qdrant. Bring it up?

  y - this machine gets:
          * container {vectorstore.CONTAINER} from image {vectorstore.IMAGE}
            (the image is pulled if missing), ports 6333 and 6334;
          * named volume {vectorstore.VOLUME}, where the data will live;
          * model {embed.MODEL_NAME} (128 MB on disk) in ~/.cache/huggingface.
        {cost}
        Each query then costs about 70 ms.

  N - (default, also what an empty line means) nothing is installed and Docker
        is not touched. The server will search by words over the same set of
        documents: ready at once, needs no container, no model and no network.
        The price is that a query has to use the same words as the section you
        are looking for.

  q - quit without deciding. Nothing is written, nothing is started.

Nothing existing is ever deleted: not other collections in Qdrant, not the
volume, not the container. You can change your mind at any time by running this
same command with --vectors or --no-vectors.
""")
    if not have_docker:
        print("Docker does not answer on this machine right now, so \"y\" will stop\n"
              "at that and word search will be recorded instead. This is not a\n"
              "failure -- Docker is simply not installed or not running.\n")

    # Порожній рядок означає «n» — це те, що показує велика літера в [y/N/q], і
    # це безпечний бік: не встановити нічого. Мовчазним тлумаченням це не є, бо
    # мовчазним воно було б тоді, коли так само сприймалася б і друкарська
    # помилка; будь-яка інша відповідь нижче не вгадується, а перепитується.
    while True:
        answer = input("Bring up Docker and Qdrant? [y/N/q]: ").strip().lower()
        if not answer:
            return False
        if answer in YES:
            return True
        if answer in NO:
            return False
        if answer in QUIT:
            return None
        print("Unclear answer. Please enter one of the three letters above:\n"
              "y to bring it up, n to stay with word search, q to quit.")


def status() -> int:
    from practice.common import embed, nform, vectorstore
    from practice.common.corpus import DOC_SET

    mode = read_mode()
    print(f"Файл рішення : {MODE_PATH}")
    print(f"Вирішено     : {mode.get('search')} (від {mode.get('decided', '—')})")
    print(f"Набір        : {DOC_SET}")
    print(f"Модель       : {embed.MODEL_NAME}, {embed.DIM} "
          f"{nform(embed.DIM, 'вимір', 'виміри', 'вимірів')}")
    print(f"Колекція     : {vectorstore.COLLECTION}")
    if vectorstore.alive():
        from practice.common.corpus import load_passages

        info = vectorstore.collection_info()
        have = info["points_count"] if info else 0
        total = len(load_passages())
        state = ("залито повністю" if have == total else
                 "колекції ще немає" if info is None else
                 f"недолито {total - have}" if have < total else
                 f"на {have - total} більше, ніж фрагментів — колекція від "
                 f"іншого видання набору, її треба залити наново")
        print(f"Qdrant       : відповідає, точок {have} із {total} — {state}")
    else:
        print(f"Qdrant       : не відповідає ({vectorstore.QDRANT_URL})")
    return 0


def _aligned(passages, uid_of, have: int) -> bool:
    """Чи означають наявні точки ті самі фрагменти, що й тепер.

    Продовження перерваного заливання тримається на одному припущенні: номер
    точки — це порядковий номер фрагмента в наборі, і перші N точок описують
    перші N фрагментів. Припущення чесне рівно доти, доки набір лише росте з
    кінця. Варто додати документ, який за іменем стає в середину списку, — і всі
    наступні фрагменти з'їдуть на місце сусідів, а дорахунок з N-го тихо
    припише текст одного фрагмента до вектора іншого. Зовні це не видно ніяк:
    пошук працює, просто відповідає не тим.

    Тому перед дорахунком беруться три наявні точки — перша, середня й остання —
    і звіряються їхні ідентифікатори з тими, що лежать на тих самих місцях
    зараз. Три, а не всі: збіг на кінцях і в середині означає, що список не
    зсувався, а повна звірка коштувала б окремого проходу по всій базі.
    """
    from practice.common import vectorstore

    probes = sorted({0, have // 2, have - 1})
    stored = vectorstore.fetch(probes)
    for i in probes:
        payload = stored.get(i)
        if payload is None or payload.get("uid") != uid_of[passages[i]]:
            print(f"  точка {i} описує «{(payload or {}).get('uid')}», а на цьому "
                  f"місці тепер «{uid_of[passages[i]]}»")
            return False
    return True


def _fill(passages, uid_of, start: int) -> int:
    """Рахує вектори і заливає їх пачками, друкуючи поступ.

    Пачками, а не одним махом, з двох причин. Перша: рахунок трьох із половиною
    тисяч фрагментів триває хвилини, і людина за терміналом мусить бачити, що
    робота йде, а не гадати, чи процес живий. Друга: пачка, яку вже прийняв
    Qdrant, лишається в колекції назавжди, тому перерваний Ctrl+C запуск не
    зникає в нікуди — наступний починає з того місця, де зупинився попередній.

    Продовження спирається на те, що номер точки — це порядковий номер фрагмента
    в наборі, а заливання йде строго по порядку. Тому N точок у колекції означає
    рівно перші N фрагментів, і рахувати треба з N-го; чи це припущення досі
    правдиве, звіряє _aligned вище. Нічого не видаляється: до наявних точок лише
    дописуються нові.
    """
    from practice.common import embed, vectorstore

    rest = passages[start:]
    total = len(passages)
    t0 = time.perf_counter()
    batch: list[dict] = []
    sent = 0

    # embed() віддає вектори по одному, у порядку тексту, тож накопичуємо пачку
    # і відправляємо її, не чекаючи, поки порахується весь набір.
    stream = embed.model().embed([p.text for p in rest], batch_size=embed.BATCH)
    for offset, vector in enumerate(stream):
        p = rest[offset]
        batch.append({
            "id": start + offset,
            "vector": vector.tolist(),
            "payload": {"uid": uid_of[p], "pid": p.pid, "doc_id": p.doc_id,
                        "doc_title": p.doc_title, "section": p.section,
                        "label": p.label, "url": p.url, "text": p.text},
        })
        if len(batch) == vectorstore.BATCH:
            sent += vectorstore.upsert(batch)
            batch = []
            done = start + sent
            spent = time.perf_counter() - t0
            left = spent / sent * (total - done)
            print(f"  {done}/{total}, минуло {spent:.0f} с, "
                  f"лишилося приблизно {left:.0f} с", flush=True)
    if batch:
        sent += vectorstore.upsert(batch)
    print(f"  пораховано і залито за {time.perf_counter() - t0:.0f} с")
    return sent


# Скільки триває підйом самого сервера. Обидва числа зняті на цій машині на
# наборі «suite»: збірка індексу при старті — близько п'яти секунд, прогрів
# пошуку за змістом у фоновій нитці — ще близько семи після того, як сервер уже
# відповідає (у журналі це видно як проміжок між першим викликом і рядком «пошук
# за змістом готовий»).
START_SEC = 5
WARMUP_SEC_AFTER_START = 7


def _report(spent: float | None = None) -> None:
    """Звіт після рішення: що записано, у якому стані сервер і що робити далі.

    Це не прикраса. Людина щойно відповіла на єдине питання практики і має піти
    з відповіддю на своє власне — чи можна вже піднімати MCP-сервер, чи ще ні, і
    скільки він підійматиметься. Два рядки «записано, Docker не потрібен» на це
    не відповідають.

    Українською, бо діалог скінчився на відповіді: англійською тут лише саме
    питання і його підказки.
    """
    from practice.common import embed, nform, vectorstore
    from practice.common.corpus import DOC_SET, load_passages

    mode = read_mode()
    vectors = mode.get("search") == "vectors"
    passages = load_passages()
    total = len(passages)
    docs = len({p.doc_id for p in passages})

    print()
    print("Записано" + (":" if not vectors else " — пошук за змістом і по словах разом:"))
    print(f"  файл рішення : {MODE_PATH}")
    print(f"  спосіб пошуку: " + ("за змістом і по словах разом (RRF)" if vectors
                                  else "лише по словах (BM25)"))
    print(f"  набір        : «{DOC_SET}» — {total} "
          f"{nform(total, 'фрагмент', 'фрагменти', 'фрагментів')} із {docs} "
          f"{nform(docs, 'документа', 'документів', 'документів')}")
    if vectors:
        points = vectorstore.count() if vectorstore.alive() else 0
        print(f"  модель       : {embed.MODEL_NAME}, {embed.DIM} "
              f"{nform(embed.DIM, 'вимір', 'виміри', 'вимірів')}")
        print(f"  колекція     : {vectorstore.COLLECTION} — {points} "
              f"{nform(points, 'точка', 'точки', 'точок')}")
        print(f"  контейнер    : {vectorstore.CONTAINER} на {vectorstore.QDRANT_URL}")
    else:
        print(f"  Docker       : не потрібен, контейнер не піднімається")
    # Рядок про час доречний лише тоді, коли час справді витрачено. «0 с» після
    # запуску, який нічого не рахував, — зайвий рядок, а не звіт.
    if spent is not None and spent >= 1:
        print(f"  витрачено    : {spent:.0f} с на цю підготовку")

    print()
    print("MCP-сервер можна піднімати — точніше, піднімати його руками й не треба:")
    print("його запускає сам клієнт (Claude Code, Inspector), коли до нього звертається.")
    print(f"Від запуску до першої відповіді — близько {START_SEC} с: стільки збирається")
    print("індекс по словах.")
    if vectors:
        print(f"Ще близько {WARMUP_SEC_AFTER_START} с у фоні йде прогрів пошуку за "
              f"змістом — контейнер і модель.")
        print("Ці секунди нікого не тримають: сервер уже відповідає, поки що по словах,")
        print("а поле `search` у кожній відповіді каже, який спосіб відпрацював.")
    print()
    print("Далі:")
    print("  .venv/bin/python -m practice.base.smoke     перевірки, ~15 с")
    print("  .venv/bin/python -m practice.base.check     діалог по протоколу, ~10 с")
    if vectors:
        print("  .venv/bin/python -m practice.base.quality   що дає пошук за змістом, ~30 с")
    print("  .venv/bin/python -m practice.base.setup --status   стан у будь-який момент")
    print()
    print("Передумати: та сама команда з "
          + ("--no-vectors." if vectors else "--vectors."))


def enable_vectors(refill: bool = False) -> int:
    """Піднімає Qdrant, заливає фрагменти і записує рішення."""
    from practice.common import embed, nform, vectorstore
    from practice.common.corpus import DOC_SET, load_passages
    from practice.common.idmap import assign_ids

    started = time.perf_counter()

    if not vectorstore.docker_available():
        print("Docker на цій машині не відповідає. Пошук за змістом без нього не\n"
              "працює, тому лишаю пошук по словах — сервер від цього не постраждає.")
        write_mode({"search": "words", "why": "docker недоступний"})
        _report()
        return 1

    print(f"Піднімаю Qdrant ({vectorstore.CONTAINER})...")
    if not vectorstore.ensure_running():
        print("Контейнер не піднявся. Лишаю пошук по словах.")
        write_mode({"search": "words", "why": "контейнер не піднявся"})
        _report()
        return 1
    print(f"  Qdrant відповідає: {vectorstore.QDRANT_URL}")

    passages = load_passages()
    _, uid_of = assign_ids(passages)
    print(f"  фрагментів у наборі «{DOC_SET}»: {len(passages)}")

    created = vectorstore.ensure_collection(embed.DIM)
    print(f"  колекція {vectorstore.COLLECTION}: "
          f"{'створена' if created else 'уже була'}")

    have = 0 if refill else vectorstore.count()
    if have > len(passages):
        print(f"\nУ колекції {have} точок, а фрагментів у наборі {len(passages)}.\n"
              "Це не «залито з запасом», а інше видання набору: документи відтоді\n"
              "змінилися, фрагментів стало менше, і зайві точки описують текст,\n"
              "якого в наборі вже немає, — але пошук їх і далі знаходить.\n"
              "Дорахунок не рятує: міняти треба не хвіст, а всі номери після того\n"
              "місця, де набір скоротився. Колекцію треба прибрати і залити наново;\n"
              "видаляєте її ви самі, у практиці такої команди немає навмисно:\n"
              f"  curl -X DELETE {vectorstore.QDRANT_URL}/collections/"
              f"{vectorstore.COLLECTION}\n"
              "  python -m practice.base.setup --vectors")
        return 1
    if have and have < len(passages) and not _aligned(passages, uid_of, have):
        print("\nНаявні точки описують не ті фрагменти, що лежать на їхніх місцях\n"
              "тепер: набір документів змінився не з кінця, а всередині. Дорахунок\n"
              "у такому стані приписав би текст одного фрагмента до вектора іншого,\n"
              "тому я його не роблю і нічого не чіпаю.\n"
              "Лікується перерахунком усього набору:\n"
              "  python -m practice.base.setup --vectors --refill")
        return 1

    if have >= len(passages):
        print(f"  у колекції вже {have} "
              f"{nform(have, 'точка', 'точки', 'точок')} — заливати нічого")
    else:
        if have:
            print(f"  у колекції {have} {nform(have, 'точка', 'точки', 'точок')} "
                  f"із {len(passages)} — рахую решту")
        print(f"  рахую вектори моделлю {embed.MODEL_NAME} "
              f"(перший запуск ще й довантажує її)...")
        sent = _fill(passages, uid_of, have)
        print(f"  залито точок: {sent}, у колекції тепер {vectorstore.count()}")

    write_mode({"search": "vectors", "docs": DOC_SET, "model": embed.MODEL_KEY,
                "collection": vectorstore.COLLECTION, "points": vectorstore.count()})
    _report(spent=time.perf_counter() - started)
    return 0


def disable_vectors() -> int:
    """Відповідь «n» — і те саме, що робить --no-vectors."""
    write_mode({"search": "words", "why": "вибір власника"})
    _report()
    return 0


def stop_vectors() -> int:
    """--stop: вимкнути пошук за змістом і зупинити контейнер.

    Порядок тут не випадковий. Зупинити контейнер, не змінивши рішення, —
    марна праця: сервер прочитає з файла «vectors» і при наступному ж запуску
    підніме його назад, бо саме так він і задуманий. Тому спершу записується
    пошук по словах, і аж потім зупиняється контейнер.

    Нічого не видаляється: ані колекція, ані том, ані сам контейнер. Дані
    лишаються на місці, і `--vectors` повертає все за секунди, не перераховуючи
    жодного вектора. Видалення тому — робота людини, і команда для неї названа
    в README.
    """
    from practice.common import vectorstore

    write_mode({"search": "words", "why": "вимкнено командою --stop"})
    print("Записано пошук по словах — тепер сервер не підніматиме контейнер сам.")

    if not vectorstore.alive():
        print(f"Контейнер {vectorstore.CONTAINER} і так не відповідає — зупиняти нічого.")
    elif vectorstore.stop():
        print(f"Контейнер {vectorstore.CONTAINER} зупинено. Дані лишилися в томі\n"
              f"{vectorstore.VOLUME}: нічого не видалено, і `--vectors` поверне все\n"
              f"за секунди, не перераховуючи векторів.")
    else:
        print(f"Не вдалося зупинити {vectorstore.CONTAINER}. Це не заважає: рішення\n"
              f"вже записане, сервер шукатиме по словах і до бази не звертатиметься.\n"
              f"Зупинити руками: docker stop {vectorstore.CONTAINER}")
    _report()
    return 0


def main(argv: list[str]) -> int:
    if "--status" in argv:
        return status()
    if "--vectors" in argv:
        return enable_vectors(refill="--refill" in argv)
    if "--no-vectors" in argv:
        return disable_vectors()
    if "--stop" in argv:
        return stop_vectors()

    answer = _ask()
    if answer is None:
        # Вихід без рішення. Файл рішення не переписується навіть тим самим
        # значенням: людина натиснула «вийти», а не «лиши як є», і мовчазний
        # запис з новою датою виглядав би так, наче вона щось підтвердила.
        print("Nothing changed. The decision file is left exactly as it was:\n"
              f"  {MODE_PATH}")
        return 0
    return enable_vectors() if answer else disable_vectors()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
