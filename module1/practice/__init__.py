r"""
Практика модуля 1 — домашнє завдання курсу.

Живе всередині module1/, але НЕ є частиною курсового матеріалу: жоден курсовий файл
тут не змінюється. Практика лише перевикористовує ядро (`core/agent.py`, `core/cost.py`,
`core/escalation.py`) і додає власний бекенд із двома інструментами в ланцюжку.

Чому окремо: `CAPABILITIES[1]` навмисно дає рівно один інструмент — це головний
навчальний важіль курсу. Завдання ж вимагає ланцюжка з двох. Практика тому не
чіпає ні `CAPABILITIES`, ні `tools_for()`, а передає власний список схем прямо
в `run_agent(tools=...)`.

Як запускати. Усе — з теки module1/ і інтерпретатором з .venv; нижче для стислості
написано просто `python`, читайте як `.venv/bin/python`. Кожна точка входу є модулем
ЦЬОГО пакета, тому й викликається через `python -m practice.<модуль>`, а не як окремий
файл. З кореня репозиторію не запуститься нічого: `config`, `core`, `domain` шукаються
від module1/. Позначка $0 означає, що прогін до моделі не звертається і грошей не коштує.

ОСНОВА — ланцюжок і всі стани ядра:

    python -m practice.run                 # щасливий ланцюжок, ~$0.02
    python -m practice.run direct          # клієнт сам знає трек-номер
    python -m practice.run range           # телефон + період дат
    python -m practice.run tool_error      # збій інструмента
    python -m practice.run hostile         # клієнт підкидає суму
    python -m practice.run unknown         # телефону немає в базі
    python -m practice.run --help          # перелік сценаріїв, $0
    python -m practice.demo                # шість сцен, по одній на стан, ~$0.05
    python -m practice.demo 5 6            # лише безкоштовні сцени, $0
    python -m practice.demo --list         # перелік сцен, $0
    python -m unittest practice.test_practice.ChainTest \
        practice.test_practice.BackendContractTest practice.test_practice.RegistrationTest \
        practice.test_practice.MoneyCheckTest practice.test_practice.DemoTest \
        practice.test_practice.ResultsFileTest        # 32 тести основи, $0

ЧЕЛЕНДЖ A — опис інструмента визначає поведінку (practice/experiment_a.py):

    python -m practice.experiment_a --query period_words  # головний результат: до/після, ~$0.02
    python -m practice.experiment_a --hunt                # полювання по кандидатах, ~$0.08
    python -m practice.experiment_a --list                # що це за кандидати, $0
    python -m practice.experiment_a --rescore             # переоцінка збережених прогонів, $0
    python -m unittest practice.test_practice.SchemaVariantTest \
        practice.test_practice.MisroutedArgumentsTest \
        practice.test_practice.DateFilterTest             # 22 тести челенджа, $0

ЧЕЛЕНДЖ B — зламай свого агента (practice/redteam.py):

    python -m practice.redteam                            # усі п'ятнадцять атак, ~$0.06-0.09
    python -m practice.redteam --round 3                  # лише один раунд, дешевше
    python -m practice.redteam --case foreign_tracking    # виправлений дефект, два промпти, ~$0.01
    python -m practice.redteam --case poisoned_fact       # відкритий дефект: видно, як влучає
    python -m practice.redteam --list                     # атаки і чим кожна небезпечна, $0
    python -m practice.redteam --rescore                  # переоцінка збережених прогонів, $0
    python -m unittest practice.test_practice.RedTeamCheckTest   # 24 тести челенджа, $0

ЧЕЛЕНДЖ C — тест без мережі і бюджет (practice/test_practice.py, practice/budget.py).
Тут безкоштовне все:

    python -m unittest practice.test_practice -v          # усі 104 тести, $0
    python -m unittest practice.test_practice.BudgetTest  # бюджет і таблиця цін, 7 тестів, $0
    PRACTICE_BUDGET_USD=0.0001 python -m practice.run     # жива відмова бюджету, $0
    python -m practice.demo 6                             # та сама відмова окремою сценою, $0

ЧЕЛЕНДЖ D — дія з наслідками (practice/action.py + practice/actions.py):

    python -m practice.action              # три кроки на ТИМЧАСОВОМУ сховищі, ~$0.08
    python -m practice.action request      # крок 1 окремо — уже на реальному сховищі
    python -m practice.action confirm      # крок 2: згода клієнта підтверджує заявку
    python -m practice.action repeat       # крок 3: повтор не створює дубля
    python -m practice.action --status     # що лежить у сховищі заявок, $0
    python -m unittest practice.test_practice.RedirectActionTest  # 19 тестів челенджа, $0

Зламані стани викликаються оточенням поверх звичайного прогону, без правки файлів:

    ANTHROPIC_API_KEY=sk-ant-invalid python -m practice.run   # api_error, $0
    MAX_TURNS=1 python -m practice.run                        # turns_exhausted

Кожна точка входу має власний ліміт витрат у змінній оточення: PRACTICE_BUDGET_USD,
PRACTICE_DEMO_BUDGET_USD, PRACTICE_EXPERIMENT_BUDGET_USD, PRACTICE_REDTEAM_BUDGET_USD,
PRACTICE_ACTION_BUDGET_USD. Розбір кожного челенджа з дослівними прогонами — у
practice/README.md, статус по чекбоксах картки — у practice/CHECKLIST.md.
"""
