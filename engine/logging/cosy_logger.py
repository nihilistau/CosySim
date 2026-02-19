"""
CosyLogger - In-process log capture for CosySim
Captures log records from the standard logging framework and stores them
in a ring-buffer so the phone-scene control panel terminal can stream them.
"""
import logging
import threading
from collections import deque
from datetime import datetime

# ── Constants ────────────────────────────────────────────────────────────────
MAX_RECORDS = 2000          # maximum log lines kept in memory
DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

# ── Levels exposed to the UI ──────────────────────────────────────────────────
LEVELS = {
    "ALL":     logging.DEBUG,
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
}


# ── Handler ──────────────────────────────────────────────────────────────────
class _RingHandler(logging.Handler):
    """Thread-safe ring-buffer log handler."""

    def __init__(self, maxlen: int = MAX_RECORDS):
        super().__init__()
        self._buf: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord):
        try:
            self.format(record)           # populate record.message etc.
            entry = {
                "id":      self._next_id(),
                "ts":      datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3],
                "level":   record.levelname,
                "logger":  record.name,
                "message": record.getMessage(),
            }
            with self._lock:
                self._buf.append(entry)
        except Exception:                 # never crash the emitting thread
            self.handleError(record)

    def _next_id(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    # ── Query ─────────────────────────────────────────────────────────────────
    def get_logs(
        self,
        level: str = "ALL",
        limit: int = 200,
        since_id: int = 0,
    ) -> list:
        """
        Return log entries filtered by *level*, limited to *limit* most-recent
        entries, and optionally only those with id > *since_id* (for polling).
        """
        min_level = LEVELS.get(level.upper(), logging.DEBUG)
        with self._lock:
            snapshot = list(self._buf)

        if since_id:
            snapshot = [e for e in snapshot if e["id"] > since_id]

        filtered = [e for e in snapshot if LEVELS.get(e["level"], 0) >= min_level]
        return filtered[-limit:]

    def clear(self):
        with self._lock:
            self._buf.clear()


# ── Singleton ─────────────────────────────────────────────────────────────────
_handler: _RingHandler | None = None
_installed = False


def install_logger(
    logger_name: str = "",          # "" = root logger
    level: int = logging.DEBUG,
    propagate_root: bool = True,
    fmt: str = DEFAULT_FORMAT,
) -> _RingHandler:
    """
    Install the ring-buffer handler on the given logger (default: root).
    Safe to call multiple times — returns the same singleton handler.
    """
    global _handler, _installed
    if _installed and _handler is not None:
        return _handler

    _handler = _RingHandler()
    _handler.setFormatter(logging.Formatter(fmt, datefmt=DATE_FORMAT))

    target = logging.getLogger(logger_name)
    target.setLevel(level)
    target.addHandler(_handler)

    if propagate_root and logger_name:
        # Also add to root so we catch 3rd-party logs
        root = logging.getLogger()
        if _handler not in root.handlers:
            root.setLevel(level)
            root.addHandler(_handler)

    _installed = True
    logging.getLogger(__name__).info("CosyLogger installed — ring buffer active")
    return _handler


def get_handler() -> _RingHandler | None:
    """Return the installed handler, or None if not yet installed."""
    return _handler


def get_logs(level: str = "ALL", limit: int = 200, since_id: int = 0) -> list:
    """Convenience wrapper — works even if logger not installed (returns [])."""
    if _handler is None:
        return []
    return _handler.get_logs(level=level, limit=limit, since_id=since_id)


def clear_logs():
    """Clear the ring buffer."""
    if _handler:
        _handler.clear()
