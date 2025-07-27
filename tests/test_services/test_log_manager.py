"""Tests for log manager service and Redis operations."""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

import fakeredis.aioredis

from app.services.log_manager import LogManager, RedisLogHandler, get_log_manager
from app.core.redis import RedisOperations
from app.models.logs import (
    LogEntry, LogLevel, LogFilter, LogStats, LogConfig,
    LogListResponse, LogEntryResponse
)


class TestRedisLogHandler:
    """Test Redis log handler functionality."""
    
    @pytest.fixture
    def redis_handler(self):
        """Create Redis handler with fake Redis instance."""
        import redis.asyncio as redis
        fake_redis = fakeredis.aioredis.FakeRedis()
        handler = RedisLogHandler(fake_redis)
        return handler
    
    @pytest.mark.asyncio
    async def test_redis_handler_store_single(self, redis_handler):
        """Test storing a single log entry."""
        log_entry = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module"
        )
        
        # Store the entry
        await redis_handler.store(log_entry)
        
        # Verify it was stored
        redis = redis_handler.client  # Use raw Redis client, not RedisOperations wrapper
        stored_message = await redis.hget(f"log_entry:{log_entry.id}", "message")
        assert stored_message is not None
        assert stored_message.decode() == "Test message"
        
        stored_level = await redis.hget(f"log_entry:{log_entry.id}", "level")
        # Enums are stored with their value only
        assert stored_level.decode() == "INFO"
        
        stored_module = await redis.hget(f"log_entry:{log_entry.id}", "module")
        assert stored_module.decode() == "test_module"
    
    @pytest.mark.asyncio
    async def test_redis_handler_batch_store(self, redis_handler):
        """Test batch storing multiple log entries."""
        log_entries = [
            LogEntry(
                level=LogLevel.INFO,
                message=f"Test message {i}",
                module="test_module"
            )
            for i in range(5)
        ]
        
        # Batch store the entries
        await redis_handler.batch_store(log_entries)
        
        # Verify all entries were stored
        redis = redis_handler.client  # Use raw Redis client, not RedisOperations wrapper
        for entry in log_entries:
            stored_message = await redis.hget(f"log_entry:{entry.id}", "message")
            assert stored_message is not None
            assert "Test message" in stored_message.decode()
    
    @pytest.mark.asyncio
    async def test_redis_handler_indexing(self, redis_handler):
        """Test that log entries are properly indexed."""
        log_entry = LogEntry(
            level=LogLevel.ERROR,
            message="Error message",
            module="error_module",
            request_id="req-123"
        )
        
        await redis_handler.store(log_entry)
        
        redis = redis_handler.client  # Use raw Redis client
        
        # Check timestamp index - using correct key format from implementation
        timestamp_key = "log_index:timestamp"
        timestamp_score = int(log_entry.timestamp.timestamp())
        timestamp_members = await redis.zrange(timestamp_key, 0, -1)
        assert log_entry.id.encode() in timestamp_members
        
        # Check level index - using correct key format from implementation
        level_key = "log_index:level:ERROR"
        level_members = await redis.smembers(level_key)
        assert log_entry.id.encode() in level_members
        
        # Check module index - using correct key format from implementation
        module_key = "log_index:module:error_module"
        module_members = await redis.smembers(module_key)
        assert log_entry.id.encode() in module_members
        
        # Check request ID index (if present)
        if log_entry.request_id:
            req_key = f"log_index:request:{log_entry.request_id}"
            req_members = await redis.smembers(req_key)
            assert log_entry.id.encode() in req_members
    
    @pytest.mark.asyncio
    async def test_redis_handler_ttl(self, redis_handler):
        """Test that TTL is set on log entries."""
        log_entry = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module"
        )
        
        await redis_handler.store(log_entry)
        
        redis = redis_handler.client  # Use raw Redis client
        ttl = await redis.ttl(f"log_entry:{log_entry.id}")
        
        # TTL should be set (not -1 which means no expiry)
        assert ttl > 0
        # Should be around 30 days (allow some variance)
        assert ttl > 30 * 24 * 3600 - 100  # 30 days minus 100 seconds


