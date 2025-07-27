"""Logs API endpoints for management and visualization."""

import io
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Request, HTTPException, Depends, Query, Response
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.services.log_manager import LogManager, get_log_manager
from app.models.logs import (
    LogFilter, LogEntry, LogListResponse, LogEntryResponse,
    LogStats, LogStatsResponse, LogConfig, LogExportRequest,
    BulkDeleteRequest, LogLevel
)
from app.models.admin import AdminSession
from app.api.admin import require_admin_auth
from app.utils.log_formatter import export_logs, get_formatter

logger = logging.getLogger(__name__)

# Create router for logs endpoints
router = APIRouter(prefix="/admin/api/logs", tags=["logs"])


# Log Retrieval Endpoints

@router.get("", response_model=LogListResponse)
async def list_logs(
    # Filter parameters
    level: Optional[LogLevel] = Query(None, description="Filter by log level"),
    module: Optional[str] = Query(None, description="Filter by module name"),
    request_id: Optional[str] = Query(None, description="Filter by request ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    start_time: Optional[datetime] = Query(None, description="Start time for date range"),
    end_time: Optional[datetime] = Query(None, description="End time for date range"),
    search_query: Optional[str] = Query(None, description="Search in message content"),
    
    # Pagination parameters
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Number of logs per page"),
    
    # Sorting parameters
    sort_by: str = Query("timestamp", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    
    # Dependencies
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Get paginated list of logs with filtering options."""
    try:
        # Build filter object
        filters = LogFilter(
            level=level,
            module=module,
            request_id=request_id,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            search_query=search_query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Get logs using the manager
        result = await log_manager.get_logs(filters)
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} retrieved {len(result.logs)} logs (page {page})")
        
        return result
        
    except Exception as e:
        logger.error(f"Error listing logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs")


@router.get("/{log_id}", response_model=LogEntryResponse)
async def get_log_detail(
    log_id: str,
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Get detailed information for a specific log entry."""
    try:
        log_entry = await log_manager.get_log_by_id(log_id)
        
        if not log_entry:
            raise HTTPException(status_code=404, detail="Log entry not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} viewed log details for {log_id}")
        
        return LogEntryResponse(**log_entry.dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting log detail {log_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve log details")


# Log Management Endpoints

@router.delete("/{log_id}")
async def delete_log(
    log_id: str,
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Delete a specific log entry."""
    try:
        success = await log_manager.delete_log(log_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Log entry not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} deleted log entry {log_id}")
        
        return {"success": True, "message": "Log entry deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting log {log_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete log entry")


@router.delete("/bulk")
async def bulk_delete_logs(
    request_data: BulkDeleteRequest,
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Delete multiple log entries in bulk."""
    try:
        deleted_count = await log_manager.bulk_delete_logs(request_data.log_ids)
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} bulk deleted {deleted_count} log entries")
        
        return {
            "success": True,
            "message": f"Successfully deleted {deleted_count} log entries",
            "deleted_count": deleted_count,
            "requested_count": len(request_data.log_ids)
        }
        
    except Exception as e:
        logger.error(f"Error bulk deleting logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete log entries")


# Export Endpoints

@router.get("/export")
async def export_logs_endpoint(
    format: str = Query("json", description="Export format: json, csv, txt"),
    
    # Filter parameters (same as list_logs)
    level: Optional[LogLevel] = Query(None),
    module: Optional[str] = Query(None),
    request_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    search_query: Optional[str] = Query(None),
    
    # Export options
    include_metadata: bool = Query(True, description="Include metadata in export"),
    max_records: int = Query(10000, ge=1, le=100000, description="Maximum records to export"),
    
    # Dependencies
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Export logs in various formats (JSON, CSV, TXT)."""
    try:
        # Validate format
        if format.lower() not in ["json", "csv", "txt"]:
            raise HTTPException(status_code=400, detail="Unsupported export format")
        
        # Build filter with large page size for export
        filters = LogFilter(
            level=level,
            module=module,
            request_id=request_id,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            search_query=search_query,
            page=1,
            page_size=min(max_records, 10000),  # Limit to prevent memory issues
            sort_by="timestamp",
            sort_order="desc"
        )
        
        # Get logs
        result = await log_manager.get_logs(filters)
        
        # Convert to LogEntry objects for formatting
        log_entries = []
        for log_response in result.logs:
            # Convert back to LogEntry for formatter
            log_dict = log_response.dict()
            if 'timestamp' in log_dict and isinstance(log_dict['timestamp'], str):
                log_dict['timestamp'] = datetime.fromisoformat(log_dict['timestamp'])
            log_entries.append(LogEntry(**log_dict))
        
        # Generate export content
        export_content = export_logs(log_entries, format, include_metadata)
        
        # Determine content type and filename
        content_types = {
            "json": "application/json",
            "csv": "text/csv",
            "txt": "text/plain"
        }
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"logs_export_{timestamp}.{format}"
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} exported {len(log_entries)} logs in {format} format")
        
        # Return as streaming response
        return StreamingResponse(
            io.StringIO(export_content),
            media_type=content_types[format],
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to export logs")


# Statistics Endpoints

@router.get("/stats", response_model=LogStatsResponse)
async def get_log_statistics(
    days: int = Query(7, ge=1, le=90, description="Number of days to include in stats"),
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Get log statistics for dashboard display."""
    try:
        stats = await log_manager.get_stats(days)
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} retrieved log statistics for {days} days")
        
        return LogStatsResponse(stats=stats)
        
    except Exception as e:
        logger.error(f"Error getting log statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve log statistics")


# Configuration Endpoints

@router.get("/config", response_model=LogConfig)
async def get_log_configuration(
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Get current log configuration."""
    try:
        config = await log_manager.get_config()
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} retrieved log configuration")
        
        return config
        
    except Exception as e:
        logger.error(f"Error getting log configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve log configuration")


@router.post("/config")
async def update_log_configuration(
    config: LogConfig,
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Update log configuration."""
    try:
        success = await log_manager.save_config(config)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        # Apply configuration to existing loggers
        from app.core.logging import set_default_config
        set_default_config(config)
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} updated log configuration")
        
        return {
            "success": True,
            "message": "Log configuration updated successfully",
            "config": config.dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating log configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to update log configuration")


# Maintenance Endpoints

@router.post("/cleanup")
async def cleanup_old_logs(
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Clean up old log entries based on retention policy."""
    try:
        deleted_count = await log_manager.cleanup_old_logs()
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} cleaned up {deleted_count} old log entries")
        
        return {
            "success": True,
            "message": f"Successfully cleaned up {deleted_count} old log entries",
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up old logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to clean up old logs")


# WebSocket endpoint for real-time logs
@router.websocket("/live")
async def websocket_live_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming."""
    await websocket.accept()
    
    try:
        # Simple implementation - in production, you'd want to:
        # 1. Authenticate the WebSocket connection
        # 2. Subscribe to Redis pub/sub for new log entries
        # 3. Filter logs based on client preferences
        
        # For now, just send a connection confirmation
        await websocket.send_json({
            "type": "connection",
            "message": "Connected to live log stream",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Keep connection alive and wait for messages
        while True:
            try:
                # Wait for client messages (filters, etc.)
                data = await websocket.receive_json()
                
                # Echo back for now - in production, this would handle filter updates
                await websocket.send_json({
                    "type": "echo",
                    "data": data,
                    "timestamp": datetime.utcnow().isoformat()
                })
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                })
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from live logs")
    except Exception as e:
        logger.error(f"Error in live logs WebSocket: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass


# Utility endpoints

@router.get("/modules")
async def get_log_modules(
    admin_session: AdminSession = Depends(require_admin_auth),
    log_manager: LogManager = Depends(get_log_manager)
):
    """Get list of modules that have logged entries."""
    try:
        # Get recent log stats to extract module list
        stats = await log_manager.get_stats(days=7)
        modules = list(stats.logs_by_module.keys())
        
        return {
            "modules": sorted(modules),
            "count": len(modules)
        }
        
    except Exception as e:
        logger.error(f"Error getting log modules: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve log modules")


@router.get("/levels")
async def get_log_levels(
    admin_session: AdminSession = Depends(require_admin_auth)
):
    """Get available log levels."""
    return {
        "levels": [level.value for level in LogLevel],
        "descriptions": {
            "DEBUG": "Detailed information for diagnosing problems",
            "INFO": "General information about system operation",
            "WARNING": "Warning about potential issues",
            "ERROR": "Error conditions that need attention",
            "CRITICAL": "Critical errors that may cause system failure"
        }
    }