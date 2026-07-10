import logging
import os
import sys

def setup_logger():
    """Configure le logger pour l'application."""
    logger = logging.getLogger("HorRAGor")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console handler (UTF-8 forcé pour Windows cp1252)
    ch = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger

logger = setup_logger()
