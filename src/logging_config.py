import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


class ExcludeLoggerFilter(logging.Filter):
    def __init__(self, excluded_prefixes: tuple[str, ...]):
        super().__init__()
        self.excluded_prefixes = excluded_prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(self.excluded_prefixes)


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    exclude_filter = ExcludeLoggerFilter(
        (
            "watchfiles",
        )
    )

    # Console: INFO and above
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    console.addFilter(exclude_filter)
    root.addHandler(console)

    # File: INFO and above, rotate at 10 MB, keep 5 backups
    app_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    app_handler.addFilter(exclude_filter)
    root.addHandler(app_handler)

    # Error file: WARNING and above only
    err_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    err_handler.addFilter(exclude_filter)
    root.addHandler(err_handler)

    # Suppress noisy third-party loggers
    for name in (
        "watchfiles",
        "watchfiles.main",
        "httpx",
        "httpcore",
        "urllib3",
        "pymilvus",
        "neo4j",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True