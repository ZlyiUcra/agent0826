"""
ЧЕЛЕНДЖ D · дія з наслідками — БЕКЕНД (інструменти переадресації).
Пара до practice/challenges/d_run.py (точка входу).

Це перший інструмент практики, який ЩОСЬ ЗМІНЮЄ: заявка на переадресацію
лягає записом у out/redirects.json і переживає процес. Саме тому навколо
нього два запобіжники, яких читальним інструментам не треба:

Підтвердження людиною. Дія розбита на два інструменти. `request_redirect`
нічого незворотного не робить — створює заявку в стані pending і повертає
її клієнтові на очі. Змінює стан лише `confirm_redirect`, і викликати його
агент має право тільки після явної згоди клієнта. Двофазність живе в
бекенді, а не в промпті: навіть агент, що знехтує правилом, не зможе
підтвердити заявку тим самим викликом, яким її створив.

Ідемпотентність. Ідентифікатор заявки виводиться з трек-номера і міста
детерміновано, тож повторне прохання повертає ту САМУ заявку з позначкою
`already_exists`, а повторне підтвердження — `already_confirmed`. Другого
запису не виникає ні там, ні там; це і є відповідь на «клієнт клацнув
двічі» без жодної магії з блокуваннями.

Свідома межа: право діяти в курсі з'являється з модуля 4 (`create_claim`
у `CAPABILITIES[4]`), і цей файл його не чіпає. Переадресація — власна
дія практики у власному сховищі, вона не створює претензій і не конкурує
з матеріалом майбутнього заняття. Курсові файли, як і всюди в практиці,
недоторкані.

Контракт бекенду той самий, що в backend.py: ніколи не кидати винятків,
ніколи не повертати клієнтський текст назад у tool_result.
"""

import hashlib
import json
import re
from datetime import date

from config import OUT_DIR
from practice.common.backend import _CUSTOMERS, _DETAILS, normalize_phone

# Сховище заявок. Живе поруч із practice_results.json і так само переживає
# процес — інакше «підтвердження наступним повідомленням» було б неможливе:
# run_agent не тримає історії між прогонами, тож стан заявки мусить жити тут.
STORE = OUT_DIR / "redirects.json"


def _quarantine(path):
    """Відсуває пошкоджений файл убік під іменем *.corrupt і повертає нову
    назву. Попередніх рятунків не затирає: якщо .corrupt уже зайняте, шукає
    .corrupt.1, .corrupt.2 і так далі — жоден пошкоджений файл не пропаде."""
    target, n = path.parent / (path.name + ".corrupt"), 1
    while target.exists():
        target = path.parent / (path.name + f".corrupt.{n}")
        n += 1
    path.rename(target)
    return target


def _load() -> dict:
    if not STORE.exists():
        return {}
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Пошкоджений файл НЕ затираємо — це знищило б уцілілі заявки. Раніше
        # тут просто повертався {}, і наступний _save мовчки переписував файл
        # начисто; тепер спершу відсуваємо його вбік під *.corrupt, щоб уміст
        # можна було розібрати руками, і лише тоді починаємо з чистого аркуша.
        try:
            _quarantine(STORE)
        except OSError:
            pass  # не змогли відсунути — принаймні не впадемо і не затремо мовчки
        return {}


