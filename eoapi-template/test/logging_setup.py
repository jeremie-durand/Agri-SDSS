import logging
import os
import sys

def setup_logging():
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    numeric_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )