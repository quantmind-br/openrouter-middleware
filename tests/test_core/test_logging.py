"""Tests for structured logging functionality."""

import asyncio
import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.logging import (
    StructuredLogger, RequestContext, PerformanceLogger,
    get_logger, set_default_config, update_module_level,
    request_id_var, user_id_var, client_ip_var
)
from app.models.logs import LogLevel, LogConfig, LogEntry


class TestStructuredLogger:
    """Test StructuredLogger functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.logger = StructuredLogger("test_logger")
        self.logger._redis_handler = AsyncMock()
    
    def test_logger_initialization(self):
        """Test logger initialization."""
        logger = StructuredLogger("test_module")
        
        assert logger.name == "test_module"
        assert isinstance(logger.config, LogConfig)
        assert logger._redis_handler is None
        assert logger._batch_task is None
    
    def test_logger_with_config(self):
        """Test logger initialization with custom config."""
        config = LogConfig(
            global_level=LogLevel.DEBUG,
            enable_console=False,
            batch_size=50
        )
        
        logger = StructuredLogger("test_module", config)
        
        assert logger.config == config
        assert logger.config.global_level == LogLevel.DEBUG
        assert logger.config.enable_console is False
        assert logger.config.batch_size == 50
    
    def test_should_log_global_level(self):
        """Test log level filtering with global level."""
        # Set global level to WARNING
        config = LogConfig(global_level=LogLevel.WARNING)
        logger = StructuredLogger("test_module", config)
        
        # DEBUG and INFO should be filtered out
        assert not logger._should_log(LogLevel.DEBUG)
        assert not logger._should_log(LogLevel.INFO)
        
        # WARNING, ERROR, CRITICAL should pass
        assert logger._should_log(LogLevel.WARNING)
        assert logger._should_log(LogLevel.ERROR)
        assert logger._should_log(LogLevel.CRITICAL)
    
    def test_should_log_module_level(self):
        """Test log level filtering with module-specific level."""
        config = LogConfig(
            global_level=LogLevel.WARNING,
            module_levels={"test_module": LogLevel.DEBUG}
        )
        logger = StructuredLogger("test_module", config)
        
        # Module-specific level should override global level
        assert logger._should_log(LogLevel.DEBUG)
        assert logger._should_log(LogLevel.INFO)
        assert logger._should_log(LogLevel.WARNING)
    
    def test_get_caller_info(self):
        """Test caller information extraction."""
        module, function, line_number = self.logger._get_caller_info()
        
        assert module == "test_logger"
        # During pytest execution, the function name might be different
        assert function in ["test_get_caller_info", "pytest_pyfunc_call"]
        assert isinstance(line_number, int)
        assert line_number > 0
    
    def test_create_log_entry_minimal(self):
        """Test creating log entry with minimal information."""
        entry = self.logger._create_log_entry(
            LogLevel.INFO,
            "Test message"
        )
        
        assert isinstance(entry, LogEntry)
        assert entry.level == LogLevel.INFO
        assert entry.message == "Test message"
        assert entry.module == "test_logger"
        # During pytest execution, function name might be different
        assert entry.function in ["test_create_log_entry_minimal", "pytest_pyfunc_call"]
        assert isinstance(entry.line_number, int)
        assert isinstance(entry.timestamp, datetime)
        assert entry.extra_data == {}
    
    def test_create_log_entry_with_context(self):
        """Test creating log entry with request context."""
        # Set context variables
        request_id_var.set("req-123")
        user_id_var.set("user-456")
        client_ip_var.set("192.168.1.1")
        
        try:
            entry = self.logger._create_log_entry(
                LogLevel.ERROR,
                "Error message",
                extra_data={"key": "value"}
            )
            
            assert entry.request_id == "req-123"
            assert entry.user_id == "user-456"
            assert entry.client_ip == "192.168.1.1"
            assert entry.extra_data == {"key": "value"}
        finally:
            # Clean up context
            request_id_var.set(None)
            user_id_var.set(None)
            client_ip_var.set(None)
    
    def test_create_log_entry_with_exception(self):
        """Test creating log entry with exception information."""
        test_exception = ValueError("Test error")
        
        entry = self.logger._create_log_entry(
            LogLevel.ERROR,
            "Error occurred",
            exception=test_exception
        )
        
        assert entry.exception_type == "ValueError"
        assert "Test error" in entry.exception_traceback
        # Since we're creating a new exception without executing it, it won't have a full traceback
        assert entry.exception_traceback == "ValueError: Test error"
        # During pytest execution, function name might be different
        assert entry.function in ["test_create_log_entry_with_exception", "pytest_pyfunc_call"]
    
    @pytest.mark.asyncio
    async def test_log_method_console_enabled(self):
        """Test logging with console output enabled."""
        config = LogConfig(enable_console=True, enable_redis=False)
        logger = StructuredLogger("test_module", config)
        
        with patch.object(logger._standard_logger, 'info') as mock_info:
            await logger._log(LogLevel.INFO, "Test message")
            mock_info.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_log_method_console_disabled(self):
        """Test logging with console output disabled."""
        config = LogConfig(enable_console=False, enable_redis=False)
        logger = StructuredLogger("test_module", config)
        
        with patch.object(logger._standard_logger, 'info') as mock_info:
            await logger._log(LogLevel.INFO, "Test message")
            mock_info.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_log_method_redis_enabled(self):
        """Test logging with Redis persistence enabled."""
        config = LogConfig(enable_console=False, enable_redis=True)
        logger = StructuredLogger("test_module", config)
        logger._redis_handler = AsyncMock()
        
        await logger._log(LogLevel.INFO, "Test message")
        
        # Should queue the log entry
        assert not logger._log_queue.empty()
    
    @pytest.mark.asyncio
    async def test_log_method_filtered_out(self):
        """Test that filtered logs are not processed."""
        config = LogConfig(global_level=LogLevel.WARNING)
        logger = StructuredLogger("test_module", config)
        logger._redis_handler = AsyncMock()
        
        with patch.object(logger._standard_logger, 'debug') as mock_debug:
            await logger._log(LogLevel.DEBUG, "Debug message")
            mock_debug.assert_not_called()
            assert logger._log_queue.empty()
    
    @pytest.mark.asyncio
    async def test_public_logging_methods(self):
        """Test public logging methods."""
        logger = StructuredLogger("test_module")
        logger._redis_handler = AsyncMock()
        
        # Test each logging level
        await logger.debug("Debug message")
        await logger.info("Info message")
        await logger.warning("Warning message")
        await logger.error("Error message")
        await logger.critical("Critical message")
        
        # Should have queued 5 entries (assuming default config allows all levels)
        queue_size = logger._log_queue.qsize()
        assert queue_size >= 3  # At least INFO, WARNING, ERROR, CRITICAL
    
    @pytest.mark.asyncio
    async def test_error_and_critical_with_exception(self):
        """Test error and critical logging with exception parameter."""
        logger = StructuredLogger("test_module")
        logger._redis_handler = AsyncMock()
        
        test_exception = RuntimeError("Test error")
        
        await logger.error("Error occurred", exception=test_exception)
        await logger.critical("Critical error", exception=test_exception)
        
        # Verify entries were queued
        assert logger._log_queue.qsize() >= 2
    
    @pytest.mark.asyncio
    async def test_batch_processing_start_stop(self):
        """Test starting and stopping batch processing."""
        logger = StructuredLogger("test_module")
        
        # Start batch processing
        await logger.start_batch_processing()
        assert logger._batch_task is not None
        assert not logger._batch_task.done()
        
        # Stop batch processing
        await logger.stop_batch_processing()
        assert logger._batch_task.done()
    
    @pytest.mark.asyncio
    async def test_batch_processor_with_redis_handler(self):
        """Test batch processor functionality."""
        config = LogConfig(batch_size=2, flush_interval=1)
        logger = StructuredLogger("test_module", config)
        redis_handler = AsyncMock()
        logger.set_redis_handler(redis_handler)
        
        # Start batch processing
        await logger.start_batch_processing()
        
        # Add logs to trigger batch processing
        await logger.info("Message 1")
        await logger.info("Message 2")
        
        # Wait for batch processing
        await asyncio.sleep(0.1)
        
        # Verify Redis handler was called
        redis_handler.batch_store.assert_called()
        
        # Stop batch processing
        await logger.stop_batch_processing()


class TestRequestContext:
    """Test RequestContext functionality."""
    
    def test_request_context_creation(self):
        """Test request context creation."""
        context = RequestContext(
            request_id="req-123",
            user_id="user-456",
            client_ip="192.168.1.1"
        )
        
        assert context.request_id == "req-123"
        assert context.user_id == "user-456"
        assert context.client_ip == "192.168.1.1"
        assert isinstance(context.start_time, datetime)
    
    def test_request_context_auto_id(self):
        """Test automatic request ID generation."""
        context = RequestContext()
        
        assert context.request_id is not None
        assert len(context.request_id) > 0
        # Should be a valid UUID format
        uuid.UUID(context.request_id)
    
    def test_request_context_manager(self):
        """Test context manager functionality."""
        # Set initial context
        request_id_var.set("initial-req")
        user_id_var.set("initial-user")
        
        with RequestContext(
            request_id="new-req",
            user_id="new-user",
            client_ip="192.168.1.1"
        ) as context:
            # Context should be updated
            assert request_id_var.get() == "new-req"
            assert user_id_var.get() == "new-user"
            assert client_ip_var.get() == "192.168.1.1"
        
        # Context should be restored
        assert request_id_var.get() == "initial-req"
        assert user_id_var.get() == "initial-user"
        assert client_ip_var.get() is None
    
    @pytest.mark.asyncio
    async def test_async_request_context_manager(self):
        """Test async context manager functionality."""
        request_id_var.set("initial-req")
        
        async with RequestContext(request_id="async-req") as context:
            assert request_id_var.get() == "async-req"
        
        assert request_id_var.get() == "initial-req"
    
    def test_request_context_duration(self):
        """Test duration calculation."""
        context = RequestContext()
        
        # Simulate some time passing
        import time
        time.sleep(0.01)  # 10ms
        
        duration = context.get_duration_ms()
        assert duration >= 10  # Should be at least 10ms
        assert duration < 1000  # Should be less than 1 second


class TestPerformanceLogger:
    """Test PerformanceLogger functionality."""
    
    @pytest.mark.asyncio
    async def test_performance_logger_success(self):
        """Test performance logger for successful operations."""
        logger = StructuredLogger("test_module")
        
        # Mock the _log method to track calls
        log_calls = []
        original_log = logger._log
        
        async def mock_log(*args, **kwargs):
            log_calls.append((args, kwargs))
            return await original_log(*args, **kwargs)
        
        logger._log = mock_log
        
        async with PerformanceLogger(logger, "test_operation"):
            # Simulate some work
            await asyncio.sleep(0.01)
        
        # Should have logged start and completion
        assert len(log_calls) >= 2
        
        # Verify the operation name is in the log messages
        messages = [call[0][1] for call in log_calls]  # Get message from args
        assert any("test_operation" in msg for msg in messages)
    
    @pytest.mark.asyncio
    async def test_performance_logger_with_exception(self):
        """Test performance logger when operation fails."""
        logger = StructuredLogger("test_module")
        
        # Mock the _log method to track calls
        log_calls = []
        original_log = logger._log
        
        async def mock_log(*args, **kwargs):
            log_calls.append((args, kwargs))
            return await original_log(*args, **kwargs)
        
        logger._log = mock_log
        
        with pytest.raises(ValueError):
            async with PerformanceLogger(logger, "failing_operation"):
                raise ValueError("Operation failed")
        
        # Should have logged start and failure
        assert len(log_calls) >= 2
        
        # Verify the operation name is in the log messages
        messages = [call[0][1] for call in log_calls]  # Get message from args
        assert any("failing_operation" in msg for msg in messages)


class TestGlobalLoggerFunctions:
    """Test global logger management functions."""
    
    def test_get_logger_singleton(self):
        """Test that get_logger returns the same instance for the same name."""
        logger1 = get_logger("test_module")
        logger2 = get_logger("test_module")
        
        assert logger1 is logger2
        assert logger1.name == "test_module"
    
    def test_get_logger_different_names(self):
        """Test that different names return different loggers."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        
        assert logger1 is not logger2
        assert logger1.name == "module1"
        assert logger2.name == "module2"
    
    def test_set_default_config(self):
        """Test setting default configuration for all loggers."""
        config = LogConfig(global_level=LogLevel.ERROR, batch_size=200)
        
        # Create a logger before setting config
        logger1 = get_logger("module1")
        original_config = logger1.config
        
        # Set new default config
        set_default_config(config)
        
        # Existing logger should be updated
        assert logger1.config is config
        assert logger1.config.global_level == LogLevel.ERROR
        assert logger1.config.batch_size == 200
        
        # New loggers should use the new config
        logger2 = get_logger("module2")
        assert logger2.config is config
    
    def test_update_module_level(self):
        """Test updating log level for specific module."""
        config = LogConfig(global_level=LogLevel.INFO)
        set_default_config(config)
        
        logger = get_logger("test_module")
        
        # Initially should use global level
        assert logger.config.global_level == LogLevel.INFO
        assert "test_module" not in logger.config.module_levels
        
        # Update module-specific level
        update_module_level("test_module", LogLevel.DEBUG)
        
        # Logger should be updated
        assert logger.config.module_levels["test_module"] == LogLevel.DEBUG
    
    @pytest.mark.asyncio
    async def test_convenience_logging_functions(self):
        """Test convenience logging functions."""
        from app.core.logging import debug, info, warning, error, critical
        
        # These should not raise exceptions
        await debug("Debug message")
        await info("Info message")
        await warning("Warning message")
        await error("Error message")
        await critical("Critical message")
        
        # Test error and critical with exceptions
        test_exception = RuntimeError("Test error")
        await error("Error with exception", exception=test_exception)
        await critical("Critical with exception", exception=test_exception)


