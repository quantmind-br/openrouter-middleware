"""Tests for logging models and validation."""

import pytest
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any

from app.models.logs import (
    LogEntry, LogLevel, LogFilter, LogStats, LogConfig,
    LogExportRequest, BulkDeleteRequest, LogEntryResponse,
    LogListResponse, LogStatsResponse
)


class TestLogEntry:
    """Test LogEntry model validation and behavior."""
    
    def test_log_entry_creation_minimal(self):
        """Test creating log entry with minimal required fields."""
        log = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module"
        )
        
        assert log.level == LogLevel.INFO
        assert log.message == "Test message"
        assert log.module == "test_module"
        assert isinstance(log.id, str)
        assert isinstance(log.timestamp, datetime)
        assert log.extra_data == {}
    
    def test_log_entry_creation_full(self):
        """Test creating log entry with all fields."""
        extra_data = {"key": "value", "number": 42}
        
        log = LogEntry(
            level=LogLevel.ERROR,
            message="Error occurred",
            module="test_module",
            function="test_function",
            line_number=123,
            request_id="req-123",
            user_id="user-456",
            client_ip="192.168.1.1",
            extra_data=extra_data,
            exception_type="ValueError",
            exception_traceback="Traceback...",
            duration_ms=150.5,
            memory_usage=1024
        )
        
        assert log.level == LogLevel.ERROR
        assert log.message == "Error occurred"
        assert log.module == "test_module"
        assert log.function == "test_function"
        assert log.line_number == 123
        assert log.request_id == "req-123"
        assert log.user_id == "user-456"
        assert log.client_ip == "192.168.1.1"
        assert log.extra_data == extra_data
        assert log.exception_type == "ValueError"
        assert log.exception_traceback == "Traceback..."
        assert log.duration_ms == 150.5
        assert log.memory_usage == 1024
    
    def test_log_entry_message_validation(self):
        """Test message validation."""
        # Empty message should raise validation error
        with pytest.raises(ValueError, match="Log message cannot be empty"):
            LogEntry(
                level=LogLevel.INFO,
                message="",
                module="test_module"
            )
        
        # Whitespace-only message should raise validation error
        with pytest.raises(ValueError, match="Log message cannot be empty"):
            LogEntry(
                level=LogLevel.INFO,
                message="   ",
                module="test_module"
            )
        
        # Valid message with whitespace should be stripped
        log = LogEntry(
            level=LogLevel.INFO,
            message="  Valid message  ",
            module="test_module"
        )
        assert log.message == "Valid message"
    
    def test_log_entry_module_validation(self):
        """Test module validation."""
        # Empty module should raise validation error
        with pytest.raises(ValueError, match="Module name cannot be empty"):
            LogEntry(
                level=LogLevel.INFO,
                message="Test message",
                module=""
            )
        
        # Whitespace-only module should raise validation error
        with pytest.raises(ValueError, match="Module name cannot be empty"):
            LogEntry(
                level=LogLevel.INFO,
                message="Test message",
                module="   "
            )
        
        # Valid module with whitespace should be stripped
        log = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="  test_module  "
        )
        assert log.module == "test_module"
    
    def test_log_entry_extra_data_validation(self):
        """Test extra data validation and serialization."""
        # Valid serializable data
        valid_data = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "list": [1, 2, 3],
            "dict": {"nested": "value"}
        }
        
        log = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module",
            extra_data=valid_data
        )
        assert log.extra_data == valid_data
        
        # Non-dict should raise validation error in Pydantic v2
        with pytest.raises(ValueError):
            LogEntry(
                level=LogLevel.INFO,
                message="Test message",
                module="test_module",
                extra_data="not a dict"
            )
        
        # Non-serializable values should be filtered out
        invalid_data = {
            "valid": "value",
            "invalid": lambda x: x,  # Functions are not JSON serializable
            "also_valid": 42
        }
        
        log = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module",
            extra_data=invalid_data
        )
        
        # Should only contain serializable fields
        assert "valid" in log.extra_data
        assert "also_valid" in log.extra_data
        assert "invalid" not in log.extra_data
    
    def test_log_entry_json_serialization(self):
        """Test JSON serialization of log entry."""
        log = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module"
        )
        
        # Should be able to serialize to JSON
        json_data = log.dict()
        assert isinstance(json_data, dict)
        assert json_data["level"] == "INFO"
        assert json_data["message"] == "Test message"
        assert json_data["module"] == "test_module"
        
        # Timestamp should be ISO format in JSON
        json_str = log.json()
        assert isinstance(json_str, str)
        assert "INFO" in json_str
        assert "Test message" in json_str


