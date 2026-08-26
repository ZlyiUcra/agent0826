# Практика модуля 2 — агент над власними документами

Домашнє завдання курсу. Живе всередині `module2/`, але курсовим матеріалом **не є**: жоден курсовий файл
тут не змінено. Практика перевикористовує ядро (`core/agent.py`, `core/cost.py`) і додає власні документи,
два різні пошуки по них і один інструмент, яким агент цим пошуком користується.

Статус чекбоксів картки — у `CHECKLIST.md`. Тут — як воно влаштоване і що показали прогони.

> **Набір документів.** Усі числа в цьому файлі стосуються набору `core` — вісімнадцяти розділів навколо
> `sec-object-type`. У `.env` типовим набором стоїть `full` (уся специфікація, 38 розділів, 2436
> фрагментів), тому щоб відтворити записане тут, запускайте з `PRACTICE_DOCS=core`. Про самі набори —
> `STORAGE.md`.

## Швидкий старт

Три команди, з теки `module2/`, інтерпретатором із `module2/.venv`:

```bash
.venv/bin/python -m practice.base.compare      # де лексика промахується, а ембединги влучають, $0
.venv/bin/python -m practice.base.threshold    # звідки взялася нижня межа відмови, $0
.venv/bin/python -m practice.base.ask          # агент над документами, сценарій replace, ~$0.03
```

Повний перелік команд із цінами — нижче, розділ «Запуск». За чим дивитись у виводі кожної — там-таки,
підрозділ «Що друкує кожна команда».

## Від задуму до результату, коротко

Задум був узяти документи, на яких пошук по словах не має шансів. Специфікація ECMAScript підходить
ідеально: вона описує звичні речі мовою, якою про них ніхто не говорить — «підмінний об'єкт» там зветься
Proxy, а читання властивості описане через внутрішній метод `[[Get]]`.

Вісімнадцять розділів навколо типу Object поділено на 283 фрагменти по власній нумерації специфікації.
Поверх них два пошуки: BM25 як точка відліку і ембединги як пошук по змісту. Пошук відданий агентові
інструментом, щоб він сам вирішував, коли і що шукати.

Далі задум був простий: підібрати межу схожості, нижче якої агент мовчить. Вимір його зруйнував — питання
з відповіддю в документах і питання без неї дали однакові оцінки, бо схожість міряє тему, а тема в них спільна.
Довелося визнати межу лише відсічкою для чужої теми, а відмову покласти на модель, яка читає сам текст
фрагментів.

Найцінніше вийшло з невдач. Дрібніші шматки погіршили пошук, бо рвуть алгоритм посеред кроків. А
через переписування запиту агент ледь не почав відповідати там, де мусить відмовлятися: допоміжна модель
відмовлялася переписувати стороннє питання, і її відмова зі словом «JavaScript» ішла в пошук як запит.

## Задача і чому саме ця специфікація

Картка вимагає десять-двадцять **справжніх** документів: робочі інструкції, умови банку, документація
бібліотеки — що завгодно, аби не вигадане. Далі з цих документів має вийти дві речі. Перша: пошук
знаходить те, що питають іншими словами. Друга, і головна: на питання, якого в документах немає, агент
каже «не знаю», а не викручується.

Домен — специфікація мови ECMAScript, https://tc39.es/ecma262/, вісімнадцять розділів навколо
`sec-object-type`. Вибір не випадковий, і він робить завдання складнішим, ніж воно виглядає.

У цієї специфікації є дві особливості, і обидві важать для завдання.

Перша — вона описує звичні речі мовою, якою про них ніхто не говорить. Те, що програміст називає
«підмінний об'єкт», у ній зветься Proxy і описується через внутрішні методи `[[Get]]` і `[[Set]]`.
Те, що людина називає «заморозити об'єкт», лежить у розділі `Object.freeze` серед кроків на кшталт
«Let keys be ? O.[[OwnPropertyKeys]]()». Розрив між словами питання і словами документа тут максимальний,
і саме на цьому розриві видно різницю між пошуком по словах і пошуком по змісту.

Друга — усі вісімнадцять документів про одне: про об'єкти в JavaScript. Цю однорідність я брав за
дрібницю, а вона вирішила більше, ніж розрив у словах. Розрив дав добре порівняння двох пошуків і
тільки. Однорідність зруйнувала задум із межею схожості: коли всі документи про одну тему, оцінка
схожості міряє тему, а не наявність відповіді, і питання з відповіддю в документах не відрізнити від
питання без неї. Числа — у розділі «Нижня межа відмови і те, чого вона не закриває».

Що взято: тип Object і його внутрішні методи, інваріанти цих методів, звичайні об'єкти, сім видів
екзотичних об'єктів (зв'язані функції, масиви, рядки, `arguments`, типізовані масиви, простори імен
модулів, незмінні прототипи), Proxy, і об'єктні обгортки Object, Boolean, Symbol, Number, String.
Разом 253 406 байтів, від 1570 до 52 257 символів у документі.

Запити до агента англійські, бо документи англійські. Питати українською можна — модель ембедингів
багатомовна, — але тоді до різниці «слова проти змісту» додається ще й різниця мов, і незрозуміло, що
саме показує прогін.

## Розкладка файлів

```
practice/
  docs/            вісімнадцять .txt і index.json — вхідні дані, не код
  index/           кеш векторів; створюється сам, у git не потрапляє
  out/             practice_results.json — записи прогонів агента
  common/
    corpus.py      читання документів і поділ на фрагменти
    lexical.py     BM25 — точка відліку
    vectors.py     ембединги, кеш, нижня межа схожості
    tools.py       search_docs, реєстрація в курсовому IMPL, промпт
    rewrite.py     переписування запиту, коли знайшлося мало
  base/
    compare.py     BM25 проти ембедингів, $0
    threshold.py   вимір нижньої межі відмови, $0
    ask.py         агент, п'ять сценаріїв
  challenges/
    a_chunking.py     розмір шматка на одному довгому документі, $0
    qdrant_store.py   ті самі вектори, але в сервері Qdrant, $0 (потрібен Docker)
    spec_download.py  вивантаження всієї специфікації у docs-full/, $0
  docs-full/          уся специфікація, 38 розділів; вмикається PRACTICE_DOCS=full
```

Сховище фрагментів — база в Docker чи документи на диску — описане в `STORAGE.md`, і цей файл однаковий
у всіх модулях, де практика шукає по документах.

Точки входу — тільки в `base/`. `common/` ніхто не запускає, його імпортують.

## Як влаштовані ключові рішення

### Документів вісімнадцять, а індексуються фрагменти

Розділи специфікації різні за розміром у тридцять три рази: найменший (10.4.7, незмінний прототип) —
1570 символів, найбільший (22.1, String Objects) — 52 257. Якби одиницею пошуку був цілий документ, то на
питання про `String.prototype.replace` пошук повернув би весь розділ 22.1: п'ятдесят кілобайтів, з яких
потрібні дві сотні символів. У промпт таке не влізе, а якби й влізло — модель шукала б відповідь у стосі
стороннього тексту.

Межу фрагмента задає сама специфікація: «22.1.3.19 String.prototype.replace ( searchValue , replaceValue )»
стоїть окремим рядком перед своїм текстом. Різати за кількістю символів наосліп не треба — підзаголовок уже
позначає, де закінчується одна тема.

