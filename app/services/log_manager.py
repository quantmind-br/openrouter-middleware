"""Log management service with Redis storage and advanced querying capabilities."""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from math import ceil

import redis.asyncio as redis

from app.core.redis import RedisOperations, get_redis_client
from app.models.logs import (
    LogEntry, LogFilter, LogStats, LogConfig, 
    LogListResponse, LogEntryResponse, LogLevel
)

logger = logging.getLogger(__name__)


class RedisLogHandler:
    """Redis handler for structured log persistence."""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = RedisOperations(redis_client)
        self.client = redis_client
        self.log_prefix = "log_entry"
        self.index_prefix = "log_index"
        self.stats_prefix = "log_stats"
        self.config_key = "log_config"
        
    async def store(self, entry: LogEntry) -> bool:
        """Store a single log entry in Redis."""
        try:
            # Store the log entry
            log_key = f"{self.log_prefix}:{entry.id}"
            log_data = entry.dict()
            
            # Convert datetime objects to ISO strings for Redis
            log_data['timestamp'] = entry.timestamp.isoformat()
            if entry.last_used:
                log_data['last_used'] = entry.last_used.isoformat()
            elif 'last_used' in log_data:
                # Remove last_used if it's None to avoid storing 'None' string
                del log_data['last_used']
            
            result = await self.redis.hash_set_safely(log_key, {
                k: json.dumps(v) if isinstance(v, (dict, list)) else (v.value if hasattr(v, 'value') else str(v))
                for k, v in log_data.items()
            })
            
            # hset returns number of fields added, we want to return True if any fields were added
            success = result > 0
            
            if success:
                # Add to indexes for efficient querying
                await self._update_indexes(entry)
                # Update statistics
                await self._update_stats(entry)
                # Set TTL for automatic cleanup
                await self._set_ttl(log_key, entry)
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to store log entry {entry.id}: {e}")
            return False
    
    async def batch_store(self, entries: List[LogEntry]) -> int:
        """Store multiple log entries efficiently using pipeline."""
        if not entries:
            return 0
            
        stored_count = 0
        
        try:
            # Use pipeline for batch operations
            pipe = self.client.pipeline()
            
            for entry in entries:
                log_key = f"{self.log_prefix}:{entry.id}"
                log_data = entry.dict()
                
                # Convert datetime objects
                log_data['timestamp'] = entry.timestamp.isoformat()
                if entry.last_used:
                    log_data['last_used'] = entry.last_used.isoformat()
                
                # Add to pipeline
                serialized_data = {
                    k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) 
                    for k, v in log_data.items()
                }
                pipe.hset(log_key, mapping=serialized_data)
                
                # Index operations
                await self._update_indexes_pipeline(pipe, entry)
                
                # TTL
                config = await self.get_config()
                ttl_seconds = config.retention_days * 24 * 3600
                pipe.expire(log_key, ttl_seconds)
            
            # Execute pipeline
            results = await pipe.execute()
            stored_count = len([r for r in results if r])
            
            # Update statistics for all entries
            for entry in entries:
                await self._update_stats(entry)
                
        except Exception as e:
            logger.error(f"Failed to batch store {len(entries)} log entries: {e}")
        
        return stored_count
    
    async def _update_indexes(self, entry: LogEntry):
        """Update Redis indexes for efficient querying."""
        try:
            timestamp_key = f"{self.index_prefix}:timestamp"
            level_key = f"{self.index_prefix}:level:{entry.level.value}"
            module_key = f"{self.index_prefix}:module:{entry.module}"
            
            # Add to sorted set with timestamp score for time-based queries
            timestamp_score = entry.timestamp.timestamp()
            await self.client.zadd(timestamp_key, {entry.id: timestamp_score})
            
            # Add to level-specific sets
            await self.client.sadd(level_key, entry.id)
            await self.client.sadd(module_key, entry.id)
            
            # Request ID index if available
            if entry.request_id:
                request_key = f"{self.index_prefix}:request:{entry.request_id}"
                await self.client.sadd(request_key, entry.id)
            
            # User ID index if available
            if entry.user_id:
                user_key = f"{self.index_prefix}:user:{entry.user_id}"
                await self.client.sadd(user_key, entry.id)
                
        except Exception as e:
            logger.error(f"Failed to update indexes for log {entry.id}: {e}")
    
    async def _update_indexes_pipeline(self, pipe: redis.client.Pipeline, entry: LogEntry):
        """Update indexes using pipeline for batch operations."""
        timestamp_key = f"{self.index_prefix}:timestamp"
        level_key = f"{self.index_prefix}:level:{entry.level.value}"
        module_key = f"{self.index_prefix}:module:{entry.module}"
        
        timestamp_score = entry.timestamp.timestamp()
        pipe.zadd(timestamp_key, {entry.id: timestamp_score})
        pipe.sadd(level_key, entry.id)
        pipe.sadd(module_key, entry.id)
        
        if entry.request_id:
            request_key = f"{self.index_prefix}:request:{entry.request_id}"
            pipe.sadd(request_key, entry.id)
        
        if entry.user_id:
            user_key = f"{self.index_prefix}:user:{entry.user_id}"
            pipe.sadd(user_key, entry.id)
    
    async def _set_ttl(self, log_key: str, entry: LogEntry):
        """Set TTL for log entry based on configuration."""
        try:
            config = await self.get_config()
            ttl_seconds = config.retention_days * 24 * 3600
            await self.client.expire(log_key, ttl_seconds)
        except Exception as e:
            logger.error(f"Failed to set TTL for log {log_key}: {e}")
    
    async def _update_stats(self, entry: LogEntry):
        """Update log statistics."""
        try:
            stats_key = f"{self.stats_prefix}:daily:{entry.timestamp.strftime('%Y-%m-%d')}"
            
            # Increment counters
            await self.client.hincrby(stats_key, "total", 1)
            await self.client.hincrby(stats_key, f"level:{entry.level.value}", 1)
            await self.client.hincrby(stats_key, f"module:{entry.module}", 1)
            
            # Set TTL for stats (keep for 90 days)
            await self.client.expire(stats_key, 90 * 24 * 3600)
            
        except Exception as e:
            logger.error(f"Failed to update stats for log {entry.id}: {e}")
    
    async def get_config(self) -> LogConfig:
        """Get current log configuration."""
        try:
            config_data = await self.redis.hash_get_all_safely(self.config_key)
            if config_data:
                # Parse configuration from Redis
                config_dict = {}
                for key, value in config_data.items():
                    try:
                        if key == 'module_levels':
                            config_dict[key] = json.loads(value)
                        elif key in ['global_level']:
                            config_dict[key] = LogLevel(value)
                        elif key in ['enable_console', 'enable_redis']:
                            config_dict[key] = value.lower() == 'true'
                        else:
                            config_dict[key] = int(value) if value.isdigit() else value
                    except (ValueError, json.JSONDecodeError):
                        continue
                
                return LogConfig(**config_dict)
            
        except Exception as e:
            logger.error(f"Failed to get log config: {e}")
        
        # Return default config if not found or error
        return LogConfig()
    
    async def save_config(self, config: LogConfig) -> bool:
        """Save log configuration to Redis."""
        try:
            config_data = {
                'global_level': config.global_level.value,
                'enable_console': str(config.enable_console).lower(),
                'enable_redis': str(config.enable_redis).lower(),
                'module_levels': json.dumps({k: v.value for k, v in config.module_levels.items()}),
                'retention_days': str(config.retention_days),
                'max_logs_per_day': str(config.max_logs_per_day),
                'batch_size': str(config.batch_size),
                'flush_interval': str(config.flush_interval)
            }
            
            return await self.redis.hash_set_safely(self.config_key, config_data)
            
        except Exception as e:
            logger.error(f"Failed to save log config: {e}")
            return False


