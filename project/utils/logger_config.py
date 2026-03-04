# project/utils/logger_config.py
import logging
import warnings

def setup_clean_logging():
    warnings.filterwarnings("ignore")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.WARNING)