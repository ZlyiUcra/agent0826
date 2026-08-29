# Установка і розробка

Як підняти оточення практики модуля 3 з нуля і як з ним працювати далі. Усі команди виконуються з теки
`module3/`, не з кореня репозиторію: скрипти імпортують `config`, `core`, `domain` як пакети верхнього рівня.

## Швидкий старт

Шість команд, з теки `module3/`, інтерпретатором із `module3/.venv`:

```
.venv/bin/python -m practice.base.smoke                          # перевірки переносу, 52 перевірки, $0
.venv/bin/python -m practice.base.graph --show                   # вузли і ребра графа, $0
.venv/bin/python -m practice.base.graph --fast "Що таке Proxy?"  # своє питання через граф, ~$0.01–0.05
.venv/bin/python -m practice.base.graph --fast --alt "…"         # плюс три альтернативні спроби, ~$0.1–0.2
.venv/bin/python -m practice.base.chat --fast                    # бесіда з графом, ~$0.02–0.05 за репліку
.venv/bin/python -m practice.base.compare --fast                 # три запити через обидва стеки, ~$0.15
```

Питання — будь-який текст у лапках, відповідь приходить мовою питання. Повний перелік команд, ціна кожної і
що саме шукати у виводі — у README, розділ «Як перевірити імплементацію».

## Оточення

У модуля власне віртуальне середовище — `module3/.venv`. Глобальним і середовищами сусідніх модулів він не
користується: модуль має підніматися сам по собі, не знаючи про сусідів. Піднято 26 серпня 2026 такими
командами:

```
cd module3
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements.txt 'anthropic==0.122.*'
```

Чому саме так, а не один `pip install -r requirements.txt`:

- Торч ставиться з окремого індексу PyTorch, збірка лише під процесор. Звичайний `pip install torch` тягне
  збірку з CUDA — кілька гігабайтів під відеокарту, якої це середовище не використовує. Торч потрібен моделі
  ембедингів `sentence-transformers`, тобто векторному пошукові по документах.
- Курсовий `requirements.txt` береться цілком, усі чотири стеки: практиці потрібні `langgraph` і
  `langchain-anthropic` (стек переносу), а `claude-agent-sdk` і `google-adk` — курсовим `run_agent_sdk.py` і
  `run_adk.py`, які тут ганяються як зразки. Це найважче середовище з усіх модулів: 186 пакетів, 1,3 ГБ, і на
  цьому диску (Windows через 9p) установка тривала 37 хвилин — десять на торч і двадцять сім на решту.
  Обмежував запис файлів на диск, не мережа.
- `anthropic` закріплено на гілці 0.122 — наступний розділ.

Версії, які стоять у середовищі: `anthropic` 0.122.0, `langchain` 1.3.17, `langchain-anthropic` 1.6.1,
`langchain-core` 1.6.0, `langgraph` 1.2.11, `claude-agent-sdk` 0.2.144, `google-adk` 2.7.1, `litellm` 1.98.0,
`torch` 2.13.0+cpu, `sentence-transformers` 6.0.0, `qdrant-client` 1.19.0, `python-dotenv` 1.2.3. Перевірка з
README курсу проходить:

```
.venv/bin/python -c "import langchain, langgraph, claude_agent_sdk, google.adk; print('ok')"
```

## Версія anthropic закріплена на 0.122.* — не змінювати мовчки

У версії 1.0.0 з `client.messages.create` прибрано параметр `temperature`: у колесі 1.1.0, чинному на 26
серпня 2026, цього слова немає в жодному файлі пакета. Курсовий `core/agent.py` — функція `ask()`, якою
ходять маршрутизатор, критик і переписування запиту ручного стека, а в курсовому `run_langgraph.py` — вузол
`CONFIRM` — передає `temperature=0.0` на кожен виклик і на 1.x падає з `TypeError`. Курсові файли в цьому
репозиторії не змінюються, тому лагодиться не код, а версія залежності; модулі 1, 2 і 4 живуть на тій самій
гілці 0.122.

У цьому модулі закріплення тримається подвійно: `langchain-anthropic` 1.6.1 сам вимагає
`anthropic<1.0.0,>=0.120.0`, тож повне встановлення з `requirements.txt` і без явного піна отримало б 0.x.
Явний пін робить це рішенням, а не збігом: хто поставить лише `anthropic` і `langgraph` без
`langchain-anthropic`, отримає 1.1.0 і падіння. Стек переносу (`base/graph.py`) звертається до моделі через
`ChatAnthropic` із `langchain-anthropic`, тобто через той самий пакет `anthropic` 0.122, і `temperature` для
нього — штатний параметр.

## Сховище фрагментів