def _save(records: dict) -> None:
    """Пише сховище цілком. Записи звідси ніколи не видаляються — стани
    лише додаються і просуваються вперед (pending -> confirmed)."""
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(records, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def normalize_city(raw) -> str:
    """Місто призначення: 2-40 символів, є хоч дві літери. Інакше порожньо.

    Та сама дисципліна, що з телефоном у backend.py: значення, яке не схоже
    на місто, відхиляється цілком і НЕ повертається клієнтові назад — у
    рядку може бути довільний текст, а все з tool_result модель читає як
    факт від системи.
    """
    city = re.sub(r"\s+", " ", str(raw or "")).strip()
    letters = sum(ch.isalpha() for ch in city)
    if not 2 <= len(city) <= 40 or letters < 2:
        return ""
    return city


def _redirect_id(tracking: str, city: str) -> str:
    """Детермінований ідентифікатор заявки — він і є ключем ідемпотентності.

    Той самий трек-номер і те саме місто дають той самий id за будь-якої
    кількості спроб, тож «повторний запит» упирається в уже наявний запис
    ще до того, як постане питання про дублікат. Формат RDR- навмисно НЕ
    схожий на курсовий CLM-: претензії — матеріал модуля 4.
    """
    digest = hashlib.sha1(f"{tracking}|{city.lower()}".encode()).hexdigest()
    return f"RDR-{digest[:6].upper()}"


def _public(record: dict) -> dict:
    """Те, що бачить модель. Копія, щоб виклик не мутував сховище."""
    return dict(record)


def request_redirect(phone: str, tracking: str, new_city: str) -> dict:
    """Створює заявку на переадресацію. Незворотного не робить нічого.

    Переадресувати можна ЛИШЕ посилку, зареєстровану на вказаний телефон.
    Це навмисне обмеження, а не формальність: без нього будь-хто, хто знає
    (чи перебором вгадав) чужий трек-номер, міг би завернути фізичну посилку
    собі — інструмент віддавав дію кожному, хто назве номер.

    Межу цієї прив'язки треба знати точно, бо покластися на неї більше, ніж вона
    витримує, дуже легко. Вона зупиняє того, хто має трек-номер і не знає
    телефону власника, і тільки його. Хто телефон знає, той дістає трек-номери
    з find_shipments — цей інструмент нічим не захищений — і оформлює
    переадресацію тією самою парою. Тобто крадіжку перебором не закрито: вона
    перемістилася з трек-номерів на телефони. Перевіряється знання пари значень,
    а не особа того, хто питає; справжня автентифікація — рівень модуля 4.

    Повертає заявку в стані pending або, якщо така вже є, її ж із позначкою
    already_exists.
    """
    key = normalize_phone(phone)
    if not key:
        return {"error": "bad_phone",
                "hint": "Потрібен номер телефону, на який оформлено посилку."}

    track = str(tracking or "").strip().upper()
    owned = {t for t, _ in _CUSTOMERS.get(key, [])}
    if track not in owned:
        # Єдина відповідь і для чужої, і для неіснуючої посилки: не викриваємо
        # навіть факту, що такий трек-номер існує в системі.
        return {"error": "not_owner",
                "hint": "На цей номер такої посилки не зареєстровано. "
                        "Переадресувати можна лише власне відправлення — "
                        "спершу знайдіть його за своїм телефоном."}

    details = _DETAILS.get(track)
    if not details:
        return {"error": "record_unavailable", "tracking": track,
                "hint": "Дані по цьому відправленню недоступні — "
                        "переадресацію оформити не можна."}
    if details["status"] != "В дорозі":
        return {"error": "not_redirectable", "tracking": track,
                "status": details["status"],
                "hint": "Переадресувати можна лише відправлення в дорозі."}

    city = normalize_city(new_city)
    if not city:
        # Свідомо без ехо введеного значення — див. normalize_city.
        return {"error": "bad_city",
                "hint": "Потрібна назва міста, напр. Одеса."}
    if city.lower() == details["recipient_city"].lower():
        return {"error": "same_city", "tracking": track, "city": city,
                "hint": "Відправлення і так прямує в це місто."}

    rid = _redirect_id(track, city)
    records = _load()
    if rid in records:
        return {**_public(records[rid]), "already_exists": True}

    record = {"redirect_id": rid, "tracking": track, "new_city": city,
              "state": "pending", "requested_on": date.today().isoformat()}
    records[rid] = record
    _save(records)
    return {**_public(record),
            "hint": "Заявку створено, але НЕ виконано. Перекажи її клієнту "
                    "і спитай підтвердження. Підтверджує confirm_redirect."}


def confirm_redirect(redirect_id: str) -> dict:
    """Підтверджує заявку — єдина незворотна дія в усій практиці.

    Викликається лише після явної згоди клієнта; це правило контракту
    агента, а бекенд зі свого боку гарантує інше: підтвердити можна тільки
    заявку, яка вже існує, і повторне підтвердження нічого не змінює.
    """
    rid = str(redirect_id or "").strip().upper()
    records = _load()
    record = records.get(rid)
    if not record:
        # Ідентифікатор міг бути довільним текстом — назад його не віддаємо.
        return {"error": "no_pending_request",
                "hint": "Такої заявки немає. Спершу створи її через "
                        "request_redirect."}
    if record["state"] == "confirmed":
        return {**_public(record), "already_confirmed": True}

    record["state"] = "confirmed"
    record["confirmed_on"] = date.today().isoformat()
    _save(records)
    return {**_public(record),
            "hint": "Переадресацію підтверджено. Повідом клієнту місто і "
                    "номер заявки."}


ACTION_IMPL = {
    "request_redirect": request_redirect,
    "confirm_redirect": confirm_redirect,
}


def _schema(name, description, properties, required):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required}}


# Описи писані за уроком челенджа A: що повертає, коли брати, звідки
# походить кожен аргумент — і, для незворотної дії, коли брати НЕ можна.
ACTION_SCHEMAS = [
    _schema(
        "request_redirect",
        "Створює ЗАЯВКУ на переадресацію відправлення в інше місто. Нічого не "
        "змінює одразу: повертає заявку в стані pending, яку клієнт має "
        "підтвердити. Використовуй, коли клієнт попросив переадресувати "
        "посилку і назвав місто. Працює лише для відправлень у дорозі і лише "
        "для посилок, зареєстрованих на вказаний телефон. Повертає "
        "redirect_id — він знадобиться для підтвердження.",
        {"phone": {"type": "string",
                   "description": "Телефон клієнта, на який оформлено посилку — "
                                  "той самий, за яким шукали find_shipments"},
         "tracking": {"type": "string",
                      "description": "Трек-номер відправлення — з результату "
                                     "find_shipments або від клієнта"},
         "new_city": {"type": "string",
                      "description": "Місто, яке назвав клієнт, напр. Одеса"}},
        ["phone", "tracking", "new_city"]),
    _schema(
        "confirm_redirect",
        "ОСТАТОЧНО підтверджує заявку на переадресацію. Незворотна дія. "
        "Викликай ЛИШЕ якщо клієнт у своєму повідомленні явно підтвердив цю "
        "переадресацію («так, підтверджую»). НІКОЛИ не викликай у тому "
        "самому ході, де клієнт лише попросив переадресувати: спершу він має "
        "побачити заявку і погодитись.",
        {"redirect_id": {"type": "string",
                         "description": "Ідентифікатор заявки — ТІЛЬКИ з "
                                        "результату request_redirect"}},
        ["redirect_id"]),
]
