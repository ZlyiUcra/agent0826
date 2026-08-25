# Практика модуля 2 — агент над власним корпусом документів

Домашнє завдання курсу. Живе всередині `module2/`, але курсовим матеріалом **не є**: жоден курсовий файл
тут не змінено. Практика перевикористовує ядро (`core/agent.py`, `core/cost.py`) і додає власний корпус
документів, два різні пошуки по ньому і один інструмент, яким агент цим пошуком користується.

Статус чекбоксів картки — у `CHECKLIST.md`. Тут — як воно влаштоване і що показали прогони.

## Задача і чому саме ця специфікація

Картка вимагає десять-двадцять **справжніх** документів: робочі інструкції, умови банку, документація
бібліотеки — що завгодно, аби не вигадане. Далі з цих документів має вийти дві речі. Перша: пошук
знаходить те, що питають іншими словами. Друга, і головна: на питання, якого в документах немає, агент
чесно каже «не знаю», а не викручується.

Домен — специфікація мови ECMAScript, https://tc39.es/ecma262/, вісімнадцять розділів навколо
`sec-object-type`. Вибір не випадковий, і він робить завдання складнішим, ніж воно виглядає.

Специфікація описує звичні речі мовою, якою про них ніхто не говорить. Те, що програміст називає
«підмінний об'єкт», у ній зветься Proxy і описується через внутрішні методи `[[Get]]` і `[[Set]]`.
Те, що людина називає «заморозити об'єкт», лежить у розділі `Object.freeze` серед кроків на кшталт
«Let keys be ? O.[[OwnPropertyKeys]]()». Розрив між словами питання і словами документа тут максимальний,
і саме на цьому розриві видно різницю між пошуком по словах і пошуком по змісту.

Друга особливість — корпус однорідний. Усі вісімнадцять документів про одне: про об'єкти в JavaScript.
Це виявилося важливішим за перше, і чому саме — у розділі «Підлога відмови і те, чого вона не закриває».

Що взято: тип Object і його внутрішні методи, інваріанти цих методів, звичайні об'єкти, сім видів
екзотичних об'єктів (зв'язані функції, масиви, рядки, `arguments`, типізовані масиви, простори імен
модулів, незмінні прототипи), Proxy, і об'єктні обгортки Object, Boolean, Symbol, Number, String.
Разом 253 406 байтів, від 1570 до 52 257 символів у документі.

Запити до агента англійські, бо корпус англійський. Питати українською можна — модель ембедингів
багатомовна, — але тоді до різниці «слова проти змісту» додається ще й різниця мов, і незрозуміло, що
саме показує прогін.

## Мапа файлів

```
practice/
  docs/            вісімнадцять .txt і index.json — вхідні дані, не код
  index/           кеш векторів; створюється сам, у git не потрапляє
  out/             practice_results.json — записи прогонів агента
  common/
    corpus.py      читання документів і поділ на фрагменти
    lexical.py     BM25 — базова лінія
    vectors.py     ембединги, кеш, нижня межа схожості
    tools.py       search_docs, реєстрація в курсовому IMPL, промпт
    rewrite.py     переписування запиту, коли знайшлося мало
  base/
    compare.py     BM25 проти ембедингів, $0
    threshold.py   вимір нижньої межі відмови, $0
    ask.py         агент, п'ять сценаріїв
  challenges/
    a_chunking.py  розмір шматка на одному довгому документі, $0
```

Точки входу — тільки в `base/`. `common/` ніхто не запускає, його імпортують.

## Як влаштовані ключові рішення

### Корпус — це вісімнадцять документів, а індексуються фрагменти

Розділи специфікації різні за розміром у тридцять три рази: найменший (10.4.7, незмінний прототип) —
1570 символів, найбільший (22.1, String Objects) — 52 257. Якби одиницею пошуку був цілий документ, то на
питання про `String.prototype.replace` пошук повернув би весь розділ 22.1: п'ятдесят кілобайтів, з яких
потрібні дві сотні символів. У промпт таке не влізе, а якби й влізло — модель шукала б відповідь у стосі
стороннього тексту.

Межу фрагмента задає сама специфікація: «22.1.3.19 String.prototype.replace ( searchValue , replaceValue )»
стоїть окремим рядком перед своїм текстом. Різати за кількістю символів наосліп не треба — підзаголовок уже
позначає, де закінчується одна тема.

Стелю розміру задає не смак, а вікно моделі ембедингів. `e5-small` читає 512 токенів і мовчки відрізає все
далі. При стелі 1800 символів п'ятнадцять фрагментів із 284 вилазили за вікно, найдовший на 616 токенів, і
їхні хвости в індекс не потрапляли зовсім. Стеля опущена до 1400. Жорсткою вона лишилася не всюди: абзац,
який сам довший за неї — а в специфікації це довгий алгоритм суцільним списком кроків, — не ріжеться, бо
розрив посередині кроку гірший за перевищення стелі. Звідси найдовший фрагмент у 1543 символи.

