"""Спільна підготовка тестів.

Перевірки набору і правил живуть усередині модуля і фабрики `docfactory/` не
потребують: вони читають набір кейсів і паспорт корпусу з `data/`, обидва під
git. Тому `pytest practice` працює в голому клоні репозиторію.

Коли фабрика все-таки лежить поруч, її підключають — тоді додається один тест,
який звіряє паспорт із живим корпусом і падає, щойно вони розійдуться.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # module7/

from practice import bootstrap                                          # noqa: E402

if bootstrap.available():
    bootstrap.use()
