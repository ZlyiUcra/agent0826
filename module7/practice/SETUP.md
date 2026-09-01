# Установка і прогін

Як підняти оточення практики модуля 7 і як перевірити її безкоштовно. Усі команди виконуються з теки
`module7/`, не з кореня репозиторію: код практики імпортує `practice` як пакет верхнього рівня, а через
`bootstrap.py` дістає ще й `docfactory/` поруч.

## Яким інтерпретатором

Практика працює у **venv примірника фабрики**, а не у власному venv модуля 7:

```
/mnt/c/Projects/fwdays/agent0826/docfactory/instances/ecmascript/.venv/bin/python
```

Причина в тому, що міряється агент, який живе у фабриці. Йому потрібні `mcp` 2.1, `anthropic` 0.125 і
`fastembed`; у `module7/.venv` стоять `torch`, LangChain і A2A на 3.7 ГБ, а того, що потрібно агентові,
там немає. Запускати агента одним оточенням, а міряти іншим означало б міряти не його.

Шлях до інтерпретатора треба писати повністю. Відносний (`../docfactory/…/python`) працює, але Python
друкує на кожен запуск два попередження `RuntimeWarning: Unexpected value in sys.prefix` — він порівнює
шлях, з якого його запустили, з тим, що записаний у venv, і не зводить `..` сам.

## Три пакети понад те, що вже є в примірнику

```
cd /mnt/c/Projects/fwdays/agent0826/docfactory/instances/ecmascript
.venv/bin/python -m pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http pytest
```

Стоять версії `opentelemetry-sdk` 1.44.0, `opentelemetry-exporter-otlp-proto-http` 1.44.0 (тягне за собою
`opentelemetry-api` і `opentelemetry-proto` тієї ж версії) і `pytest` 9.1.1. Разом близько 5 МБ. Нічого з
цього агент не імпортує — обгортки накладає практика ззовні.

## Приймач трейсів

Спани йдуть у Arize Phoenix, піднятий локально. Він ставиться **в окреме оточення**, і це не примха: разом
із ним ставляться `mcp` 1.29.1 і `anthropic` 1.3.0, які розійшлися б із версіями примірника й зламали б
самого агента.

```
python3 -m venv ~/.venv-phoenix
~/.venv-phoenix/bin/pip install arize-phoenix
~/.venv-phoenix/bin/phoenix serve
```

Оточення виходить на 946 МБ. Інтерфейс — `http://127.0.0.1:6006`, сервіс у ньому називається
`docfactory-ecmascript`. Прогін лишає в ньому дерево спанів: корінь звернення, під ним по спану на кожне
звернення до моделі й на кожен виконаний інструмент.

Одну межу варто знати наперед. Змінна `PHOENIX_HOST=127.0.0.1` звужує до локальної адреси лише HTTP-порт
6006; порт gRPC 4317 Phoenix відкриває на всіх інтерфейсах незалежно від неї — адреса зашита в його
`grpc_server.py`. Практика шле спани по HTTP, тож для неї це нічого не змінює, але на спільній машині 4317
лишається відкритим, і закривати його доводиться зовні.

Приймач можна замінити, не чіпаючи практику: `--backend console` друкує спани в термінал і не потребує
нічого, `langfuse`, `langsmith` і `otlp` беруть адреси й ключі з оточення. Перелік адресатів один на
модуль — курсовий `otel_tracing._exporter`.

## Пошук за змістом

Прогони знімалися з увімкненим пошуком за змістом, і режим записується в кожен прогін
(`test_run_is_comparable` не дасть порівняти прогін по словах із прогоном за змістом). Для цього потрібен
Qdrant у Docker — той самий контейнер, що в решті практик:

```
cd /mnt/c/Projects/fwdays/agent0826/docfactory
./df ecmascript vectors      # підняти Qdrant і залити колекцію docs-ecmascript
./df ecmascript status       # стан бази
```

`bootstrap.use()` виставляє `DF_VECTORS_WAIT=1`, тобто сервер відповідає лише коли вектори прогріті. Без
цього перші питання прогону шукали б по словах, а пізніші — за змістом, і число залежало б від того, що
встигло раніше.

## Ключ

Ключ Anthropic лежить в одному місці — `docfactory/instances/ecmascript/.env`. `bootstrap.use()` читає його
до першого імпорту `common.llm` і не залежить від того, який примірник міряється: деградована копія власного
`.env` не має навмисно.

## Безкоштовна перевірка

```
cd /mnt/c/Projects/fwdays/agent0826/module7
/mnt/c/Projects/fwdays/agent0826/docfactory/instances/ecmascript/.venv/bin/python -m pytest practice -q
```

Тридцять сім перевірок: форма набору, наявність очікуваних розділів у названих документах, правила
детермінованих перевірок і сам гейт над останнім збереженим прогоном. До моделі не звертається жодна з них.

**Фабрика для цього не потрібна.** Перевірки набору читають `data/corpus-passport.json` — знімок корпусу під
git, — тож у голому клоні репозиторію, де теки `docfactory/` немає, `pytest practice` проходить: тринадцять
перевірок за частки секунди, решта пропускається з поясненням, чого бракує. Коли фабрика лежить поруч,
додається перевірка, яка звіряє паспорт із живим корпусом.

Паспорт перезнімають після кожної зміни набору кейсів або корпусу:

```
cd /mnt/c/Projects/fwdays/agent0826/module7
/mnt/c/Projects/fwdays/agent0826/docfactory/instances/ecmascript/.venv/bin/python \
    -m practice.base.passport            # --check, щоб лише звірити, нічого не пишучи
```

Якщо збереженого прогону немає, гейт пропускається зі `skip`, а решта працює.

Окремо перевіряється сам агент — у фабриці, теж безкоштовно:

```
cd /mnt/c/Projects/fwdays/agent0826/docfactory
./df ecmascript smoke
```

## Платні прогони

```
cd /mnt/c/Projects/fwdays/agent0826/module7
P=/mnt/c/Projects/fwdays/agent0826/docfactory/instances/ecmascript/.venv/bin/python

$P -m practice.base.run_traced "How does Object.prototype.toString build the tag?"   # ~$0.05
$P -m practice.base.run_eval --label baseline                                        # ~$1.01, ~10 хв
$P -m practice.base.run_eval --instance ecmascript-degraded --label degraded         # ~$1.05, ~10 хв
$P -m practice.base.rejudge --from baseline --label baseline-v2                      # ~$0.04
```

`--only same-value,json-valid` звужує прогін до названих кейсів — цим перевіряють зміну в коді, не
оплачуючи всі двадцять. Кожен прогін лишає файл у `out/` і рядок у `data/history.jsonl`.
