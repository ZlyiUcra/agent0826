"""
ПРАКТИКА М7 · підготовка пошуку за змістом (Qdrant) з точковим оновленням.

Сервер знань шукає по словах завжди, а за змістом — лише коли власник погодився
на це тут і залив колекцію. Рішення записується у practice/out/mode.json; сервер
його лише читає й нікого вирішувати не змушує. Без бази нічого не ламається:
пошук лишається по словах.

    .venv/bin/python -m practice.base.setup --status            # $0: що вирішено, що в базі, що змінилося
    .venv/bin/python -m practice.base.setup --vectors           # підняти Qdrant і долити лише нове й змінене
    .venv/bin/python -m practice.base.setup --vectors --refill  # перерахувати вектори всіх фрагментів
    .venv/bin/python -m practice.base.setup --verify            # звірити вибірку векторів на підміну
    .venv/bin/python -m practice.base.setup --words             # повернутися на пошук по словах

ЧОМУ ТОЧКОВЕ ОНОВЛЕННЯ

Номер точки в Qdrant — не позиція фрагмента у списку, а стійкий номер, зроблений
з його ідентифікатора (uuid5 від uid). Тому точка лишається на своєму місці, хоч
би що сталося із сусідами: коли документ у середині набору правлять, вставляють
чи викидають фрагмент, номери решти не з'їжджають. Поряд із текстом у payload
кладеться його сума (sha256). За цими двома речами — стійким номером і сумою —
заливання бачить, що з кожним фрагментом сталося:

    номер відсутній у базі      -> фрагмент новий, рахуємо вектор;
    номер є, але сума інша       -> текст змінився, перераховуємо вектор;
    номер є і сума та сама        -> не чіпаємо, вектор уже правильний.

Отже повторний --vectors рахує лише те, що додалося чи змінилося, а не весь
набір. Модель довантажується тільки тоді, коли є що рахувати. --refill змушує
перерахувати всі: це потрібно раз при переході на цю схему номерів і будь-коли,
коли треба перекласти вектори наново.

ЩО ЦЕЙ МОДУЛЬ НЕ ВИДАЛЯЄ

Точку фрагмента, якого в документах уже немає (його номер зник із набору), тут не
видаляють. Сервер такі точки й так не показує: у відповіді пошуку він бере з
payload uid і лишає лише ті, чий uid входить у поточний набір, — зайва точка
просто відсіюється й чужого тексту не віддає. Прибрати її фізично можна тільки
знесенням колекції, а це робить людина; команда названа в попередженні нижче.

Заливання довге: вектор кожного фрагмента рахує модель, і на наборі suite перший
повний прогін — десятки хвилин. Перерваний прогін не пропадає: точки, які вже
прийняв Qdrant, лишаються, і наступний запуск бачить їх як «сума та сама» й
доливає лише решту.
"""

import hashlib
import math
import random
import sys
import time
import uuid

from practice.common import embed, nform, vectorstore
from practice.common.corpus import DOC_SET, load_passages
from practice.common.idmap import assign_ids
from practice.common.mode import PATH as MODE_PATH, read as read_mode, write as write_mode

# Простір імен для стійких номерів точок. Стала назавжди: номер фрагмента мусить
# виходити той самий на будь-якій машині й у будь-якому прогоні, інакше «те саме»
# не впізнається. Саме значення довільне — важливо лише, щоб воно не мінялося.
_NAMESPACE = uuid.UUID("6d0d1f6e-2b8a-4a1e-9f3c-6ec0ffee6006")

# Скільки триває рахунок вектора одного фрагмента на цій машині — лише для оцінки
# часу в попередженні (виміряно в модулі 5: 0.635 с/фрагмент).
SEC_PER_PASSAGE = 0.635

# Перевірка --verify: скільки випадкових фрагментів перерахувати й наскільки
# близьким має бути збережений вектор до перерахованого (косинус). Похибка ONNX
# мала, тож усе нижче межі — це вже не шум, а інший вектор. Косинус, а не
# порізнична різниця, бо Qdrant для Cosine зберігає вектор унормованим, і
# порівнювати треба напрям, а не довжину.
VERIFY_SAMPLE = 64
VERIFY_MIN_COS = 0.999