class TestLogFilter:
    """Test LogFilter model validation and behavior."""
    
    def test_log_filter_defaults(self):
        """Test default values for log filter."""
        filter_obj = LogFilter()
        
        assert filter_obj.level is None
        assert filter_obj.module is None
        assert filter_obj.request_id is None
        assert filter_obj.user_id is None
        assert filter_obj.start_time is None
        assert filter_obj.end_time is None
        assert filter_obj.search_query is None
        assert filter_obj.page == 1
        assert filter_obj.page_size == 50
        assert filter_obj.sort_by == "timestamp"
        assert filter_obj.sort_order == "desc"
    
    def test_log_filter_with_values(self):
        """Test log filter with all values set."""
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow()
        
        filter_obj = LogFilter(
            level=LogLevel.ERROR,
            module="test_module",
            request_id="req-123",
            user_id="user-456",
            start_time=start_time,
            end_time=end_time,
            search_query="error message",
            page=2,
            page_size=100,
            sort_by="level",
            sort_order="asc"
        )
        
        assert filter_obj.level == LogLevel.ERROR
        assert filter_obj.module == "test_module"
        assert filter_obj.request_id == "req-123"
        assert filter_obj.user_id == "user-456"
        assert filter_obj.start_time == start_time
        assert filter_obj.end_time == end_time
        assert filter_obj.search_query == "error message"
        assert filter_obj.page == 2
        assert filter_obj.page_size == 100
        assert filter_obj.sort_by == "level"
        assert filter_obj.sort_order == "asc"
    
    def test_log_filter_pagination_validation(self):
        """Test pagination validation."""
        # Page must be >= 1
        with pytest.raises(ValueError):
            LogFilter(page=0)
        
        # Page size must be >= 1 and <= 1000
        with pytest.raises(ValueError):
            LogFilter(page_size=0)
        
        with pytest.raises(ValueError):
            LogFilter(page_size=1001)
        
        # Valid values should work
        filter_obj = LogFilter(page=1, page_size=1000)
        assert filter_obj.page == 1
        assert filter_obj.page_size == 1000
    
    def test_log_filter_sort_order_validation(self):
        """Test sort order validation."""
        # Invalid sort order should raise error
        with pytest.raises(ValueError, match="Sort order must be 'asc' or 'desc'"):
            LogFilter(sort_order="invalid")
        
        # Valid sort orders should work
        filter_obj = LogFilter(sort_order="ASC")
        assert filter_obj.sort_order == "asc"
        
        filter_obj = LogFilter(sort_order="DESC")
        assert filter_obj.sort_order == "desc"


class TestLogStats:
    """Test LogStats model."""
    
    def test_log_stats_defaults(self):
        """Test default values for log stats."""
        stats = LogStats()
        
        assert stats.total_logs == 0
        assert stats.logs_by_level == {}
        assert stats.logs_by_module == {}
        assert stats.logs_by_hour == {}
        assert stats.error_rate == 0.0
        assert stats.top_errors == []
        assert stats.avg_response_time is None
        assert stats.memory_usage_trend == []
    
    def test_log_stats_with_data(self):
        """Test log stats with data."""
        logs_by_level = {
            LogLevel.INFO: 100,
            LogLevel.ERROR: 10,
            LogLevel.WARNING: 5
        }
        
        stats = LogStats(
            total_logs=115,
            logs_by_level=logs_by_level,
            logs_by_module={"module1": 50, "module2": 65},
            error_rate=8.7,
            avg_response_time=250.5
        )
        
        assert stats.total_logs == 115
        assert stats.logs_by_level == logs_by_level
        assert stats.error_rate == 8.7
        assert stats.avg_response_time == 250.5