Межу розміру задає не смак, а вікно моделі ембедингів. `e5-small` читає 512 токенів і мовчки відрізає все
далі. При межі 1800 символів п'ятнадцять фрагментів із 284 вилазили за вікно, найдовший на 616 токенів, і
їхні хвости в індекс не потрапляли зовсім. Межа опущена до 1400. Жорсткою вона лишилася не всюди: абзац,
який сам довший за неї — а в специфікації це довгий алгоритм суцільним списком кроків, — не ріжеться, бо
розрив посередині кроку гірший за перевищення межі. Звідси найдовший фрагмент у 1543 символи.

Ще одне різання зробили самі документи. Розділ 6.1.7 The Object Type містить підрозділи 6.1.7.1–6.1.7.4, а вони
вивантажені ще й окремими документами — тобто три файли з вісімнадцяти повторюють шматки першого слово в
слово. Без злиття пошук повертав обидві копії, і в перші два рядки двічі потрапляв той самий текст. Однакові
тексти тепер зливаються в один фрагмент; п'ятнадцять повторів прибрано. Документів від цього не меншає:
як було вісімнадцять, так і лишається.

Разом: 283 унікальні фрагменти, від 200 до 1543 символів, у середньому 746.

### Два пошуки, і чому точка відліку саме BM25

Показати, що вектори виграють у пошуку, який рахує голі перетини слів, легко й нічого не доводить. Тому
точкою відліку тут є BM25, той самий алгоритм, що стоїть за замовчуванням у Postgres, Elasticsearch і Lucene.
Він рахує три речі: скільки разів слово запиту трапилось у фрагменті, але з насиченням; наскільки слово
рідкісне в усіх документах — «prototype» є всюди й важить мало, «lastIndexOf» є в одному місці й важить
багато; і наскільки фрагмент довгий, бо в довгому більше шансів зачепити слово випадково.

Пошук по змісту — `intfloat/multilingual-e5-small`, 118 мільйонів параметрів, локально на процесорі.
Ключів не потребує, ваги (471 МБ) вантажаться з Hugging Face один раз.

Ця модель обрана заради однаковості з курсом: курсовий `knowledge_vec.py` бере саме її. Плата за це
виміряна і названа в розділі «Що ще пробував».

### Пошук як інструмент, а не як домішка до промпта

Курсовий `modules/m02_rag.py` кладе знайдене в системний промпт до початку роботи агента — правила
потрапляють у промпт завжди, потрібні вони чи ні. Тут пошук відданий агентові інструментом `search_docs`, і він сам
вирішує, що і скільки разів шукати.

Різниця видно на прогоні `proxy` нижче: питання складене з двох частин, і агент зробив чотири пошуки
поспіль, щоразу міняючи формулювання. Одна домішка в промпт дала б суміш із двох тем.

Реєстрація інструмента потребувала обхідного маневру, і його варто розуміти. `core/agent.py` імпортує
`dispatch` з `domain/backend.py`, а той шукає реалізацію лише у своєму словнику `IMPL`. Передати власні
СХЕМИ можна параметром `run_agent(tools=...)`, власні РЕАЛІЗАЦІЇ — ні. Тому `register()` дописує
`search_docs` в `IMPL`, а перед тим перевіряє, що такого імені там ще немає: `dict.update` мовчки підмінив
би курсову функцію, і курс поламався б непомітно. Виклик живе в точці входу практики, а не в імпорті, тож
курсові `run.py` і `demo.py` — окремі процеси, які практику не імпортують, — його ніколи не виконують.
`CAPABILITIES` і `tools_for()` не змінюються.

### Нижня межа відмови і те, чого вона не закриває

Задум був звичайний: виміряти косинуси для питань, відповідь на які в документах є, і для питань, яких документи
не покривають, і поставити поріг у проміжок між ними. Нижче порога пошук нічого не віддає, агент не має з чого
вигадувати.

Проміжку немає. Вимір (`python -m practice.base.threshold`, вивід нижче) дає 0.831–0.883 для восьми питань
з відповіддю і 0.732–0.845 для шести питань без. Набори перекриваються.

Причина не в моделі й не в порозі. Питання «How does async iteration over a stream work?» (0.845) і «What
is the difference between let and var?» (0.818) — це питання про JavaScript, а всі документи про JavaScript.
Схожість міряє тему, а не наявність відповіді. Окремо додає шуму розділ 6.1.7.4 Well-Known Intrinsic
Objects: це суцільна таблиця імен від `%Array%` до `%WeakSet%`, і вона виявилася найкращим збігом одразу
для трьох сторонніх питань — про асинхронну ітерацію, про npm і про борщ.

Тому 0.80 — це нижня межа, а не роздільна риса: вона відсікає чуже, але не відділяє знайдене від
незнайденого. Закриває вона рівно один випадок: запит, у якого з нашими документами немає спільної теми. «What is
the capital of France?» (0.732) і «What is the recipe for borscht?» (0.768) крізь неї не проходять, і на
них інструмент повертає порожньо.

Другий випадок — питання про JavaScript, відповіді на яке в цих вісімнадцяти розділах немає — нижня межа
пропускає. Інструмент поверне три фрагменти, і жоден із них питання не закриє. Відмовити тут може тільки
модель, бо тільки вона читає сам текст, а не оцінку схожості. Саме це наказує промпт: відповідати виключно
з того, що повернув пошук. Що з цього виходить на практиці — прогін `known` нижче.

## Запуск

### Де стояти і яким Python

Усі команди виконуються з теки `module2/`, не з кореня репозиторію. Це не примха: `config.py`, `core/` і
`domain/` лежать саме там, і Python шукає їх від поточної теки. З кореня не запуститься нічого.

```bash
cd module2
```

У модуля своє віртуальне середовище, `module2/.venv`, і саме в ньому стоять torch, sentence-transformers
і клієнт Anthropic. Кореневе середовище їх не має. Тому всюди нижче `python` означає `.venv/bin/python`;
просто `python` дасть `ModuleNotFoundError: No module named 'torch'`.

І ще одне: запускати треба через `-m`, тобто `python -m practice.base.ask`, а не
`python practice/base/ask.py`. Це модуль усередині пакета, і як окремий файл він не бачить своїх сусідів.

### Перший запуск — найдовший

```bash
python -m practice.base.compare
```

Уперше він завантажить ваги моделі ембедингів — 471 МБ з Hugging Face — і порахує вектори для всіх 283
фрагментів, приблизно дві хвилини на процесорі. Далі вектори лягають у `practice/index/`, і всі
наступні запуски беруть їх звідти за секунду. Мережа потрібна рівно один раз, для цього завантаження.

У виводі шість запитів, під кожним два блоки — що знайшов BM25 і що знайшли ембединги, плюс місце
правильного розділу в кожного. Останній запит, про столицю Франції, стоїть там навмисно: BM25 на нього
щось повертає, ембединги мовчать.

### Лабораторна: ті самі вектори в Qdrant

Додаткова картка з презентації, не основне завдання. Сервер піднімається в Docker, фрагменти заливаються
в нього за секунди, а агент про підміну сховища не дізнається — він отримує побайтово той самий
`tool_result`. Чекбокси, докази і всі команди — у `LAB1-QDRANT.md`; коротко:

```bash
docker compose up -d                                # підняти базу (з кореня репозиторію)
python -m practice.challenges.qdrant_store          # залити фрагменти, $0, питає згоди
python -m practice.challenges.qdrant_store --check  # звірити видачу з матрицею, $0
```

Правило вибору сховища, поведінка зі згодою і опис колекцій — у `STORAGE.md`.

### Решта безкоштовного

```bash
python -m practice.base.compare --full         # те саме з текстом знайдених фрагментів
python -m practice.base.threshold              # чому поріг не розділяє «є» і «немає»
python -m practice.challenges.a_chunking       # чому дрібні шматки шкодять
python -m practice.base.ask --list             # перелік сценаріїв
```

