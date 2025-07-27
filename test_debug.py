import pytest
import fakeredis.aioredis
from app.services.log_manager import LogManager
from app.models.logs import LogEntry, LogLevel, LogFilter

class TestSimpleLogManager:
    """Simplified test to debug the fixture issue."""
    
    @pytest.fixture
    def log_manager(self):
        """Create LogManager with fake Redis instance."""
        fake_redis = fakeredis.aioredis.FakeRedis()
        manager = LogManager(fake_redis)
        return manager
    
    @pytest.fixture
    async def sample_logs(self, log_manager):
        """Create sample log entries for testing."""
        log_entry = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            module="test_module"
        )
        
        # Store the log
        await log_manager.handler.store(log_entry)
        print(f"Stored log with ID: {log_entry.id}")
        
        # Verify it was stored by checking the Redis directly
        redis = log_manager.client
        stored_message = await redis.hget(f"log_entry:{log_entry.id}", "message")
        print(f"Direct Redis check - stored message: {stored_message}")
        
        return [log_entry]
    
    @pytest.mark.asyncio
    async def test_simple_store_and_retrieve(self, log_manager, sample_logs):
        """Test storing and retrieving a log entry."""
        print(f"Number of sample logs: {len(sample_logs)}")
        
        # Try to get logs with no filters
        filters = LogFilter(page=1, page_size=5)
        result = await log_manager.get_logs(filters)
        print(f"Retrieved logs: {len(result.logs)}, total: {result.total}")
        
        # Try to retrieve by ID
        if sample_logs:
            retrieved = await log_manager.get_log_by_id(sample_logs[0].id)
            print(f"Retrieved by ID: {retrieved}")