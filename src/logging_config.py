import logging
import sys
from contextvars import ContextVar, Token
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import settings

# 请求级链路追踪 ID：HTTP middleware 入口 set，workflow 入口兜底 set。
# 同一线程/协程内的所有日志都会带上这个 ID，方便排查"一次请求跑了哪些节点"。
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | [req_id=%(request_id)s] | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


class ExcludeLoggerFilter(logging.Filter):
    def __init__(self, excluded_prefixes: tuple[str, ...]):
        super().__init__()
        self.excluded_prefixes = excluded_prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(self.excluded_prefixes)


class RequestIdFilter(logging.Filter):
    """把 contextvar 中的 request_id 注入到每条 LogRecord 上。

    LOG_FORMAT 里用 %(request_id)s 引用，未设置时显示 "-"（便于过滤无请求上下文的日志，
    如启动日志、定时任务）。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


def set_request_id(request_id: str) -> Token:
    """设置当前上下文的 request_id，返回 Token 供 reset_request_id 还原。

    典型用法：
        token = set_request_id("abc123")
        try:
            ...  # 同一上下文的所有日志都带 [req_id=abc123]
        finally:
            reset_request_id(token)
    """
    return _request_id_var.set(request_id)


def reset_request_id(token: Token) -> None:
    """还原 request_id 到 set_request_id 之前的状态。"""
    _request_id_var.reset(token)


def get_request_id() -> str:
    """获取当前上下文的 request_id（用于业务代码主动打日志时带上）。"""
    return _request_id_var.get()


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
    request_id_filter = RequestIdFilter()

    # Console: INFO and above
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    console.addFilter(exclude_filter)
    console.addFilter(request_id_filter)
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
    app_handler.addFilter(request_id_filter)
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
    err_handler.addFilter(request_id_filter)
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