import sys
from datetime import datetime
from loguru import logger as _logger # Renamed to avoid conflict with the global logger
from app.config import PROJECT_ROOT

_print_level = "INFO"

def define_log_level(print_level="INFO", logfile_level="DEBUG", name: str = "DRIM_AI"): # [Source: 217] Changed default name
    """Adjust the log level to above level"""
    global _print_level
    _print_level = print_level

    current_date = datetime.now()
    formatted_date = current_date.strftime("%Y%m%d%H%M%S")
    log_name = (
        f"{name}_{formatted_date}" if name else formatted_date
    ) # [Source: 217] name a log with prefix name

    # Ensure logs directory exists
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    _logger.remove()
    _logger.add(sys.stderr, level=print_level)
    _logger.add(logs_dir / f"{log_name}.log", level=logfile_level) # [Source: 217]
    return _logger

logger = define_log_level() # [Source: 217]

if __name__ == "__main__": # [Source: 218]
    logger.info("Starting DRIM AI application logging test") # Changed message
    logger.debug("Debug message test")
    logger.warning("Warning message test")
    logger.error("Error message test")
    logger.critical("Critical message test")

    try:
        raise ValueError("Test error for logging")
    except Exception as e:
        logger.exception(f"An error occurred during logging test: {e}")