class TestLogConfig:
    """Test LogConfig model validation and behavior."""
    
    def test_log_config_defaults(self):
        """Test default configuration values."""
        config = LogConfig()
        
        assert config.global_level == LogLevel.INFO
        assert config.enable_console is True
        assert config.enable_redis is True
        assert config.module_levels == {}
        assert config.retention_days == 30
        assert config.max_logs_per_day == 100000
        assert config.batch_size == 100
        assert config.flush_interval == 5
    
    def test_log_config_validation(self):
        """Test configuration validation."""
        # Test retention days bounds
        with pytest.raises(ValueError):
            LogConfig(retention_days=0)
        
        with pytest.raises(ValueError):
            LogConfig(retention_days=366)
        
        # Test max logs per day minimum
        with pytest.raises(ValueError):
            LogConfig(max_logs_per_day=999)
        
        # Test batch size bounds
        with pytest.raises(ValueError):
            LogConfig(batch_size=0)
        
        with pytest.raises(ValueError):
            LogConfig(batch_size=1001)
        
        # Test flush interval bounds
        with pytest.raises(ValueError):
            LogConfig(flush_interval=0)
        
        with pytest.raises(ValueError):
            LogConfig(flush_interval=61)
    
    def test_log_config_module_levels_validation(self):
        """Test module levels validation."""
        # Valid module levels
        module_levels = {
            "module1": LogLevel.DEBUG,
            "module2": "ERROR"  # String should be converted
        }
        
        config = LogConfig(module_levels=module_levels)
        
        assert config.module_levels["module1"] == LogLevel.DEBUG
        assert config.module_levels["module2"] == LogLevel.ERROR
        
        # Invalid log level should raise validation error in Pydantic v2
        with pytest.raises(ValueError):
            LogConfig(module_levels={
                "module1": LogLevel.INFO,
                "module2": "INVALID_LEVEL",  # This will cause validation error
                "module3": LogLevel.ERROR
            })


class TestLogExportRequest:
    """Test LogExportRequest model."""
    
    def test_export_request_defaults(self):
        """Test default export request values."""
        request = LogExportRequest()
        
        assert request.format == "json"
        assert isinstance(request.filters, LogFilter)
        assert request.include_metadata is True
        assert request.compress is False
    
    def test_export_request_format_validation(self):
        """Test export format validation."""
        # Valid formats
        for fmt in ["json", "csv", "txt"]:
            request = LogExportRequest(format=fmt)
            assert request.format == fmt
        
        # Case insensitive
        request = LogExportRequest(format="JSON")
        assert request.format == "json"
        
        # Invalid format
        with pytest.raises(ValueError, match="Format must be one of"):
            LogExportRequest(format="invalid")


class TestBulkDeleteRequest:
    """Test BulkDeleteRequest model."""
    
    def test_bulk_delete_request_validation(self):
        """Test bulk delete request validation."""
        # Empty log IDs should raise error
        with pytest.raises(ValueError, match="At least one log ID is required"):
            BulkDeleteRequest(log_ids=[], confirm=True)
        
        # Too many log IDs should raise error
        with pytest.raises(ValueError, match="Cannot delete more than 1000 logs"):
            BulkDeleteRequest(log_ids=[f"id-{i}" for i in range(1001)], confirm=True)
        
        # Confirm must be True
        with pytest.raises(ValueError, match="Confirmation is required"):
            BulkDeleteRequest(log_ids=["id-1"], confirm=False)
        
        # Valid request
        request = BulkDeleteRequest(log_ids=["id-1", "id-2"], confirm=True)
        assert request.log_ids == ["id-1", "id-2"]
        assert request.confirm is True


class TestResponseModels:
    """Test response models."""
    
    def test_log_entry_response(self):
        """Test LogEntryResponse model."""
        response = LogEntryResponse(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            level=LogLevel.INFO,
            message="Test message",
            module="test_module"
        )
        
        assert isinstance(response.id, str)
        assert isinstance(response.timestamp, datetime)
        assert response.level == LogLevel.INFO
        assert response.message == "Test message"
        assert response.module == "test_module"
    
    def test_log_list_response(self):
        """Test LogListResponse model."""
        logs = [
            LogEntryResponse(
                id=str(uuid.uuid4()),
                timestamp=datetime.utcnow(),
                level=LogLevel.INFO,
                message="Test message",
                module="test_module"
            )
        ]
        
        response = LogListResponse(
            logs=logs,
            total=100,
            page=1,
            page_size=50,
            total_pages=2,
            has_next=True,
            has_prev=False
        )
        
        assert len(response.logs) == 1
        assert response.total == 100
        assert response.page == 1
        assert response.page_size == 50
        assert response.total_pages == 2
        assert response.has_next is True
        assert response.has_prev is False
    
    def test_log_stats_response(self):
        """Test LogStatsResponse model."""
        stats = LogStats(total_logs=100)
        response = LogStatsResponse(stats=stats)
        
        assert response.stats.total_logs == 100
        assert isinstance(response.generated_at, datetime)