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

    python -m practice.base.run             # щасливий ланцюжок, ~$0.02
    python -m practice.base.run direct      # клієнт сам знає трек-номер
    python -m practice.base.run range       # телефон + період дат
    python -m practice.base.run tool_error  # збій інструмента
    python -m practice.base.run hostile     # клієнт підкидає суму
    python -m practice.base.run unknown     # телефону немає в базі
    python -m practice.base.run --help      # перелік сценаріїв, $0
    python -m practice.base.demo            # шість сцен, по одній на стан, ~$0.05
    python -m practice.base.demo 5 6        # лише безкоштовні сцени, $0
    python -m practice.base.demo --list     # перелік сцен, $0
    python -m unittest practice.challenges.c_tests.ChainTest \
        practice.challenges.c_tests.BackendContractTest practice.challenges.c_tests.RegistrationTest \
        practice.challenges.c_tests.MoneyCheckTest practice.challenges.c_tests.DemoTest \
        practice.challenges.c_tests.ResultsFileTest  # 32 тести основи, $0

ЧЕЛЕНДЖ A — опис інструмента визначає поведінку (practice/challenges/a_experiment.py):

    python -m practice.challenges.a_experiment --query period_words  # головний результат: до/після, ~$0.02
    python -m practice.challenges.a_experiment --hunt                # полювання по кандидатах, ~$0.08
    python -m practice.challenges.a_experiment --list                # що це за кандидати, $0
    python -m practice.challenges.a_experiment --rescore             # переоцінка збережених прогонів, $0
    python -m unittest practice.challenges.c_tests.SchemaVariantTest \
        practice.challenges.c_tests.MisroutedArgumentsTest \
        practice.challenges.c_tests.DateFilterTest  # 22 тести челенджа, $0

ЧЕЛЕНДЖ B — зламай свого агента (practice/challenges/b_redteam.py):

    python -m practice.challenges.b_redteam                          # усі сімнадцять атак, ~$0.27
    python -m practice.challenges.b_redteam --round 3                # лише один раунд, дешевше
    python -m practice.challenges.b_redteam --case foreign_tracking  # виправлений дефект, два промпти, ~$0.01
    python -m practice.challenges.b_redteam --case poisoned_fact     # відкритий дефект: видно, як влучає
    python -m practice.challenges.b_redteam --list                   # атаки і чим кожна небезпечна, $0
    python -m practice.challenges.b_redteam --rescore                # переоцінка збережених прогонів, $0
    python -m unittest practice.challenges.c_tests.RedTeamCheckTest  # 24 тести челенджа, $0

ЧЕЛЕНДЖ C — тест без мережі і бюджет (practice/challenges/c_tests.py, practice/common/budget.py).
Тут безкоштовне все:

    python -m unittest practice.challenges.c_tests -v          # усі 107 тестів, $0
    python -m unittest practice.challenges.c_tests.BudgetTest  # бюджет і таблиця цін, 7 тестів, $0
    PRACTICE_BUDGET_USD=0.0001 python -m practice.base.run     # жива відмова бюджету, $0
    python -m practice.base.demo 6                             # та сама відмова окремою сценою, $0

ЧЕЛЕНДЖ D — дія з наслідками (practice/challenges/d_run.py + practice/challenges/d_tools.py):

    python -m practice.challenges.d_run                                # три кроки на ТИМЧАСОВОМУ сховищі, ~$0.08
    python -m practice.challenges.d_run request                        # крок 1 окремо — уже на реальному сховищі
    python -m practice.challenges.d_run confirm                        # крок 2: згода клієнта підтверджує заявку
    python -m practice.challenges.d_run repeat                         # крок 3: повтор не створює дубля
    python -m practice.challenges.d_run --status                       # що лежить у сховищі заявок, $0
    python -m unittest practice.challenges.c_tests.RedirectActionTest  # 19 тестів челенджа, $0

Зламані стани викликаються оточенням поверх звичайного прогону, без правки файлів:

    ANTHROPIC_API_KEY=sk-ant-invalid python -m practice.base.run  # api_error, $0
    MAX_TURNS=1 python -m practice.base.run                       # turns_exhausted

Кожна точка входу має власний ліміт витрат у змінній оточення: PRACTICE_BUDGET_USD,
PRACTICE_DEMO_BUDGET_USD, PRACTICE_EXPERIMENT_BUDGET_USD, PRACTICE_REDTEAM_BUDGET_USD,
PRACTICE_ACTION_BUDGET_USD. Розбір кожного челенджа з дослівними прогонами — у
practice/README.md, статус по чекбоксах картки — у practice/CHECKLIST.md.
"""
