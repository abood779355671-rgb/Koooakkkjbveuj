import sys
import os
from loguru import logger
from pathlib import Path


def setup_logger(log_level: str = "INFO", log_file: str = "logs/system.log",
                 max_size: str = "100 MB", backup_count: int = 5,
                 console_output: bool = True) -> None:
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    if console_output:
        logger.add(
            sys.stdout,
            format=log_format,
            level=log_level,
            colorize=True,
        )

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        format=log_format,
        level=log_level,
        rotation=max_size,
        retention=backup_count,
        compression="zip",
        enqueue=True,
    )

    logger.add(
        "logs/errors.log",
        format=log_format,
        level="ERROR",
        rotation="50 MB",
        retention=3,
        compression="zip",
        enqueue=True,
    )


def get_logger(name: str):
    return logger.bind(name=name)
