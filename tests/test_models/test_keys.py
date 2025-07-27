"""Tests for API key models."""

from datetime import datetime, timezone
from typing import List, Optional

import pytest
from pydantic import ValidationError

from app.models.keys import ClientAPIKey, OpenRouterAPIKey, BulkImportResult, BulkImportRequest


class TestClientAPIKey:
    """Test the ClientAPIKey model."""
    
    def test_client_api_key_creation(self):
        """Test creating a valid client API key."""
        key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="abc123def456",
            rate_limit=1000,
            permissions=["chat.completions", "models.list"]
        )
        
        assert key.user_id == "test_user"
        assert key.api_key_hash == "abc123def456"
        assert key.rate_limit == 1000
        assert key.permissions == ["chat.completions", "models.list"]
        assert key.is_active is True
        assert key.usage_count == 0
        assert isinstance(key.created_at, datetime)
        assert key.last_used is None
    
    def test_client_api_key_with_defaults(self):
        """Test creating client API key with default values."""
        key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="abc123def456"
        )
        
        assert key.rate_limit == 1000  # default
        assert key.permissions == []  # default
        assert key.is_active is True  # default
        assert key.usage_count == 0  # default
        assert key.last_used is None  # default
    
    def test_client_api_key_validation_errors(self):
        """Test validation errors for client API key."""
        # Missing required fields
        with pytest.raises(ValidationError):
            ClientAPIKey()
        
        # Empty user_id
        with pytest.raises(ValidationError):
            ClientAPIKey(user_id="", api_key_hash="abc123")
        
        # Empty api_key_hash
        with pytest.raises(ValidationError):
            ClientAPIKey(user_id="test_user", api_key_hash="")
        
        # Negative rate_limit
        with pytest.raises(ValidationError):
            ClientAPIKey(
                user_id="test_user",
                api_key_hash="abc123",
                rate_limit=-1
            )
    
    def test_client_api_key_optional_fields(self):
        """Test optional fields in client API key."""
        key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="abc123def456",
            rate_limit=500,
            permissions=None,  # Should default to empty list
            is_active=False,
            usage_count=10,
            last_used=datetime.now(timezone.utc)
        )
        
        assert key.permissions == []
        assert key.is_active is False
        assert key.usage_count == 10
        assert isinstance(key.last_used, datetime)
    
    def test_client_api_key_datetime_timezone(self):
        """Test that datetime fields have timezone info."""
        key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="abc123def456"
        )
        
        # created_at should have timezone
        assert key.created_at.tzinfo is not None
        
        # Test with explicit timezone
        now = datetime.now(timezone.utc)
        key_with_time = ClientAPIKey(
            user_id="test_user",
            api_key_hash="abc123def456",
            last_used=now
        )
        assert key_with_time.last_used == now
    
    def test_client_api_key_json_serialization(self):
        """Test JSON serialization/deserialization."""
        key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="abc123def456",
            rate_limit=1000,
            permissions=["chat.completions"],
            usage_count=5
        )
        
        # Serialize to dict
        key_dict = key.model_dump()
        assert isinstance(key_dict, dict)
        assert key_dict["user_id"] == "test_user"
        assert key_dict["rate_limit"] == 1000
        
        # Deserialize from dict
        key_restored = ClientAPIKey(**key_dict)
        assert key_restored.user_id == key.user_id
        assert key_restored.api_key_hash == key.api_key_hash
        assert key_restored.permissions == key.permissions