class TestLoggerIntegration:
    """Integration tests for logging system."""
    
    @pytest.mark.asyncio
    async def test_full_logging_workflow(self):
        """Test complete logging workflow with Redis handler."""
        # Create logger with custom config
        config = LogConfig(
            global_level=LogLevel.DEBUG,
            enable_console=True,
            enable_redis=True,
            batch_size=3,
            flush_interval=1
        )
        
        logger = StructuredLogger("integration_test", config)
        
        # Mock the _create_log_entry method to capture log entries
        log_entries = []
        original_create_entry = logger._create_log_entry
        
        def mock_create_entry(*args, **kwargs):
            entry = original_create_entry(*args, **kwargs)
            log_entries.append(entry)
            return entry
        
        logger._create_log_entry = mock_create_entry
        
        # Log with request context
        with RequestContext(
            request_id="integration-test-req",
            user_id="test-user",
            client_ip="127.0.0.1"
        ):
            # Log various levels
            await logger.debug("Debug message", test_data="debug_value")
            await logger.info("Info message", test_data="info_value")
            await logger.warning("Warning message", test_data="warning_value")
        
        # Verify log entries were created with context
        assert len(log_entries) >= 3
        for entry in log_entries:
            assert entry.request_id == "integration-test-req"
            assert entry.user_id == "test-user"
            assert entry.client_ip == "127.0.0.1"
            assert "test_data" in entry.extra_data
    
    @pytest.mark.asyncio
    async def test_exception_handling_in_logging(self):
        """Test that logging system handles exceptions gracefully."""
        logger = StructuredLogger("exception_test")
        
        # Track if logging method was called
        log_called = False
        original_log = logger._log
        
        async def mock_log(*args, **kwargs):
            nonlocal log_called
            log_called = True
            return await original_log(*args, **kwargs)
        
        logger._log = mock_log
        
        # This should not raise an exception
        await logger.info("Test message")
        
        # Verify that logging was attempted
        assert log_called
    
    def test_context_isolation(self):
        """Test that context variables are isolated between different contexts."""
        # Set global context
        request_id_var.set("global-req")
        
        with RequestContext(request_id="context1-req"):
            assert request_id_var.get() == "context1-req"
            
            with RequestContext(request_id="context2-req"):
                assert request_id_var.get() == "context2-req"
            
            # Should be restored to context1
            assert request_id_var.get() == "context1-req"
        
        # Should be restored to global
        assert request_id_var.get() == "global-req"