class TestLogManager:
    """Test LogManager functionality."""
    
    @pytest.fixture
    def log_manager(self):
        """Create LogManager with fake Redis instance."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        manager = LogManager(fake_redis)
        return manager
    
    async def create_sample_logs(self):
        """Create sample log entries for testing."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        
        logs = []
        base_time = datetime.utcnow()
        
        for i in range(10):
            level = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR][i % 4]
            log_entry = LogEntry(
                level=level,
                message=f"Test message {i}",
                module=f"module_{i % 3}",
                request_id=f"req-{i % 5}" if i % 2 == 0 else None,
                user_id=f"user-{i % 3}" if i % 3 == 0 else None,
                timestamp=base_time + timedelta(minutes=i)
            )
            logs.append(log_entry)
        
        # Store all logs
        for log in logs:
            await log_manager.handler.store(log)
        
        # Return both logs and log_manager as a tuple
        return logs, log_manager
    
    @pytest.mark.asyncio
    async def test_log_manager_initialization(self):
        """Test LogManager initialization."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        manager = LogManager(fake_redis)
        
        assert manager.client is fake_redis  # Raw Redis client
        assert isinstance(manager.redis, RedisOperations)  # Redis operations wrapper
        assert isinstance(manager.handler, RedisLogHandler)
        # Config is accessed via get_config() method, not stored as attribute
    
    @pytest.mark.asyncio
    async def test_log_manager_store_log(self):
        """Test storing a log through LogManager."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        log_entry = LogEntry(
            level=LogLevel.INFO,
            message="Manager test message",
            module="test_module"
        )
        
        await log_manager.store_log(log_entry)
        
        # Verify it was stored
        retrieved = await log_manager.get_log_by_id(log_entry.id)
        assert retrieved is not None
        assert retrieved.message == "Manager test message"
        assert retrieved.level == LogLevel.INFO
    
    @pytest.mark.asyncio
    async def test_log_manager_get_logs_no_filters(self):
        """Test getting logs without filters."""
        logs, log_manager = await self.create_sample_logs()
        filters = LogFilter(page=1, page_size=5)
        result = await log_manager.get_logs(filters)
        
        assert isinstance(result, LogListResponse)
        assert len(result.logs) == 5  # page_size
        assert result.total == 10  # total logs
        assert result.page == 1
        assert result.page_size == 5
        assert result.total_pages == 2
        assert result.has_next is True
        assert result.has_prev is False
    
    @pytest.mark.asyncio
    async def test_log_manager_get_logs_with_level_filter(self):
        """Test getting logs with level filter."""
        logs, log_manager = await self.create_sample_logs()
        filters = LogFilter(level=LogLevel.ERROR, page_size=20)
        result = await log_manager.get_logs(filters)
        
        # Should only return ERROR level logs
        error_logs = [log for log in logs if log.level == LogLevel.ERROR]
        expected_count = len(error_logs)
        
        assert len(result.logs) == expected_count
        for log_response in result.logs:
            assert log_response.level == LogLevel.ERROR
    
    @pytest.mark.asyncio
    async def test_log_manager_get_logs_with_module_filter(self):
        """Test getting logs with module filter."""
        logs, log_manager = await self.create_sample_logs()
        filters = LogFilter(module="module_1", page_size=20)
        result = await log_manager.get_logs(filters)
        
        # Should only return logs from module_1
        module_logs = [log for log in logs if log.module == "module_1"]
        expected_count = len(module_logs)
        
        assert len(result.logs) == expected_count
        for log_response in result.logs:
            assert log_response.module == "module_1"
    
    @pytest.mark.asyncio
    async def test_log_manager_get_logs_with_time_filter(self):
        """Test getting logs with time range filter."""
        logs, log_manager = await self.create_sample_logs()
        base_time = datetime.utcnow()
        start_time = base_time + timedelta(minutes=3)
        end_time = base_time + timedelta(minutes=7)
        
        filters = LogFilter(start_time=start_time, end_time=end_time, page_size=20)
        result = await log_manager.get_logs(filters)
        
        # Should only return logs within time range
        for log_response in result.logs:
            log_time = log_response.timestamp
            assert start_time <= log_time <= end_time
    
    @pytest.mark.asyncio
    async def test_log_manager_get_logs_with_search_query(self):
        """Test getting logs with search query."""
        logs, log_manager = await self.create_sample_logs()
        # First, store a log with specific searchable content
        searchable_log = LogEntry(
            level=LogLevel.INFO,
            message="This is a searchable error message",
            module="search_module"
        )
        await log_manager.store_log(searchable_log)
        
        filters = LogFilter(search_query="searchable error", page_size=20)
        result = await log_manager.get_logs(filters)
        
        # Should find the searchable log
        assert len(result.logs) >= 1
        found_searchable = any(
            "searchable error" in log.message.lower()
            for log in result.logs
        )
        assert found_searchable
    
    @pytest.mark.asyncio
    async def test_log_manager_get_logs_pagination(self):
        """Test pagination functionality."""
        logs, log_manager = await self.create_sample_logs()
        # Get first page
        filters = LogFilter(page=1, page_size=3)
        page1 = await log_manager.get_logs(filters)
        
        assert len(page1.logs) == 3
        assert page1.page == 1
        assert page1.has_prev is False
        assert page1.has_next is True
        
        # Get second page
        filters = LogFilter(page=2, page_size=3)
        page2 = await log_manager.get_logs(filters)
        
        assert len(page2.logs) == 3
        assert page2.page == 2
        assert page2.has_prev is True
        assert page2.has_next is True
        
        # Logs should be different
        page1_ids = {log.id for log in page1.logs}
        page2_ids = {log.id for log in page2.logs}
        assert page1_ids.isdisjoint(page2_ids)
    
    @pytest.mark.asyncio
    async def test_log_manager_get_log_by_id(self):
        """Test getting specific log by ID."""
        logs, log_manager = await self.create_sample_logs()
        target_log = logs[0]
        
        retrieved = await log_manager.get_log_by_id(target_log.id)
        
        assert retrieved is not None
        assert retrieved.id == target_log.id
        assert retrieved.message == target_log.message
        assert retrieved.level == target_log.level
        assert retrieved.module == target_log.module
    
    @pytest.mark.asyncio
    async def test_log_manager_get_log_by_id_not_found(self):
        """Test getting non-existent log by ID."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        non_existent_id = "non-existent-id"
        
        retrieved = await log_manager.get_log_by_id(non_existent_id)
        
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_log_manager_delete_log(self):
        """Test deleting a log entry."""
        logs, log_manager = await self.create_sample_logs()
        target_log = logs[0]
        
        # Verify log exists
        retrieved = await log_manager.get_log_by_id(target_log.id)
        assert retrieved is not None
        
        # Delete the log
        success = await log_manager.delete_log(target_log.id)
        assert success is True
        
        # Verify log is deleted
        retrieved = await log_manager.get_log_by_id(target_log.id)
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_log_manager_delete_log_not_found(self):
        """Test deleting non-existent log."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        success = await log_manager.delete_log("non-existent-id")
        assert success is False
    
    @pytest.mark.asyncio
    async def test_log_manager_bulk_delete_logs(self):
        """Test bulk deleting log entries."""
        logs, log_manager = await self.create_sample_logs()
        # Delete first 3 logs
        log_ids = [log.id for log in logs[:3]]
        
        deleted_count = await log_manager.bulk_delete_logs(log_ids)
        assert deleted_count == 3
        
        # Verify logs are deleted
        for log_id in log_ids:
            retrieved = await log_manager.get_log_by_id(log_id)
            assert retrieved is None
        
        # Verify remaining logs still exist
        for log in logs[3:]:
            retrieved = await log_manager.get_log_by_id(log.id)
            assert retrieved is not None
    
    @pytest.mark.asyncio
    async def test_log_manager_get_stats(self):
        """Test getting log statistics."""
        logs, log_manager = await self.create_sample_logs()
        stats = await log_manager.get_stats(days=7)
        
        assert isinstance(stats, LogStats)
        assert stats.total_logs == 10
        
        # Check logs by level
        assert LogLevel.DEBUG in stats.logs_by_level
        assert LogLevel.INFO in stats.logs_by_level
        assert LogLevel.WARNING in stats.logs_by_level
        assert LogLevel.ERROR in stats.logs_by_level
        
        # Check logs by module
        assert "module_0" in stats.logs_by_module
        assert "module_1" in stats.logs_by_module
        assert "module_2" in stats.logs_by_module
        
        # Check error rate calculation
        error_count = stats.logs_by_level.get(LogLevel.ERROR, 0)
        expected_error_rate = (error_count / stats.total_logs) * 100
        assert abs(stats.error_rate - expected_error_rate) < 0.01
    
    @pytest.mark.asyncio
    async def test_log_manager_get_config(self):
        """Test getting log configuration."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        config = await log_manager.get_config()
        
        assert isinstance(config, LogConfig)
        assert config.global_level == LogLevel.INFO  # Default
        assert config.enable_console is True  # Default
        assert config.enable_redis is True  # Default
    
    @pytest.mark.asyncio
    async def test_log_manager_save_config(self):
        """Test saving log configuration."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        new_config = LogConfig(
            global_level=LogLevel.WARNING,
            enable_console=False,
            retention_days=60,
            batch_size=50
        )
        
        success = await log_manager.save_config(new_config)
        assert success is True
        
        # Verify config was saved
        retrieved_config = await log_manager.get_config()
        assert retrieved_config.global_level == LogLevel.WARNING
        assert retrieved_config.enable_console is False
        assert retrieved_config.retention_days == 60
        assert retrieved_config.batch_size == 50
    
    @pytest.mark.asyncio
    async def test_log_manager_cleanup_old_logs(self):
        """Test cleaning up old log entries."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        # Create old log entries
        old_time = datetime.utcnow() - timedelta(days=35)  # Older than default retention
        old_logs = []
        
        for i in range(3):
            old_log = LogEntry(
                level=LogLevel.INFO,
                message=f"Old log {i}",
                module="old_module",
                timestamp=old_time
            )
            old_logs.append(old_log)
            await log_manager.store_log(old_log)
        
        # Run cleanup
        deleted_count = await log_manager.cleanup_old_logs()
        
        # Should have deleted the old logs
        assert deleted_count >= 3
        
        # Verify old logs are deleted
        for old_log in old_logs:
            retrieved = await log_manager.get_log_by_id(old_log.id)
            assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_log_manager_error_handling(self):
        """Test error handling in log manager operations."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        # Mock Redis to raise an exception
        with patch.object(log_manager.redis, 'hget', side_effect=Exception("Redis error")):
            # Should not raise exception, should return None
            result = await log_manager.get_log_by_id("test-id")
            assert result is None
        
        # Test with other operations
        with patch.object(log_manager.redis, 'pipeline', side_effect=Exception("Redis error")):
            # Should not raise exception, should return empty result
            filters = LogFilter()
            result = await log_manager.get_logs(filters)
            assert isinstance(result, LogListResponse)
            assert len(result.logs) == 0


