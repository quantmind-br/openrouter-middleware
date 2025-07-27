"""Pydantic models for logging system data structures."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class LogLevel(str, Enum):
    """Log level enumeration."""
    DEBUG = "DEBUG"
    INFO = "INFO" 
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogEntry(BaseModel):
    """Data model for structured log entries stored in Redis."""
    
    # Core fields
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique log entry ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the log was created")
    level: LogLevel = Field(..., description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    message: str = Field(..., description="Log message content")
    
    # Context fields
    module: str = Field(..., description="Python module that generated the log")
    function: Optional[str] = Field(None, description="Function name where log was generated")
    line_number: Optional[int] = Field(None, description="Line number in source code")
    last_used: Optional[datetime] = Field(None, description="Last access time for cleanup purposes")
    
    # Request context
    request_id: Optional[str] = Field(None, description="Correlation ID for request tracing")
    user_id: Optional[str] = Field(None, description="User ID if available")
    client_ip: Optional[str] = Field(None, description="Client IP address")
    
    # Additional data
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="Additional structured data")
    exception_type: Optional[str] = Field(None, description="Exception class name if applicable")
    exception_traceback: Optional[str] = Field(None, description="Full exception traceback")
    
    # Performance metrics
    duration_ms: Optional[float] = Field(None, description="Operation duration in milliseconds")
    memory_usage: Optional[int] = Field(None, description="Memory usage in bytes")
    
    @validator("message")
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Log message cannot be empty")
        return v.strip()
    
    @validator("module") 
    def validate_module(cls, v):
        if not v or not v.strip():
            raise ValueError("Module name cannot be empty")
        return v.strip()
    
    @validator("extra_data")
    def validate_extra_data(cls, v):
        # Ensure all keys are strings and values are JSON serializable
        if not isinstance(v, dict):
            return {}
        
        cleaned = {}
        for key, value in v.items():
            if isinstance(key, str) and key.strip():
                # Basic JSON serializable check
                try:
                    import json
                    json.dumps(value)
                    cleaned[key.strip()] = value
                except (TypeError, ValueError):
                    # Skip non-serializable values
                    continue
        return cleaned
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class LogFilter(BaseModel):
    """Model for log filtering parameters."""
    
    level: Optional[LogLevel] = Field(None, description="Filter by log level")
    module: Optional[str] = Field(None, description="Filter by module name (supports wildcards)")
    request_id: Optional[str] = Field(None, description="Filter by request ID")
    user_id: Optional[str] = Field(None, description="Filter by user ID")
    
    # Time range
    start_time: Optional[datetime] = Field(None, description="Start time for date range filter")
    end_time: Optional[datetime] = Field(None, description="End time for date range filter")
    
    # Search
    search_query: Optional[str] = Field(None, description="Search in message content")
    
    # Pagination
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(50, ge=1, le=1000, description="Number of logs per page")
    
    # Sorting
    sort_by: str = Field("timestamp", description="Field to sort by")
    sort_order: str = Field("desc", description="Sort order: asc or desc")
    
    @validator("sort_order")
    def validate_sort_order(cls, v):
        if v.lower() not in ["asc", "desc"]:
            raise ValueError("Sort order must be 'asc' or 'desc'")
        return v.lower()


class LogStats(BaseModel):
    """Model for log statistics."""
    
    total_logs: int = Field(0, description="Total number of logs")
    logs_by_level: Dict[LogLevel, int] = Field(default_factory=dict, description="Count by log level")
    logs_by_module: Dict[str, int] = Field(default_factory=dict, description="Count by module")
    logs_by_hour: Dict[str, int] = Field(default_factory=dict, description="Count by hour (last 24h)")
    
    # Error statistics
    error_rate: float = Field(0.0, description="Error rate as percentage")
    top_errors: List[Dict[str, Any]] = Field(default_factory=list, description="Most common errors")
    
    # Performance statistics  
    avg_response_time: Optional[float] = Field(None, description="Average response time in ms")
    memory_usage_trend: List[Dict[str, Any]] = Field(default_factory=list, description="Memory usage over time")


class LogConfig(BaseModel):
    """Model for dynamic log configuration."""
    
    # Global settings
    global_level: LogLevel = Field(LogLevel.INFO, description="Global minimum log level")
    enable_console: bool = Field(True, description="Enable console logging")
    enable_redis: bool = Field(True, description="Enable Redis persistence")
    
    # Module-specific levels
    module_levels: Dict[str, LogLevel] = Field(default_factory=dict, description="Per-module log levels")
    
    # Retention settings
    retention_days: int = Field(30, ge=1, le=365, description="Log retention period in days")
    max_logs_per_day: int = Field(100000, ge=1000, description="Maximum logs per day")
    
    # Performance settings
    batch_size: int = Field(100, ge=1, le=1000, description="Batch size for Redis operations")
    flush_interval: int = Field(5, ge=1, le=60, description="Flush interval in seconds")
    
    @validator("module_levels")
    def validate_module_levels(cls, v):
        # Ensure all values are valid LogLevel enums
        validated = {}
        for module, level in v.items():
            if isinstance(level, str):
                try:
                    validated[module] = LogLevel(level.upper())
                except ValueError:
                    continue  # Skip invalid levels
            elif isinstance(level, LogLevel):
                validated[module] = level
        return validated


class LogExportRequest(BaseModel):
    """Model for log export requests."""
    
    format: str = Field("json", description="Export format: json, csv, txt")
    filters: LogFilter = Field(default_factory=LogFilter, description="Filters to apply")
    include_metadata: bool = Field(True, description="Include metadata in export")
    compress: bool = Field(False, description="Compress export file")
    
    @validator("format")
    def validate_format(cls, v):
        valid_formats = ["json", "csv", "txt"]
        if v.lower() not in valid_formats:
            raise ValueError(f"Format must be one of: {', '.join(valid_formats)}")
        return v.lower()


class BulkDeleteRequest(BaseModel):
    """Model for bulk delete operations."""
    
    log_ids: List[str] = Field(..., description="List of log IDs to delete")
    confirm: bool = Field(False, description="Confirmation flag for safety")
    
    @validator("log_ids")
    def validate_log_ids(cls, v):
        if not v:
            raise ValueError("At least one log ID is required")
        if len(v) > 1000:
            raise ValueError("Cannot delete more than 1000 logs at once")
        return v
    
    @validator("confirm")
    def validate_confirm(cls, v):
        if not v:
            raise ValueError("Confirmation is required for bulk delete operations")
        return v


# Response models for API endpoints

class LogEntryResponse(BaseModel):
    """Response model for log entry API endpoints."""
    
    id: str
    timestamp: datetime
    level: LogLevel
    message: str
    module: str
    function: Optional[str] = None
    line_number: Optional[int] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    client_ip: Optional[str] = None
    extra_data: Dict[str, Any] = {}
    exception_type: Optional[str] = None
    duration_ms: Optional[float] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class LogListResponse(BaseModel):
    """Response model for paginated log lists."""
    
    logs: List[LogEntryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool


class LogStatsResponse(BaseModel):
    """Response model for log statistics."""
    
    stats: LogStats
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class LogConfigResponse(BaseModel):
    """Response model for log configuration operations."""
    
    success: bool
    message: str
    config: Optional[LogConfig] = None
    
    
class LogCleanupResponse(BaseModel):
    """Response model for log cleanup operations."""
    
    success: bool
    message: str
    deleted_count: int
    
    
class LogModulesResponse(BaseModel):
    """Response model for log modules list."""
    
    modules: List[str]
    count: int
    
    
class LogLevelsResponse(BaseModel):
    """Response model for log levels information."""
    
    levels: List[str]
    descriptions: Dict[str, str]