Ще одне різання зробив сам корпус. Розділ 6.1.7 The Object Type містить підрозділи 6.1.7.1–6.1.7.4, а вони
вивантажені ще й окремими документами — тобто три файли з вісімнадцяти повторюють шматки першого слово в
слово. Без злиття пошук чесно повертав обидві копії, і в топ-2 приїжджав двічі той самий текст. Однакові
тексти тепер зливаються в один фрагмент; п'ятнадцять повторів прибрано. Корпус від цього не меншає:
документів як було вісімнадцять, так і лишається.

Разом: 283 унікальні фрагменти, від 200 до 1543 символів, у середньому 746.

### Два пошуки, і чому базова лінія саме BM25

Показати, що вектори виграють у пошуку, який рахує голі перетини слів, легко й нічого не доводить. Тому
базова лінія тут — BM25, той самий алгоритм, що стоїть за замовчуванням у Postgres, Elasticsearch і Lucene.
Він рахує три речі: скільки разів слово запиту трапилось у фрагменті, але з насиченням; наскільки слово
рідкісне в усьому корпусі — «prototype» є всюди й важить мало, «lastIndexOf» є в одному місці й важить
багато; і наскільки фрагмент довгий, бо в довгому більше шансів зачепити слово випадково.

Пошук по змісту — `intfloat/multilingual-e5-small`, 118 мільйонів параметрів, локально на процесорі.
Ключів не потребує, ваги (471 МБ) вантажаться з Hugging Face один раз.

Ця модель обрана заради однаковості з курсом: курсовий `knowledge_vec.py` бере саме її. Плата за це
виміряна і названа в розділі «Що ще пробував».

### Пошук як інструмент, а не як домішка до промпта

Курсовий `modules/m02_rag.py` кладе знайдене в системний промпт до початку роботи агента — правила
приїжджають завжди, потрібні вони чи ні. Тут пошук відданий агентові інструментом `search_docs`, і він сам
вирішує, що і скільки разів шукати.

Різниця видно на прогоні `proxy` нижче: питання складене з двох частин, і агент зробив шість пошуків
поспіль, щоразу міняючи формулювання. Одна домішка в промпт дала б суміш із двох тем.

Реєстрація інструмента потребувала обхідного маневру, і його варто розуміти. `core/agent.py` імпортує
`dispatch` з `domain/backend.py`, а той шукає реалізацію лише у своєму словнику `IMPL`. Передати власні
СХЕМИ можна параметром `run_agent(tools=...)`, власні РЕАЛІЗАЦІЇ — ні. Тому `register()` дописує
`search_docs` в `IMPL`, а перед тим перевіряє, що такого імені там ще немає: `dict.update` мовчки підмінив
би курсову функцію, і курс поламався б непомітно. Виклик живе в точці входу практики, а не в імпорті, тож
курсові `run.py` і `demo.py` — окремі процеси, які практику не імпортують, — його ніколи не виконують.
`CAPABILITIES` і `tools_for()` не змінюються.

### Підлога відмови і те, чого вона не закриває

Задум був звичайний: виміряти косинуси для питань, відповідь на які в корпусі є, і для питань, яких корпус
не покриває, і поставити поріг у проміжок між ними. Нижче порога пошук нічого не віддає, агент не має з чого
вигадувати.

Проміжку немає. Вимір (`python -m practice.base.threshold`, вивід нижче) дає 0.831–0.883 для восьми питань
з відповіддю і 0.732–0.845 для шести питань без. Набори перекриваються.

Причина не в моделі й не в порозі. Питання «How does async iteration over a stream work?» (0.845) і «What
is the difference between let and var?» (0.818) — це питання про JavaScript, а весь корпус про JavaScript.
Схожість міряє тему, а не наявність відповіді. Окремо додає шуму розділ 6.1.7.4 Well-Known Intrinsic
Objects: це суцільна таблиця імен від `%Array%` до `%WeakSet%`, і вона виявилася найкращим збігом одразу
для трьох сторонніх питань — про асинхронну ітерацію, про npm і про борщ.

Тому 0.80 — це нижня межа, а не роздільна риса: вона відсікає чуже, але не відділяє знайдене від
незнайденого. Закриває вона рівно один випадок: запит, у якого з корпусом немає спільної теми. «What is
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

Друга особливість того самого штибу: запускати треба через `-m`, тобто `python -m practice.base.ask`, а не
`python practice/base/ask.py`. Це модуль усередині пакета, і як окремий файл він не бачить своїх сусідів.

### Перший запуск — найдовший

```bash
python -m practice.base.compare
```

Уперше він завантажить ваги моделі ембедингів — 471 МБ з Hugging Face — і порахує вектори для всіх 283
фрагментів корпусу, приблизно дві хвилини на процесорі. Далі вектори лягають у `practice/index/`, і всі
наступні запуски беруть їх звідти за секунду. Мережа потрібна рівно один раз, для цього завантаження.

