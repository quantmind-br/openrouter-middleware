"""Pydantic models for admin authentication and session management."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator


class AdminLogin(BaseModel):
    """Model for admin login form data."""
    
    username: str = Field(..., description="Admin username")
    password: str = Field(..., description="Admin password")
    
    @validator("username")
    def validate_username(cls, v):
        if not v or not v.strip():
            raise ValueError("Username cannot be empty")
        return v.strip()
    
    @validator("password")
    def validate_password(cls, v):
        if not v:
            raise ValueError("Password cannot be empty")
        return v


class AdminSession(BaseModel):
    """Model for admin session data stored in cookies/Redis."""
    
    user_id: str = Field(..., description="Admin user identifier")
    authenticated: bool = Field(..., description="Whether session is authenticated")
    session_token: str = Field(..., description="Unique session token")
    created_at: datetime = Field(..., description="When session was created")
    expires_at: datetime = Field(..., description="When session expires")
    csrf_token: Optional[str] = Field(None, description="CSRF protection token")
    permissions: List[str] = Field(default_factory=list, description="Session permissions")
    
    @validator("session_token")
    def validate_session_token(cls, v):
        if not v or len(v) < 20:
            raise ValueError("Session token must be at least 20 characters")
        return v
    
    def is_expired(self) -> bool:
        """Check if session is expired."""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if session is valid (authenticated and not expired)."""
        return self.authenticated and not self.is_expired()
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AdminLoginResponse(BaseModel):
    """Response model for successful admin login."""
    
    success: bool = Field(True, description="Login success status")
    message: str = Field("Login successful", description="Response message")
    redirect_url: str = Field("/admin", description="URL to redirect after login")
    session_expires_at: datetime = Field(..., description="When session expires")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AdminDashboardData(BaseModel):
    """Model for admin dashboard data."""
    
    total_client_keys: int = Field(0, description="Total number of client API keys")
    active_client_keys: int = Field(0, description="Number of active client keys")
    total_openrouter_keys: int = Field(0, description="Total number of OpenRouter keys")
    healthy_openrouter_keys: int = Field(0, description="Number of healthy OpenRouter keys")
    total_requests_today: int = Field(0, description="Total requests processed today")
    successful_requests_today: int = Field(0, description="Successful requests today")
    failed_requests_today: int = Field(0, description="Failed requests today")
    system_uptime: str = Field("", description="System uptime")
    redis_status: str = Field("", description="Redis connection status")
    
    @property
    def client_key_usage_rate(self) -> float:
        """Calculate percentage of active client keys."""
        if self.total_client_keys == 0:
            return 0.0
        return (self.active_client_keys / self.total_client_keys) * 100
    
    @property
    def openrouter_key_health_rate(self) -> float:
        """Calculate percentage of healthy OpenRouter keys."""
        if self.total_openrouter_keys == 0:
            return 0.0
        return (self.healthy_openrouter_keys / self.total_openrouter_keys) * 100
    
    @property
    def success_rate_today(self) -> float:
        """Calculate success rate for today."""
        if self.total_requests_today == 0:
            return 0.0
        return (self.successful_requests_today / self.total_requests_today) * 100


class SystemStatus(BaseModel):
    """Model for system status information."""
    
    status: str = Field(..., description="Overall system status")
    timestamp: datetime = Field(..., description="Status check timestamp")
    services: Dict[str, str] = Field(default_factory=dict, description="Individual service statuses")
    metrics: Dict[str, float] = Field(default_factory=dict, description="System metrics")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AdminAction(BaseModel):
    """Model for admin actions/audit log."""
    
    action: str = Field(..., description="Action performed")
    resource: str = Field(..., description="Resource affected")
    resource_id: Optional[str] = Field(None, description="ID of affected resource")
    timestamp: datetime = Field(..., description="When action was performed")
    admin_user: str = Field(..., description="Admin user who performed action")
    details: Dict = Field(default_factory=dict, description="Additional action details")
    success: bool = Field(True, description="Whether action was successful")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AdminError(BaseModel):
    """Model for admin error responses."""
    
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[str] = Field(None, description="Additional error details")
    timestamp: datetime = Field(..., description="When error occurred")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class CSRFToken(BaseModel):
    """Model for CSRF token response."""
    
    csrf_token: str = Field(..., description="CSRF protection token")
    expires_at: datetime = Field(..., description="When token expires")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AdminSettings(BaseModel):
    """Model for admin configurable settings."""
    
    max_client_keys_per_user: int = Field(5, description="Maximum client keys per user")
    default_rate_limit: int = Field(1000, description="Default rate limit per hour")
    key_rotation_interval: int = Field(300, description="Key rotation interval in seconds")
    max_failures_before_disable: int = Field(5, description="Max failures before disabling key")
    session_timeout_hours: int = Field(24, description="Session timeout in hours")
    enable_analytics: bool = Field(True, description="Enable analytics collection")
    log_level: str = Field("INFO", description="Logging level")
    
    @validator("max_client_keys_per_user")
    def validate_max_keys(cls, v):
        if v < 1 or v > 50:
            raise ValueError("Max client keys per user must be between 1 and 50")
        return v
    
    @validator("default_rate_limit")
    def validate_rate_limit(cls, v):
        if v < 10 or v > 10000:
            raise ValueError("Default rate limit must be between 10 and 10000")
        return v
    
    @validator("log_level")
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()


class AdminNotification(BaseModel):
    """Model for admin notifications."""
    
    id: str = Field(..., description="Notification ID")
    type: str = Field(..., description="Notification type")
    title: str = Field(..., description="Notification title")
    message: str = Field(..., description="Notification message")
    severity: str = Field("info", description="Notification severity")
    created_at: datetime = Field(..., description="When notification was created")
    read: bool = Field(False, description="Whether notification has been read")
    
    @validator("severity")
    def validate_severity(cls, v):
        valid_severities = ["info", "warning", "error", "success"]
        if v.lower() not in valid_severities:
            raise ValueError(f"Severity must be one of: {valid_severities}")
        return v.lower()
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }