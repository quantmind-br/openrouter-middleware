"""Pydantic models for API key data structures."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class ClientKeyData(BaseModel):
    """Data model for client API keys stored in Redis."""
    
    user_id: str = Field(..., description="Identifier for the user/client")
    created_at: datetime = Field(..., description="When the key was created")
    last_used: Optional[datetime] = Field(None, description="When the key was last used")
    is_active: bool = Field(True, description="Whether the key is currently active")
    permissions: List[str] = Field(default_factory=list, description="List of permissions for this key")
    usage_count: int = Field(0, description="Number of times this key has been used")
    rate_limit: int = Field(1000, description="Rate limit for this key per hour")
    
    @validator("user_id")
    def validate_user_id(cls, v):
        if not v or not v.strip():
            raise ValueError("User ID cannot be empty")
        return v.strip()
    
    @validator("permissions")
    def validate_permissions(cls, v):
        valid_permissions = {
            "chat.completions",
            "models.list",
            "embeddings",
            "images.generate"
        }
        for permission in v:
            if permission not in valid_permissions:
                raise ValueError(f"Invalid permission: {permission}")
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class OpenRouterKeyData(BaseModel):
    """Data model for OpenRouter API keys stored in Redis."""
    
    key_hash: str = Field(..., description="SHA256 hash of the original key")
    added_at: datetime = Field(..., description="When the key was added to the system")
    is_active: bool = Field(True, description="Whether the key is currently active")
    is_healthy: bool = Field(True, description="Whether the key is healthy (not rate limited)")
    failure_count: int = Field(0, description="Number of consecutive failures")
    last_used: Optional[datetime] = Field(None, description="When the key was last used")
    rate_limit_reset: Optional[datetime] = Field(None, description="When rate limit resets")
    usage_count: int = Field(0, description="Total number of times this key has been used")
    last_error: Optional[str] = Field(None, description="Last error message if any")
    
    @validator("key_hash")
    def validate_key_hash(cls, v):
        if not v or len(v) != 64:  # SHA256 produces 64-character hex string
            raise ValueError("Key hash must be a valid SHA256 hash (64 characters)")
        return v
    
    @validator("failure_count")
    def validate_failure_count(cls, v):
        if v < 0:
            raise ValueError("Failure count cannot be negative")
        return v
    
    def is_rate_limited(self) -> bool:
        """Check if the key is currently rate limited."""
        if not self.rate_limit_reset:
            return False
        return datetime.utcnow() < self.rate_limit_reset
    
    def should_disable(self, max_failures: int = 5) -> bool:
        """Check if the key should be disabled due to failures."""
        return self.failure_count >= max_failures
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ClientKeyCreate(BaseModel):
    """Model for creating a new client API key."""
    
    user_id: str = Field(..., description="Identifier for the user/client")
    permissions: List[str] = Field(default_factory=list, description="Permissions for this key")
    rate_limit: int = Field(1000, description="Rate limit for this key per hour")
    
    @validator("user_id")
    def validate_user_id(cls, v):
        if not v or not v.strip():
            raise ValueError("User ID cannot be empty")
        return v.strip()


class ClientKeyResponse(BaseModel):
    """Response model for client API key operations."""
    
    key_hash: str = Field(..., description="Hash of the API key")
    user_id: str = Field(..., description="User identifier")
    created_at: datetime = Field(..., description="Creation timestamp")
    is_active: bool = Field(..., description="Whether key is active")
    permissions: List[str] = Field(..., description="Key permissions")
    usage_count: int = Field(..., description="Usage count")
    rate_limit: int = Field(..., description="Rate limit per hour")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class OpenRouterKeyCreate(BaseModel):
    """Model for adding a new OpenRouter API key."""
    
    api_key: str = Field(..., description="The OpenRouter API key", min_length=20)
    
    @validator("api_key")
    def validate_api_key(cls, v):
        if not v or not v.strip():
            raise ValueError("API key cannot be empty")
        return v.strip()


class OpenRouterKeyResponse(BaseModel):
    """Response model for OpenRouter API key operations."""
    
    key_hash: str = Field(..., description="Hash of the API key")
    added_at: datetime = Field(..., description="When key was added")
    is_active: bool = Field(..., description="Whether key is active")
    is_healthy: bool = Field(..., description="Whether key is healthy")
    failure_count: int = Field(..., description="Number of failures")
    usage_count: int = Field(..., description="Usage count")
    last_used: Optional[datetime] = Field(None, description="Last used timestamp")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class BulkImportRequest(BaseModel):
    """Model for bulk importing OpenRouter keys."""
    
    keys: List[str] = Field(..., description="List of OpenRouter API keys to import")
    
    @validator("keys")
    def validate_keys(cls, v):
        if not v:
            raise ValueError("Keys list cannot be empty")
        if len(v) > 100:  # Reasonable limit for bulk import
            raise ValueError("Cannot import more than 100 keys at once")
        
        # Validate each key
        for key in v:
            if not key or not key.strip() or len(key.strip()) < 20:
                raise ValueError("All keys must be valid (at least 20 characters)")
        
        return [key.strip() for key in v]


class BulkImportResponse(BaseModel):
    """Response model for bulk import operations."""
    
    total_keys: int = Field(..., description="Total number of keys processed")
    successful_imports: int = Field(..., description="Number of successfully imported keys")
    failed_imports: int = Field(..., description="Number of failed imports")
    errors: List[str] = Field(default_factory=list, description="List of error messages")
    imported_hashes: List[str] = Field(default_factory=list, description="Hashes of successfully imported keys")


class KeyUsageStats(BaseModel):
    """Model for key usage statistics."""
    
    total_requests: int = Field(0, description="Total number of requests")
    successful_requests: int = Field(0, description="Number of successful requests")
    failed_requests: int = Field(0, description="Number of failed requests")
    rate_limited_requests: int = Field(0, description="Number of rate limited requests")
    average_response_time: float = Field(0.0, description="Average response time in seconds")
    last_24h_requests: int = Field(0, description="Requests in last 24 hours")
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100