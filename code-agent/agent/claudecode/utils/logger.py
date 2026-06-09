"""Logger 工具 - 统一日志输出"""
import logging
import sys

_logger = None


def setup_logger(level=logging.INFO, name="claudecode"):
    global _logger
    if _logger:
        return _logger
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    _logger = logger
    return logger


def get_logger():
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger


logger = logging.getLogger("claudecode")
if not logger.handlers:
    setup_logger()
