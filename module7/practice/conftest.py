"""Спільна підготовка тестів: практика бачить фабрику, фабрика — свій примірник."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # module7/

from practice import bootstrap                                          # noqa: E402

bootstrap.use()