Практика шукає або в базі Qdrant, що працює в Docker, або в документах на диску — і вибирає сама. Правило,
команди підняття, поведінка зі згодою на заливання і опис колекцій — у `STORAGE.md`; цей файл однаковий у
всіх модулях, де практика шукає по документах. Документи модуля 3 побайтово ті самі, що в модулі 4, тому й
колекції ті самі: `spec-core-e5`, `spec-full-e5`, `spec-suite-e5`. Колекцію практика знаходить за іменем і
вважає готовою, коли точок у ній не менше, ніж фрагментів у наборі. `core` і `full` цю умову виконують —
заливати їх удруге не треба. Набір `suite` виріс із 3964 фрагментів до 4171, коли до нього додали шосту й
сьому частини UTS #35, тож залита раніше `spec-suite-e5` тримає 3964 точки й потребує дозаливання:

```bash
docker compose up -d                                             # підняти базу (з кореня репозиторію)
.venv/bin/python -m practice.challenges.qdrant_store --info      # що в ній зараз
.venv/bin/python -m practice.challenges.qdrant_store             # долити suite до 4171 точки, $0
.venv/bin/python -m practice.challenges.qdrant_store --check     # звірити видачу бази з матрицею, $0
```

Дозаливання не коштує грошей, але коштує часу: відбиток набору змінився, кеш векторів у `practice/index/`
під нього не підходить, і модель `e5` рахує на процесорі вектори всіх 4171 фрагмента наново — це хвилини.

Набір документів у `.env` — `suite`: уся ECMA-262 разом з ECMA-402, 404, 414 і документами довкола 402 (72
документи, 4171 фрагмент). У модулі 4 типовим стоїть `full`; тут узято все, що є, бо агентові модуля 3
дають ті самі питання, що й у модулі 4, і задачу про Promise серед них. Родини спеціалістів для `suite` ті
самі, що для `full`; документи інших стандартів дістаються лише маршрутові GENERAL — див. `base/team.py`.

## Ключ

Секрети живуть у `module3/.env`, звідки їх читає `config.py`:

```
cp .env.example .env    # і впишіть ANTHROPIC_API_KEY
```

Той самий `.env` тримає налаштування практики: адресу Qdrant, набір документів, вид пошуку, `MAX_TURNS=8`
і `MAX_TOKENS=2000`, як у модулі 4 (курсовий `.env.example` модуля 3 має 6 і 1200 — числа виміру модуля 4
зроблені з вісьмома кроками, і щоб порівняння стеків було з ними сумісне, узято їх). Ключ ніколи не потрапляє
ні в код, ні в чат, ні в закомічені файли.

## Перша збірка індексів

З піднятою базою Qdrant індекси не збираються: вектори беруться із сервера. Без бази перший запуск будь-якої
точки входу з векторним пошуком вантажить модель ембедингів `intfloat/multilingual-e5-small` з Hugging Face
(близько 470 МБ, один раз) і рахує вектори фрагментів на процесорі — для набору `suite` це хвилини; далі
вектори лежать у `practice/index/`. Модель ембедингів у будь-якому разі піднімається при першому запитному
ембедингу, і `graph`, `system` та `compare` роблять це до секундомірів (`team.warm_search`).

## Точки входу і що скільки коштує

Позначка `$0` означає, що прогін не звертається до моделей Anthropic і грошей не коштує. Оцінки в доларах —
для дешевої моделі каскаду з прапорцем `--fast`; без нього спеціалісти, субагент і критик ідуть на
`claude-sonnet-4-6`, і прогін коштує в 5–10 разів більше.

### Перша картка — перенос на LangGraph (`practice/base/`)

```
.venv/bin/python -m practice.base.smoke                 # 52 перевірки переносу, $0
.venv/bin/python -m practice.base.graph --show          # вузли і ребра графа, $0
.venv/bin/python -m practice.base.graph --list          # п'ять зафіксованих запитів, $0
.venv/bin/python -m practice.base.graph --fast attrs    # один запит через граф, ~$0.01–0.05
.venv/bin/python -m practice.base.graph --fast "…"      # довільне питання через граф
MAX_TURNS=1 .venv/bin/python -m practice.base.graph --fast --pause flat   # пауза перед передачею і продовження, ~$0.02
.venv/bin/python -m practice.base.graph --fast --alt "…"      # плюс три альтернативні спроби, ~$0.1–0.2
.venv/bin/python -m practice.base.graph --confirm       # підтвердити запит із черги, $0
.venv/bin/python -m practice.base.chat --fast           # бесіда з графом з клавіатури, ~$0.02–0.05 за репліку
.venv/bin/python -m practice.base.chat --fast "…"       # перша репліка з рядка, далі з клавіатури
.venv/bin/python -m practice.base.chat --fast --pause   # пауза перед передачею всередині репліки
.venv/bin/python -m practice.base.chat --fast --no-memory   # без пам'яті: лише історія
                                                        # у бесіді: /alt — три альтернативні спроби, /exit — вихід
.venv/bin/python -m practice.base.system --fast attrs   # той самий запит через ручний стек
.venv/bin/python -m practice.base.compare --loc         # рядки коду обох стеків, $0
.venv/bin/python -m practice.base.compare --fast        # три запити × два стеки, ~$0.15
.venv/bin/python -m practice.base.compare --fast --all  # п'ять запитів × два стеки, ~$0.30
```

