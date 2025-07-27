"""API key management service with Redis storage and health monitoring."""

import json
import logging
from datetime import datetime
from typing import List, Optional, Tuple

import redis.asyncio as redis

from app.core.redis import RedisOperations, get_redis_client
from app.core.security import hash_api_key, generate_api_key
from app.models.keys import (
    ClientKeyData, 
    OpenRouterKeyData, 
    ClientKeyCreate,
    OpenRouterKeyCreate,
    BulkImportResponse,
    KeyUsageStats
)

logger = logging.getLogger(__name__)


class KeyManager:
    """Manages API keys for both clients and OpenRouter with Redis storage."""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = RedisOperations(redis_client)
        self.client_key_prefix = "clientkey"
        self.openrouter_key_prefix = "openrouter"
        self.user_keys_prefix = "user_keys"
        self.key_stats_prefix = "key_stats"
        
    # Client Key Management
    
    async def create_client_key(self, key_data: ClientKeyCreate) -> Tuple[str, str]:
        """Create a new client API key and store in Redis."""
        try:
            # Generate new API key and hash
            api_key = generate_api_key()
            key_hash = hash_api_key(api_key)
            
            # Create client key data
            client_data = ClientKeyData(
                user_id=key_data.user_id,
                created_at=datetime.utcnow(),
                permissions=key_data.permissions,
                rate_limit=key_data.rate_limit
            )
            
            # Store in Redis with proper serialization
            redis_key = f"{self.client_key_prefix}:{key_hash}"
            client_dict = {
                'user_id': client_data.user_id,
                'created_at': client_data.created_at.isoformat(),
                'last_used': client_data.last_used.isoformat() if client_data.last_used else '',
                'is_active': str(client_data.is_active).lower(),
                'permissions': json.dumps(client_data.permissions),
                'usage_count': str(client_data.usage_count),
                'rate_limit': str(client_data.rate_limit)
            }
            await self.redis.hash_set_safely(redis_key, client_dict)
            
            # Add to user's key set
            user_keys_key = f"{self.user_keys_prefix}:{key_data.user_id}"
            await self.redis.add_to_set_safely(user_keys_key, key_hash)
            
            logger.info(f"Created client key for user {key_data.user_id}")
            return api_key, key_hash
            
        except Exception as e:
            logger.error(f"Failed to create client key for user {key_data.user_id}: {e}")
            raise
    
    async def validate_client_key(self, api_key: str) -> Optional[ClientKeyData]:
        """Validate a client API key and return its data."""
        try:
            key_hash = hash_api_key(api_key)
            redis_key = f"{self.client_key_prefix}:{key_hash}"
            
            # Get key data from Redis
            key_data = await self.redis.hash_get_all_safely(redis_key)
            if not key_data:
                return None
            
            # Parse the stored data
            client_data = ClientKeyData(
                user_id=key_data.get('user_id'),
                created_at=datetime.fromisoformat(key_data.get('created_at')),
                last_used=datetime.fromisoformat(key_data.get('last_used')) if key_data.get('last_used') else None,
                is_active=key_data.get('is_active', 'true').lower() == 'true',
                permissions=json.loads(key_data.get('permissions', '[]')),
                usage_count=int(key_data.get('usage_count', 0)),
                rate_limit=int(key_data.get('rate_limit', 1000))
            )
            
            # Check if key is active
            if not client_data.is_active:
                return None
            
            # Update last used timestamp and usage count
            await self._update_client_key_usage(key_hash, client_data)
            
            return client_data
            
        except Exception as e:
            logger.error(f"Failed to validate client key: {e}")
            return None
    
    async def _update_client_key_usage(self, key_hash: str, client_data: ClientKeyData):
        """Update client key usage statistics."""
        try:
            redis_key = f"{self.client_key_prefix}:{key_hash}"
            
            # Update last used and usage count
            client_data.last_used = datetime.utcnow()
            client_data.usage_count += 1
            
            # Update in Redis
            updates = {
                'last_used': client_data.last_used.isoformat(),
                'usage_count': str(client_data.usage_count)
            }
            await self.redis.hash_set_safely(redis_key, updates)
            
        except Exception as e:
            logger.error(f"Failed to update client key usage for {key_hash}: {e}")
    
    async def get_client_keys(self, user_id: Optional[str] = None) -> List[ClientKeyData]:
        """Get all client keys, optionally filtered by user."""
        try:
            if user_id:
                # Get keys for specific user
                user_keys_key = f"{self.user_keys_prefix}:{user_id}"
                key_hashes = await self.redis.get_set_members_safely(user_keys_key)
            else:
                # Get all client keys (this is expensive - consider pagination)
                # For now, we'll scan for all keys with client key prefix
                key_hashes = await self._scan_keys_by_prefix(self.client_key_prefix)
            
            client_keys = []
            for key_hash in key_hashes:
                redis_key = f"{self.client_key_prefix}:{key_hash}"
                key_data = await self.redis.hash_get_all_safely(redis_key)
                
                if key_data:
                    client_data = ClientKeyData(
                        user_id=key_data.get('user_id'),
                        created_at=datetime.fromisoformat(key_data.get('created_at')),
                        last_used=datetime.fromisoformat(key_data.get('last_used')) if key_data.get('last_used') else None,
                        is_active=key_data.get('is_active', 'true').lower() == 'true',
                        permissions=json.loads(key_data.get('permissions', '[]')),
                        usage_count=int(key_data.get('usage_count', 0)),
                        rate_limit=int(key_data.get('rate_limit', 1000))
                    )
                    client_keys.append(client_data)
            
            return client_keys
            
        except Exception as e:
            logger.error(f"Failed to get client keys: {e}")
            return []
    
    async def get_client_keys_with_hashes(self, user_id: Optional[str] = None) -> List[Tuple[str, ClientKeyData]]:
        """Get all client keys with their hashes, optionally filtered by user."""
        try:
            if user_id:
                # Get keys for specific user
                user_keys_key = f"{self.user_keys_prefix}:{user_id}"
                key_hashes = await self.redis.get_set_members_safely(user_keys_key)
            else:
                # Get all client keys (this is expensive - consider pagination)
                # For now, we'll scan for all keys with client key prefix
                key_hashes = await self._scan_keys_by_prefix(self.client_key_prefix)
            
            client_keys_with_hashes = []
            for key_hash in key_hashes:
                redis_key = f"{self.client_key_prefix}:{key_hash}"
                key_data = await self.redis.hash_get_all_safely(redis_key)
                
                if key_data:
                    client_data = ClientKeyData(
                        user_id=key_data.get('user_id'),
                        created_at=datetime.fromisoformat(key_data.get('created_at')),
                        last_used=datetime.fromisoformat(key_data.get('last_used')) if key_data.get('last_used') else None,
                        is_active=key_data.get('is_active', 'true').lower() == 'true',
                        permissions=json.loads(key_data.get('permissions', '[]')),
                        usage_count=int(key_data.get('usage_count', 0)),
                        rate_limit=int(key_data.get('rate_limit', 1000))
                    )
                    client_keys_with_hashes.append((key_hash, client_data))
            
            return client_keys_with_hashes
            
        except Exception as e:
            logger.error(f"Failed to get client keys with hashes: {e}")
            return []
    
    async def deactivate_client_key(self, key_hash: str) -> bool:
        """Deactivate a client API key."""
        try:
            redis_key = f"{self.client_key_prefix}:{key_hash}"
            
            # Check if key exists
            key_data = await self.redis.hash_get_all_safely(redis_key)
            if not key_data:
                return False
            
            # Update active status
            await self.redis.hash_set_safely(redis_key, {'is_active': 'false'})
            
            logger.info(f"Deactivated client key {key_hash}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deactivate client key {key_hash}: {e}")
            return False
    
    async def delete_client_key(self, key_hash: str) -> bool:
        """Permanently delete a client API key."""
        try:
            redis_key = f"{self.client_key_prefix}:{key_hash}"
            
            # Check if key exists and get user_id for cleanup
            key_data = await self.redis.hash_get_all_safely(redis_key)
            if not key_data:
                return False
            
            user_id = key_data.get('user_id')
            if not user_id:
                logger.error(f"Client key {key_hash} missing user_id, cannot clean up user_keys set")
                return False
            
            # Perform atomic deletion from both Redis structures
            # 1. Remove the key hash data
            await self.redis.client.delete(redis_key)
            
            # 2. Remove key hash from user's key set
            user_keys_key = f"{self.user_keys_prefix}:{user_id}"
            await self.redis.client.srem(user_keys_key, key_hash)
            
            logger.info(f"Permanently deleted client key {key_hash} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete client key {key_hash}: {e}")
            return False
    
    async def reactivate_client_key(self, key_hash: str) -> bool:
        """Reactivate a deactivated client API key."""
        try:
            redis_key = f"{self.client_key_prefix}:{key_hash}"
            
            # Check if key exists
            key_data = await self.redis.hash_get_all_safely(redis_key)
            if not key_data:
                return False
            
            # Update active status
            await self.redis.hash_set_safely(redis_key, {'is_active': 'true'})
            
            logger.info(f"Reactivated client key {key_hash}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reactivate client key {key_hash}: {e}")
            return False
    
    # OpenRouter Key Management
    
    async def add_openrouter_key(self, key_data: OpenRouterKeyCreate) -> Optional[str]:
        """Add a new OpenRouter API key to the pool."""
        try:
            # Hash the key for storage
            key_hash = hash_api_key(key_data.api_key)
            
            # Check if key already exists
            redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
            existing_key = await self.redis.hash_get_all_safely(redis_key)
            if existing_key:
                logger.warning(f"OpenRouter key {key_hash} already exists")
                return None
            
            # Create OpenRouter key data
            openrouter_data = OpenRouterKeyData(
                key_hash=key_hash,
                added_at=datetime.utcnow()
            )
            
            # Store in Redis
            await self.redis.hash_set_safely(redis_key, openrouter_data.dict())
            
            # Add to active keys set for quick lookup
            await self.redis.add_to_set_safely("openrouter:active", key_hash)
            
            logger.info(f"Added OpenRouter key {key_hash}")
            return key_hash
            
        except Exception as e:
            logger.error(f"Failed to add OpenRouter key: {e}")
            return None
    
    async def get_healthy_openrouter_keys(self) -> List[OpenRouterKeyData]:
        """Get all healthy OpenRouter keys for rotation."""
        try:
            # Get all active keys
            active_keys = await self.redis.get_set_members_safely("openrouter:active")
            
            healthy_keys = []
            for key_hash in active_keys:
                redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
                key_data = await self.redis.hash_get_all_safely(redis_key)
                
                if key_data:
                    openrouter_data = OpenRouterKeyData(
                        key_hash=key_data.get('key_hash'),
                        added_at=datetime.fromisoformat(key_data.get('added_at')),
                        is_active=key_data.get('is_active', 'true').lower() == 'true',
                        is_healthy=key_data.get('is_healthy', 'true').lower() == 'true',
                        failure_count=int(key_data.get('failure_count', 0)),
                        last_used=datetime.fromisoformat(key_data.get('last_used')) if key_data.get('last_used') else None,
                        rate_limit_reset=datetime.fromisoformat(key_data.get('rate_limit_reset')) if key_data.get('rate_limit_reset') else None,
                        usage_count=int(key_data.get('usage_count', 0)),
                        last_error=key_data.get('last_error')
                    )
                    
                    # Only include healthy and active keys
                    if openrouter_data.is_active and openrouter_data.is_healthy and not openrouter_data.is_rate_limited():
                        healthy_keys.append(openrouter_data)
            
            return healthy_keys
            
        except Exception as e:
            logger.error(f"Failed to get healthy OpenRouter keys: {e}")
            return []
    
    async def mark_key_unhealthy(self, key_hash: str, error_message: str = None):
        """Mark an OpenRouter key as unhealthy due to failures."""
        try:
            redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
            
            # Get current key data
            key_data = await self.redis.hash_get_all_safely(redis_key)
            if not key_data:
                return
            
            # Update failure count and health status
            failure_count = int(key_data.get('failure_count', 0)) + 1
            updates = {
                'failure_count': str(failure_count),
                'last_error': error_message or "Unknown error",
                'is_healthy': 'false' if failure_count >= 5 else 'true'  # Disable after 5 failures
            }
            
            await self.redis.hash_set_safely(redis_key, updates)
            
            # Remove from active set if too many failures
            if failure_count >= 5:
                await self.redis.client.srem("openrouter:active", key_hash)
                logger.warning(f"Disabled OpenRouter key {key_hash} after {failure_count} failures")
            
        except Exception as e:
            logger.error(f"Failed to mark key {key_hash} as unhealthy: {e}")
    
    async def mark_key_rate_limited(self, key_hash: str, reset_time: datetime):
        """Mark an OpenRouter key as rate limited."""
        try:
            redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
            
            updates = {
                'rate_limit_reset': reset_time.isoformat(),
                'is_healthy': 'false'
            }
            
            await self.redis.hash_set_safely(redis_key, updates)
            
            logger.info(f"Marked OpenRouter key {key_hash} as rate limited until {reset_time}")
            
        except Exception as e:
            logger.error(f"Failed to mark key {key_hash} as rate limited: {e}")
    
    async def update_key_usage(self, key_hash: str):
        """Update OpenRouter key usage statistics."""
        try:
            redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
            
            # Get current data
            key_data = await self.redis.hash_get_all_safely(redis_key)
            if not key_data:
                return
            
            # Update usage
            usage_count = int(key_data.get('usage_count', 0)) + 1
            updates = {
                'last_used': datetime.utcnow().isoformat(),
                'usage_count': str(usage_count),
                'is_healthy': 'true',  # Reset health on successful use
                'failure_count': '0'   # Reset failure count on success
            }
            
            await self.redis.hash_set_safely(redis_key, updates)
            
        except Exception as e:
            logger.error(f"Failed to update key usage for {key_hash}: {e}")
    
    async def bulk_import_openrouter_keys(self, keys: List[str]) -> BulkImportResponse:
        """Bulk import OpenRouter API keys."""
        total_keys = len(keys)
        successful_imports = 0
        failed_imports = 0
        errors = []
        imported_hashes = []
        
        for api_key in keys:
            try:
                key_create = OpenRouterKeyCreate(api_key=api_key)
                key_hash = await self.add_openrouter_key(key_create)
                
                if key_hash:
                    successful_imports += 1
                    imported_hashes.append(key_hash)
                else:
                    failed_imports += 1
                    errors.append(f"Key already exists or invalid: {api_key[:10]}...")
                    
            except Exception as e:
                failed_imports += 1
                errors.append(f"Failed to import key {api_key[:10]}...: {str(e)}")
        
        return BulkImportResponse(
            total_keys=total_keys,
            successful_imports=successful_imports,
            failed_imports=failed_imports,
            errors=errors,
            imported_hashes=imported_hashes
        )
    
    async def get_openrouter_keys(self) -> List[OpenRouterKeyData]:
        """Get all OpenRouter keys."""
        try:
            # Scan for all OpenRouter keys
            key_hashes = await self._scan_keys_by_prefix(self.openrouter_key_prefix)
            
            openrouter_keys = []
            for key_hash in key_hashes:
                redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
                key_data = await self.redis.hash_get_all_safely(redis_key)
                
                if key_data:
                    openrouter_data = OpenRouterKeyData(
                        key_hash=key_data.get('key_hash'),
                        added_at=datetime.fromisoformat(key_data.get('added_at')),
                        is_active=key_data.get('is_active', 'true').lower() == 'true',
                        is_healthy=key_data.get('is_healthy', 'true').lower() == 'true',
                        failure_count=int(key_data.get('failure_count', 0)),
                        last_used=datetime.fromisoformat(key_data.get('last_used')) if key_data.get('last_used') else None,
                        rate_limit_reset=datetime.fromisoformat(key_data.get('rate_limit_reset')) if key_data.get('rate_limit_reset') else None,
                        usage_count=int(key_data.get('usage_count', 0)),
                        last_error=key_data.get('last_error')
                    )
                    openrouter_keys.append(openrouter_data)
            
            return openrouter_keys
            
        except Exception as e:
            logger.error(f"Failed to get OpenRouter keys: {e}")
            return []
    
    async def delete_openrouter_key(self, key_hash: str) -> bool:
        """Delete an OpenRouter key."""
        try:
            redis_key = f"{self.openrouter_key_prefix}:{key_hash}"
            
            # Delete from Redis
            deleted = await self.redis.delete_safely(redis_key)
            
            # Remove from active set
            await self.redis.client.srem("openrouter:active", key_hash)
            
            if deleted:
                logger.info(f"Deleted OpenRouter key {key_hash}")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to delete OpenRouter key {key_hash}: {e}")
            return False
    
    # Utility Methods
    
    async def _scan_keys_by_prefix(self, prefix: str) -> List[str]:
        """Scan Redis keys by prefix and extract the hash part."""
        try:
            pattern = f"{prefix}:*"
            keys = []
            
            async for key in self.redis.client.scan_iter(match=pattern):
                # Extract the hash part from the key
                if ":" in key:
                    hash_part = key.split(":", 1)[1]
                    keys.append(hash_part)
            
            return keys
            
        except Exception as e:
            logger.error(f"Failed to scan keys with prefix {prefix}: {e}")
            return []
    
    async def get_key_stats(self) -> KeyUsageStats:
        """Get overall key usage statistics."""
        try:
            # This would require implementing stats collection
            # For now, return empty stats
            return KeyUsageStats()
            
        except Exception as e:
            logger.error(f"Failed to get key stats: {e}")
            return KeyUsageStats()


# Dependency for FastAPI
async def get_key_manager() -> KeyManager:
    """Get KeyManager instance for dependency injection."""
    redis_client = await get_redis_client()
    return KeyManager(redis_client)