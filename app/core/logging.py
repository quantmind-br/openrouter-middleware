"""Structured logging system with Redis persistence and request context tracing."""

import asyncio
import contextvars
import inspect
import logging
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.models.logs import LogEntry, LogLevel, LogConfig

settings = get_settings()

# Context variables for request tracing
request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('request_id', default=None)
user_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('user_id', default=None)
client_ip_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('client_ip', default=None)


class StructuredLogger:
    """Enhanced logger with structured output and context tracking."""
    
    def __init__(self, name: str, config: Optional[LogConfig] = None):
        self.name = name
        self.config = config or LogConfig()
        self._standard_logger = logging.getLogger(name)
        self._log_queue: asyncio.Queue = asyncio.Queue()
        self._redis_handler: Optional['RedisLogHandler'] = None
        self._batch_task: Optional[asyncio.Task] = None
        
    def set_redis_handler(self, redis_handler: 'RedisLogHandler'):
        """Set the Redis handler for persistence."""
        self._redis_handler = redis_handler
        
    async def start_batch_processing(self):
        """Start background task for batch processing logs."""
        if not self._batch_task or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._batch_processor())
    
    async def stop_batch_processing(self):
        """Stop background batch processing."""
        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
    
    async def _batch_processor(self):
        """Background task to process logs in batches."""
        batch = []
        
        while True:
            try:
                # Wait for logs or timeout
                try:
                    log_entry = await asyncio.wait_for(
                        self._log_queue.get(), 
                        timeout=self.config.flush_interval
                    )
                    batch.append(log_entry)
                except asyncio.TimeoutError:
                    # Timeout reached, flush current batch
                    if batch and self._redis_handler:
                        await self._redis_handler.batch_store(batch)
                        batch.clear()
                    continue
                
                # Check if batch is full
                if len(batch) >= self.config.batch_size:
                    if self._redis_handler:
                        await self._redis_handler.batch_store(batch)
                    batch.clear()
                    
            except asyncio.CancelledError:
                # Flush remaining logs before stopping
                if batch and self._redis_handler:
                    await self._redis_handler.batch_store(batch)
                break
            except Exception as e:
                # Log processing error - avoid infinite loops
                print(f"Error in log batch processor: {e}")
                await asyncio.sleep(1)
    
    def _get_caller_info(self) -> tuple[str, Optional[str], Optional[int]]:
        """Get information about the calling function."""
        frame = inspect.currentframe()
        try:
            # Walk up the stack to find the actual caller (skip logging internals)
            while frame:
                frame = frame.f_back
                if frame and not frame.f_code.co_filename.endswith(('logging.py', 'log_formatter.py')):
                    function_name = frame.f_code.co_name
                    line_number = frame.f_lineno
                    return self.name, function_name, line_number
            return self.name, None, None
        finally:
            del frame
    
    def _should_log(self, level: LogLevel) -> bool:
        """Check if log should be recorded based on configuration."""
        # Check module-specific level first
        if self.name in self.config.module_levels:
            min_level = self.config.module_levels[self.name]
        else:
            min_level = self.config.global_level
        
        # Convert to numeric values for comparison
        level_values = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50
        }
        
        return level_values[level] >= level_values[min_level]
    
    def _create_log_entry(
        self, 
        level: LogLevel, 
        message: str, 
        extra_data: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None,
        duration_ms: Optional[float] = None
    ) -> LogEntry:
        """Create a structured log entry."""
        module, function, line_number = self._get_caller_info()
        
        entry = LogEntry(
            level=level,
            message=message,
            module=module,
            function=function,
            line_number=line_number,
            request_id=request_id_var.get(),
            user_id=user_id_var.get(),
            client_ip=client_ip_var.get(),
            extra_data=extra_data or {},
            duration_ms=duration_ms
        )
        
        # Add exception information if provided
        if exception:
            entry.exception_type = type(exception).__name__
            # If we're in an exception context, use format_exc(), otherwise format manually
            if hasattr(exception, '__traceback__') and exception.__traceback__:
                entry.exception_traceback = ''.join(traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                ))
            else:
                # Create a simple traceback representation
                entry.exception_traceback = f"{type(exception).__name__}: {str(exception)}"
        
        return entry
    
    async def _log(
        self, 
        level: LogLevel, 
        message: str, 
        extra_data: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None,
        duration_ms: Optional[float] = None
    ):
        """Internal logging method."""
        if not self._should_log(level):
            return
            
        entry = self._create_log_entry(level, message, extra_data, exception, duration_ms)
        
        # Console logging if enabled
        if self.config.enable_console:
            getattr(self._standard_logger, level.lower())(
                f"[{entry.timestamp.isoformat()}] {entry.request_id or 'no-req'} "
                f"{entry.module}:{entry.function}:{entry.line_number} - {message}"
            )
        
        # Queue for Redis persistence if enabled
        if self.config.enable_redis and self._redis_handler:
            try:
                self._log_queue.put_nowait(entry)
            except asyncio.QueueFull:
                # Queue full - log directly without batching
                await self._redis_handler.store(entry)
    
    async def debug(self, message: str, **kwargs):
        """Log debug message."""
        await self._log(LogLevel.DEBUG, message, kwargs)
    
    async def info(self, message: str, **kwargs):
        """Log info message."""
        await self._log(LogLevel.INFO, message, kwargs)
    
    async def warning(self, message: str, **kwargs):
        """Log warning message."""
        await self._log(LogLevel.WARNING, message, kwargs)
    
    async def error(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """Log error message."""
        await self._log(LogLevel.ERROR, message, kwargs, exception)
    
    async def critical(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """Log critical message."""
        await self._log(LogLevel.CRITICAL, message, kwargs, exception)


class RequestContext:
    """Context manager for request-scoped logging context."""
    
    def __init__(self, request_id: Optional[str] = None, user_id: Optional[str] = None, client_ip: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.user_id = user_id
        self.client_ip = client_ip
        self.start_time = datetime.utcnow()
        
        # Store previous context values for restoration
        self._prev_request_id = None
        self._prev_user_id = None
        self._prev_client_ip = None
    
    def __enter__(self):
        # Store previous values
        self._prev_request_id = request_id_var.get()
        self._prev_user_id = user_id_var.get()
        self._prev_client_ip = client_ip_var.get()
        
        # Set new values
        request_id_var.set(self.request_id)
        if self.user_id:
            user_id_var.set(self.user_id)
        if self.client_ip:
            client_ip_var.set(self.client_ip)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore previous values
        request_id_var.set(self._prev_request_id)
        user_id_var.set(self._prev_user_id)
        client_ip_var.set(self._prev_client_ip)
    
    async def __aenter__(self):
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.__exit__(exc_type, exc_val, exc_tb)
    
    def get_duration_ms(self) -> float:
        """Get request duration in milliseconds."""
        delta = datetime.utcnow() - self.start_time
        return delta.total_seconds() * 1000


class PerformanceLogger:
    """Context manager for performance logging."""
    
    def __init__(self, logger: StructuredLogger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = datetime.utcnow()
    
    async def __aenter__(self):
        await self.logger.debug(f"Starting {self.operation}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.utcnow() - self.start_time).total_seconds() * 1000
        
        if exc_type:
            await self.logger.error(
                f"Failed {self.operation}",
                exception=exc_val,
                duration_ms=duration,
                operation=self.operation
            )
        else:
            await self.logger.info(
                f"Completed {self.operation}",
                duration_ms=duration,
                operation=self.operation
            )


# Global logger registry
_loggers: Dict[str, StructuredLogger] = {}
_default_config: Optional[LogConfig] = None


def get_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger instance."""
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name, _default_config)
    return _loggers[name]


def set_default_config(config: LogConfig):
    """Set default configuration for all loggers."""
    global _default_config
    _default_config = config
    
    # Update existing loggers
    for logger in _loggers.values():
        logger.config = config


def update_module_level(module: str, level: LogLevel):
    """Update log level for a specific module."""
    if _default_config:
        _default_config.module_levels[module] = level
        
        # Update existing logger for this module
        if module in _loggers:
            _loggers[module].config = _default_config


async def shutdown_all_loggers():
    """Shutdown all loggers and flush pending logs."""
    for logger in _loggers.values():
        await logger.stop_batch_processing()


# Convenience functions that mimic standard logging
async def debug(message: str, **kwargs):
    """Log debug message using default logger."""
    logger = get_logger(__name__)
    await logger.debug(message, **kwargs)


async def info(message: str, **kwargs):
    """Log info message using default logger."""
    logger = get_logger(__name__)
    await logger.info(message, **kwargs)


async def warning(message: str, **kwargs):
    """Log warning message using default logger."""
    logger = get_logger(__name__)
    await logger.warning(message, **kwargs)


async def error(message: str, exception: Optional[Exception] = None, **kwargs):
    """Log error message using default logger."""
    logger = get_logger(__name__)
    await logger.error(message, exception, **kwargs)


async def critical(message: str, exception: Optional[Exception] = None, **kwargs):
    """Log critical message using default logger."""
    logger = get_logger(__name__)
    await logger.critical(message, exception, **kwargs)


def setup_structured_logging(config: Optional[LogConfig] = None):
    """Initialize structured logging system with default configuration."""
    if config is None:
        config = LogConfig()
    
    set_default_config(config)
    
    # Initialize Redis handler when the system starts
    # This will be set up later when Redis becomes available
    return config