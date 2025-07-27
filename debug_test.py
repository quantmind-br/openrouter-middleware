import asyncio
import fakeredis.aioredis
from app.services.log_manager import LogManager
from app.models.logs import LogEntry, LogLevel, LogFilter, LogListResponse

async def test_basic_functionality():
    # Create fake Redis instance
    fake_redis = fakeredis.aioredis.FakeRedis()
    
    # Create LogManager
    log_manager = LogManager(fake_redis)
    
    # Create a log entry
    log_entry = LogEntry(
        level=LogLevel.INFO,
        message="Test message",
        module="test_module"
    )
    
    print(f"Created log entry with ID: {log_entry.id}")
    
    # Store the log entry
    result = await log_manager.store_log(log_entry)
    print(f"Store result: {result}")
    
    # Try to retrieve the log by ID
    retrieved = await log_manager.get_log_by_id(log_entry.id)
    print(f"Retrieved by ID: {retrieved}")
    
    # Check what's in the timestamp index
    timestamp_key = "log_index:timestamp"
    all_scores = await fake_redis.zrange(timestamp_key, 0, -1, withscores=True)
    print(f"Timestamp index contents: {all_scores}")
    
    # Check level index
    level_key = "log_index:level:INFO"
    level_members = await fake_redis.smembers(level_key)
    print(f"Level index contents: {level_members}")
    
    # Check module index
    module_key = "log_index:module:test_module"
    module_members = await fake_redis.smembers(module_key)
    print(f"Module index contents: {module_members}")
    
    # Try the filtering method directly
    filters = LogFilter(page=1, page_size=5)
    log_ids = await log_manager._get_filtered_log_ids(filters)
    print(f"Filtered log IDs: {log_ids}")
    
    # Try to get logs with no filters
    log_list = await log_manager.get_logs(filters)
    print(f"Log list result: {log_list}")
    print(f"Number of logs: {len(log_list.logs)}")
    print(f"Total logs: {log_list.total}")

if __name__ == "__main__":
    asyncio.run(test_basic_functionality())