У виводі шість запитів, під кожним два блоки — що знайшов BM25 і що знайшли ембединги, плюс місце
правильного розділу в кожного. Останній запит, про столицю Франції, стоїть там навмисно: BM25 на нього
щось повертає, ембединги мовчать.

### Решта безкоштовного

```bash
python -m practice.base.compare --full         # те саме з текстом знайдених фрагментів
python -m practice.base.threshold              # чому поріг не розділяє «є» і «немає»
python -m practice.challenges.a_chunking       # чому дрібні шматки шкодять
python -m practice.base.ask --list             # перелік сценаріїв
```

Дослід зі стелями рахує чотири окремі індекси і триває близько п'яти хвилин. Кеш йому не допомагає:
індекси там тимчасові й на диск не лягають.

Жодна з цих команд до Anthropic не звертається. Локальна модель ембедингів грошей не коштує взагалі —
вона крутиться на процесорі машини.

### Платне: агент

Потрібен ключ у `module2/.env`. Модель — `claude-sonnet-4-6`, $3 за мільйон вхідних токенів і $15 за
мільйон вихідних. Переписування запиту, якщо його ввімкнути, іде на `claude-haiku-4-5` за $1 і $5.

Ціни нижче — з реальних прогонів, не з оцінок:

```bash
python -m practice.base.ask            # replace — $0.0232
python -m practice.base.ask proxy      #           $0.0816
python -m practice.base.ask absent     #           $0.0041
python -m practice.base.ask known      #           $0.0233
python -m practice.base.ask thin       #           $0.0232
```

Разом ці п'ять — приблизно $0.155.

Чому `proxy` коштує вчетверо більше за решту. Питання там складене з двох частин, агент зробив шість
пошуків підряд, і кожен наступний виклик до моделі несе в собі всі попередні знахідки. Вхідних токенів
набігло 19 278 проти чотирьох тисяч у звичайному сценарії. Це нормальна поведінка агентного циклу, і саме
тому в `config.py` стоїть `MAX_TURNS=6` — стеля, за яку він не вийде.

Найдешевший — `absent`, чотири десятих цента: агент не зробив жодного пошуку, побачив, що питання про
географію, і відмовився одразу.

### Перемикачі

```bash
python -m practice.base.ask known --rewrite    # $0.0377
python -m practice.base.ask absent --rewrite   # $0.0039
python -m practice.base.ask known --lexical    # той самий агент на BM25
PRACTICE_EMBED_MODEL=bge python -m practice.base.compare
```

`--rewrite` вмикає переписування запиту через Haiku. Прогін дорожчає приблизно в півтора раза: у `known`
було $0.0233, стало $0.0377, бо додалися три виклики Haiku і два зайві пошуки.

`--lexical` пускає того самого агента не на ембедингах, а на BM25 — видно, як міняється відповідь від
самої лише заміни пошуку.

`PRACTICE_EMBED_MODEL=bge` перемикає модель ембедингів на англійську. Перший запуск з нею завантажить ще
130 МБ ваг і порахує окремий індекс, дві хвилини. Кеш у кожної моделі свій, тож назад повернення миттєве.

### Що куди пишеться

Кожен прогін агента дописує запис у `practice/out/practice_results.json` під ключем виду
`known:vector:rewrite`. Повторний прогін тієї самої пари замінює свій попередній запис, чужих не чіпає.
Теки `out/` і `index/` у git не потрапляють.

### Повний перезнім усіх доказів

П'ять базових сценаріїв плюс три з перемикачами — приблизно $0.20. Усе інше безкоштовне, але забере
близько десяти хвилин процесорного часу.

## Реальні прогони

Чотири сценарії, один прогін кожного, модель `claude-sonnet-4-6`, `MAX_TURNS=6`. Разом $0.1322. Вивід
нижче — дослівний, разом із форматуванням Markdown, яке модель вставила у відповідь попри вказівку в
промпті писати простим текстом.

### Сценарій replace — людське формулювання замість назви методу

