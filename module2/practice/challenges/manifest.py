"""
СПІЛЬНЕ ДЛЯ ЗАВАНТАЖУВАЧІВ · маніфест набору документів. $0, без мережі.

Кожен .txt у теці набору починається з трирядкової шапки: назва, адреса
джерела, дата вивантаження. Походження кожного документа вже записане в ньому
самому — маніфест збирає це в один файл і додає те, чого в шапці немає: суму
тексту і валідатор, яким сервер відповідає на питання «чи змінилося».

Формат — той самий index.json, що вже лежить у practice/docs/: перелік
документів із полями file, id, title, url. Новий вигляд обгортає перелік в
об'єкт, щоб поруч помістилися назва набору й дата запису, і додає до кожного
документа fetched, chars і sha256. Читаються обидва вигляди.

ЧОМУ СУМА РАХУЄТЬСЯ ЛИШЕ ПО ТІЛУ

Третій рядок шапки — дата вивантаження, і вона міняється щоразу, коли документ
перезавантажують. Якби сума рахувалася по цілому файлу, кожне перезавантаження
виглядало б як зміна вмісту, навіть коли текст той самий. Тому шапка з-під суми
виключена: сума описує текст специфікації, а не факт звернення до сервера.

ЧОМУ ІДЕНТИФІКАТОР І ІМ'Я ФАЙЛА — ЦЕ РІЗНІ РЕЧІ

Ім'я файла в docs-full/ несе позицію документа у змісті видання:
«22-text-processing.txt» — двадцять другий за порядком, а не двадцять другий
розділ специфікації. Вклиниться нова глава раніше — і всі наступні файли
перейменуються, а разом з іменами поїдуть ідентифікатори фрагментів, номери
точок у Qdrant і номери глав, якими задані маршрути спеціалістів у base/team.py.

Ідентифікатор такого зсуву не має. Для docs-full/ це слаг сторінки видання
(«text-processing»), для розділів ECMA-402 — слаг розділу («intl-object»), для
вільних документів — ключ у таблиці адрес («uts35-7-keyboards»). Тому маніфест
тримає і ім'я, і ідентифікатор: за ідентифікатором документ упізнається після
зсуву, а за іменем видно, що зсув стався.
"""

import hashlib
import json
import pathlib

NAME = "index.json"

_SOURCE = "джерело:"
_FETCHED = "отримано:"


def header(path: pathlib.Path) -> dict:
    """Назва, адреса і дата з трирядкової шапки документа."""
    out = {"title": "", "url": "", "fetched": ""}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            value = line[1:].strip()
            if value.startswith(_SOURCE):
                out["url"] = value[len(_SOURCE):].strip()
            elif value.startswith(_FETCHED):
                out["fetched"] = value[len(_FETCHED):].strip()
            elif not out["title"]:
                out["title"] = value
    return out


def body_of(text: str) -> str:
    """Текст документа без шапки — те, що справді прийшло зі специфікації.

    Береться від рядка, який уже не починається з «#», і далі до кінця. Через цю
    саму функцію проходить і документ із диска, і щойно зібраний із сторінки —
    інакше суми порівнювати не можна, бо дата в шапці в них різна за означенням.
    """
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "".join(lines[i:])


def body(path: pathlib.Path) -> str:
    """Тіло документа, що лежить на диску."""
    return body_of(path.read_text(encoding="utf-8"))