Дослід з межами рахує чотири окремі індекси і триває близько п'яти хвилин. Кеш йому не допомагає:
індекси там тимчасові й на диск не лягають.

Жодна з цих команд до Anthropic не звертається. Локальна модель ембедингів грошей не коштує взагалі —
вона працює на процесорі машини.

### Платне: агент

Потрібен ключ у `module2/.env`. Модель — `claude-sonnet-4-6`, $3 за мільйон вхідних токенів і $15 за
мільйон вихідних. Переписування запиту, якщо його ввімкнути, іде на `claude-haiku-4-5` за $1 і $5.

Ціни нижче — з реальних прогонів 25 серпня, усі п'ять за один захід:

```bash
python -m practice.base.ask            # replace — $0.0253
python -m practice.base.ask proxy      #           $0.0517
python -m practice.base.ask absent     #           $0.0041
python -m practice.base.ask known      #           $0.0412
python -m practice.base.ask thin       #           $0.0225
```

Разом ці п'ять — приблизно $0.145.

Числа не повторюються від прогону до прогону, і різниця буває в півтора-два рази. Причина в тому, що
агент сам вирішує, скільки разів шукати, і рішення це щоразу інше. Той самий `proxy` при попередньому
вимірі зробив шість пошуків і коштував $0.0816, тепер зробив чотири і коштував $0.0517. `known` пішов у
зворотний бік: було два пошуки і $0.0233, стало три і $0.0412. Тому ці ціни — порядок величини, а не
константа.

Чому `proxy` найдорожчий. Питання там складене з двох частин, агент шукає по кожній окремо, і кожен
наступний виклик до моделі несе в собі всі попередні знахідки. Вхідних токенів набігло 10 096 проти
4 322 у сценарії `replace`. Це нормальна поведінка агентного циклу, і саме тому в `config.py` стоїть
`MAX_TURNS=6` — межа, за яку він не вийде.

Найдешевший — `absent`, чотири десятих цента: агент не зробив жодного пошуку, побачив, що питання про
географію, і відмовився одразу.

### Перемикачі

```bash
python -m practice.base.ask known --rewrite    # $0.0353
python -m practice.base.ask absent --rewrite   # $0.0038
python -m practice.base.ask known --lexical    # той самий агент на BM25
PRACTICE_EMBED_MODEL=bge python -m practice.base.compare
```

`--rewrite` вмикає переписування запиту через Haiku. Сам механізм додає три виклики Haiku і два зайві
пошуки, і це копійки: Haiku коштує втричі дешевше за Sonnet, а пошук не коштує нічого. У вимірі 25 серпня
`known --rewrite` вийшов навіть дешевшим за `known` без нього — $0.0353 проти $0.0412, — бо агент того разу
дійшов до відповіді за три кроки замість чотирьох. Ціну прогону вирішує кількість кроків Sonnet, а не
переписування.

`--lexical` пускає того самого агента не на ембедингах, а на BM25 — видно, як міняється відповідь від
самої лише заміни пошуку.

`PRACTICE_EMBED_MODEL=bge` перемикає модель ембедингів на англійську. Перший запуск з нею завантажить ще
130 МБ ваг і порахує окремий індекс, дві хвилини. Кеш у кожної моделі свій, тож назад повернення миттєве.

### Метрики Ragas: три конфігурації і два сховища

Тут міряє не практика, а курсовий `ragas_compare.py`, і міряє він не наші документи специфікації, а курсову
базу правил поштового оператора з `domain/knowledge.py`. Метрик три: `faithfulness` — чи відповідь спирається
на видані правила, `answer_relevancy` — чи вона відповідає на питання, `context_recall` — чи пошук узагалі
дістав потрібне правило. Остання і є головною, коли порівнюють між собою пошуки.

```bash
python ragas_compare.py                       # три конфігурації: lexical, vector, agentic-vector
python ragas_compare.py lexical vector        # лише дві з трьох
```

Попередження: на цьому середовищі обидві команди друкують `nan` замість чисел. Причина не в них — вона
описана нижче, абзац «Пастка середовища», разом із тим, чому курсовий файл ми не правимо.

У виводі спочатку блок на конфігурацію з переліком питань, далі таблиця «конфігурація · faithful. ·
relevancy · ctx_recall» із середнім по кожній, а під нею `context_recall` по кожному з шести питань — саме
там видно, на яких перефразах лексика програє векторам.

Скільки це коштує, тут не записано, бо прогону ще не було: шість питань на три конфігурації, кожне з
відповіддю агента і трьома оцінками судді.

Ті самі метрики, але порівнюються не пошуки, а сховища — наш `ragas_modes`. Конфігурація одна, `vector`,
і проганяється двічі: спершу з правилами в пам'яті процесу, потім з тими самими правилами із сервера
Qdrant. Правила туди кладе `kb_qdrant` — це наш відповідник курсового `knowledge_qdrant.py`, якого в
матеріалах немає:

```bash
python -m practice.challenges.kb_qdrant           # залити курсові правила в сервер, $0
python -m practice.challenges.kb_qdrant --info    # що зараз у колекції kb-e5, $0
python -m practice.challenges.kb_qdrant --check   # звірити видачу з режимом у пам'яті, $0
python -m practice.challenges.ragas_modes         # обидва режими підряд, платно
python -m practice.challenges.ragas_modes memory  # лише один режим, платно
```

Наприкінці `ragas_modes` друкує таблицю «режим сховища» на два рядки і `context_recall` по питаннях у два
стовпчики — «пам'ять» і «Qdrant», — а під ними вердикт: збіглося чи розійшлося.

**Пастка середовища, через яку вимір друкував `nan`.** Пакет `ragas` під час імпорту викликає
`nest_asyncio.apply()`, а той підмінює `asyncio.Task` реалізацією мовою Python. Ця реалізація записує
поточну задачу у власний облік, а `asyncio.current_task()` у Python 3.14 — реалізація мовою C і читає облік
C: усередині задачі вона знаходить порожньо і повертає `None`. Далі `asyncio.timeout`, яким `ragas` обгортає
кожне звернення до судді, відмовляється стартувати з `RuntimeError: Timeout should be used inside a task`,
виконавець ловить виняток, друкує `Exception raised in Job[...]` і ставить замість оцінки `nan`. Так падають
усі вісімнадцять завдань прогону, і таблиця виходить порожньою.

Лікування — одне присвоєння: хай `current_task` читає той самий облік, у який пише підмінена задача.
`ragas_modes` накладає цю латку сам і друкує про це рядок; побачивши в таблиці `nan`, він більше не робить
вигляд, що це результат, а каже, що прогін зірвався. Перевірено безкоштовно, окремою пробою: три завдання
виконавця `ragas` з тим самим `asyncio.wait_for`, яким користуються метрики, дають `[nan, nan, nan]` без
латки і `[2, 4, 6]` з нею. Дослівні обидва прогони — у `LAB1-QDRANT.md`, четвертий чекбокс.

Курсовий `ragas_compare.py` латки не має, і змінювати його ми не будемо: дефект живе не в ньому, а в парі
`nest_asyncio` плюс Python 3.14. Поки цей файл запускають напряму, його таблиця на цьому середовищі
лишатиметься порожньою.

### Що друкує кожна команда

- `practice.base.compare` — по блоку на кожен із шести запитів: рядок `очікуємо:` з правильним розділом,
  під ним `BM25` і `ембединги`, у кожного рядок «правильний розділ на місці: N з M» і два найкращі
  фрагменти з оцінкою. Наприкінці — на скількох запитах правильний розділ стоїть вище в ембедингів, і
  окремий рядок про запит, відповіді на який у документах немає.
