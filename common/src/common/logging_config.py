import logging
import os
import sys


DEMO_LEVEL = 25
logging.addLevelName(DEMO_LEVEL, "DEMO")

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def setup_logging(component: str) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    if level_name == "CLEAN":
        level_name = "DEMO"
    level = DEMO_LEVEL if level_name == "DEMO" else getattr(logging, level_name, logging.INFO)
    log_format = "%(asctime)s %(message)s" if level_name == "DEMO" else f"%(asctime)s %(levelname)s [{component}] %(name)s: %(message)s"
    date_format = "%H:%M:%S" if level_name == "DEMO" else "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        stream=sys.stdout,
        force=True,
    )

    if level_name == "DEMO":
        for handler in logging.getLogger().handlers:
            handler.addFilter(_DemoOnlyFilter())

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)


def demo_log(logger: logging.Logger, message: str, *args) -> None:
    if is_demo_logging():
        logger.log(DEMO_LEVEL, message, *args)


def is_demo_logging() -> bool:
    return os.getenv("LOG_LEVEL", "").upper() in {"DEMO", "CLEAN"}


def color_delta(value: float, previous: float | None, *, lower_is_better: bool = False) -> str:
    formatted = _format_number(value)
    if previous is None or value == previous or os.getenv("NO_COLOR"):
        return formatted

    improved = value < previous if lower_is_better else value > previous
    color = GREEN if improved else RED
    return f"{color}{formatted}{RESET}"


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


class _DemoOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == DEMO_LEVEL or record.levelno >= logging.ERROR