class TestLogManagerIntegration:
    """Integration tests for LogManager."""
    
    @pytest.mark.asyncio
    async def test_full_log_lifecycle(self):
        """Test complete log lifecycle from creation to deletion."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        
        # Create and store a log
        log_entry = LogEntry(
            level=LogLevel.ERROR,
            message="Integration test error",
            module="integration_module",
            request_id="integration-req-123",
            user_id="integration-user",
            extra_data={"test": "data", "number": 42}
        )
        
        # Store the log
        await log_manager.store_log(log_entry)
        
        # Retrieve by ID
        retrieved = await log_manager.get_log_by_id(log_entry.id)
        assert retrieved is not None
        assert retrieved.message == "Integration test error"
        assert retrieved.request_id == "integration-req-123"
        assert retrieved.extra_data["test"] == "data"
        
        # Search for the log
        filters = LogFilter(
            level=LogLevel.ERROR,
            module="integration_module",
            search_query="integration test"
        )
        search_result = await log_manager.get_logs(filters)
        assert len(search_result.logs) >= 1
        
        found_log = None
        for log in search_result.logs:
            if log.id == log_entry.id:
                found_log = log
                break
        
        assert found_log is not None
        assert found_log.message == "Integration test error"
        
        # Delete the log
        success = await log_manager.delete_log(log_entry.id)
        assert success is True
        
        # Verify deletion
        retrieved = await log_manager.get_log_by_id(log_entry.id)
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test concurrent log operations."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        
        # Create multiple logs concurrently
        async def create_log(i):
            log_entry = LogEntry(
                level=LogLevel.INFO,
                message=f"Concurrent log {i}",
                module=f"module_{i % 3}"
            )
            await log_manager.store_log(log_entry)
            return log_entry
        
        # Create 20 logs concurrently
        tasks = [create_log(i) for i in range(20)]
        created_logs = await asyncio.gather(*tasks)
        
        # Verify all logs were created
        assert len(created_logs) == 20
        
        # Retrieve all logs
        filters = LogFilter(page_size=25)
        result = await log_manager.get_logs(filters)
        assert len(result.logs) == 20
        
        # Verify concurrent deletion
        log_ids = [log.id for log in created_logs[:10]]
        deleted_count = await log_manager.bulk_delete_logs(log_ids)
        assert deleted_count == 10
        
        # Verify remaining logs
        filters = LogFilter(page_size=25)
        result = await log_manager.get_logs(filters)
        assert len(result.logs) == 10


class TestGetLogManager:
    """Test get_log_manager dependency function."""
    
    @pytest.mark.asyncio
    async def test_get_log_manager_dependency(self):
        """Test get_log_manager dependency injection."""
        with patch('app.services.log_manager.redis_manager') as mock_redis_manager:
            mock_redis = AsyncMock()
            mock_redis_manager.get_redis.return_value = mock_redis
            
            log_manager = await get_log_manager()
            
            assert isinstance(log_manager, LogManager)
            assert log_manager.redis is mock_redis
            mock_redis_manager.get_redis.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_log_manager_singleton_behavior(self):
        """Test that get_log_manager returns singleton instance."""
        with patch('app.services.log_manager.redis_manager') as mock_redis_manager:
            mock_redis = AsyncMock()
            mock_redis_manager.get_redis.return_value = mock_redis
            
            manager1 = await get_log_manager()
            manager2 = await get_log_manager()
            
            # Should return the same instance
            assert manager1 is manager2