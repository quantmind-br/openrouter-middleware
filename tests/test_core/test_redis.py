"""Tests for Redis connection management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.redis import RedisManager


class TestRedisManager:
    """Test the RedisManager class."""
    
    @pytest.mark.asyncio
    async def test_redis_manager_initialization(self):
        """Test Redis manager initialization."""
        manager = RedisManager("redis://localhost:6379/0")
        
        assert manager.redis_url == "redis://localhost:6379/0"
        assert manager.password is None
        assert manager._redis is None
        assert manager._pool is None
    
    @pytest.mark.asyncio
    async def test_redis_manager_with_password(self):
        """Test Redis manager with password."""
        manager = RedisManager("redis://localhost:6379/0", "test_password")
        
        assert manager.redis_url == "redis://localhost:6379/0"
        assert manager.password == "test_password"
    
    @pytest.mark.asyncio
    @patch('redis.asyncio.ConnectionPool.from_url')
    @patch('redis.asyncio.Redis')
    async def test_get_redis_connection(self, mock_redis, mock_pool):
        """Test getting Redis connection."""
        # Mock the Redis instance and pool
        mock_redis_instance = AsyncMock()
        mock_pool_instance = MagicMock()
        
        mock_redis.return_value = mock_redis_instance
        mock_pool.return_value = mock_pool_instance
        
        manager = RedisManager("redis://localhost:6379/0")
        
        # First call should create connection
        redis = await manager.get_redis()
        
        assert redis is mock_redis_instance
        assert manager._redis is mock_redis_instance
        assert manager._pool is mock_pool_instance
        
        # Second call should return cached connection
        redis2 = await manager.get_redis()
        assert redis2 is mock_redis_instance
        
        # Verify pool was created with correct parameters
        mock_pool.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=20,
            retry_on_timeout=True,
            health_check_interval=30,
            socket_keepalive=True
        )
    
    @pytest.mark.asyncio
    @patch('redis.asyncio.ConnectionPool.from_url')
    @patch('redis.asyncio.Redis')
    async def test_get_redis_connection_with_password(self, mock_redis, mock_pool):
        """Test getting Redis connection with password."""
        mock_redis_instance = AsyncMock()
        mock_pool_instance = MagicMock()
        
        mock_redis.return_value = mock_redis_instance
        mock_pool.return_value = mock_pool_instance
        
        manager = RedisManager("redis://localhost:6379/0", "test_password")
        
        redis = await manager.get_redis()
        
        # Verify Redis was created with connection pool
        mock_redis.assert_called_once_with(connection_pool=mock_pool_instance)
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, redis_manager):
        """Test health check when Redis is healthy."""
        # Mock ping to return True
        redis_manager._redis = AsyncMock()
        redis_manager._redis.ping.return_value = True
        
        is_healthy = await redis_manager.health_check()
        
        assert is_healthy is True
        redis_manager._redis.ping.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, redis_manager):
        """Test health check when Redis is unhealthy."""
        # Mock ping to raise exception
        redis_manager._redis = AsyncMock()
        redis_manager._redis.ping.side_effect = Exception("Connection failed")
        
        is_healthy = await redis_manager.health_check()
        
        assert is_healthy is False
        redis_manager._redis.ping.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_health_check_no_connection(self, redis_manager):
        """Test health check when no Redis connection exists."""
        # No Redis connection
        redis_manager._redis = None
        
        is_healthy = await redis_manager.health_check()
        
        assert is_healthy is False
    
    @pytest.mark.asyncio
    async def test_close_connection(self, redis_manager):
        """Test closing Redis connection."""
        # Mock Redis instance and pool
        redis_manager._redis = AsyncMock()
        redis_manager._pool = MagicMock()
        redis_manager._pool.aclose = AsyncMock()
        
        await redis_manager.close()
        
        # Verify cleanup
        redis_manager._pool.aclose.assert_called_once()
        assert redis_manager._redis is None
        assert redis_manager._pool is None
    
    @pytest.mark.asyncio
    async def test_close_no_connection(self, redis_manager):
        """Test closing when no connection exists."""
        # No Redis connection
        redis_manager._redis = None
        redis_manager._pool = None
        
        # Should not raise exception
        await redis_manager.close()
    
    @pytest.mark.asyncio
    @patch('redis.asyncio.ConnectionPool.from_url')
    @patch('redis.asyncio.Redis')
    async def test_connection_error_handling(self, mock_redis, mock_pool):
        """Test handling of connection errors."""
        # Mock connection to raise exception
        mock_pool.side_effect = Exception("Connection failed")
        
        manager = RedisManager("redis://localhost:6379/0")
        
        with pytest.raises(Exception, match="Connection failed"):
            await manager.get_redis()
    
    @pytest.mark.asyncio
    async def test_get_redis_idempotent(self, redis_manager):
        """Test that multiple calls to get_redis return the same instance."""
        # Mock Redis instance
        mock_redis_instance = AsyncMock()
        
        with patch('redis.asyncio.Redis') as mock_redis, \
             patch('redis.asyncio.ConnectionPool.from_url') as mock_pool:
            
            mock_redis.return_value = mock_redis_instance
            mock_pool.return_value = MagicMock()
            
            # Multiple calls should return same instance
            redis1 = await redis_manager.get_redis()
            redis2 = await redis_manager.get_redis()
            redis3 = await redis_manager.get_redis()
            
            assert redis1 is redis2 is redis3
            
            # Connection pool should only be created once
            mock_pool.assert_called_once()
            mock_redis.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_context_manager_usage(self):
        """Test using RedisManager as async context manager."""
        manager = RedisManager("redis://localhost:6379/0")
        
        with patch.object(manager, 'close') as mock_close:
            async with manager:
                pass
            
            mock_close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connection_pool_parameters(self):
        """Test that connection pool is created with correct parameters."""
        with patch('redis.asyncio.ConnectionPool.from_url') as mock_pool:
            mock_pool.return_value = MagicMock()
            
            manager = RedisManager("redis://localhost:6379/0")
            await manager.get_redis()
            
            mock_pool.assert_called_once_with(
                "redis://localhost:6379/0",
                max_connections=20,
                retry_on_timeout=True,
                health_check_interval=30,
                socket_keepalive=True
            )