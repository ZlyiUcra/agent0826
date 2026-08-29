"""
ОСНОВА · безкоштовні перевірки сервера повз протокол. Ані моделей, ані мережі.

Тут інструменти викликаються як звичайні функції Python: перевіряється те, що
сервер віддає, а не те, як він це загортає в JSON-RPC. Протокол перевіряє сусідній
check.py, і розділяти ці дві перевірки варто — коли клієнт отримує дурницю, одразу
видно, у кому вона: у пошуку чи в обгортці.

Кожна перевірка друкує рядок ok/FAIL; будь-який FAIL завершує процес ненульовим
кодом.

    python -m practice.base.smoke           # $0, секунди
"""

import sys

FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def main(argv: list[str]) -> int:
    from practice.base import spec_mcp
    from practice.common import nform

    search, read = spec_mcp.search_spec, spec_mcp.read_section

    # 1. Розділи на місці, і поділені вони тим самим кодом, що в модулі 4. Скільки
    # саме фрагментів вийде, залежить від набору документів; числа зняті 29 серпня
    # 2026 року на тих самих файлах, що лежать у practice/docs*.
    from practice.common.corpus import DOC_SET

    EXPECTED = {"core": 283, "full": 2436, "suite": 3964}
    total = len(spec_mcp._INDEX.passages)
    check(f"індекс зібрано при завантаженні модуля (набір {DOC_SET})",
          total == EXPECTED[DOC_SET],
          f"{total} {nform(total, 'фрагмент', 'фрагменти', 'фрагментів')}")
    check("кожен фрагмент доступний за своїм id", len(spec_mcp._BY_ID) == total)
    check("опис називає моделі, що саме завантажено",
          spec_mcp._LOADED in spec_mcp.TOOL_DESCRIPTIONS["search_spec"]
          and spec_mcp._LOADED in spec_mcp.TOOL_DESCRIPTIONS["read_section"],
          spec_mcp._LOADED[:60] + "...")

    # 2. Пошук знаходить те, що в розділах явно є, і кожен знайдений фрагмент
    # приходить із заповненими полями — саме за ними клієнт цитує джерело.
    hits = search("Object.prototype.toString tag")
    found = hits.get("found", 0)
    check("search_spec знаходить Object.prototype.toString", found > 0,
          f"found={found}")
    first = (hits.get("passages") or [{}])[0]
    check("у відповіді є id, section, document, text",
          all(first.get(f) for f in ("id", "section", "document", "text")),
          first.get("id", "—"))
    check("k керує кількістю", len(search("prototype", 5).get("passages", [])) == 5)

    # 3. Обрізка. Довший за межу фрагмент має прийти рівно 600 символів плюс три
    # крапки, і серед розділів мусить бути хоч один такий, інакше перевірка порожня.
    long_hits = search("string prototype replace searchValue replaceValue", 10)
    texts = [p["text"] for p in long_hits.get("passages", [])]
    check("жоден текст у відповіді пошуку не довший за 603 символи",
          texts and max(len(t) for t in texts) <= 603,
          f"найдовший {max(len(t) for t in texts) if texts else 0}")
    check("обрізаний текст позначено трьома крапками",
          any(t.endswith("...") for t in texts))

    # 4. Мова запиту. Запит ріжеться на слова виразом [a-z0-9_]+, тобто кирилиця
    # зникає ще до пошуку, і суто український запит не має жодного шансу — це не
    # «погано шукає», це порожній вхід. Опис search_spec каже про це моделі прямо,
    # і саме тому перевіряється тут: якщо розділи колись заміняться іншими, разом
    # із перевіркою доведеться правити й опис.
    from practice.common.lexical import tokenize

    ua = "Як працює перехоплення читання властивості"
    check("кирилиця дає нуль токенів", tokenize(ua) == [])
    check("суто український запит повертає found=0", search(ua).get("found") == 0)
    mixed = "Що каже специфікація про Object.prototype.toString?"
    check("український запит із латинським ідентифікатором працює",
          search(mixed).get("found", 0) > 0, str(tokenize(mixed)))
    check("опис search_spec попереджає про мову запиту",
          "in English" in (search.__doc__ or ""))
    check("опис search_spec каже, як писати українську відповідь",
          all(s in (search.__doc__ or "")
              for s in ("Answer in the language", "розділ", "Never call this set")))

    # 5. Межі k. Виняток тут був би гіршим за словник: клієнт побачив би збій
    # інструмента замість пояснення, що саме не так із аргументом.
    check("k=0 дає error", "error" in search("object", 0))
    check("k=11 дає error", "error" in search("object", 11))
    check("k=1 і k=10 проходять",
          "error" not in search("object", 1) and "error" not in search("object", 10))

    # 6. read_section віддає повний текст того самого фрагмента, а не свій.
    pid = first.get("id", "")
    full = read(pid)
    origin = spec_mcp._BY_ID.get(pid)
    check("read_section повертає текст розділу дослівно",
          origin is not None and full.get("text") == origin.text,
          f"{len(full.get('text', ''))} симв.")
    # Адреса джерела. У наборах core і full усе приходить з ecma262; у suite поруч
    # лежать ECMA-402, 404, 414 і вільні документи довкола 402, тому там перевіряємо
    # лише те, що адреса взагалі є і вона https.
    url = str(full.get("url", ""))
    expected = "https://" if DOC_SET == "suite" else "https://tc39.es/ecma262/"
    check("read_section дає посилання на джерело", url.startswith(expected), url)
    check("повний текст не коротший за обрізаний",
          len(full.get("text", "")) >= len(first.get("text", "")))

    # 7. Вигаданий ідентифікатор. Підказка в помилці важить не менше за саму
    # помилку: без неї модель починає гадати id далі.
    bad = read("22.1.3.19")
    check("вигаданий id дає error", "error" in bad)
    check("до помилки додано підказку, звідки брати id", bool(bad.get("hint")))

    # 8. Описи інструментів — головна робота цього завдання, тож перевіряється і
    # те, що вони взагалі доїхали до сервера, і те, що вони не однорядкові.
    for name, fn in (("search_spec", search), ("read_section", read)):
        doc = (fn.__doc__ or "").strip()
        check(f"{name}: опис довший за один рядок", len(doc) > 400,
              f"{len(doc)} симв.")
        check(f"{name}: опис каже, коли НЕ викликати", "Do not " in doc)

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — " + "; ".join(FAILED))
        return 1
    print("Усі перевірки пройдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
