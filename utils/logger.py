import logging
import sys
from typing import Optional


class Logger:
    """
    Centralized logger for vending machine application components.
    Supports different log levels and output formats.
    """

    # Log levels
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    # Log level names for display
    LEVEL_NAMES = {
        DEBUG: "DEBUG",
        INFO: "INFO",
        WARNING: "WARN",
        ERROR: "ERROR",
        CRITICAL: "CRIT",
    }

    def __init__(
        self,
        name: str,
        level: int = INFO,
        console_output: bool = True,
        file_output: Optional[str] = None,
    ):
        """
        Initialize logger with specified name and settings.

        Args:
            name: Name identifier for the logger
            level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            console_output: Whether to output logs to console
            file_output: Optional file path for log output
        """
        self.name = name
        self.level = level
        self.console_output = console_output
        self.file_output = file_output

        # Initialize Python's built-in logger
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._logger.handlers = []  # Clear any existing handlers

        formatter = logging.Formatter(
            "%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Add console handler if requested
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)

        # Add file handler if requested
        if file_output:
            file_handler = logging.FileHandler(file_output)
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def _log(self, level: int, *args):
        """Internal logging method."""
        message = " ".join(str(arg) for arg in args)
        self._logger.log(level, message)

    def debug(self, *args):
        """Log debug message."""
        self._log(Logger.DEBUG, *args)

    def info(self, *args):
        """Log info message."""
        self._log(Logger.INFO, *args)

    def warning(self, *args):
        """Log warning message."""
        self._log(Logger.WARNING, *args)

    def error(self, *args):
        """Log error message."""
        self._log(Logger.ERROR, *args)

    def critical(self, *args):
        """Log critical message."""
        self._log(Logger.CRITICAL, *args)

    # Shorthand methods
    def warn(self, *args):
        """Alias for warning."""
        self.warning(*args)

    def err(self, *args):
        """Alias for error."""
        self.error(*args)

    def crit(self, *args):
        """Alias for critical."""
        self.critical(*args)


# Default logger instances
system_logger = Logger("SYSTEM")
vending_logger = Logger("VENDING")
payment_logger = Logger("PAYMENT")
broker_logger = Logger("BROKER")
app_logger = Logger("APP")


def get_logger(name: str, level: int = Logger.INFO) -> Logger:
    """
    Get a logger with the specified name and level.
    Creates a new logger if one doesn't exist.
    """
    return Logger(name, level)