Прапорці `--lexical`, `--rewrite`, `--live` у `graph`, `chat` і `system` однакові. Гілки альтернативних
спроб граф запускає сам, коли відповідь не пройшла `decide()`, — без прапорця; `--alt` і `/alt` вмикають
їх і для відповіді, яка пройшла. Записи прогонів: граф пише в `out/graph_results.json` (з `--alt` — під
ключем `graph[-fast]-alt:…`), ручний стек — в `out/system_results.json`, порівняння — у новий файл
`out/compare-<дата>.json` щоразу, бесіда — в `out/chat-<дата>.json`.

### Друга картка — чат і пам'ять (`practice/context/`), перенесено з модуля 4 без змін

```
.venv/bin/python -m practice.context.dialog --list          # сценарії розмов, $0
.venv/bin/python -m practice.context.dialog --chat "Що таке Proxy?"   # жива бесіда, ~$0.01–0.05 за репліку
.venv/bin/python -m practice.context.memory --info          # що лежить у довгій пам'яті, $0
.venv/bin/python -m practice.context.window                 # з чого складається вікно контексту, $0
.venv/bin/python -m practice.context.cleanup --status       # слід бесід, який можна прибрати, $0
```

Цей чат працює на ручному стеку з одним агентом поверх тих самих `team.py` і `common/`, що й граф, і міряє
стратегії історії та кеш. Бесіда через сам граф — `practice.base.chat` вище; вона бере з `context/` лише
`memory.py` — README, розділи «Друга картка» і «Бесіда з графом».

### Курсові файли модуля

`run.py 3`, `run_langgraph.py --pause`, `run_create_agent.py`, `run_agent_sdk.py`, `run_adk.py` — курсовий
поштовий агент на п'яти стеках, усі платні, описані в README курсу в корені `module3/`. До практики вони не
належать, але це ті зразки, з яких взято прийоми переносу.

## Змінні оточення

Усі читаються з `module3/.env` (`practice/__init__.py` підтягує його і для безкоштовних прогонів):

- `ANTHROPIC_API_KEY` — ключ; `ANTHROPIC_MODEL` — дорога модель (`claude-sonnet-4-6`); дешева задана в
  `config.py` (`claude-haiku-4-5-20251001`).
- `MAX_TURNS`, `MAX_TOKENS` — ліміт кроків і довжина відповіді; ті самі для обох стеків.
- `PRACTICE_DOCS` — `core` | `full` | `suite`; `PRACTICE_RETRIEVER` — `auto` | `vector` | `qdrant` | `lexical`;
  `PRACTICE_REWRITE=1` — переписування бідного запиту; `PRACTICE_DROP_TOOLS` — прибрані інструменти.
- `QDRANT_URL`, `QDRANT_CONTAINER`, `QDRANT_VOLUME`, `QDRANT_IMAGE`, `QDRANT_AUTO_INGEST` — див. `STORAGE.md`.

## Правила розробки

- Курсові файли (`core/`, `domain/`, `config.py`, `modules/`, `run_*.py`) не змінюються. `CAPABILITIES` не
  розширюється — практика до поштового бекенду взагалі не звертається.
- `base/team.py`, `base/critic.py`, `base/system.py`, `base/single.py`, `base/queries.py`, `common/`,
  `challenges/` і `context/` — копії з практики модуля 4 станом на 26 серпня 2026. Порівняння стеків має
  сенс, лише поки промпти й інструменти в обох стеках однакові, тому правити ці файли тут — значить свідомо
  розводити модулі; якщо таке рішення ухвалене, воно записується в README обох.
- Усе, що стосується LangGraph, живе в `base/graph.py`; те, що міряє, — у `base/compare.py`; безкоштовні
  перевірки — у `base/smoke.py`, і вони мають лишатися зеленими після кожної правки.
- Платні прогони — на дешевій моделі з `--fast`, і запускає їх власник; записи прогонів у `out/` не
  видаляються і не перезаписуються: `compare` щоразу пише новий файл, `graph` і `system` дописують під
  своїм ключем.