- `practice.base.threshold` — два стовпчики косинусів: питання з відповіддю в документах і питання без неї.
  Далі `найгірше «є»`, `найкраще «немає»`, `проміжок:` — і висновок, що проміжку немає, тобто самим числом
  ці два набори не розділити.
- `practice.base.ask <сценарій>` — шапка зі сценарієм і моделлю, далі `запит:`, `документи:`, `пошук:` з
  видом пошуку, по рядку на кожен пошук агента з кількістю знайденого (або `пошуки: жодного`), `outcome:`
  з кількістю кроків, `вартість:` з викликами і токенами, `відповідь:` і `збережено:`. З `--rewrite`
  додається рядок `переписано:` зі старим і новим формулюванням та вердиктом, чи взяли другий набір.
- `practice.challenges.a_chunking` — по рядку на межу розміру («межа 400: рахую 134 фрагментів»), потім
  таблиця: рядок на запит, стовпчик на межу, у клітинках місце правильного підрозділу, а внизу рядок
  `середнє`. Менше число — краще.
- `practice.challenges.qdrant_store --check` — по рядку на запит зі словом `ok` або `FAIL`, під ним
  «порядок той самий» чи «РІЗНИЙ» і найбільша розбіжність косинуса, далі найкращі фрагменти парами
  «матриця .npy / сервер». Наприкінці — чи всі запити дали однакову видачу, чи скільки розійшлося.
- `practice.challenges.kb_qdrant --check` — те саме для курсових правил: пари «пам'ять / сервер» під
  кожним із демонстраційних запитів `knowledge_vec`.
- `practice.challenges.spec_download --list` — перелік розділів усієї специфікації, без завантаження, $0.

### Що куди пишеться

Кожен прогін агента дописує запис у `practice/out/practice_results.json` під ключем виду
`known:vector:rewrite`. Повторний прогін тієї самої пари замінює свій попередній запис, чужих не чіпає.
Теки `out/` і `index/` у git не потрапляють.

### Повний перезнім усіх доказів

П'ять базових сценаріїв плюс два з `--rewrite` — приблизно $0.19. Усе інше безкоштовне, але забере
близько десяти хвилин процесорного часу.

## Реальні прогони

Чотири сценарії, один прогін кожного, модель `claude-sonnet-4-6`, `MAX_TURNS=6`. Разом $0.1223. Вивід
нижче — дослівний, разом із форматуванням Markdown, яке модель вставила у відповідь попри вказівку в
промпті писати простим текстом.

### Сценарій replace — людське формулювання замість назви методу