def _stable_id(uid: str) -> str:
    """Стійкий номер точки з ідентифікатора фрагмента. Не залежить ні від позиції
    у списку, ні від машини — лише від самого uid."""
    return str(uuid.uuid5(_NAMESPACE, uid))


def _digest(text: str) -> str:
    """Сума тексту фрагмента. За нею відрізняємо змінений фрагмент від того, що
    лежить у базі без змін."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan(passages, uid_of):
    """Розкладає фрагменти на три купи, не рахуючи жодного вектора: нові (номера
    немає в базі), змінені (номер є, сума інша) і незмінні (номер є, сума та
    сама). Повертає (new, changed, unchanged) — списки четвірок
    (фрагмент, uid, стійкий номер, сума) — і множину стійких номерів усіх
    поточних фрагментів."""
    want = [(p, uid_of[p], _stable_id(uid_of[p]), _digest(p.text)) for p in passages]
    want_ids = {sid for _, _, sid, _ in want}
    ids = [sid for _, _, sid, _ in want]
    stored: dict = {}
    for start in range(0, len(ids), vectorstore.BATCH):
        stored.update(vectorstore.fetch(ids[start:start + vectorstore.BATCH]))
    new, changed, unchanged = [], [], []
    for rec in want:
        _, _, sid, digest = rec
        payload = stored.get(sid)
        if payload is None:
            new.append(rec)
        elif payload.get("digest") != digest:
            changed.append(rec)
        else:
            unchanged.append(rec)
    return new, changed, unchanged, want_ids


def _orphans(want_ids: set) -> list:
    """Стійкі номери точок, що лежать у колекції, але яких немає серед поточних
    фрагментів: описують текст, який із документів зник. Лише читання."""
    return [sid for sid in vectorstore.all_ids() if sid not in want_ids]


def _fill(todo: list) -> int:
    """Рахує вектори для `todo` (список четвірок з _plan) і заливає пачками,
    друкуючи поступ. Порядок не важливий — у кожної точки свій стійкий номер,
    тож перервати безпечно: наступний запуск побачить залите як незмінне й
    продовжить із рештою."""
    total = len(todo)
    t0 = time.perf_counter()
    batch, sent = [], 0
    stream = embed.model().embed([p.text for p, _, _, _ in todo],
                                 batch_size=embed.BATCH)
    for offset, vector in enumerate(stream):
        p, uid, sid, digest = todo[offset]
        batch.append({
            "id": sid,
            "vector": vector.tolist(),
            "payload": {"uid": uid, "digest": digest, "pid": p.pid,
                        "doc_id": p.doc_id, "doc_title": p.doc_title,
                        "section": p.section, "label": p.label,
                        "url": p.url, "text": p.text},
        })
        if len(batch) == vectorstore.BATCH:
            sent += vectorstore.upsert(batch)
            batch = []
            spent = time.perf_counter() - t0
            left = spent / sent * (total - sent)
            print(f"  {sent}/{total}, минуло {spent:.0f} с, "
                  f"лишилося приблизно {left:.0f} с", flush=True)
    if batch:
        sent += vectorstore.upsert(batch)
    print(f"  пораховано і залито за {time.perf_counter() - t0:.0f} с")
    return sent


def _points_line(new, changed, unchanged, orphans) -> str:
    return (f"нових {len(new)}, змінених {len(changed)}, "
            f"незмінних {len(unchanged)}, зайвих {len(orphans)}")


def status() -> int:
    mode = read_mode()
    passages = load_passages()
    print(f"Файл рішення : {MODE_PATH}")
    print(f"Вирішено     : {mode.get('search')} (від {mode.get('decided', '—')})")
    print(f"Набір        : {DOC_SET}, {len(passages)} фрагментів")
    print(f"Колекція     : {vectorstore.COLLECTION}")
    if not vectorstore.docker_available():
        print("Docker       : не відповідає")
        return 0
    if not vectorstore.alive():
        print("Qdrant       : контейнер не піднято (docker down)")
        return 0
    have = vectorstore.count()
    print(f"Qdrant       : живий, {have} {nform(have, 'точка', 'точки', 'точок')}")
    if vectorstore.collection_info() is None:
        print("Оновлення    : колекції ще немає — залийте: --vectors")
        return 0
    _, uid_of = assign_ids(passages)
    new, changed, unchanged, want_ids = _plan(passages, uid_of)
    orphans = _orphans(want_ids)
    print(f"Оновлення    : {_points_line(new, changed, unchanged, orphans)}")
    if have and not unchanged and not changed:
        print("               жодну наявну точку не впізнано як поточний фрагмент —")
        print("               стара схема номерів або інший корпус; --vectors скаже, "
              "як перейти")
    elif not new and not changed:
        print("               усі вектори на місці й актуальні — рахувати нічого")
    return 0


def enable_vectors(refill: bool = False) -> int:
    if not vectorstore.docker_available():
        print("Docker не відповідає — пошук за змістом без нього не працює. "
              "Лишаю пошук по словах.")
        write_mode({"search": "words", "why": "docker недоступний"})
        return 1
    print(f"Піднімаю Qdrant ({vectorstore.CONTAINER})...")
    if not vectorstore.ensure_running():
        print("Контейнер не піднявся. Лишаю пошук по словах.")
        write_mode({"search": "words", "why": "контейнер не піднявся"})
        return 1
    print(f"  Qdrant відповідає: {vectorstore.QDRANT_URL}")

    passages = load_passages()
    _, uid_of = assign_ids(passages)
    n = len(passages)
    print(f"  фрагментів у наборі «{DOC_SET}»: {n}")

    created = vectorstore.ensure_collection(embed.DIM)
    print(f"  колекція {vectorstore.COLLECTION}: "
          f"{'створена' if created else 'уже була'}")

    new, changed, unchanged, want_ids = _plan(passages, uid_of)
    have = vectorstore.count()

    # Жоден поточний фрагмент не впізнано, а точки в колекції є: або вона під
    # старою схемою номерів (номер-позиція з першої версії практики), або в ній
    # зовсім інший корпус. Доливати не можна — старі точки лишилися б поряд
    # дублями. Знести й залити наново вирішує людина.
    if have and not refill and not unchanged and not changed:
        print(f"\nУ колекції {have} точок, але жодну не впізнано як поточний "
              f"фрагмент.\nСхоже, це стара схема номерів або інший корпус. Доливання "
              f"лишило б\nстарі точки поряд дублями, тому я його не роблю. Перехід — "
              f"через\nодноразове перезаливання наново (видаляєте колекцію ви самі):\n"
              f"  curl -X DELETE {vectorstore.QDRANT_URL}/collections/{vectorstore.COLLECTION}\n"
              f"  python -m practice.base.setup --vectors")
        return 1

    todo = (new + changed + unchanged) if refill else (new + changed)
    if refill:
        print(f"  --refill: перераховую всі {n}")
    else:
        print(f"  нових {len(new)}, змінених {len(changed)}, "
              f"незмінних {len(unchanged)} — рахую {len(todo)}")

    if not todo:
        print("  рахувати нічого — усі вектори на місці й актуальні")
    else:
        minutes = max(1, round(len(todo) * SEC_PER_PASSAGE / 60))
        print(f"  рахую вектори моделлю {embed.MODEL_NAME} "
              f"(перший запуск ще й довантажує її, ~{minutes} хв)...")
        _fill(todo)

    orphans = _orphans(want_ids)
    if orphans:
        m = len(orphans)
        print(f"\n  {m} {nform(m, 'точка', 'точки', 'точок')} описують текст, "
              f"якого в документах уже немає.\n"
              f"  Пошук їх не показує (їхній фрагмент не входить у набір). Прибрати\n"
              f"  фізично можна лише знесенням колекції — робите це ви самі:\n"
              f"    curl -X DELETE {vectorstore.QDRANT_URL}/collections/{vectorstore.COLLECTION}\n"
              f"    python -m practice.base.setup --vectors")

    write_mode({"search": "vectors", "docs": DOC_SET, "model": embed.MODEL_KEY,
                "collection": vectorstore.COLLECTION, "points": vectorstore.count()})
    print("\nЗаписано: пошук за змістом. Сервер піднімати не треба — клієнт "
          "запускає його сам.")
    return 0


def _cos(a: list, b: list) -> float:
    """Косинус між двома векторами. 1.0 — однакові напрями."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def verify(sample: int = VERIFY_SAMPLE) -> int:
    """Звіряє випадкову вибірку збережених векторів із перерахованими наново.

    Сума в payload (її дивиться --status) ловить підміну тексту, але не підміну
    самого вектора: хтось лишає текст, а числа переписує так, щоб фрагмент завжди
    спливав високо на чужих запитах. Ця перевірка рахує вектори кількох
    випадкових фрагментів наново тією самою моделлю і порівнює з тим, що лежить у
    Qdrant. Близькість помітно нижча за одиницю при незмінному тексті означає, що
    вектор у базі не той, який дає модель, — підміна, інша модель або недолита
    точка. Вибірка щоразу нова, тож повторні прогони покривають різні місця."""
    if not vectorstore.alive():
        print("Qdrant не відповідає — нема чого звіряти.")
        return 1
    if vectorstore.collection_info() is None:
        print(f"Колекції {vectorstore.COLLECTION} немає — залийте: --vectors")
        return 1

    passages = load_passages()
    _, uid_of = assign_ids(passages)
    k = min(sample, len(passages))
    picked = random.sample(passages, k)
    ids = [_stable_id(uid_of[p]) for p in picked]
    stored = vectorstore.fetch_vectors(ids)
    if not stored:
        if vectorstore.count():
            print(f"Жодної з {k} перевірених точок у базі немає, хоча точки в "
                  f"колекції\nє — це стара схема номерів. Перезалийте наново: "
                  f"--vectors (він скаже, як).")
        else:
            print(f"Колекція {vectorstore.COLLECTION} порожня — залийте: --vectors")
        return 1

    print(f"Звіряю {k} випадкових фрагментів у {vectorstore.COLLECTION} "
          f"(модель {embed.MODEL_NAME})...")
    fresh = list(embed.model().embed([p.text for p in picked],
                                     batch_size=embed.BATCH))

    bad, missing, worst = 0, 0, 1.0
    for p, sid, vec in zip(picked, ids, fresh):
        have = stored.get(sid)
        if have is None:
            missing += 1
            print(f"  НЕМА  {uid_of[p]}: точки з таким номером у базі немає")
            continue
        sim = _cos(have, vec.tolist())
        worst = min(worst, sim)
        if sim < VERIFY_MIN_COS:
            bad += 1
            print(f"  РІЗНО {uid_of[p]}: близькість до перерахованого {sim:.5f}")

    ok = k - bad - missing
    print(f"\n  збіглося {ok}, розійшлося {bad}, немає в базі {missing}; "
          f"найменша близькість {worst:.5f} (межа {VERIFY_MIN_COS})")
    if bad:
        print("  Вектор розійшовся при незмінному тексті — привід підозрювати\n"
              "  підміну в базі. Перезалийте наново: --vectors --refill")
        return 1
    if missing:
        print("  Частина точок відсутня — колекція недолита: --vectors")
        return 1
    print("  Усі перевірені вектори збігаються з тим, що дає модель.")
    return 0


def words() -> int:
    write_mode({"search": "words", "why": "вибір власника"})
    print("Записано пошук по словах. Колекція й контейнер не чіпаються.")
    return 0


def main(argv: list[str]) -> int:
    if "--status" in argv:
        return status()
    if "--vectors" in argv:
        return enable_vectors(refill="--refill" in argv)
    if "--verify" in argv:
        return verify()
    if "--words" in argv or "--no-vectors" in argv:
        return words()
    print("Пошук за змістом вимагає Qdrant. Команди:")
    print("  --status   що зараз вирішено, що в базі, що змінилося")
    print("  --vectors  підняти Qdrant і долити лише нове й змінене")
    print("  --verify   звірити вибірку збережених векторів із перерахованими")
    print("  --words    лишитися на пошуку по словах")
    return status()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
