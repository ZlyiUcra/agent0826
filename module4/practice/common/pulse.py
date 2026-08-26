"""
СПІЛЬНЕ · пульс: рядок стану, що оновлюється на місці, поки триває довга робота.

Виклик моделі триває секунди, а між його початком і відповіддю на екран не
йде нічого — зовні це не відрізняється від очікування вводу з клавіатури.
Пульс закриває цю прогалину: у тому самому рядку, через повернення каретки,
кожні пів секунди перемальовується «думає · 7 с · виклик 2 з 8 · пошук: «…»»,
а коли робота закінчилася, рядок стирається і далі йде звичайний вивід.

    from practice.common.pulse import Pulse

    with Pulse("думає") as pulse:
        pulse.note("виклик 2 з 8")
        ...

Пише лише тоді, коли потік виводу — термінал: у файл журналу чи в канал не
потрапляє жодного знака, тож фонові прогони й записи прогонів лишаються
чистими. Малює фоновий потік, тому робота, яку пульс супроводжує, про нього
не знає; єдина вимога — не друкувати нічого іншого, поки пульс живий, інакше
чужий рядок ляже поверх нього.
"""

import sys
import threading
import time


class Pulse:
    """Контекстний менеджер: вхід запускає малювання, вихід стирає рядок."""

    def __init__(self, label: str, stream=None, every: float = 0.5):
        self.label = label
        self.stream = stream if stream is not None else sys.stdout
        self.every = every
        self.active = bool(getattr(self.stream, "isatty", lambda: False)())
        self.elapsed = 0.0
        self._detail = ""
        self._width = 0
        self._started = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def note(self, detail: str) -> None:
        """Уточнення в кінці рядка: який виклик, який пошук."""
        self._detail = detail
        if self.active:
            self._draw()

    def _draw(self) -> None:
        text = f"  {self.label} · {int(time.time() - self._started)} с"
        if self._detail:
            text += f" · {self._detail}"
        with self._lock:
            pad = " " * max(0, self._width - len(text))
            self.stream.write("\r" + text + pad)
            self.stream.flush()
            self._width = max(self._width, len(text))

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            self._draw()

    def __enter__(self):
        self._started = time.time()
        if self.active:
            self._draw()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self.elapsed = time.time() - self._started
        if self.active:
            with self._lock:
                self.stream.write("\r" + " " * self._width + "\r")
                self.stream.flush()
        return False
