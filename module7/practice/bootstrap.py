"""
ОСНОВА · підключення практики до фабрики docfactory.

Практика лежить у репозиторії курсу, а агент, якого вона міряє, — у теці
docfactory/ поруч, поза репозиторієм. Цей модуль зшиває їх рівно так, як це
робить скрипт ./df: додає корені в sys.path, вибирає примірник і виставляє
змінні, які читає спільний код фабрики.

use() кличеться ПЕРШИМ, до будь-якого імпорту common.* чи server.*. Порядок тут
не формальність: common.llm читає .env примірника на імпорті модуля, тож
запізнілий виклик use() уже нічого не змінить.

    from practice import bootstrap
    bootstrap.use()                      # здоровий примірник
    bootstrap.use("ecmascript-degraded") # деградована копія
"""

import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCFACTORY = REPO / "docfactory"
MODULE7 = REPO / "module7"
INSTANCES = DOCFACTORY / "instances"

#: Примірник, з якого завжди береться ключ. Деградована копія — це копія даних,
#: а не другий обліковий запис, і другого файла з ключем ми не заводимо.
KEY_INSTANCE = "ecmascript"


def available(instance: str = KEY_INSTANCE) -> bool:
    """Чи лежить поруч примірник фабрики.

    Тека `docfactory/` живе поза репозиторієм курсу, тож у клоні її немає. Це
    нормальний стан, а не збій: безкоштовні перевірки набору й правил обходяться
    паспортом корпусу з `data/`. Питання ставлять тут, а не через try/except
    навколо імпорту, щоб відсутність фабрики не плуталася з поламаним імпортом.
    """
    return (INSTANCES / instance).is_dir()


def use(instance: str = "ecmascript", vectors_wait: bool = True) -> pathlib.Path:
    """Готує процес до роботи з примірником і повертає його теку."""
    target = INSTANCES / instance
    if not target.is_dir():
        # Дві різні біди, і повідомлення в них різні: фабрики немає взагалі
        # (звичайний стан клону) чи вона є, але без цього примірника.
        if not INSTANCES.is_dir():
            raise SystemExit(
                f"Фабрики немає: {DOCFACTORY}\n"
                f"  Платні прогони працюють лише поруч із нею. Безкоштовні перевірки\n"
                f"  її не потребують: python -m pytest practice")
        raise SystemExit(
            f"Немає примірника «{instance}»: {target}\n"
            f"  наявні: {', '.join(sorted(p.name for p in INSTANCES.iterdir() if p.is_dir()))}")

    for root in (DOCFACTORY, MODULE7):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    # Ключ — з базового примірника і до першого імпорту common.llm. python-dotenv
    # не перекриває вже виставлену змінну, тож пізніший load_dotenv усередині
    # common.llm (він читає .env вибраного примірника) цього значення не зачепить.
    from dotenv import load_dotenv
    load_dotenv(INSTANCES / KEY_INSTANCE / ".env")

    os.environ["DF_INSTANCE_DIR"] = str(target)

    # Те саме, що ./df кладе в оточення з config.json примірника: колекція, модель
    # векторів, порт. Копія примірника успадковує ці значення разом із файлом —
    # деградований корпус навмисно шукається в тій самій колекції, бо це і є
    # випадок «текст оновили, вектори не перерахували».
    cfg_path = target / "config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for key, env in (("collection", "QDRANT_COLLECTION"),
                         ("embed_model", "PRACTICE_EMBED_MODEL"),
                         ("port", "DF_PORT")):
            if cfg.get(key):
                os.environ[env] = str(cfg[key])

    # Прогрів векторів синхронний: інакше перші питання прогону шукали б по
    # словах, пізніші за змістом, і число залежало б від того, що встигло раніше.
    if vectors_wait:
        os.environ["DF_VECTORS_WAIT"] = "1"

    return target
