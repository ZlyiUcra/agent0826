"""
ОСНОВА · п'ять запитів виміру. Зафіксовані ДО перших прогонів порівняння.

Картка вимагає прогнати ті самі п'ять запитів через одного агента і через
систему. Щоб добір не підігравав жодній стороні, склад зафіксований заздалегідь
і побудований так:

  два прості довідкові запити з РІЗНИХ родин — на них маршрутизатор має чітку
  правильну відповідь, і виграш системи, якщо він є, видно в чистому вигляді;
  два складені міжтемні запити — на них правильний маршрут GENERAL, тобто
  субагент і найдорожчий шлях системи; якщо система десь програє одному
  агентові, то тут;
  один запит про специфікацію, відповіді на який у документах немає, — він
  міряє не якість відповіді, а якість відмови в обох.

Один із п'яти — українською: правило «мова відповіді = мова запиту» має бути
перевірене виміром, а не лише написане у промпті.

Ключ expected_route — очікування для читання результату, а не підказка системі:
маршрутизаторові ці ключі не передаються ніколи.
"""

QUERIES = {
    "attrs": {
        "query": "What are the attributes of a data property, and what default "
                 "values do they get when a property is created?",
        "expected_route": "OBJECT",
        "kind": "простий, одна родина",
    },
    "replace": {
        "query": "Як String.prototype.replace вирішує, чим замінити знайдений "
                 "збіг, і що відбувається з рештою рядка?",
        "expected_route": "WRAPPERS",
        "kind": "простий, одна родина, українською",
    },
    "proxy": {
        "query": "When a proxy stands in for another object, what stops it from "
                 "reporting a value that contradicts the real object, and how "
                 "does reading a property through it actually work?",
        "expected_route": "GENERAL",
        "kind": "складений: інваріанти (OBJECT) плюс Proxy (EXOTIC)",
    },
    "tofixed": {
        "query": "What does Number.prototype.toFixed do when its argument is "
                 "outside the allowed range, and could a Proxy around a Number "
                 "object change that behaviour?",
        "expected_route": "GENERAL",
        "kind": "складений: Number (WRAPPERS) плюс Proxy (EXOTIC)",
    },
    "flat": {
        "query": "How does Array.prototype.flat decide how deep to flatten "
                 "a nested array?",
        "expected_route": "EXOTIC",
        "kind": "поза документами: тема наша, розділу 23.1 у нас немає",
    },
}
