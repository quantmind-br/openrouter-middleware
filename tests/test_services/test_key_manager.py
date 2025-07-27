"""Tests for key management service."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.key_manager import KeyManager
from app.models.keys import ClientAPIKey, OpenRouterAPIKey, BulkImportResult


class TestKeyManager:
    """Test the KeyManager service."""
    
    @pytest.mark.asyncio
    async def test_create_client_key(self, key_manager: KeyManager, sample_client_key_data: dict):
        """Test creating a client API key."""
        result = await key_manager.create_client_key(**sample_client_key_data)
        
        assert isinstance(result, dict)
        assert "api_key" in result
        assert result["api_key"].startswith("sk-or-")
        assert "key_data" in result
        
        key_data = result["key_data"]
        assert key_data.user_id == sample_client_key_data["user_id"]
        assert key_data.rate_limit == sample_client_key_data["rate_limit"]
        assert key_data.permissions == sample_client_key_data["permissions"]
        assert key_data.is_active is True
    
    @pytest.mark.asyncio
    async def test_create_client_key_duplicate_user(self, key_manager: KeyManager):
        """Test creating a client key for an existing user."""
        user_data = {"user_id": "duplicate_user", "rate_limit": 1000}
        
        # Create first key
        await key_manager.create_client_key(**user_data)
        
        # Try to create second key for same user - should raise error
        with pytest.raises(ValueError, match="already exists"):
            await key_manager.create_client_key(**user_data)
    
    @pytest.mark.asyncio
    async def test_get_client_key_by_user_id(self, key_manager: KeyManager):
        """Test retrieving client key by user ID."""
        user_data = {"user_id": "test_get_user", "rate_limit": 500}
        
        # Create key
        result = await key_manager.create_client_key(**user_data)
        
        # Retrieve by user ID
        retrieved = await key_manager.get_client_key_by_user_id("test_get_user")
        
        assert retrieved is not None
        assert retrieved.user_id == "test_get_user"
        assert retrieved.rate_limit == 500
    
    @pytest.mark.asyncio
    async def test_get_client_key_by_hash(self, key_manager: KeyManager):
        """Test retrieving client key by hash."""
        user_data = {"user_id": "test_get_hash", "rate_limit": 750}
        
        # Create key
        result = await key_manager.create_client_key(**user_data)
        api_key = result["api_key"]
        key_hash = key_manager.security_manager.hash_api_key(api_key)
        
        # Retrieve by hash
        retrieved = await key_manager.get_client_key_by_hash(key_hash)
        
        assert retrieved is not None
        assert retrieved.user_id == "test_get_hash"
        assert retrieved.api_key_hash == key_hash
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_client_key(self, key_manager: KeyManager):
        """Test retrieving non-existent client key."""
        # By user ID
        result = await key_manager.get_client_key_by_user_id("nonexistent_user")
        assert result is None
        
        # By hash
        result = await key_manager.get_client_key_by_hash("nonexistent_hash")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_update_client_key_usage(self, key_manager: KeyManager):
        """Test updating client key usage statistics."""
        user_data = {"user_id": "test_usage", "rate_limit": 1000}
        
        # Create key
        result = await key_manager.create_client_key(**user_data)
        api_key = result["api_key"]
        key_hash = key_manager.security_manager.hash_api_key(api_key)
        
        # Update usage
        await key_manager.update_client_key_usage(key_hash)
        
        # Verify update
        retrieved = await key_manager.get_client_key_by_hash(key_hash)
        assert retrieved.usage_count == 1
        assert retrieved.last_used is not None
        
        # Update again
        await key_manager.update_client_key_usage(key_hash)
        retrieved = await key_manager.get_client_key_by_hash(key_hash)
        assert retrieved.usage_count == 2
    
    @pytest.mark.asyncio
    async def test_list_client_keys(self, key_manager: KeyManager):
        """Test listing all client keys."""
        # Create multiple keys
        users = ["list_user_1", "list_user_2", "list_user_3"]
        for user in users:
            await key_manager.create_client_key(user_id=user, rate_limit=1000)
        
        # List all keys
        keys = await key_manager.list_client_keys()
        
        # Should contain at least our created keys
        user_ids = [key.user_id for key in keys]
        for user in users:
            assert user in user_ids
    
    @pytest.mark.asyncio
    async def test_add_openrouter_key(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test adding an OpenRouter API key."""
        result = await key_manager.add_openrouter_key(sample_openrouter_key)
        
        assert isinstance(result, OpenRouterAPIKey)
        assert result.is_active is True
        assert result.is_healthy is True
        assert result.usage_count == 0
        assert result.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_add_duplicate_openrouter_key(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test adding duplicate OpenRouter key."""
        # Add first time
        await key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Try to add again - should raise error
        with pytest.raises(ValueError, match="already exists"):
            await key_manager.add_openrouter_key(sample_openrouter_key)
    
    @pytest.mark.asyncio
    async def test_get_openrouter_key(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test retrieving OpenRouter key."""
        # Add key
        added_key = await key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Retrieve by hash
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        
        assert retrieved is not None
        assert retrieved.key_hash == added_key.key_hash
        assert retrieved.is_active is True
    
    @pytest.mark.asyncio
    async def test_update_openrouter_key_usage(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test updating OpenRouter key usage."""
        # Add key
        added_key = await key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Update usage (success)
        await key_manager.update_openrouter_key_usage(added_key.key_hash, success=True)
        
        # Verify update
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        assert retrieved.usage_count == 1
        assert retrieved.failure_count == 0
        assert retrieved.is_healthy is True
        assert retrieved.last_used is not None
        
        # Update usage (failure)
        await key_manager.update_openrouter_key_usage(added_key.key_hash, success=False)
        
        # Verify failure update
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        assert retrieved.usage_count == 1  # Unchanged
        assert retrieved.failure_count == 1
        assert retrieved.last_failure is not None
    
    @pytest.mark.asyncio
    async def test_mark_openrouter_key_unhealthy(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test marking OpenRouter key as unhealthy."""
        # Add key
        added_key = await key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Mark unhealthy
        await key_manager.mark_openrouter_key_unhealthy(added_key.key_hash)
        
        # Verify
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        assert retrieved.is_healthy is False
        assert retrieved.last_failure is not None
    
    @pytest.mark.asyncio
    async def test_mark_openrouter_key_healthy(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test marking OpenRouter key as healthy."""
        # Add key and mark unhealthy
        added_key = await key_manager.add_openrouter_key(sample_openrouter_key)
        await key_manager.mark_openrouter_key_unhealthy(added_key.key_hash)
        
        # Mark healthy again
        await key_manager.mark_openrouter_key_healthy(added_key.key_hash)
        
        # Verify
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        assert retrieved.is_healthy is True
    
    @pytest.mark.asyncio
    async def test_list_openrouter_keys(self, key_manager: KeyManager, sample_openrouter_keys: list[str]):
        """Test listing OpenRouter keys."""
        # Add multiple keys
        for key in sample_openrouter_keys:
            await key_manager.add_openrouter_key(key)
        
        # List all keys
        keys = await key_manager.list_openrouter_keys()
        
        # Should contain at least our created keys
        assert len(keys) >= len(sample_openrouter_keys)
        
        # All should be active by default
        for key in keys:
            assert key.is_active is True
    
    @pytest.mark.asyncio
    async def test_list_healthy_openrouter_keys(self, key_manager: KeyManager, sample_openrouter_keys: list[str]):
        """Test listing only healthy OpenRouter keys."""
        # Add keys and mark some unhealthy
        for i, key in enumerate(sample_openrouter_keys):
            added_key = await key_manager.add_openrouter_key(key)
            if i % 2 == 0:  # Mark every other key unhealthy
                await key_manager.mark_openrouter_key_unhealthy(added_key.key_hash)
        
        # List healthy keys
        healthy_keys = await key_manager.list_healthy_openrouter_keys()
        
        # All returned keys should be healthy
        for key in healthy_keys:
            assert key.is_healthy is True
            assert key.is_active is True
    
    @pytest.mark.asyncio
    async def test_delete_openrouter_key(self, key_manager: KeyManager, sample_openrouter_key: str):
        """Test deleting OpenRouter key."""
        # Add key
        added_key = await key_manager.add_openrouter_key(sample_openrouter_key)
        
        # Verify it exists
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        assert retrieved is not None
        
        # Delete key
        await key_manager.delete_openrouter_key(added_key.key_hash)
        
        # Verify deletion
        retrieved = await key_manager.get_openrouter_key(added_key.key_hash)
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_bulk_import_openrouter_keys(self, key_manager: KeyManager, sample_openrouter_keys: list[str]):
        """Test bulk importing OpenRouter keys."""
        result = await key_manager.bulk_import_openrouter_keys(sample_openrouter_keys)
        
        assert isinstance(result, BulkImportResult)
        assert result.total_keys == len(sample_openrouter_keys)
        assert result.successful_imports == len(sample_openrouter_keys)
        assert result.failed_imports == 0
        assert len(result.errors) == 0
    
    @pytest.mark.asyncio
    async def test_bulk_import_with_duplicates(self, key_manager: KeyManager, sample_openrouter_keys: list[str]):
        """Test bulk import with duplicate keys."""
        # Add one key first
        await key_manager.add_openrouter_key(sample_openrouter_keys[0])
        
        # Try to import all keys (including the duplicate)
        result = await key_manager.bulk_import_openrouter_keys(sample_openrouter_keys)
        
        assert result.total_keys == len(sample_openrouter_keys)
        assert result.successful_imports == len(sample_openrouter_keys) - 1  # One duplicate
        assert result.failed_imports == 1
        assert len(result.errors) == 1
        assert "already exists" in result.errors[0]
    
    @pytest.mark.asyncio
    async def test_bulk_import_overwrite_existing(self, key_manager: KeyManager, sample_openrouter_keys: list[str]):
        """Test bulk import with overwrite flag."""
        # Add one key first
        await key_manager.add_openrouter_key(sample_openrouter_keys[0])
        
        # Import with overwrite=True
        result = await key_manager.bulk_import_openrouter_keys(
            sample_openrouter_keys, 
            overwrite_existing=True
        )
        
        assert result.total_keys == len(sample_openrouter_keys)
        assert result.successful_imports == len(sample_openrouter_keys)
        assert result.failed_imports == 0
        assert len(result.errors) == 0
    
    @pytest.mark.asyncio
    async def test_redis_error_handling(self, key_manager: KeyManager):
        """Test handling of Redis errors."""
        # Mock Redis to raise an exception
        key_manager.redis_manager._redis = AsyncMock()
        key_manager.redis_manager._redis.hget.side_effect = Exception("Redis error")
        
        # Should handle error gracefully
        result = await key_manager.get_client_key_by_user_id("test_user")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_json_serialization_in_redis(self, key_manager: KeyManager):
        """Test that data is properly serialized/deserialized in Redis."""
        user_data = {"user_id": "json_test", "rate_limit": 1500, "permissions": ["chat.completions"]}
        
        # Create key
        result = await key_manager.create_client_key(**user_data)
        
        # Manually check Redis storage
        redis = await key_manager.redis_manager.get_redis()
        stored_data = await redis.hget("client_keys", result["key_data"].api_key_hash)
        
        # Should be valid JSON
        parsed_data = json.loads(stored_data)
        assert parsed_data["user_id"] == "json_test"
        assert parsed_data["rate_limit"] == 1500
        assert parsed_data["permissions"] == ["chat.completions"]
    
    @pytest.mark.asyncio
    async def test_concurrent_key_creation(self, key_manager: KeyManager):
        """Test concurrent key creation doesn't cause issues."""
        import asyncio
        
        # Create multiple keys concurrently
        tasks = []
        for i in range(5):
            task = key_manager.create_client_key(
                user_id=f"concurrent_user_{i}",
                rate_limit=1000
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed
        for result in results:
            assert not isinstance(result, Exception)
            assert "api_key" in result
    
    @pytest.mark.asyncio
    async def test_key_expiration_handling(self, key_manager: KeyManager):
        """Test handling of expired or non-existent keys."""
        # Test with non-existent hash
        result = await key_manager.update_client_key_usage("nonexistent_hash")
        # Should not raise exception, just ignore
        
        result = await key_manager.update_openrouter_key_usage("nonexistent_hash", success=True)
        # Should not raise exception, just ignore