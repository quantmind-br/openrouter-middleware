"""Redis connection and lifecycle management with async connection pooling."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RedisManager:
    """Redis connection manager with connection pooling and health checks."""
    
    def __init__(self):
        self.pool: Optional[redis.ConnectionPool] = None
        self.client: Optional[redis.Redis] = None
        self._health_check_task: Optional[asyncio.Task] = None
    
    async def initialize(self) -> None:
        """Initialize Redis connection pool and client."""
        try:
            # Parse Redis URL
            redis_url = settings.redis_url
            if settings.redis_password:
                # Inject password into URL if provided separately
                if "://" in redis_url:
                    protocol, rest = redis_url.split("://", 1)
                    if "@" not in rest:
                        host_part = rest
                        redis_url = f"{protocol}://:{settings.redis_password}@{host_part}"
            
            # Create connection pool with advanced configuration
            self.pool = redis.ConnectionPool.from_url(
                redis_url,
                max_connections=settings.redis_max_connections,
                retry_on_timeout=settings.redis_retry_on_timeout,
                retry_on_error=[ConnectionError, TimeoutError],
                retry=Retry(ExponentialBackoff(), retries=3),
                health_check_interval=30,  # Health check every 30 seconds
                socket_keepalive=True,
                socket_keepalive_options={},
                encoding='utf-8',
                decode_responses=True
            )
            
            # Create Redis client from pool
            self.client = redis.Redis.from_pool(self.pool)
            
            # Test connection
            await self.client.ping()
            logger.info("Redis connection established successfully")
            
            # Start health check task
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            raise
    
    async def close(self) -> None:
        """Close Redis connections and cleanup resources."""
        try:
            # Cancel health check task
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
            
            # Close Redis client
            if self.client:
                await self.client.aclose()
                logger.info("Redis client closed")
            
            # Close connection pool
            if self.pool:
                await self.pool.aclose()
                logger.info("Redis connection pool closed")
                
        except Exception as e:
            logger.error(f"Error closing Redis connections: {e}")
    
    async def _health_check_loop(self) -> None:
        """Periodic health check for Redis connection."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                if self.client:
                    await self.client.ping()
                    logger.debug("Redis health check passed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Redis health check failed: {e}")
    
    async def get_client(self) -> redis.Redis:
        """Get Redis client instance."""
        if not self.client:
            raise RuntimeError("Redis client not initialized. Call initialize() first.")
        return self.client
    
    async def is_healthy(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            if not self.client:
                return False
            await self.client.ping()
            return True
        except Exception:
            return False


# Global Redis manager instance
redis_manager = RedisManager()


@asynccontextmanager
async def lifespan_redis() -> AsyncGenerator[RedisManager, None]:
    """Lifespan context manager for Redis connection management."""
    try:
        # Initialize Redis on startup
        await redis_manager.initialize()
        logger.info("Redis manager initialized")
        yield redis_manager
    finally:
        # Cleanup Redis on shutdown
        await redis_manager.close()
        logger.info("Redis manager closed")


async def get_redis_client() -> redis.Redis:
    """Dependency for getting Redis client in FastAPI endpoints."""
    return await redis_manager.get_client()


# Utility functions for common Redis operations
class RedisOperations:
    """Common Redis operations with error handling."""
    
    def __init__(self, client: redis.Redis):
        self.client = client
    
    async def set_with_expiry(self, key: str, value: str, expiry: int = 3600) -> bool:
        """Set a key with expiration time."""
        try:
            return await self.client.setex(key, expiry, value)
        except Exception as e:
            logger.error(f"Failed to set key {key}: {e}")
            return False
    
    async def get_safely(self, key: str) -> Optional[str]:
        """Get a key value safely with error handling."""
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Failed to get key {key}: {e}")
            return None
    
    async def delete_safely(self, key: str) -> bool:
        """Delete a key safely with error handling."""
        try:
            result = await self.client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Failed to delete key {key}: {e}")
            return False
    
    async def hash_set_safely(self, key: str, mapping: dict) -> bool:
        """Set hash mapping safely with error handling."""
        try:
            return await self.client.hset(key, mapping=mapping)
        except Exception as e:
            logger.error(f"Failed to set hash {key}: {e}")
            return False
    
    async def hash_get_all_safely(self, key: str) -> dict:
        """Get all hash fields safely with error handling."""
        try:
            return await self.client.hgetall(key)
        except Exception as e:
            logger.error(f"Failed to get hash {key}: {e}")
            return {}
    
    async def add_to_set_safely(self, key: str, *values) -> int:
        """Add values to set safely with error handling."""
        try:
            return await self.client.sadd(key, *values)
        except Exception as e:
            logger.error(f"Failed to add to set {key}: {e}")
            return 0
    
    async def get_set_members_safely(self, key: str) -> set:
        """Get set members safely with error handling."""
        try:
            return await self.client.smembers(key)
        except Exception as e:
            logger.error(f"Failed to get set members {key}: {e}")
            return set()


async def get_redis_operations() -> RedisOperations:
    """Dependency for getting Redis operations helper."""
    client = await get_redis_client()
    return RedisOperations(client)