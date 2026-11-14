"""Process metrics: peak RSS sampled in a background thread."""

import threading
from types import TracebackType


class PeakRss:
    """``with PeakRss() as rss: ...`` then ``rss.peak_mb`` (max RSS seen, in MB)."""

    def __init__(self, interval_s: float = 0.1) -> None:
        import psutil

        self._proc = psutil.Process()
        self._interval = interval_s
        self._stop = threading.Event()
        self.peak = int(self._proc.memory_info().rss)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.peak = max(self.peak, int(self._proc.memory_info().rss))

    def __enter__(self) -> "PeakRss":
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, int(self._proc.memory_info().rss))

    @property
    def peak_mb(self) -> int:
        return round(self.peak / 2**20)