def digest(text: str) -> str:
    """Сума тексту. Нею вирішується, чи змінився документ."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def entry(path: pathlib.Path, doc_id: str, **extra) -> dict:
    """Запис маніфеста для одного документа, зібраний із самого файла."""
    head = header(path)
    text = body(path)
    record = {"file": path.name, "id": doc_id, "title": head["title"],
              "url": head["url"], "fetched": head["fetched"],
              "chars": len(text), "sha256": digest(text)}
    record.update({k: v for k, v in extra.items() if v})
    return record


def build(folder: pathlib.Path, id_of, written: str) -> dict:
    """Маніфест теки з того, що вже лежить на диску. Мережа не потрібна."""
    files = sorted(folder.glob("*.txt"))
    return {"set": folder.name, "written": written,
            "documents": [entry(p, id_of(p.name)) for p in files]}


def load(folder: pathlib.Path) -> dict | None:
    """Маніфест теки або None, якщо його ще не писали.

    Старий вигляд — просто перелік документів, як у practice/docs/index.json, —
    читається теж: він загортається в той самий об'єкт, тільки без дати запису.
    """
    path = folder / NAME
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"set": folder.name, "written": "", "documents": data}
    return data


def save(folder: pathlib.Path, data: dict) -> pathlib.Path:
    """Записує маніфест поруч із документами. Повертає шлях."""
    path = folder / NAME
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def by_id(data: dict | None) -> dict:
    """Документи маніфеста за ідентифікатором."""
    return {d["id"]: d for d in (data or {}).get("documents", [])}


def ids(data: dict | None) -> list:
    """Ідентифікатори маніфеста в тому порядку, у якому їх записали."""
    return [d["id"] for d in (data or {}).get("documents", [])]


def order_change(was: list, now: list) -> dict:
    """Що сталося з переліком і з якої позиції поїхали імена файлів.

    `added` і `removed` — ідентифікатори, яких не було або не стало. `shift` —
    перша позиція, на якій переліки розійшлися: усе від неї і далі дістане інше
    ім'я файла, навіть якщо сам документ не змінився ні на символ. None означає,
    що позиції збіглися до кінця спільної частини.
    """
    was_set, now_set = set(was), set(now)
    shift = None
    for i in range(min(len(was), len(now))):
        if was[i] != now[i]:
            shift = i
            break
    if shift is None and len(was) != len(now):
        shift = min(len(was), len(now))
    return {
        "added": [(i, d) for i, d in enumerate(now) if d not in was_set],
        "removed": [(i, d) for i, d in enumerate(was) if d not in now_set],
        "shift": shift,
        "moved": 0 if shift is None else len(now) - shift,
    }


def orphans(folder: pathlib.Path, expected: list) -> list:
    """Файли на диску, яких немає в переліку адрес. Тільки перелік — нічого не
    видаляє і видаляти не має: рішення про видалення ухвалює власник."""
    want = set(expected)
    return sorted(p.name for p in folder.glob("*.txt") if p.name not in want)


def report_shift(was: list, now: list, new_files: list, known: dict,
                 note: str = "") -> bool:
    """Друкує, що сталося з переліком документів. Повертає True, якщо є зсув.

    `new_files` — імена, які документи дістануть за новим переліком, у тому ж
    порядку, що й `now`. `known` — що ми маємо зараз, за ідентифікатором; звідти
    береться нинішнє ім'я, щоб показати перейменування парою. `note` — наслідок,
    який стосується саме цього набору: він у кожного свій.
    """
    change = order_change(was, now)
    for i, doc in change["added"]:
        print(f"  + вклинився «{doc}» на позицію {i + 1}")
    for i, doc in change["removed"]:
        print(f"  - зник «{doc}», був на позиції {i + 1}")
    if change["shift"] is None:
        print("  порядок збігається — зсуву немає")
        return False

    renames = [(known[doc]["file"], new_files[i])
               for i, doc in enumerate(now)
               if i >= change["shift"] and known.get(doc, {}).get("file")
               and known[doc]["file"] != new_files[i]]
    print(f"  ! ЗСУВ від позиції {change['shift'] + 1}: інше ім'я дістануть "
          f"{len(renames)} документів, які в нас уже є")
    for was_file, now_file in renames[:3]:
        print(f"      {was_file} → {now_file}")
    if len(renames) > 3:
        print("      …")
    print("  ! разом з іменами поїдуть ідентифікатори фрагментів і номери точок")
    print("    у Qdrant: те саме місце специфікації опиниться під іншим ім'ям,")
    print("    а записані прогони почнуть посилатися в порожнечу.")
    for line in note.splitlines():
        if line.strip():
            print(f"  ! {line}")
    return True

