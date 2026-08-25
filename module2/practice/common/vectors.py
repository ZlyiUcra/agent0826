"""
СПІЛЬНЕ · пошук по змісту. Ембединги замість підрахунку слів.

Модель — `intfloat/multilingual-e5-small`, 118 мільйонів параметрів, крутиться
локально на процесорі. Ключів вона не потребує: вагу треба один раз завантажити
з Hugging Face (близько 470 МБ), далі все працює без мережі.

Чому саме e5-small, хоча вимір радить інше. Курсовий `knowledge_vec.py` бере ту
саму модель, і практика лишається з нею, щоб курс і домашнє завдання міряли
однією лінійкою.

Плата за це виміряна, і мовчати про неї не варто. Друга модель у реєстрі,
`BAAI/bge-small-en-v1.5`, того самого розміру, але англійська, і на цьому корпусі
вона краща двічі. За рангом правильного розділу на п'яти запитах practice/base/
compare.py вона дає 3, 2, 20, 15, 9 проти 2, 109, 65, 107, 6 в e5 — тобто три
запити з п'яти, безнадійні в e5, у неї робочі. За відмовою вона теж краща: її
її нижня межа 0.68 відсікає п'ять сторонніх питань із шести, у e5 — два з шести.

Причина не в тому, що одна модель розумніша. Місткість у них однакова, але в e5
вона розкладена на сотню мов, а наш корпус англійський від першого до останнього
символу. Багатомовність тут нічого не дає й коштує якості.

Перемкнутися можна не міняючи коду:

    PRACTICE_EMBED_MODEL=bge python -m practice.base.compare

Кеш векторів у кожної моделі свій (ім'я файла починається з ключа моделі), тож
перемикання нічого не псує — індекс просто порахується вперше.

ПРЕФІКСИ query: І passage:

Моделі сімейства e5 навчені асиметрично: питання і текст, що на нього відповідає,
подаються з різними префіксами. Питання йде як «query: ...», фрагмент корпусу —
як «passage: ...». Без префіксів модель однаково щось порахує, але косинуси
поїдуть, і поріг, підібраний на одному, не працюватиме на другому. Тому префікс
проставляється тут, у єдиному місці, а не в кожній точці виклику.

ПОРІГ: ЩО ВІН ЗАКРИВАЄ І ЧОГО НЕ ЗАКРИВАЄ

Вектори завжди повертають найсхожіший фрагмент — навіть якщо запит не має до
корпусу жодного стосунку. Тому нижче `THRESHOLD` пошук нічого не віддає:
порожній результат означає «у корпусі такого немає».

Значення виміряне скриптом practice/base/threshold.py окремо для кожної моделі.
Далі йдуть числа e5, бо вона стоїть за замовчуванням; вимір показав межу самого
способу. Косинуси восьми питань, відповідь на які в корпусі є, лягли в
проміжок 0.831–0.883. Косинуси шести питань, яких корпус не покриває, — у
проміжок 0.732–0.845. Проміжки перекриваються, тобто одним числом ці два набори
не розділити взагалі.

Причина не в моделі й не в порозі. Питання «How does async iteration over a
stream work?» (0.845) і «What is the difference between let and var?» (0.818) —
це питання про JavaScript, а весь наш корпус про JavaScript. Схожість міряє
тему, а не наявність відповіді. Окремо додає шуму розділ 6.1.7.4 Well-Known
Intrinsic Objects: це суцільна таблиця імен від %Array% до %WeakSet%, і вона
схожа на будь-яке питання про мову.

Перевірено ще два способи, обидва не розділяють. Відрив топ-1 від решти корпусу:
найбільший відрив дало «How do I install a package with npm?», більший за
будь-яке правильне питання. Зв'язка з BM25: у того самого «async iteration»
лексична оцінка 13.27, вища, ніж у п'яти правильних питань із восьми.

У bge розкид ширший і нижня межа 0.68 відсікає п'ять сторонніх питань із шести —
крізь неї проходить саме «async iteration». Тобто вибір моделі зсуває межу, але
не прибирає її.

Тому число в коді — це нижня межа, а не роздільна риса. Вона відсікає те, що з корпусом не має
спільної теми: «What is the capital of France?» (0.732) і «What is the recipe
for borscht?» (0.768) не проходять. Питання про JavaScript, відповіді на які в
цих вісімнадцяти розділах немає, нижня межа пропускає, і відмовляти на них має
модель — вона бачить сам текст фрагментів, а не оцінку схожості. Так це й
влаштовано в practice/common/tools.py: нижня межа закриває чужу тему, промпт
закриває свою тему без відповіді.

КЕШ

Порахувати 284 фрагменти на процесорі — це десятки секунд. Робити це на кожен
запуск немає сенсу, тому вектори лягають у practice/index/ поруч із відбитком
корпусу. Змінилися документи або межі фрагментів — відбиток інший, файл із таким
іменем не знайдеться, індекс порахується заново. Старі файли кеша при цьому
лишаються на місці: код нічого не видаляє, прибирає їх людина, якщо захоче.
"""

import os
import pathlib

from .corpus import Passage, fingerprint, load_passages