```
── Практика М2 · сценарій: replace · модель claude-sonnet-4-6 · MAX_TURNS=6 · переписування вимкнено ──
  документи:    18 розділів специфікації, 283 фрагментів
  запит:        «How do I replace part of a text with something else, and what happens to the rest of the string?»
  пошук:        vector
  outcome:      ok  ·  кроків: 2  ·  157.26 с
  пошук:        «replacing a substring inside a string» → 3: 18-string-objects#22.1.3.20/2, 18-string-objects#22.1.3.19, 18-string-objects#22.1.3.19.1/1
  пошук:        «String replace method» → 3: 18-string-objects#22.1.3.20/2, 18-string-objects#22.1.3.19, 18-string-objects#22.1.3.19.1/1
  відповідь:
    Here is a thorough explanation of how string replacement works, based directly on the specification.
    
    **The two replacement methods**
    
    There are two methods available: `String.prototype.replace` and `String.prototype.replaceAll`. Both take a search value and a replace value.
    
    **How `String.prototype.replace` works** [18-string-objects#22.1.3.19]
    
    1. The method first coerces the `this` value to a String.
    2. If the `searchValue` is an object that has a `Symbol.replace` method (like a regular expression), that method is called instead, delegating the work to it.
    3. Otherwise, both `searchValue` and (if it is not a function) `replaceValue` are coerced to Strings.
    4. The method finds the first position of the search string inside the original string using `StringIndexOf`, starting from position 0.
    5. If the search string is not found, the original string is returned unchanged.
    6. If it is found, the string is split into two parts around the match:
       - "preceding": the substring from the start up to (but not including) the match position.
       - "following": the substring starting right after the end of the match.
    7. The replacement value is then computed. If `replaceValue` is a function, it is called with the matched string, the match position, and the full original string, and its return value (coerced to a String) is used as the replacement. If it is a plain string, the `GetSubstitution` operation is used to process any special substitution patterns in it.
    8. The final result returned is the string-concatenation of: **preceding + replacement + following**.
    
    So the rest of the string — both before and after the match — is preserved exactly as it was, and only the matched portion is replaced.
    
    **How `String.prototype.replaceAll` works** [18-string-objects#22.1.3.20/2]
    
    `replaceAll` follows the same logic but iterates over every match position in the string, not just the first. For each match it collects the text between the end of the last match and the start of the current one (the "preserved" segment), computes the replacement, and concatenates them together. After the last match, if there is any remaining text after it, that trailing portion is also appended to the result. This ensures that all text outside the matched portions is kept intact.
    
    **Special substitution patterns** [18-string-objects#22.1.3.19.1/1]
    
    When the `replaceValue` is a plain string, `GetSubstitution` processes it for special dollar-sign patterns. For example, `$$` is replaced by a literal `$`, `$&` is replaced by the matched substring itself, and `` $` `` is replaced by the portion of the original string that precedes the match. This allows you to reference parts of the original string within your replacement string.
    
    In summary: only the matched portion is substituted. Everything before the first match and everything after it (or between matches in `replaceAll`) is passed through to the result unchanged.
  вартість:     $0.0253  (2 викликів, 4322 in / 819 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

### Сценарій proxy — складене питання, чотири пошуки

Питання з двох частин: що заважає Proxy збрехати і як саме читається властивість крізь нього.
Агент розклав його на чотири пошуки, щоразу міняючи формулювання, і зібрав відповідь із того, що
повернулося. Це найдорожчий прогін набору — $0.0517 проти двох-чотирьох центів у решти, бо кожен
наступний виклик несе в собі всі попередні знахідки.

```
── Практика М2 · сценарій: proxy · модель claude-sonnet-4-6 · MAX_TURNS=6 · переписування вимкнено ──
  документи:    18 розділів специфікації, 283 фрагментів
  запит:        «When a proxy stands in for another object, what stops it from reporting a value that contradicts the real object, and how does reading a property through it actually work?»
  пошук:        vector
  outcome:      ok  ·  кроків: 3  ·  166.16 с
  пошук:        «proxy invariant validation trap result contradicts target» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.4, 13-proxy-object-internal-methods-and-internal-slots#10.5.13, 13-proxy-object-internal-methods-and-internal-slots#10.5.14
  пошук:        «proxy get property trap handler target» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.8/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.5/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.11/1
  пошук:        «proxy [[Get]] invariants non-configurable non-writable data property accessor undefined getter» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.8/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.5/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.8/1
  пошук:        «proxy [[GetOwnProperty]] invariants non-configurable trap result reported» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.11/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.5/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.7
  відповідь:
    Here is a thorough explanation drawn directly from the specification.
    
    ---
    
    **Part 1: What stops a proxy from lying about the real object?**
    
    The specification builds an invariant-enforcement layer directly into every internal method of a Proxy exotic object. The handler's trap is called, its result is captured, and then the engine compares that result against the actual state of the target before ever returning anything to the caller. If the result contradicts the target in a forbidden way, a TypeError is thrown. This happens in several places:
    
    **[[Get]] invariants** [13-proxy-object-internal-methods-and-internal-slots#10.5.8/2]
    
    After the "get" trap returns a value (trapResult), the engine fetches the target's own property descriptor for the same key. Two contradictions are forbidden:
    
    1. If the target's own property is a non-writable, non-configurable data property, then trapResult must be the SameValue as that property's [[Value]]. If it is not, a TypeError is thrown.
    2. If the target's own property is a non-configurable accessor whose [[Getter]] is undefined, then trapResult must itself be undefined. If it is not, a TypeError is thrown.
    
    In other words, the proxy cannot invent a different value for a property that the target has permanently locked down.
    
    **[[GetOwnProperty]] invariants** [13-proxy-object-internal-methods-and-internal-slots#10.5.5/2]
    
    After the "getOwnPropertyDescriptor" trap runs, the engine applies a battery of checks against the real target descriptor. The full list of things that are forbidden:
    
    - A property cannot be reported as non-existent if it exists as a non-configurable own property of the target.
    - A property cannot be reported as non-existent if the target is non-extensible and the property exists on it.
    - A property cannot be reported as existent if it does not exist on the target and the target is non-extensible.
    - A property cannot be reported as non-configurable unless it actually is non-configurable on the target.
    - A property cannot be reported as both non-configurable and non-writable unless it actually is both on the target.
    
    **[[HasProperty]] invariants** [13-proxy-object-internal-methods-and-internal-slots#10.5.7]
    
    If the "has" trap says a property does not exist (returns false), the engine still checks the target. If the property exists on the target as a non-configurable own property, or if the property exists and the target is non-extensible, a TypeError is thrown. The proxy cannot hide a property that cannot be removed.
    
    **[[PreventExtensions]] invariant** [13-proxy-object-internal-methods-and-internal-slots#10.5.4]
    
    If the "preventExtensions" trap returns true (claiming extensions are now prevented), the engine checks whether the target is actually non-extensible. If the target is still extensible, a TypeError is thrown. The proxy cannot claim to have locked the object down when it hasn't.
    
    The common thread in all of these is the same: the specification explicitly queries the real target after the trap fires and throws a TypeError whenever the trap's answer contradicts what the target's actual state mandates.
    
    ---
    
    **Part 2: How does reading a property through a proxy actually work?**
    
    The [[Get]] internal method on a Proxy exotic object [13-proxy-object-internal-methods-and-internal-slots#10.5.8/1] follows these steps:
    
    1. First, ValidateNonRevokedProxy is called. If the proxy has been revoked (its [[ProxyTarget]] is null), a TypeError is thrown immediately [13-proxy-object-internal-methods-and-internal-slots#10.5.14].
    
    2. The target object is taken from the proxy's [[ProxyTarget]] internal slot, and the handler object is taken from [[ProxyHandler]].
    
    3. The engine calls GetMethod on the handler looking for a property named "get". This is the trap.
    
    4. If no "get" trap is found (trap is undefined), the operation falls through transparently: the engine simply calls target.[[Get]](propertyKey, receiver) directly, as if the proxy weren't there.
    
    5. If a "get" trap is found, the engine calls it as: Call(trap, handler, « target, propertyKey, receiver »). The trap receives the target object, the property key being read, and the receiver (the original object the [[Get]] was triggered on, which could be the proxy itself or something further down a prototype chain).
    
    6. Whatever the trap returns becomes trapResult.
    
    7. The engine then runs the invariant checks described above, throwing a TypeError if the result contradicts a locked-down property on the target.
    
    8. If all checks pass, trapResult is returned as the value of the property read.
    
    So the full flow is: revocation check → find handler trap → if no trap, delegate straight to target → if trap, call it with full access to the target → enforce invariants → return the result.
  вартість:     $0.0517  (3 викликів, 10096 in / 1428 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

### Сценарій absent — питання не з наших документів

Найпростіший випадок відмови: питання не має з нашими документами спільної теми взагалі. Агент не зробив
жодного пошуку — вирішив з самого формулювання.

```
── Практика М2 · сценарій: absent · модель claude-sonnet-4-6 · MAX_TURNS=6 · переписування вимкнено ──
  документи:    18 розділів специфікації, 283 фрагментів
  запит:        «What is the capital of France, and how far is it from Lviv?»
  пошук:        vector
  outcome:      ok  ·  кроків: 1  ·  2.85 с
  пошуки:       жодного — агент відповів, не звернувшись до документів
  відповідь:
    The available specification excerpts cover only ECMAScript language specification topics, such as object types, exotic objects (Array, String, Arguments, TypedArray, Proxy, bound functions, module namespaces, immutable prototypes), and wrapper objects (String, Symbol, Number, Boolean). Geography questions like the capital of France or distances between cities are completely outside the scope of what I can answer here.
    
    Please ask me something about the ECMAScript specification, and I'll be happy to help!
  вартість:     $0.0041  (1 викликів, 852 in / 106 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

### Сценарій known — питання, відповідь на яке модель знає напам'ять

Ось це і є справжня перевірка. `Array.prototype.flat` описаний у розділі 23.1 специфікації, якого
серед наших вісімнадцяти документів немає. Модель знає цей метод із власного навчання і могла
відповісти правильно й без наших документів — правильно, але без джерела, а це рівно те, що картка називає
головним багом.

Пошук її не спинив: три запити повернули дев'ять фрагментів, здебільшого з `10.4.2 Array Exotic
Objects`, бо тема спільна і межу вони подолали. Жоден на питання не відповідав, і агент це сказав,
ще й перелічив, що з масивів у документах таки є.

```
── Практика М2 · сценарій: known · модель claude-sonnet-4-6 · MAX_TURNS=6 · переписування вимкнено ──
  документи:    18 розділів специфікації, 283 фрагментів
  запит:        «How does Array.prototype.flat decide how deep to flatten a nested array?»
  пошук:        vector
  outcome:      ok  ·  кроків: 4  ·  150.67 с
  пошук:        «Array.prototype.flat depth flattening» → 3: 07-array-exotic-objects#10.4.2.2, 07-array-exotic-objects#10.4.2.1, 07-array-exotic-objects#10.4.2.4/1
  пошук:        «FlattenIntoArray depth parameter» → 3: 01-object-type#6.1.7.4/5, 07-array-exotic-objects#10.4.2.4/1, 07-array-exotic-objects#10.4.2.1
  пошук:        «Array.prototype.flat specification steps» → 3: 07-array-exotic-objects#10.4.2.2, 10-typedarray-exotic-objects#10.4.5.11, 01-object-type#6.1.7.4/3
  відповідь:
    The available excerpts do not contain the specific algorithm for `Array.prototype.flat` or the `FlattenIntoArray` abstract operation. The excerpts I have access to cover topics such as Array exotic object internal methods (like `[[DefineOwnProperty]]` and `ArraySetLength`), `ArrayCreate`, TypedArray creation, and well-known intrinsic objects, but they do not include the `Array.prototype.flat` method specification or its helper operation.
    
    Because the rules require me to answer only from what the search results return, I cannot give you a precise, citation-backed account of how `Array.prototype.flat` decides how deep to flatten. I can tell you what the available excerpts do cover:
    
    - How Array exotic objects enforce their `length` property (section 10.4.2.1).
    - How new Array objects are created via `ArrayCreate` (section 10.4.2.2).
    - How `ArraySetLength` works when changing the `length` property (section 10.4.2.4).
    - TypedArray exotic object creation.
    - The catalogue of well-known intrinsic objects.
    
    If you have a question that falls within any of those areas, I am happy to help with a proper citation.
  вартість:     $0.0412  (4 викликів, 11417 in / 461 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

## Виміри

### BM25 проти ембедингів

Прогін `python -m practice.base.compare`. Міряється не влучання в перший рядок, а **місце** правильного
розділу в повному списку з 283 фрагментів. Влучання — надто груба міра: воно однаково показує «промахнувся
на один рядок» і «правильна відповідь на сотому місці», а це різні хвороби.

Останній запит у наборі відповіді в документах не має. Він показує те, чого не видно на решті: BM25 і на нього
повертає непорожній результат з ненульовою оцінкою, тобто відрізнити «знайшов» від «не знайшов» за самою
оцінкою BM25 неможливо.

```
Будую індекси…
фрагментів: 283 · модель intfloat/multilingual-e5-small · нижня межа 0.8
векторний індекс з кеша (e5-efd486f065643910.npy)

Запит: «How do I replace part of a text with something else?»
  очікуємо:    22.1.3.19
  BM25         правильний розділ на місці: 4 з 283
                10.872  10.4.5.8 [[OwnPropertyKeys]] ( )
                        10-typedarray-exotic-objects#10.4.5.8
                10.665  10.4.3.3 [[OwnPropertyKeys]] ( )
                        08-string-exotic-objects#10.4.3.3
  ембединги    правильний розділ на місці: 2 з 283
                 0.834  22.1.3.20 String.prototype.replaceAll ( searchValue , repl
                        18-string-objects#22.1.3.20/2
              +  0.833  22.1.3.19.1 GetSubstitution ( matched , string , position 
                        18-string-objects#22.1.3.19.1/1

Запит: «What happens when a wrapper for true or false is created?»
  очікуємо:    20.3.1.1
  BM25         правильний розділ на місці: 260 з 283
                 9.476  6.1.7.2 Object Internal Methods and Internal Slots (частин
                        01-object-type#6.1.7.2/5
                 8.463  10.1.6.3 ValidateAndApplyPropertyDescriptor ( obj , proper
                        05-ordinary-object-internal-methods-and-internal-slots#10.1.6.3/1
  ембединги    правильний розділ на місці: 101 з 283
                 0.846  6.1.7.1 Property Attributes (частина 2 з 2)
                        01-object-type#6.1.7.1/2
                 0.840  10.5.6 [[DefineOwnProperty]] ( propertyKey , propertyDesc 
                        13-proxy-object-internal-methods-and-internal-slots#10.5.6/2

Запит: «Can the parent of an object be locked so it never changes?»
  очікуємо:    10.4.7
  BM25         правильний розділ на місці: 76 з 283
                10.149  10.1.7.1 OrdinaryHasProperty ( obj , propertyKey )
                        05-ordinary-object-internal-methods-and-internal-slots#10.1.7.1
                 9.692  10.1.8.1 OrdinaryGet ( obj , propertyKey , receiver )
                        05-ordinary-object-internal-methods-and-internal-slots#10.1.8.1
  ембединги    правильний розділ на місці: 55 з 283
                 0.839  10.5.9 [[Set]] ( propertyKey , value , receiver ) (частина
                        13-proxy-object-internal-methods-and-internal-slots#10.5.9/2
                 0.836  10.1 Ordinary Object Internal Methods and Internal Slots (
                        05-ordinary-object-internal-methods-and-internal-slots#10.1/1

Запит: «How does a stand-in object forward reads to the real one?»
  очікуємо:    10.5.8
  BM25         правильний розділ на місці: 171 з 283
                 8.781  6.1.7.2 Object Internal Methods and Internal Slots (частин
                        01-object-type#6.1.7.2/3
                 7.932  22.1.3.23 String.prototype.split ( separator , limit ) (ча
                        18-string-objects#22.1.3.23/3
  ембединги    правильний розділ на місці: 101 з 283
                 0.831  10.4.3.1 [[GetOwnProperty]] ( propertyKey )
                        08-string-exotic-objects#10.4.3.1
                 0.830  10.4.3.5 StringGetOwnProperty ( string , propertyKey )
                        08-string-exotic-objects#10.4.3.5

Запит: «How does a function remember the object it was attached to?»
  очікуємо:    10.4.1
  BM25         правильний розділ на місці: 10 з 283
                 8.585  6.1.7.2 Object Internal Methods and Internal Slots (частин
                        01-object-type#6.1.7.2/6
                 7.879  20.1.3.6 Object.prototype.toString ( ) (частина 2 з 2)
                        14-object-objects#20.1.3.6/2
  ембединги    правильний розділ на місці: 4 з 283
                 0.839  6.1.7.2 Object Internal Methods and Internal Slots (частин
                        01-object-type#6.1.7.2/6
                 0.835  6.1.7 The Object Type (частина 2 з 2)
                        01-object-type#6.1.7/2

Запит: «What is the capital of France?»
  очікуємо:    нічого — у наших документах відповіді немає
  BM25         правильного розділу немає — має віддати порожньо
                 6.659  22.1.3.12 String.prototype.localeCompare ( that [ , reserv
                        18-string-objects#22.1.3.12/2
                 0.780  22.1.3.25 String.prototype.substring ( start , end )
                        18-string-objects#22.1.3.25
  ембединги    правильного розділу немає — має віддати порожньо
               віддає: нічого

Правильний розділ стоїть вище в ембедингів на 5 запитах, нижче на 0, однаково на 0.
Запит без відповіді в наших документах: BM25 усе одно щось віддає, ембединги мовчать, якщо найкращий фрагмент не дотяг до межі.
```

### Нижня межа відмови

Прогін `python -m practice.base.threshold`.

```
фрагментів: 283 · поріг у коді: 0.8

Питання, відповідь на які в документах Є:
   0.834  How do I replace part of a text with something else?   18-string-objects#22.1.3.20/2
   0.846  What happens when a wrapper for true or false is cre   01-object-type#6.1.7.1/2
   0.839  Can the parent of an object be locked so it never ch   13-proxy-object-internal-methods-and-internal-slots#10.5.9/2
   0.831  How does a stand-in object forward reads to the real   08-string-exotic-objects#10.4.3.1
   0.839  How does a function remember the object it was attac   01-object-type#6.1.7.2/6
   0.855  How is the length of an array kept in step with its    07-array-exotic-objects#10.4.2.4/1
   0.859  What does freezing an object actually do to its prop   14-object-objects#20.1.2.6
   0.883  How do I turn a number into a string with a fixed nu   17-number-objects#21.1.3.5/1

Питання, яких документи НЕ покривають:
   0.732  What is the capital of France?                         18-string-objects#22.1.3.12/2
   0.814  How do I open a file and read it line by line?         18-string-objects#22.1.3.1
   0.768  What is the recipe for borscht?                        01-object-type#6.1.7.4/4
   0.845  How does async iteration over a stream work?           01-object-type#6.1.7.4/1
   0.814  How do I install a package with npm?                   01-object-type#6.1.7.4/4
   0.818  What is the difference between let and var?            18-string-objects#22.1.2.4

найгірше «є»:      0.831
найкраще «немає»:  0.845
проміжку немає: набори перекриваються, самим числом їх не розділити

нижня межа 0.8 відсікає 2 із 6 питань не з наших документів:
   0.732  What is the capital of France?
   0.768  What is the recipe for borscht?
долають межу 4 — на них відмовляє модель, не пошук:
   0.814  How do I open a file and read it line by line?
   0.845  How does async iteration over a stream work?
   0.814  How do I install a package with npm?
   0.818  What is the difference between let and var?
```

### Що ще пробував і що не спрацювало

Перш ніж записати «проміжку немає» як висновок, я перевірив чотири інші способи його дістати. Жоден не
спрацював, і кожен варто назвати — інакше висновок виглядає як здача без спроби.

Числа в цьому розділі виміряні **до** злиття дублікатів, тобто на 298 фрагментах, а не на 283.
Тому місця правильного розділу тут не збігаються з таблицею порівняння вище — там після злиття вони стали
на кілька позицій кращі. Порівнювати ці числа між собою можна лише в межах цього розділу, де всі варіанти
міряні на тих самих фрагментах. Перерахунок після злиття не робився: злиття прибрало п'ятнадцять
повторів з 298 і на висновок «жоден спосіб не розділяє набори» вплинути не могло.

**Відрив найкращого фрагмента від решти.** Замість абсолютного косинуса — наскільки найкращий фрагмент
вирізняється з-поміж усіх 283. Задум був у тому, що на сторонньому запиті всі оцінки мають лягти купно, а на
правильному одна має стирчати. Не розділяє: найбільший відрив дало «How do I install a package with npm?», більший за
будь-яке правильне питання.

**Зв'язка з BM25.** Вимога, щоб фрагмент пройшов обидва пошуки: у стороннього запиту не має бути рідкісних
слів наших документів. Не розділяє: у «How does async iteration over a stream work?» лексична оцінка 13.27, вища,
ніж у п'яти правильних питань із восьми. Додавати другий вимірник, який помиляється на тих самих запитах,
сенсу немає.

**Інша подача тексту моделі.** Гіпотеза була така: у вектор іде заголовок підрозділу разом із текстом, а
текст — це щільний алгоритм на кшталт «Let O be ? ToObject(this value)», однаковий на всю специфікацію,
тож заголовок втрачає в ньому вагу. Перевірено два варіанти проти нинішнього — з назвою документа перед заголовком
і з окремим вектором на самий заголовок, беручи більшу з двох схожостей. Місця правильного розділу
(нинішній / з назвою документа / тільки заголовок): `22.1.3.19` — 2 / 2 / 2, `20.3.1.1` — 109 / 139 / 177,
`10.4.7` — 65 / 31 / 168, `10.5.8` — 107 / 110 / 199, `10.4.1` — 6 / 6 / 5. Гіпотеза хибна: окремий вектор
на заголовок дає гірше, назва документа допомагає одному запиту з п'яти й шкодить двом.

**Інша модель.** Ось це спрацювало, і саме тому воно тут. `BAAI/bge-small-en-v1.5` того самого розміру, але
англійська. Місця правильного розділу (`e5` / `bge`): 2 / 3, 109 / 2, 65 / 20, 107 / 15, 6 / 9 — тобто три
запити з п'яти, безнадійні в `e5`, у неї робочі. На відмові вона теж краща: її нижня межа 0.68 відсікає п'ять
сторонніх питань із шести, нижня межа `e5` — два з шести.

Причина не в тому, що одна модель розумніша. Місткість у них однакова, але в `e5` вона розкладена на сотню
мов, а документи тут англійські від першого до останнього символу. Багатомовність нічого не дає й коштує
якості.

За замовчуванням лишилася `e5` — заради однаковості з курсовим `knowledge_vec.py`, який бере ту саму модель.
Це свідомий вибір з відомою ціною: на чотирьох сторонніх питаннях із шести відмовляти доводиться моделі, а
не пошуку. Перемкнутися можна змінною `PRACTICE_EMBED_MODEL=bge`, нічого не міняючи в коді.

## Розмір шматка

Необов'язковий пункт картки. Довгий документ тут один очевидний: 22.1 String Objects, 52 257 символів,
п'ята частина всього тексту. Він ріжеться на чотирьох межах, на кожній будується окремий індекс лише з нього,
і вісім запитів міряються за місцем правильного підрозділу у видачі. Прогін
`python -m practice.challenges.a_chunking`, офлайн, $0, кілька хвилин процесора.

```
документ: 22.1 String Objects · 52257 символів · модель intfloat/multilingual-e5-small
запитів: 8 · межі: 400, 700, 1400, 2500

межа 400: рахую 134 фрагментів (найдовший 933, у середньому 360)
межа 700: рахую 94 фрагментів (найдовший 933, у середньому 514)
межа 1400: рахую 57 фрагментів (найдовший 1505, у середньому 849)
межа 2500: рахую 53 фрагментів (найдовший 2445, у середньому 913)

підрозділ        400     700    1400    2500   запит
----------------------------------------------------
22.1.3.19          7       6       5       3   How do I replace part of a text with something
22.1.3.24          2       1       4       4   How do I check whether a text begins with cert
22.1.3.32         99      66      35      31   How do I remove spaces from both ends of a tex
22.1.3.9           3       2       2       1   How do I find where a piece of text appears in
22.1.3.18          1       2       1       1   How can I repeat a piece of text several times
22.1.3.30         81      59      33      29   How do I make all the letters in a text capita
22.1.3.17          1       1       1       1   How do I pad a text at the front so it reaches
22.1.3.1          27      19       6       7   How do I get a single character at a given pos

фрагментів       134      94      57      53
перший рядок       2       2       2       3
перша трійка       4       4       3       4
середнє         27.6    19.5    10.9     9.6
```

Результат протилежний до звичної поради «ріж дрібніше — буде точніше». Середнє місце падає монотонно з
27.6 до 9.6 у міру збільшення межі. На двох запитах різниця різка: «прибрати пробіли з обох кінців» —
99-те місце проти 31-го, «зробити всі літери великими» — 81-ше проти 29-го.

Причина в кількості фрагментів. Розділ 22.1 має 53 підрозділи, і межа 2500 дає рівно 53 фрагменти, по
одному на метод. Межа 400 дає 134 — кожен метод розрізаний на два-три шматки посеред власного алгоритму,
заголовок лишається в першому, кроки переїжджають у другий. Кроки `trim` в окремому фрагменті виглядають
як будь-які інші кроки специфікації: «Let S be ? ToString(O)», «Return TrimString(S, start+end)».

Порада «дрібніше — точніше» придумана для суцільної прози, де межі теми не позначені й дрібніший шматок
справді точніший. Специфікація вже пронумерована по темах, і різати її дрібніше за власну нумерацію означає
ламати наявну розмітку.

У коді лишилася межа 1400, а не переможна 2500. Причина окрема від місць у видачі: модель читає 512 токенів і
мовчки відрізає далі. При межах 400, 700 і 1400 за вікно не вилітає жоден фрагмент, найдовший на 1400 має
467 токенів. На 2500 вилітає п'ять із 53, найдовший на 682 токени — третини його тексту модель не бачить.
Перевага 2500 здобута вже з утраченими хвостами і залежить від того, які саме хвости відрізало. Найбільша
межа без втрат — 1400.

## Переписування запиту

Необов'язковий пункт картки: «якщо знайшлось мало — хай агент переформулює запит і спробує ще раз».
Механізм у `practice/common/rewrite.py`, вбудований у `search_docs`: інструмент сам помічає бідний
результат, іде до Haiku, просить назвати те саме словами специфікації, шукає вдруге і бере кращий з двох
наборів. Вмикається прапорцем `--rewrite`.

### Що вважається «мало» і звідки взялася планка

Спрацьовує будь-яка з двох умов: фрагментів, що подолали межу, менше трьох, або найкращий із них нижче за
планку впевненості.

Друга умова додана після виміру, і без неї механізм був би мертвим кодом. Нижня межа `e5` стоїть майже на
середньому косинусі по всіх фрагментах — крізь неї проходить приблизно половина фрагментів, і кількість знайденого до
трьох не спадає ніколи. Перевірено на дев'яти запитах: усі дев'ять дали п'ять фрагментів із п'яти.

Планку виміряно на восьми запитах, людські формулювання проти переписаних. У `e5` людські дали 0.831–0.883,
переписані 0.869–0.900, планку поставлено на 0.87. У `bge` — 0.671–0.773 проти 0.755–0.855, планка 0.78. Проміжки в
обох трохи перекриваються, і це не заважає: умова не стверджує, що відповідь знайдена, вона вирішує лише,
чи варто спробувати ще раз. Ціна хибного спрацювання — один виклик Haiku, бо з двох наборів однаково
береться кращий.

### Що переписування дає в самому пошуку

Виміряно на трьох запитах, поза агентом. Haiku перетворює «How do I remove spaces from both ends of a
text?» на «String.prototype.trim», і оцінка йде з 0.840 на 0.910. «How do I make all the letters in a text
capital?» стає «String.prototype.toUpperCase»: 0.836 на 0.936. Третій запит про заборону додавати поля:
0.828 на 0.884. У всіх трьох правильний розділ до переписування у першу трійку не потрапляв, а після — потрапив.

На `bge` ефект ще сильніший: там ці ж запити давали нуль фрагментів вище за межу, після переписування —
три з трьох.

### Чому порожній результат не переписується

Спершу було задумано інакше: порожньо теж рахувалося як «мало», бо здавалося, що саме там друга спроба
найпотрібніша. Вимір показав протилежне.

На запиті «What is the capital of France?» Haiku відмовився переписувати і відповів текстом «I appreciate
the test, but this question isn't about JavaScript or ECMAScript...». Цей текст пішов у пошук як запит.
Слова «JavaScript» і «ECMAScript» у ньому є, документи всі про JavaScript, і оцінка вийшла 0.843 — вище за
межу 0.80. На питанні про борщ те саме: 0.841.

Відмова допоміжної моделі перетворилася на дані. Агент отримав би три фрагменти там, де раніше не отримував
нічого, і, маючи текст на руках, узявся б відповідати. Заради необов'язкового пункту картки перестав би
виконуватися третій обов'язковий.

Перший запобіжник: переписування вмикається лише тоді, коли перший пошук щось таки знайшов. Порожньо
лишається порожнім.

Другий ловить ту саму відмову Haiku з іншого боку: переписаний запит має бути коротшим за 160 символів
і не починатися з «I», «Sorry», «This question» та подібного — багатослівна відповідь від першої особи це
не запит.

### Що вийшло в живому прогоні

`python -m practice.base.ask known --rewrite` — механізм увімкнувся тричі, двічі взяв другий набір, у
видачі опинилися інші фрагменти. Haiku переписав «Array.prototype.flat depth flattening» на «Array.
prototype.flat depth parameter and recursive flattening behavior» (перший набір лишився кращим),
«FlattenIntoArray algorithm» на «FlattenIntoArray abstract operation» і «ToIntegerOrInfinity depth
depthNum flat» на розгорнуте формулювання про той самий крок — обидва рази другий набір узяли.

`python -m practice.base.ask absent --rewrite` — жодного пошуку, відмова за 2.79 секунди, як і без
переписування.

В обох прогонах агент відмовився. У `known --rewrite` він написав: «Because my rules require me to answer
strictly from what the search tool returns, I cannot give you a specification-grounded answer here»,
і перелічив, що в документах таки є.

Попереднє вимірювання дало тут ще одну річ, якої в цьому прогоні немає: тоді агент порадив шукати в
розділі 23.1.3.13, якого в документах немає — номер узявся з пам'яті моделі. Як відповідь це подано не
було, це була порада, куди піти дивитися, але промпт просив не брати з голови нічого. Повторити це не
вдалося, тож на одному прогоні такий висновок не тримається.

### Обмеження: в агентському контурі механізм здебільшого зайвий

Сценарій `thin` задумувався як показова демонстрація, і вона не вдалася: слід прогону з переписуванням і
без нього однаковий, механізм не спрацював жодного разу.

Причина в тому, що в пошук іде не формулювання людини, а формулювання агента, а він переписує запит сам.
Людське «How do I remove spaces from both ends of a text?» дає 0.840, і планка спрацювала б. Перший же запит
агента — «remove spaces from both ends of a string» — дає 0.879, другий, «String.prototype.trim method», —
0.913. Обидва вище за планку 0.87.

Тобто механізм вмикається лише тоді, коли слабким виявився вже агентський запит: у `known` це було
«Array.prototype.flat depth flattening» з оцінкою 0.865. Все інше агент і так робить сам — у прогоні `proxy`
він переформулював шість разів поспіль без жодного механізму.

## Уся специфікація: що з якістю пошуку на обсязі у 8,6 раза більшому

Вісімнадцять розділів дають 283 фрагменти. Уся специфікація, вивантажена `challenges/spec_download.py` у
`practice/docs-full/`, — 38 розділів, 2 136 596 символів і 2436 фрагментів. Той самий прогін
`practice.base.compare` на цьому наборі показує, що змінюється з обсягом, а що ні.

Не змінюється головне: ембединги виграють у BM25 на всіх п'яти запитах, які мають відповідь, а на запиті
поза темою («What is the capital of France?») вектори мовчать — нижня межа 0.80 тримається і на 2436
фрагментах, тоді як BM25 і тут повертає найкращий збіг з ненульовою оцінкою.

Змінюється місце правильного розділу. Ось воно на однакових запитах, `core` проти `full`:

- «replace part of a text» — 2 з 283, стало 4 з 2436
- «wrapper for true or false» — 109 з 283, стало 685 з 2436
- «parent of an object locked» — 65 з 283, стало 244 з 2436
- «stand-in object forwards reads» — 107 з 283, стало 371 з 2436
- «function remembers the object» — 6 з 283, стало 12 з 2436

У частках набору місця майже не зрушили — правильний розділ як був у першому чи другому відсотку видачі,
так і лишився. Але пошук віддає агентові три фрагменти, а не відсотки: із п'яти запитів у трійку на
повному наборі потрапляють тільки два, ті самі, що й на малому. Тобто ширший набір документів сам по собі
відповідей не додає — він додає конкурентів за ті самі три місця, і саме тому в модулі 4 запит спершу
розкладають по темах, а вже потім шукають.

## Чого ця робота не робить

**Це не оцінка якості відповідей.** Ragas і подібні метрики тут не рахувалися. Що агент послався на
правильний розділ, видно з прогонів очима; числа, яке б це підтверджувало на ста питаннях, немає.

**Це не векторна база.** Індекс — матриця в пам'яті плюс файл `.npy` на диску. Для 283 фрагментів цього
досить із запасом: пошук — одне множення матриці на вектор. Chroma чи Qdrant тут не потрібні й не додали б
нічого, крім залежності.

Сказане лишається чинним і після лабораторної з Qdrant (`LAB1-QDRANT.md`). Та вправа не спростовує цей
абзац, бо доводить не потрібність бази, а відв'язаність шару пошуку від сховища: вектори переїхали в
сервер, а агент, промпт і `search_docs` не змінилися ні на рядок. Основним сховищем практики лишається
матриця в пам'яті — Qdrant вмикається окремим прапорцем і лише тоді, коли сервер піднято.

**Нижня межа не гарантує відмови.** Вище сказано, що саме вона закриває, і на чому тримається решта. Прогін
`known` показує, що модель у цьому випадку відмовилася. Один прогін — не гарантія на всіх питаннях такого
роду.

**Агент не перевіряє, чи відповів пошук на питання.** Він отримує три фрагменти й вирішує сам. Окремого
кроку, який оцінює придатність знайденого до того, як воно потрапить у відповідь, тут немає.