class TestOpenRouterAPIKey:
    """Test the OpenRouterAPIKey model."""
    
    def test_openrouter_api_key_creation(self):
        """Test creating a valid OpenRouter API key."""
        key = OpenRouterAPIKey(
            key_hash="def456ghi789",
            is_active=True,
            usage_count=10,
            failure_count=1
        )
        
        assert key.key_hash == "def456ghi789"
        assert key.is_active is True
        assert key.usage_count == 10
        assert key.failure_count == 1
        assert key.is_healthy is True  # default
        assert isinstance(key.added_at, datetime)
        assert key.last_used is None
        assert key.last_failure is None
    
    def test_openrouter_api_key_with_defaults(self):
        """Test creating OpenRouter API key with default values."""
        key = OpenRouterAPIKey(key_hash="def456ghi789")
        
        assert key.is_active is True  # default
        assert key.usage_count == 0  # default
        assert key.failure_count == 0  # default
        assert key.is_healthy is True  # default
        assert key.last_used is None  # default
        assert key.last_failure is None  # default
    
    def test_openrouter_api_key_validation_errors(self):
        """Test validation errors for OpenRouter API key."""
        # Missing required fields
        with pytest.raises(ValidationError):
            OpenRouterAPIKey()
        
        # Empty key_hash
        with pytest.raises(ValidationError):
            OpenRouterAPIKey(key_hash="")
        
        # Negative usage_count
        with pytest.raises(ValidationError):
            OpenRouterAPIKey(
                key_hash="def456ghi789",
                usage_count=-1
            )
        
        # Negative failure_count
        with pytest.raises(ValidationError):
            OpenRouterAPIKey(
                key_hash="def456ghi789",
                failure_count=-1
            )
    
    def test_openrouter_api_key_health_states(self):
        """Test different health states."""
        # Healthy key
        healthy_key = OpenRouterAPIKey(
            key_hash="healthy_key",
            is_healthy=True
        )
        assert healthy_key.is_healthy is True
        
        # Unhealthy key
        unhealthy_key = OpenRouterAPIKey(
            key_hash="unhealthy_key",
            is_healthy=False,
            last_failure=datetime.now(timezone.utc)
        )
        assert unhealthy_key.is_healthy is False
        assert unhealthy_key.last_failure is not None
    
    def test_openrouter_api_key_datetime_handling(self):
        """Test datetime field handling."""
        now = datetime.now(timezone.utc)
        key = OpenRouterAPIKey(
            key_hash="time_key",
            last_used=now,
            last_failure=now
        )
        
        assert key.last_used == now
        assert key.last_failure == now
        assert key.added_at.tzinfo is not None
    
    def test_openrouter_api_key_json_serialization(self):
        """Test JSON serialization/deserialization."""
        key = OpenRouterAPIKey(
            key_hash="serialization_key",
            usage_count=100,
            failure_count=5,
            is_healthy=False
        )
        
        # Serialize to dict
        key_dict = key.model_dump()
        assert isinstance(key_dict, dict)
        assert key_dict["key_hash"] == "serialization_key"
        assert key_dict["usage_count"] == 100
        assert key_dict["failure_count"] == 5
        assert key_dict["is_healthy"] is False
        
        # Deserialize from dict
        key_restored = OpenRouterAPIKey(**key_dict)
        assert key_restored.key_hash == key.key_hash
        assert key_restored.usage_count == key.usage_count
        assert key_restored.is_healthy == key.is_healthy


class TestBulkImportResult:
    """Test the BulkImportResult model."""
    
    def test_bulk_import_result_creation(self):
        """Test creating a bulk import result."""
        result = BulkImportResult(
            total_keys=10,
            successful_imports=8,
            failed_imports=2,
            errors=["Duplicate key", "Invalid format"]
        )
        
        assert result.total_keys == 10
        assert result.successful_imports == 8
        assert result.failed_imports == 2
        assert result.errors == ["Duplicate key", "Invalid format"]
    
    def test_bulk_import_result_with_defaults(self):
        """Test bulk import result with default values."""
        result = BulkImportResult(
            total_keys=5,
            successful_imports=5,
            failed_imports=0
        )
        
        assert result.errors == []  # default empty list
    
    def test_bulk_import_result_validation(self):
        """Test validation of bulk import result."""
        # Negative values should fail
        with pytest.raises(ValidationError):
            BulkImportResult(
                total_keys=-1,
                successful_imports=0,
                failed_imports=0
            )
        
        with pytest.raises(ValidationError):
            BulkImportResult(
                total_keys=10,
                successful_imports=-1,
                failed_imports=0
            )
        
        with pytest.raises(ValidationError):
            BulkImportResult(
                total_keys=10,
                successful_imports=0,
                failed_imports=-1
            )
    
    def test_bulk_import_result_math_consistency(self):
        """Test that the math adds up correctly."""
        # This is more of a logical test - the model doesn't enforce this
        # but the application logic should ensure total = successful + failed
        result = BulkImportResult(
            total_keys=10,
            successful_imports=7,
            failed_imports=3
        )
        
        assert result.successful_imports + result.failed_imports == result.total_keys


class TestBulkImportRequest:
    """Test the BulkImportRequest model."""
    
    def test_bulk_import_request_creation(self):
        """Test creating a bulk import request."""
        request = BulkImportRequest(
            keys=["sk-or-key1", "sk-or-key2", "sk-or-key3"],
            overwrite_existing=True
        )
        
        assert request.keys == ["sk-or-key1", "sk-or-key2", "sk-or-key3"]
        assert request.overwrite_existing is True
    
    def test_bulk_import_request_defaults(self):
        """Test bulk import request with default values."""
        request = BulkImportRequest(
            keys=["sk-or-key1"]
        )
        
        assert request.overwrite_existing is False  # default
    
    def test_bulk_import_request_validation(self):
        """Test validation of bulk import request."""
        # Empty keys list should fail
        with pytest.raises(ValidationError):
            BulkImportRequest(keys=[])
        
        # Missing keys should fail
        with pytest.raises(ValidationError):
            BulkImportRequest()
    
    def test_bulk_import_request_key_validation(self):
        """Test that individual keys are validated."""
        # Valid keys
        request = BulkImportRequest(
            keys=["sk-or-valid-key-1", "sk-or-valid-key-2"]
        )
        assert len(request.keys) == 2
        
        # Should accept any string format (validation happens elsewhere)
        request_any = BulkImportRequest(
            keys=["any-format-key", "another-key"]
        )
        assert len(request_any.keys) == 2