```
── Практика М2 · сценарій: replace · модель claude-sonnet-4-6 · MAX_TURNS=6 ──
  корпус:       283 фрагментів з 18 документів специфікації
  запит:        «How do I replace part of a text with something else, and what happens to the rest of the string?»
  пошук:        vector
  outcome:      ok  ·  кроків: 2  ·  129.81 с
  пошук:        «replacing a substring inside a string» → 3: 18-string-objects#22.1.3.20/2, 18-string-objects#22.1.3.19, 18-string-objects#22.1.3.19.1/1
  пошук:        «String replace method» → 3: 18-string-objects#22.1.3.20/2, 18-string-objects#22.1.3.19, 18-string-objects#22.1.3.19.1/1
  відповідь:
    Here is what the ECMAScript specification says about replacing part of a string:
    
    **`String.prototype.replace(searchValue, replaceValue)`** [22.1.3.19]
    
    This method searches the string for the first occurrence of `searchValue` and replaces it. Here is exactly what happens, step by step:
    
    1. The string value (the `this` value) is converted to a String, and `searchValue` is also converted to a String (unless it is an object with a `Symbol.replace` method, in which case that method is called instead).
    2. The method searches for the first position where `searchValue` occurs in the string, starting from index 0.
    3. If the search value is not found, the original string is returned unchanged.
    4. If it is found, the string is split into two parts around the match:
       - "preceding" — the substring from the beginning of the string up to (but not including) the match.
       - "following" — the substring starting immediately after the end of the match, going to the end of the string.
    5. The replacement is computed — either by calling `replaceValue` as a function (if it is callable), or by processing it as a string template via an internal operation called `GetSubstitution`.
    6. The final result is the string-concatenation of "preceding", then "replacement", then "following".
    
    So the rest of the string — everything before and after the matched portion — is preserved exactly as-is. Only the matched portion is swapped out.
    
    **`String.prototype.replaceAll(searchValue, replaceValue)`** [22.1.3.20]
    
    This method works similarly but replaces every occurrence, not just the first. It collects all match positions, then builds the result by iterating through them: for each match, it appends the preserved text between the end of the last match and the start of the current match, then appends the replacement. After the last match, if there is any remaining text in the string, that remainder is appended to the result as well.
    
    **The `replaceValue` can be a function** [22.1.3.19]
    
    If `replaceValue` is callable, it is invoked with the matched substring, the position of the match, and the full original string as arguments, and its return value (converted to a String) is used as the replacement.
    
    In summary: only the matched portion of the string is replaced; everything before it ("preceding") and everything after it ("following") is kept and concatenated around the new replacement to form the returned string.
  вартість:     $0.0232  (2 викликів, 4322 in / 683 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

### Сценарій proxy — складене питання, шість пошуків

Питання з двох частин: що заважає Proxy збрехати і як саме читається властивість крізь нього.
Агент розклав його на шість пошуків, щоразу міняючи формулювання, і зібрав відповідь із того, що
повернулося. Це найдорожчий прогін набору — $0.0816 проти двох-трьох центів у решти, бо кожен
наступний виклик несе в собі всі попередні знахідки.

```
── Практика М2 · сценарій: proxy · модель claude-sonnet-4-6 · MAX_TURNS=6 ──
  корпус:       283 фрагментів з 18 документів специфікації
  запит:        «When a proxy stands in for another object, what stops it from reporting a value that contradicts the real object, and how does reading a property through it actually work?»
  пошук:        vector
  outcome:      ok  ·  кроків: 4  ·  167.32 с
  пошук:        «Proxy invariants consistency checks traps» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.11/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.4, 13-proxy-object-internal-methods-and-internal-slots#10.5/3
  пошук:        «Proxy get trap [[Get]] property reading» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.8/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.5/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.7
  пошук:        «Proxy [[Get]] invariants non-configurable non-writable accessor» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.5/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.8/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.6/2
  пошук:        «Proxy [[GetOwnProperty]] invariants non-configurable configurable extensible» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.5/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.11/2, 13-proxy-object-internal-methods-and-internal-slots#10.5.6/2
  пошук:        «Proxy [[Get]] invariants note value accessor undefined» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.8/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.9/1, 13-proxy-object-internal-methods-and-internal-slots#10.5.1
  пошук:        «ValidateNonRevokedProxy revoked proxy handler null» → 3: 13-proxy-object-internal-methods-and-internal-slots#10.5.14, 13-proxy-object-internal-methods-and-internal-slots#10.5.1, 13-proxy-object-internal-methods-and-internal-slots#10.5.9/1
  відповідь:
    Here is a full, precise account drawn entirely from the specification.
    
    ---
    
    **Part 1: What stops a Proxy from lying — the invariant enforcement system**
    
    The specification is explicit that handler traps can be arbitrary ECMAScript code, so a handler could in principle return anything. The protection against contradictions comes from a set of hard-coded integrity checks that every Proxy internal method runs after calling the trap, before it returns the result to the caller. As the spec states: "Some of the internal method invariants defined in 6.1.7.3 are essential integrity invariants. These invariants are explicitly enforced by the Proxy object internal methods specified in this section." [13-proxy-object-internal-methods-and-internal-slots#10.5/3]
    
    The enforcement works differently for each operation, but several examples illustrate the pattern:
    
    For property descriptor queries ([[GetOwnProperty]]), the spec prohibits a whole family of misrepresentations. The trap may not report a property as non-existent if it exists as a non-configurable own property of the real target, nor may it report a property as non-existent if the target is non-extensible, nor may it invent a property that does not exist on a non-extensible target. It also may not report a property as non-configurable unless the target actually has a corresponding non-configurable property, and may not report a property as both non-configurable and non-writable unless the target actually has that exact combination. [13-proxy-object-internal-methods-and-internal-slots#10.5.5/2]
    
    For key enumeration ([[OwnPropertyKeys]]), the result must include every key of every non-configurable own property on the target, and if the target is non-extensible it must contain exactly the own property keys of the target — no more and no fewer. [13-proxy-object-internal-methods-and-internal-slots#10.5.11/2]
    
    For extensibility reporting ([[PreventExtensions]]), the trap may only return true (claiming extensions are prevented) if the target is genuinely non-extensible. [13-proxy-object-internal-methods-and-internal-slots#10.5.4]
    
    For prototype queries ([[GetPrototypeOf]]), if the target is non-extensible, the trap's result must be exactly the same value as the target's own prototype — a SameValue comparison is performed and a TypeError is thrown if they differ. [13-proxy-object-internal-methods-and-internal-slots#10.5.1]
    
    When a violation is detected the engine throws a TypeError immediately, before the caller ever sees the fabricated value. It is the engine, not the programmer, that runs these checks — they cannot be turned off.
    
    There is also one additional gate that runs before anything else on every single trap invocation: ValidateNonRevokedProxy checks whether the proxy has been revoked by verifying that [[ProxyTarget]] is not null, and throws a TypeError immediately if it is. [13-proxy-object-internal-methods-and-internal-slots#10.5.14]
    
    ---
    
    **Part 2: How reading a property through a Proxy actually works — [[Get]] step by step**
    
    Reading a property triggers the [[Get]] internal method, which takes a property key and a receiver (the value to use as `this` for any getter). [13-proxy-object-internal-methods-and-internal-slots#10.5.8/1]
    
    The steps are as follows:
    
    First, ValidateNonRevokedProxy is called, throwing a TypeError if the proxy has been revoked.
    
    Next, [[ProxyTarget]] and [[ProxyHandler]] are retrieved. The spec asserts that if the proxy is live, the handler is guaranteed to be an Object.
    
    The handler is then asked for a method named "get" using GetMethod. This is the critical branching point: if no "get" method exists on the handler (the result is undefined), the operation is forwarded directly to the target by calling target.[[Get]](propertyKey, receiver), bypassing all trap logic entirely. The proxy is fully transparent in this case.
    
    If a "get" trap does exist, it is called with three arguments: the target, the property key, and the receiver. The return value of the trap is captured as trapResult.
    
    After the trap returns, the spec does not simply hand trapResult back. It immediately calls target.[[GetOwnProperty]](propertyKey) to fetch the real descriptor from the actual target object. Then two invariant checks are applied:
    
    First, if the target's descriptor exists and is non-configurable, and it is a data descriptor whose [[Writable]] field is false, then SameValue(trapResult, targetDesc.[[Value]]) must be true; otherwise a TypeError is thrown. This means a handler cannot lie about the value of a frozen property.
    
    Second, if the target's descriptor is a non-configurable accessor whose [[Getter]] is undefined (i.e. a write-only-style accessor with no getter), then trapResult must be undefined; otherwise a TypeError is thrown. The proxy cannot invent a readable value where the real property has no getter.
    
    Only after passing both checks is trapResult returned to the caller. [13-proxy-object-internal-methods-and-internal-slots#10.5.8/1]
  вартість:     $0.0816  (4 викликів, 19278 in / 1586 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

### Сценарій absent — питання не з корпусу

Найпростіший випадок відмови: питання не має з корпусом спільної теми взагалі. Агент не зробив
жодного пошуку — вирішив з самого формулювання.

```
── Практика М2 · сценарій: absent · модель claude-sonnet-4-6 · MAX_TURNS=6 ──
  корпус:       283 фрагментів з 18 документів специфікації
  запит:        «What is the capital of France, and how far is it from Lviv?»
  пошук:        vector
  outcome:      ok  ·  кроків: 1  ·  3.33 с
  пошуки:       жодного — агент відповів, не звернувшись до корпусу
  відповідь:
    The available specification excerpts cover only ECMAScript language specification topics, such as object types, exotic objects, string/symbol/number/boolean wrapper objects, and related JavaScript internals. Geographic questions like the capital of France or distances between cities are entirely outside the scope of what I can answer here.
    
    Please consult a general-purpose resource (such as a map service or encyclopedia) for that information. If you have any questions about the ECMAScript specification, I am happy to help!
  вартість:     $0.0041  (1 викликів, 852 in / 104 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

### Сценарій known — питання, відповідь на яке модель знає напам'ять

Ось це і є справжня перевірка. `Array.prototype.flat` описаний у розділі 23.1 специфікації, якого
серед наших вісімнадцяти документів немає. Модель знає цей метод із власного навчання і могла
відповісти правильно й без корпусу — правильно, але без джерела, а це рівно те, що картка називає
головним багом.

Пошук її не спинив: два запити повернули шість фрагментів з `10.4.2 Array Exotic Objects`, бо тема
спільна і межу вони подолали. Жоден на питання не відповідав, і агент це сказав, ще й перелічив,
що з масивів у корпусі таки є.

```
── Практика М2 · сценарій: known · модель claude-sonnet-4-6 · MAX_TURNS=6 ──
  корпус:       283 фрагментів з 18 документів специфікації
  запит:        «How does Array.prototype.flat decide how deep to flatten a nested array?»
  пошук:        vector
  outcome:      ok  ·  кроків: 3  ·  146.1 с
  пошук:        «Array.prototype.flat depth flattening» → 3: 07-array-exotic-objects#10.4.2.2, 07-array-exotic-objects#10.4.2.1, 07-array-exotic-objects#10.4.2.4/1
  пошук:        «FlattenIntoArray depth argument» → 3: 07-array-exotic-objects#10.4.2.4/1, 01-object-type#6.1.7.4/5, 07-array-exotic-objects#10.4.2.1
  відповідь:
    The available excerpts do not cover the internal workings of `Array.prototype.flat` or the `FlattenIntoArray` abstract operation. The excerpts I have access to cover the following Array-related topics: the creation of Array exotic objects (ArrayCreate), the [[DefineOwnProperty]] internal method for arrays, and the ArraySetLength operation. None of these describe how `flat` processes its `depth` argument or decides how deeply to recurse into nested arrays.
    
    If you have questions about those covered topics — such as how an array's `length` property is set or validated, or how array index property definitions work — I am happy to help with those.
  вартість:     $0.0233  (3 викликів, 6434 in / 268 out)
  збережено:    /mnt/c/Projects/fwdays/agent0826/module2/practice/out/practice_results.json
```

## Виміри

### BM25 проти ембедингів

Прогін `python -m practice.base.compare`. Міряється не влучання в перший рядок, а **місце** правильного
розділу в повному списку з 283 фрагментів. Влучання — надто груба міра: воно однаково показує «промахнувся
на один рядок» і «правильна відповідь на сотому місці», а це різні хвороби.

Останній запит у наборі відповіді в корпусі не має. Він показує те, чого не видно на решті: BM25 і на нього
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
  очікуємо:    нічого — у корпусі відповіді немає
  BM25         правильного розділу немає — має віддати порожньо
                 6.659  22.1.3.12 String.prototype.localeCompare ( that [ , reserv
                        18-string-objects#22.1.3.12/2
                 0.780  22.1.3.25 String.prototype.substring ( start , end )
                        18-string-objects#22.1.3.25
  ембединги    правильного розділу немає — має віддати порожньо
               віддає: нічого

Правильний розділ стоїть вище в ембедингів на 5 запитах, нижче на 0, однаково на 0.
Запит без відповіді в корпусі: BM25 усе одно щось віддає, ембединги мовчать, якщо топ-1 не дотяг до межі.
```

### Підлога відмови

Прогін `python -m practice.base.threshold`.

```
фрагментів: 283 · поріг у коді: 0.8

Питання, відповідь на які в корпусі Є:
   0.834  How do I replace part of a text with something else?   18-string-objects#22.1.3.20/2
   0.846  What happens when a wrapper for true or false is cre   01-object-type#6.1.7.1/2
   0.839  Can the parent of an object be locked so it never ch   13-proxy-object-internal-methods-and-internal-slots#10.5.9/2
   0.831  How does a stand-in object forward reads to the real   08-string-exotic-objects#10.4.3.1
   0.839  How does a function remember the object it was attac   01-object-type#6.1.7.2/6
   0.855  How is the length of an array kept in step with its    07-array-exotic-objects#10.4.2.4/1
   0.859  What does freezing an object actually do to its prop   14-object-objects#20.1.2.6
   0.883  How do I turn a number into a string with a fixed nu   17-number-objects#21.1.3.5/1

Питання, яких корпус НЕ покриває:
   0.732  What is the capital of France?                         18-string-objects#22.1.3.12/2
   0.814  How do I open a file and read it line by line?         18-string-objects#22.1.3.1
   0.768  What is the recipe for borscht?                        01-object-type#6.1.7.4/4
   0.845  How does async iteration over a stream work?           01-object-type#6.1.7.4/1
   0.814  How do I install a package with npm?                   01-object-type#6.1.7.4/4
   0.818  What is the difference between let and var?            18-string-objects#22.1.2.4

найгірше «є»:      0.831
найкраще «немає»:  0.845
проміжку немає: набори перекриваються, самим числом їх не розділити

нижня межа 0.8 відсікає 2 із 6 питань не з корпусу:
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

Числа в цьому розділі виміряні на корпусі **до** злиття дублікатів, тобто на 298 фрагментах, а не на 283.
Тому місця правильного розділу тут не збігаються з таблицею порівняння вище — там після злиття вони стали
на кілька позицій кращі. Порівнювати ці числа між собою можна лише в межах цього розділу, де всі варіанти
міряні на одному й тому самому корпусі. Перерахунок після злиття не робився: злиття прибрало п'ятнадцять
повторів з 298 і на висновок «жоден спосіб не розділяє набори» вплинути не могло.

**Відрив топ-1 від решти корпусу.** Замість абсолютного косинуса — наскільки найкращий фрагмент вирізняється
з-поміж усіх 283. Задум був у тому, що на сторонньому запиті всі оцінки мають лягти купно, а на правильному
одна має стирчати. Не розділяє: найбільший відрив дало «How do I install a package with npm?», більший за
будь-яке правильне питання.

**Зв'язка з BM25.** Вимога, щоб фрагмент пройшов обидва пошуки: у стороннього запиту не має бути рідкісних
слів корпусу. Не розділяє: у «How does async iteration over a stream work?» лексична оцінка 13.27, вища,
ніж у п'яти правильних питань із восьми. Додавати другий вимірник, який помиляється на тих самих запитах,
сенсу немає.

**Інша подача тексту моделі.** Гіпотеза була така: у вектор іде заголовок підрозділу разом із текстом, а
текст — це щільний алгоритм на кшталт «Let O be ? ToObject(this value)», однаковий на всю специфікацію,
тож заголовок у ньому тоне. Перевірено два варіанти проти нинішнього — з назвою документа перед заголовком
і з окремим вектором на самий заголовок, беручи більшу з двох схожостей. Місця правильного розділу
(нинішній / з назвою документа / тільки заголовок): `22.1.3.19` — 2 / 2 / 2, `20.3.1.1` — 109 / 139 / 177,
`10.4.7` — 65 / 31 / 168, `10.5.8` — 107 / 110 / 199, `10.4.1` — 6 / 6 / 5. Гіпотеза хибна: окремий вектор
на заголовок дає гірше, назва документа допомагає одному запиту з п'яти й шкодить двом.

**Інша модель.** Ось це спрацювало, і саме тому воно тут. `BAAI/bge-small-en-v1.5` того самого розміру, але
англійська. Місця правильного розділу (`e5` / `bge`): 2 / 3, 109 / 2, 65 / 20, 107 / 15, 6 / 9 — тобто три
запити з п'яти, безнадійні в `e5`, у неї робочі. На відмові вона теж краща: її нижня межа 0.68 відсікає п'ять
сторонніх питань із шести, нижня межа `e5` — два з шести.

Причина не в тому, що одна модель розумніша. Місткість у них однакова, але в `e5` вона розкладена на сотню
мов, а корпус тут англійський від першого до останнього символу. Багатомовність нічого не дає й коштує
якості.

За замовчуванням лишилася `e5` — заради однаковості з курсовим `knowledge_vec.py`, який бере ту саму модель.
Це свідомий вибір з відомою ціною: на чотирьох сторонніх питаннях із шести відмовляти доводиться моделі, а
не пошуку. Перемкнутися можна змінною `PRACTICE_EMBED_MODEL=bge`, нічого не міняючи в коді.

## Розмір шматка

Необов'язковий пункт картки. Довгий документ тут один очевидний: 22.1 String Objects, 52 257 символів,
п'ята частина корпусу. Він ріжеться на чотирьох стелях, на кожній будується окремий індекс лише з нього,
і вісім запитів міряються за місцем правильного підрозділу у видачі. Прогін
`python -m practice.challenges.a_chunking`, офлайн, $0, кілька хвилин процесора.

```
документ: 22.1 String Objects · 52257 символів · модель intfloat/multilingual-e5-small
запитів: 8 · стелі: 400, 700, 1400, 2500

стеля 400: рахую 134 фрагментів (найдовший 933, у середньому 360)
стеля 700: рахую 94 фрагментів (найдовший 933, у середньому 514)
стеля 1400: рахую 57 фрагментів (найдовший 1505, у середньому 849)
стеля 2500: рахую 53 фрагментів (найдовший 2445, у середньому 913)

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
у топ-1            2       2       2       3
у топ-3            4       4       3       4
середнє         27.6    19.5    10.9     9.6
```

Результат протилежний до звичної поради «ріж дрібніше — буде точніше». Середнє місце падає монотонно з
27.6 до 9.6 у міру збільшення стелі. На двох запитах різниця різка: «прибрати пробіли з обох кінців» —
99-те місце проти 31-го, «зробити всі літери великими» — 81-ше проти 29-го.

Причина в кількості фрагментів. Розділ 22.1 має 53 підрозділи, і стеля 2500 дає рівно 53 фрагменти, по
одному на метод. Стеля 400 дає 134 — кожен метод розрізаний на два-три шматки посеред власного алгоритму,
заголовок лишається в першому, кроки переїжджають у другий. Кроки `trim` в окремому фрагменті виглядають
як будь-які інші кроки специфікації: «Let S be ? ToString(O)», «Return TrimString(S, start+end)».

Порада «дрібніше — точніше» придумана для суцільної прози, де межі теми не позначені й дрібніший шматок
справді точніший. Специфікація вже пронумерована по темах, і різати її дрібніше за власну нумерацію означає
ламати наявну розмітку.

У коді лишилася стеля 1400, а не переможна 2500. Причина окрема від рангів: модель читає 512 токенів і
мовчки відрізає далі. На стелях 400, 700 і 1400 за вікно не вилітає жоден фрагмент, найдовший на 1400 має
467 токенів. На 2500 вилітає п'ять із 53, найдовший на 682 токени — третини його тексту модель не бачить.
Перевага 2500 здобута вже з утраченими хвостами і залежить від того, які саме хвости відрізало. Найбільша
стеля без втрат — 1400.

## Переписування запиту

Необов'язковий пункт картки: «якщо знайшлось мало — хай агент переформулює запит і спробує ще раз».
Механізм у `practice/common/rewrite.py`, вбудований у `search_docs`: інструмент сам помічає бідний
результат, іде до Haiku, просить назвати те саме словами специфікації, шукає вдруге і бере кращий з двох
наборів. Вмикається прапорцем `--rewrite`.

### Що вважається «мало» і звідки взялася планка

Спрацьовує будь-яка з двох умов: фрагментів, що подолали межу, менше трьох, або найкращий із них нижче за
планку впевненості.

Друга умова додана після виміру, і без неї механізм був би мертвим кодом. Підлога `e5` стоїть майже на
середньому косинусі корпусу — крізь неї проходить приблизно половина фрагментів, і кількість знайденого до
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
0.828 на 0.884. У всіх трьох правильний розділ до переписування в топ-3 не потрапляв, а після — потрапив.

На `bge` ефект ще сильніший: там ці ж запити давали нуль фрагментів вище за межу, після переписування —
три з трьох.

### Чому порожній результат не переписується

Спершу було задумано інакше: порожньо теж рахувалося як «мало», бо здавалося, що саме там друга спроба
найпотрібніша. Вимір показав протилежне.

На запиті «What is the capital of France?» Haiku відмовився переписувати і відповів текстом «I appreciate
the test, but this question isn't about JavaScript or ECMAScript...». Цей текст пішов у пошук як запит.
Слова «JavaScript» і «ECMAScript» у ньому є, корпус увесь про JavaScript, і оцінка вийшла 0.843 — вище за
межу 0.80. На питанні про борщ те саме: 0.841.

Відмова допоміжної моделі перетворилася на дані. Агент отримав би три фрагменти там, де раніше отримував
чесну порожнечу, і третій обов'язковий пункт розсипався б заради необов'язкового.

Тому переписування вмикається лише тоді, коли перший пошук щось таки знайшов. Порожньо лишається порожнім.
Другий запобіжник на той самий випадок з іншого боку: переписаний запит має бути коротшим за 160 символів
і не починатися з «I», «Sorry», «This question» та подібного — багатослівна відповідь від першої особи це
не запит.

### Що вийшло в живому прогоні

`python -m practice.base.ask known --rewrite` — механізм увімкнувся тричі, двічі взяв другий набір, у
видачу заїхали інші фрагменти. Прогін коштував $0.0377 проти $0.0233 без переписування.

`python -m practice.base.ask absent --rewrite` — жодного пошуку, відмова за 2.81 секунди, як і без
переписування.

Відмова вистояла в обох. У `known --rewrite` агент написав: «Stating anything from my own general knowledge
of JavaScript would violate the rules I must follow». Одну межу він там усе ж переступив — порадив шукати
в розділі 23.1.3.13, а цього номера в корпусі немає, він з пам'яті моделі. Як відповідь це не подано, це
порада, куди піти дивитися, але промпт просив не брати з голови нічого.

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

## Чого ця робота не робить

**Це не оцінка якості відповідей.** Ragas і подібні метрики тут не рахувалися. Що агент послався на
правильний розділ, видно з прогонів очима; числа, яке б це підтверджувало на ста питаннях, немає.

**Це не векторна база.** Індекс — матриця в пам'яті плюс файл `.npy` на диску. Для 283 фрагментів цього
досить із запасом: пошук — одне множення матриці на вектор. Chroma чи Qdrant тут не потрібні й не додали б
нічого, крім залежності.

**Підлога не гарантує відмови.** Вище сказано, що саме вона закриває, і на чому тримається решта. Прогін
`known` показує, що модель у цьому випадку відмовилася. Один прогін — не гарантія на всіх питаннях такого
роду.

**Агент не перевіряє, чи відповів пошук на питання.** Він отримує три фрагменти й вирішує сам. Окремого
кроку, який оцінює придатність знайденого до того, як воно потрапить у відповідь, тут немає.