# Моделі, між якими можна перемикатися змінною оточення PRACTICE_EMBED_MODEL.
# Кожна вимагає своїх префіксів: e5 просить «query:»/«passage:», bge — довгу
# інструкцію перед запитом і нічого перед фрагментом, MiniLM — нічого взагалі.
# Подавати текст без правильного префікса не помилка, але косинуси поїдуть, і
# нижня межа, виміряна на одній моделі, перестане означати те саме на іншій.
MODELS = {
    "e5": ("intfloat/multilingual-e5-small", "query: ", "passage: "),
    "bge": ("BAAI/bge-small-en-v1.5",
            "Represent this sentence for searching relevant passages: ", ""),
}

MODEL_KEY = os.getenv("PRACTICE_EMBED_MODEL", "e5")
if MODEL_KEY not in MODELS:
    raise SystemExit(f"Невідома модель '{MODEL_KEY}'. Доступні: {', '.join(MODELS)}")
MODEL_NAME, _QUERY_PREFIX, _PASSAGE_PREFIX = MODELS[MODEL_KEY]

# Підлога схожості для кожної моделі окремо: косинуси в них живуть у різних
# діапазонах, тож одне число на всіх не годиться. Виміряно base/threshold.py.
THRESHOLDS = {"e5": 0.80, "bge": 0.68}

THRESHOLD = THRESHOLDS[MODEL_KEY]

INDEX_DIR = pathlib.Path(__file__).resolve().parent.parent / "index"

_model = None


def _hush_hub() -> None:
    """Прибирає з виводу дві речі, які до справи не стосуються.

    Перша — попередження «You are sending unauthenticated requests to the HF Hub».
    При піднятті моделі бібліотека йде на сервер Hugging Face спитати, чи не
    оновилися файли, і робить це без токена. Заводити токен не потрібно: ваги вже
    в кеші, качати нічого. `HF_HUB_OFFLINE=1` прибирає сам похід у мережу, а
    разом із ним і попередження, і кілька секунд очікування.

    Змінна ставиться ТІЛЬКИ якщо модель у кеші вже є. Інакше на чистій машині
    перше завантаження впало б, замість того щоб просто відпрацювати.

    Друга — смужка «Loading weights: 199/199» від transformers. Це поступ
    завантаження тензорів у пам'ять; у виводі прогону він тільки заважає.

    Обидві змінні виставляються, лише якщо їх ще не задано ззовні: явний вибір
    того, хто запускає, важливіший за наш.
    """
    home = pathlib.Path(os.getenv("HF_HOME", pathlib.Path.home() / ".cache" / "huggingface"))
    cached = home / "hub" / ("models--" + MODEL_NAME.replace("/", "--"))
    if cached.exists():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def _load_model():
    """Модель вантажиться один раз на процес і лише коли справді потрібна."""
    global _model
    if _model is None:
        _hush_hub()
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise SystemExit(
                "Немає sentence-transformers. З теки module2/:\n"
                "  .venv/bin/python -m pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu\n"
                "  .venv/bin/python -m pip install sentence-transformers"
            )
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts: list[str], kind: str):
    """kind: 'query' або 'passage' — від цього залежить префікс.

    Повертає матрицю нормалізованих векторів, тож косинус між ними — це
    звичайний скалярний добуток.
    """
    if kind not in ("query", "passage"):
        raise ValueError(f"kind має бути 'query' або 'passage', отримано {kind!r}")
    model = _load_model()
    prefix = _QUERY_PREFIX if kind == "query" else _PASSAGE_PREFIX
    return model.encode([prefix + t for t in texts],
                        normalize_embeddings=True, show_progress_bar=False)


class VectorIndex:
    """Ембединги фрагментів корпусу з кешем на диску."""

    def __init__(self, passages: list[Passage] | None = None, use_cache: bool = True):
        import numpy as np

        self.passages = passages if passages is not None else load_passages()
        self.fingerprint = fingerprint(self.passages)
        self.cache_path = INDEX_DIR / f"{MODEL_KEY}-{self.fingerprint}.npy"
        self.from_cache = False

        if use_cache and self.cache_path.exists():
            self.matrix = np.load(self.cache_path)
            self.from_cache = True
            return

        # Заголовок разом із текстом — так само, як у лексичному індексі:
        # модель має бачити, до якого підрозділу належить фрагмент.
        self.matrix = embed([f"{p.heading}\n{p.text}" for p in self.passages],
                            kind="passage")
        if use_cache:
            INDEX_DIR.mkdir(exist_ok=True)
            np.save(self.cache_path, self.matrix)

    def scores(self, query: str, k: int = 3) -> list[tuple[float, Passage]]:
        """Топ-k за косинусом, БЕЗ відсікання за порогом. Для налаштування порога."""
        sims = self.matrix @ embed([query], kind="query")[0]
        order = sims.argsort()[::-1][:k]
        return [(float(sims[i]), self.passages[i]) for i in order]

    def retrieve(self, query: str, k: int = 3) -> list[Passage]:
        """Топ-k з відсіканням за порогом. Порожньо означає «в корпусі немає»."""
        return [p for s, p in self.scores(query, k) if s >= THRESHOLD]