class LogManager:
    """Service for managing log entries with advanced querying and statistics."""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = RedisOperations(redis_client)
        self.client = redis_client
        self.handler = RedisLogHandler(redis_client)
        self.log_prefix = "log_entry"
        self.index_prefix = "log_index"
        self.stats_prefix = "log_stats"
    
    async def store_log(self, entry: LogEntry) -> bool:
        """Store a log entry through the Redis handler."""
        return await self.handler.store(entry)
    
    async def get_logs(self, filters: LogFilter) -> LogListResponse:
        """Get logs with filtering and pagination."""
        try:
            # Get filtered log IDs
            log_ids = await self._get_filtered_log_ids(filters)
            
            # Calculate pagination
            total = len(log_ids)
            total_pages = ceil(total / filters.page_size) if total > 0 else 0
            start_idx = (filters.page - 1) * filters.page_size
            end_idx = start_idx + filters.page_size
            
            # Get page of log IDs
            page_log_ids = log_ids[start_idx:end_idx]
            
            # Fetch log entries
            logs = []
            for log_id in page_log_ids:
                entry = await self.get_log_by_id(log_id)
                if entry:
                    logs.append(LogEntryResponse(**entry.dict()))
            
            return LogListResponse(
                logs=logs,
                total=total,
                page=filters.page,
                page_size=filters.page_size,
                total_pages=total_pages,
                has_next=filters.page < total_pages,
                has_prev=filters.page > 1
            )
            
        except Exception as e:
            logger.error(f"Failed to get logs with filters: {e}")
            return LogListResponse(logs=[], total=0, page=1, page_size=filters.page_size, total_pages=0, has_next=False, has_prev=False)
    
    async def _get_filtered_log_ids(self, filters: LogFilter) -> List[str]:
        """Get log IDs that match the given filters."""
        try:
            # Start with time-based filtering using sorted set
            timestamp_key = f"{self.index_prefix}:timestamp"
            
            # Convert time filters to timestamps
            min_score = filters.start_time.timestamp() if filters.start_time else "-inf"
            max_score = filters.end_time.timestamp() if filters.end_time else "+inf"
            
            # Get IDs in time range
            if filters.sort_order == "desc":
                log_ids = await self.client.zrevrangebyscore(timestamp_key, max_score, min_score)
            else:
                log_ids = await self.client.zrangebyscore(timestamp_key, min_score, max_score)
            
            # Apply additional filters
            if filters.level:
                level_key = f"{self.index_prefix}:level:{filters.level.value}"
                level_ids = await self.client.smembers(level_key)
                log_ids = [lid for lid in log_ids if lid in level_ids]
            
            if filters.module:
                module_key = f"{self.index_prefix}:module:{filters.module}"
                module_ids = await self.client.smembers(module_key)
                log_ids = [lid for lid in log_ids if lid in module_ids]
            
            if filters.request_id:
                request_key = f"{self.index_prefix}:request:{filters.request_id}"
                request_ids = await self.client.smembers(request_key)
                log_ids = [lid for lid in log_ids if lid in request_ids]
            
            if filters.user_id:
                user_key = f"{self.index_prefix}:user:{filters.user_id}"
                user_ids = await self.client.smembers(user_key)
                log_ids = [lid for lid in log_ids if lid in user_ids]
            
            # Search in message content if specified
            if filters.search_query:
                filtered_ids = []
                for log_id in log_ids:
                    entry = await self.get_log_by_id(log_id)
                    if entry and filters.search_query.lower() in entry.message.lower():
                        filtered_ids.append(log_id)
                log_ids = filtered_ids
            
            # Convert byte strings to regular strings properly
            converted_ids = []
            for lid in log_ids:
                if isinstance(lid, bytes):
                    converted_ids.append(lid.decode('utf-8'))
                else:
                    converted_ids.append(str(lid))
            return converted_ids
            
        except Exception as e:
            logger.error(f"Failed to filter log IDs: {e}")
            return []
    
    async def get_log_by_id(self, log_id: str) -> Optional[LogEntry]:
        """Get a specific log entry by ID."""
        try:
            log_key = f"{self.log_prefix}:{log_id}"
            log_data = await self.redis.hash_get_all_safely(log_key)
            
            if not log_data:
                return None
            
            # Parse data back from Redis
            parsed_data = {}
            for key, value in log_data.items():
                # Decode byte keys to strings if needed
                str_key = key.decode() if isinstance(key, bytes) else key
                str_value = value.decode() if isinstance(value, bytes) else value
                
                if str_key in ['timestamp', 'last_used'] and str_value:
                    parsed_data[str_key] = datetime.fromisoformat(str_value)
                elif str_key in ['extra_data'] and str_value:
                    try:
                        parsed_data[str_key] = json.loads(str_value)
                    except json.JSONDecodeError:
                        parsed_data[str_key] = {}
                elif str_key == 'level':
                    parsed_data[str_key] = LogLevel(str_value)
                elif str_key in ['line_number', 'duration_ms', 'memory_usage']:
                    try:
                        parsed_data[str_key] = float(str_value) if '.' in str_value else int(str_value)
                    except (ValueError, AttributeError):
                        parsed_data[str_key] = None
                else:
                    parsed_data[str_key] = str_value if str_value != 'None' else None
            
            return LogEntry(**parsed_data)
            
        except Exception as e:
            logger.error(f"Failed to get log by ID {log_id}: {e}")
            return None
    
    async def delete_log(self, log_id: str) -> bool:
        """Delete a specific log entry."""
        try:
            log_key = f"{self.log_prefix}:{log_id}"
            
            # Get log entry first to clean up indexes
            entry = await self.get_log_by_id(log_id)
            if not entry:
                return False
            
            # Delete from main storage
            success = await self.redis.delete_safely(log_key)
            
            if success:
                # Clean up indexes
                await self._cleanup_indexes(entry)
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to delete log {log_id}: {e}")
            return False
    
    async def bulk_delete_logs(self, log_ids: List[str]) -> int:
        """Delete multiple log entries."""
        deleted_count = 0
        
        try:
            pipe = self.client.pipeline()
            entries_to_cleanup = []
            
            # First get all entries for index cleanup
            for log_id in log_ids:
                entry = await self.get_log_by_id(log_id)
                if entry:
                    entries_to_cleanup.append(entry)
                    log_key = f"{self.log_prefix}:{log_id}"
                    pipe.delete(log_key)
            
            # Execute deletion pipeline
            results = await pipe.execute()
            deleted_count = len([r for r in results if r])
            
            # Clean up indexes
            for entry in entries_to_cleanup:
                await self._cleanup_indexes(entry)
                
        except Exception as e:
            logger.error(f"Failed to bulk delete {len(log_ids)} logs: {e}")
        
        return deleted_count
    
    async def _cleanup_indexes(self, entry: LogEntry):
        """Remove log entry from all indexes."""
        try:
            timestamp_key = f"{self.index_prefix}:timestamp"
            level_key = f"{self.index_prefix}:level:{entry.level.value}"
            module_key = f"{self.index_prefix}:module:{entry.module}"
            
            # Remove from indexes
            await self.client.zrem(timestamp_key, entry.id)
            await self.client.srem(level_key, entry.id)
            await self.client.srem(module_key, entry.id)
            
            if entry.request_id:
                request_key = f"{self.index_prefix}:request:{entry.request_id}"
                await self.client.srem(request_key, entry.id)
            
            if entry.user_id:
                user_key = f"{self.index_prefix}:user:{entry.user_id}"
                await self.client.srem(user_key, entry.id)
                
        except Exception as e:
            logger.error(f"Failed to cleanup indexes for log {entry.id}: {e}")
    
    async def get_stats(self, days: int = 7) -> LogStats:
        """Get log statistics for the specified number of days."""
        try:
            stats = LogStats()
            
            # Get stats for each day
            for i in range(days):
                date = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
                stats_key = f"{self.stats_prefix}:daily:{date}"
                daily_stats = await self.redis.hash_get_all_safely(stats_key)
                
                if daily_stats:
                    # Aggregate totals
                    total = int(daily_stats.get('total', 0))
                    stats.total_logs += total
                    
                    # Aggregate by level
                    for level in LogLevel:
                        level_count = int(daily_stats.get(f'level:{level.value}', 0))
                        if level not in stats.logs_by_level:
                            stats.logs_by_level[level] = 0
                        stats.logs_by_level[level] += level_count
                    
                    # Aggregate by module
                    for key, value in daily_stats.items():
                        if key.startswith('module:'):
                            module = key.replace('module:', '')
                            count = int(value)
                            if module not in stats.logs_by_module:
                                stats.logs_by_module[module] = 0
                            stats.logs_by_module[module] += count
            
            # Calculate error rate
            total_errors = stats.logs_by_level.get(LogLevel.ERROR, 0) + stats.logs_by_level.get(LogLevel.CRITICAL, 0)
            if stats.total_logs > 0:
                stats.error_rate = (total_errors / stats.total_logs) * 100
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get log stats: {e}")
            return LogStats()
    
    async def cleanup_old_logs(self) -> int:
        """Clean up logs older than retention period."""
        try:
            config = await self.handler.get_config()
            cutoff_date = datetime.utcnow() - timedelta(days=config.retention_days)
            cutoff_timestamp = cutoff_date.timestamp()
            
            # Get old log IDs
            timestamp_key = f"{self.index_prefix}:timestamp"
            old_log_ids = await self.client.zrangebyscore(timestamp_key, "-inf", cutoff_timestamp)
            
            if not old_log_ids:
                return 0
            
            # Delete old logs
            deleted_count = await self.bulk_delete_logs([str(lid) for lid in old_log_ids])
            
            logger.info(f"Cleaned up {deleted_count} old log entries")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {e}")
            return 0
    
    async def get_config(self) -> LogConfig:
        """Get current log configuration."""
        return await self.handler.get_config()
    
    async def save_config(self, config: LogConfig) -> bool:
        """Save log configuration."""
        return await self.handler.save_config(config)


# Dependency for FastAPI
async def get_log_manager() -> LogManager:
    """Get LogManager instance for dependency injection."""
    redis_client = await get_redis_client()
    return LogManager(redis_client)


async def get_redis_log_handler() -> RedisLogHandler:
    """Get RedisLogHandler instance for dependency injection."""
    redis_client = await get_redis_client()
    return RedisLogHandler(redis_client)