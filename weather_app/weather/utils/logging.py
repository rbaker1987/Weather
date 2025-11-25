"""Logging setup using loguru with configuration support."""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from ..core.config import get_config


def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    log_format: Optional[str] = None,
    rotation: Optional[str] = None,
    retention: Optional[str] = None
) -> None:
    """Setup application logging with loguru.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (if None, logs to console only)
        log_format: Custom log format string
        rotation: Log file rotation setting (e.g., "10 MB", "daily")
        retention: Log file retention setting (e.g., "30 days", "1 week")
    """
    config = get_config().logging

    # Use provided values or fall back to configuration
    level = log_level or config.level
    file_path = log_file or config.file
    format_str = log_format or config.format
    rotation_setting = rotation or config.rotation
    retention_setting = retention or config.retention

    # Remove default handler
    logger.remove()

    # Add console handler
    logger.add(
        sys.stdout,
        level=level,
        format=format_str,
        colorize=True,
        backtrace=True,
        diagnose=True
    )

    # Add file handler if specified
    if file_path:
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_path,
            level=level,
            format=format_str,
            rotation=rotation_setting,
            retention=retention_setting,
            backtrace=True,
            diagnose=True,
            enqueue=True  # Thread-safe logging
        )

    logger.info("Logging initialized", level=level, file=file_path)


def get_logger(name: str):
    """Get a logger instance with the given name.
    
    Args:
        name: Logger name (typically __name__ of the module)
    
    Returns:
        Logger instance
    """
    return logger.bind(name=name)


def log_function_call(func_name: str, **kwargs):
    """Log function call with parameters."""
    args_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
    logger.debug(f"Calling {func_name}({args_str})")


def log_api_request(url: str, method: str = "GET", params: Optional[dict] = None):
    """Log API request details."""
    logger.debug(f"API Request: {method} {url}", params=params)


def log_api_response(url: str, status_code: int, response_time: Optional[float] = None):
    """Log API response details."""
    if response_time:
        logger.debug(f"API Response: {url} -> {status_code} ({response_time:.2f}s)")
    else:
        logger.debug(f"API Response: {url} -> {status_code}")


def log_performance_metric(operation: str, duration: float, **context):
    """Log performance metrics."""
    logger.info(f"Performance: {operation} took {duration:.2f}s", **context)


def log_error_with_context(error: Exception, context: dict):
    """Log error with additional context."""
    logger.error(f"Error: {type(error).__name__}: {error}", **context)


# Convenience decorators for logging
def log_calls(func):
    """Decorator to log function calls."""
    def wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__name__}"
        logger.debug(f"Entering {func_name}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"Exiting {func_name} successfully")
            return result
        except Exception as e:
            logger.error(f"Error in {func_name}: {type(e).__name__}: {e}")
            raise
    return wrapper


def log_async_calls(func):
    """Decorator to log async function calls."""
    async def wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__name__}"
        logger.debug(f"Entering async {func_name}")
        try:
            result = await func(*args, **kwargs)
            logger.debug(f"Exiting async {func_name} successfully")
            return result
        except Exception as e:
            logger.error(f"Error in async {func_name}: {type(e).__name__}: {e}")
            raise
    return wrapper
