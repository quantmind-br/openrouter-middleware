"""Tests for logs API endpoints."""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.api.logs import router
from app.models.logs import (
    LogEntry, LogLevel, LogFilter, LogStats, LogConfig,
    LogListResponse, LogEntryResponse, BulkDeleteRequest
)
from app.models.admin import AdminSession


# Create test app
app = FastAPI()
app.include_router(router)


class TestLogsAPI:
    """Test logs API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_admin_session(self):
        """Create mock admin session."""
        return AdminSession(
            user_id="test_admin",
            authenticated=True,
            login_time=datetime.utcnow(),
            last_activity=datetime.utcnow()
        )
    
    @pytest.fixture
    def mock_log_manager(self):
        """Create mock log manager."""
        return AsyncMock()
    
    @pytest.fixture
    def sample_log_entry(self):
        """Create sample log entry."""
        return LogEntry(
            id="test-log-id",
            level=LogLevel.INFO,
            message="Test log message",
            module="test_module",
            function="test_function",
            line_number=123,
            request_id="test-req-123",
            user_id="test-user",
            client_ip="192.168.1.1",
            extra_data={"key": "value"},
            duration_ms=150.5
        )
    
    @pytest.fixture
    def sample_log_response(self, sample_log_entry):
        """Create sample log response."""
        return LogEntryResponse(**sample_log_entry.dict())
    
    def test_list_logs_success(self, client, mock_admin_session, mock_log_manager, sample_log_response):
        """Test successful log listing."""
        # Mock dependencies
        mock_logs_response = LogListResponse(
            logs=[sample_log_response],
            total=1,
            page=1,
            page_size=50,
            total_pages=1,
            has_next=False,
            has_prev=False
        )
        mock_log_manager.get_logs.return_value = mock_logs_response
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get("/admin/api/logs")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "logs" in data
            assert len(data["logs"]) == 1
            assert data["total"] == 1
            assert data["page"] == 1
            assert data["page_size"] == 50
            
            # Verify log manager was called with correct filter
            mock_log_manager.get_logs.assert_called_once()
            call_args = mock_log_manager.get_logs.call_args[0][0]
            assert isinstance(call_args, LogFilter)
            assert call_args.page == 1
            assert call_args.page_size == 50
    
    def test_list_logs_with_filters(self, client, mock_admin_session, mock_log_manager):
        """Test log listing with filters."""
        mock_logs_response = LogListResponse(
            logs=[],
            total=0,
            page=1,
            page_size=25,
            total_pages=0,
            has_next=False,
            has_prev=False
        )
        mock_log_manager.get_logs.return_value = mock_logs_response
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get(
                "/admin/api/logs",
                params={
                    "level": "ERROR",
                    "module": "test_module",
                    "request_id": "req-123",
                    "search_query": "error message",
                    "page": 2,
                    "page_size": 25,
                    "sort_order": "asc"
                }
            )
            
            assert response.status_code == 200
            
            # Verify filters were applied
            call_args = mock_log_manager.get_logs.call_args[0][0]
            assert call_args.level == LogLevel.ERROR
            assert call_args.module == "test_module"
            assert call_args.request_id == "req-123"
            assert call_args.search_query == "error message"
            assert call_args.page == 2
            assert call_args.page_size == 25
            assert call_args.sort_order == "asc"
    
    def test_list_logs_unauthorized(self, client):
        """Test log listing without authentication."""
        with patch('app.api.logs.require_admin_auth', side_effect=Exception("Unauthorized")):
            response = client.get("/admin/api/logs")
            assert response.status_code == 500  # FastAPI converts uncaught exceptions to 500
    
    def test_get_log_detail_success(self, client, mock_admin_session, mock_log_manager, sample_log_entry):
        """Test successful log detail retrieval."""
        mock_log_manager.get_log_by_id.return_value = sample_log_entry
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get(f"/admin/api/logs/{sample_log_entry.id}")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["id"] == sample_log_entry.id
            assert data["message"] == sample_log_entry.message
            assert data["level"] == "INFO"
            assert data["module"] == "test_module"
            
            mock_log_manager.get_log_by_id.assert_called_once_with(sample_log_entry.id)
    
    def test_get_log_detail_not_found(self, client, mock_admin_session, mock_log_manager):
        """Test log detail retrieval for non-existent log."""
        mock_log_manager.get_log_by_id.return_value = None
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get("/admin/api/logs/non-existent-id")
            
            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()
    
    def test_delete_log_success(self, client, mock_admin_session, mock_log_manager):
        """Test successful log deletion."""
        mock_log_manager.delete_log.return_value = True
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.delete("/admin/api/logs/test-log-id")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["success"] is True
            assert "deleted successfully" in data["message"]
            
            mock_log_manager.delete_log.assert_called_once_with("test-log-id")
    
    def test_delete_log_not_found(self, client, mock_admin_session, mock_log_manager):
        """Test deleting non-existent log."""
        mock_log_manager.delete_log.return_value = False
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.delete("/admin/api/logs/non-existent-id")
            
            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()
    
    def test_bulk_delete_logs_success(self, client, mock_admin_session, mock_log_manager):
        """Test successful bulk log deletion."""
        mock_log_manager.bulk_delete_logs.return_value = 3
        
        bulk_request = {
            "log_ids": ["id1", "id2", "id3"],
            "confirm": True
        }
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.delete(
                "/admin/api/logs/bulk",
                json=bulk_request
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["success"] is True
            assert data["deleted_count"] == 3
            assert data["requested_count"] == 3
            
            mock_log_manager.bulk_delete_logs.assert_called_once_with(["id1", "id2", "id3"])
    
    def test_bulk_delete_logs_validation_error(self, client, mock_admin_session, mock_log_manager):
        """Test bulk delete with validation errors."""
        # Test without confirmation
        bulk_request = {
            "log_ids": ["id1", "id2"],
            "confirm": False
        }
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.delete(
                "/admin/api/logs/bulk",
                json=bulk_request
            )
            
            assert response.status_code == 422  # Validation error
    
    def test_export_logs_json(self, client, mock_admin_session, mock_log_manager, sample_log_response):
        """Test log export in JSON format."""
        mock_logs_response = LogListResponse(
            logs=[sample_log_response],
            total=1,
            page=1,
            page_size=10000,
            total_pages=1,
            has_next=False,
            has_prev=False
        )
        mock_log_manager.get_logs.return_value = mock_logs_response
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager), \
             patch('app.api.logs.export_logs', return_value='[{"test": "data"}]') as mock_export:
            
            response = client.get(
                "/admin/api/logs/export",
                params={
                    "format": "json",
                    "max_records": 1000,
                    "include_metadata": "true"
                }
            )
            
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json; charset=utf-8"
            assert "logs_export_" in response.headers["content-disposition"]
            
            mock_export.assert_called_once()
    
    def test_export_logs_csv(self, client, mock_admin_session, mock_log_manager, sample_log_response):
        """Test log export in CSV format."""
        mock_logs_response = LogListResponse(
            logs=[sample_log_response],
            total=1,
            page=1,
            page_size=10000,
            total_pages=1,
            has_next=False,
            has_prev=False
        )
        mock_log_manager.get_logs.return_value = mock_logs_response
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager), \
             patch('app.api.logs.export_logs', return_value='timestamp,level,message\n') as mock_export:
            
            response = client.get(
                "/admin/api/logs/export",
                params={"format": "csv"}
            )
            
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/csv; charset=utf-8"
    
    def test_export_logs_invalid_format(self, client, mock_admin_session, mock_log_manager):
        """Test log export with invalid format."""
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get(
                "/admin/api/logs/export",
                params={"format": "invalid"}
            )
            
            assert response.status_code == 400
            data = response.json()
            assert "Unsupported export format" in data["detail"]
    
    def test_get_log_statistics(self, client, mock_admin_session, mock_log_manager):
        """Test getting log statistics."""
        mock_stats = LogStats(
            total_logs=100,
            logs_by_level={
                LogLevel.INFO: 70,
                LogLevel.WARNING: 20,
                LogLevel.ERROR: 10
            },
            logs_by_module={
                "module1": 50,
                "module2": 30,
                "module3": 20
            },
            error_rate=10.0
        )
        mock_log_manager.get_stats.return_value = mock_stats
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get(
                "/admin/api/logs/stats",
                params={"days": 30}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert "stats" in data
            assert data["stats"]["total_logs"] == 100
            assert data["stats"]["error_rate"] == 10.0
            assert "generated_at" in data
            
            mock_log_manager.get_stats.assert_called_once_with(30)
    
    def test_get_log_configuration(self, client, mock_admin_session, mock_log_manager):
        """Test getting log configuration."""
        mock_config = LogConfig(
            global_level=LogLevel.INFO,
            enable_console=True,
            enable_redis=True,
            retention_days=30
        )
        mock_log_manager.get_config.return_value = mock_config
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get("/admin/api/logs/config")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["global_level"] == "INFO"
            assert data["enable_console"] is True
            assert data["enable_redis"] is True
            assert data["retention_days"] == 30
    
    def test_update_log_configuration(self, client, mock_admin_session, mock_log_manager):
        """Test updating log configuration."""
        mock_log_manager.save_config.return_value = True
        
        config_data = {
            "global_level": "WARNING",
            "enable_console": False,
            "enable_redis": True,
            "retention_days": 60,
            "max_logs_per_day": 50000,
            "batch_size": 200,
            "flush_interval": 10
        }
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager), \
             patch('app.api.logs.set_default_config') as mock_set_config:
            
            response = client.post(
                "/admin/api/logs/config",
                json=config_data
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["success"] is True
            assert "updated successfully" in data["message"]
            assert "config" in data
            
            mock_log_manager.save_config.assert_called_once()
            mock_set_config.assert_called_once()
    
    def test_update_log_configuration_save_failed(self, client, mock_admin_session, mock_log_manager):
        """Test updating log configuration when save fails."""
        mock_log_manager.save_config.return_value = False
        
        config_data = {
            "global_level": "ERROR",
            "retention_days": 90
        }
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.post(
                "/admin/api/logs/config",
                json=config_data
            )
            
            assert response.status_code == 500
            data = response.json()
            assert "Failed to save configuration" in data["detail"]
    
    def test_cleanup_old_logs(self, client, mock_admin_session, mock_log_manager):
        """Test cleaning up old logs."""
        mock_log_manager.cleanup_old_logs.return_value = 25
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.post("/admin/api/logs/cleanup")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["success"] is True
            assert data["deleted_count"] == 25
            assert "cleaned up 25 old log entries" in data["message"]
    
    def test_get_log_modules(self, client, mock_admin_session, mock_log_manager):
        """Test getting list of log modules."""
        mock_stats = LogStats(
            logs_by_module={
                "module1": 50,
                "module2": 30,
                "module3": 20
            }
        )
        mock_log_manager.get_stats.return_value = mock_stats
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get("/admin/api/logs/modules")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "modules" in data
            assert "count" in data
            assert len(data["modules"]) == 3
            assert data["count"] == 3
            assert "module1" in data["modules"]
            assert "module2" in data["modules"]
            assert "module3" in data["modules"]
    
    def test_get_log_levels(self, client, mock_admin_session):
        """Test getting available log levels."""
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session):
            
            response = client.get("/admin/api/logs/levels")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "levels" in data
            assert "descriptions" in data
            
            expected_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            for level in expected_levels:
                assert level in data["levels"]
                assert level in data["descriptions"]
    
    def test_api_error_handling(self, client, mock_admin_session, mock_log_manager):
        """Test API error handling."""
        # Mock log manager to raise exception
        mock_log_manager.get_logs.side_effect = Exception("Database error")
        
        with patch('app.api.logs.require_admin_auth', return_value=mock_admin_session), \
             patch('app.api.logs.get_log_manager', return_value=mock_log_manager):
            
            response = client.get("/admin/api/logs")
            
            assert response.status_code == 500
            data = response.json()
            assert "Failed to retrieve logs" in data["detail"]


class TestWebSocketLogs:
    """Test WebSocket logs endpoint."""
    
    def test_websocket_connection(self, client):
        """Test WebSocket connection establishment."""
        with client.websocket_connect("/admin/api/logs/live") as websocket:
            # Should receive connection confirmation
            data = websocket.receive_json()
            
            assert data["type"] == "connection"
            assert "Connected to live log stream" in data["message"]
            assert "timestamp" in data
    
    def test_websocket_echo(self, client):
        """Test WebSocket echo functionality."""
        with client.websocket_connect("/admin/api/logs/live") as websocket:
            # Receive connection confirmation
            websocket.receive_json()
            
            # Send test data
            test_data = {"filter": "test", "level": "ERROR"}
            websocket.send_json(test_data)
            
            # Should receive echo
            response = websocket.receive_json()
            
            assert response["type"] == "echo"
            assert response["data"] == test_data
            assert "timestamp" in response
    
    def test_websocket_error_handling(self, client):
        """Test WebSocket error handling."""
        with client.websocket_connect("/admin/api/logs/live") as websocket:
            # Receive connection confirmation
            websocket.receive_json()
            
            # Send invalid JSON (this might trigger error handling in real implementation)
            # For this test, we just verify the connection stays stable
            test_data = {"test": "data"}
            websocket.send_json(test_data)
            
            response = websocket.receive_json()
            assert response["type"] == "echo"


class TestLogsAPIIntegration:
    """Integration tests for logs API."""
    
    @pytest.mark.asyncio
    async def test_full_api_workflow(self):
        """Test complete API workflow with actual log manager."""
        # This would be a more comprehensive test with real Redis
        # For now, we'll just test the basic structure
        
        from app.services.log_manager import LogManager
        import fakeredis.aioredis
        
        # Create real log manager with fake Redis
        fake_redis = fakeredis.aioredis.FakeRedis()
        log_manager = LogManager(fake_redis)
        
        # Create a test log
        log_entry = LogEntry(
            level=LogLevel.INFO,
            message="Integration test log",
            module="integration_test"
        )
        
        # Store the log
        await log_manager.store_log(log_entry)
        
        # Create filter
        filters = LogFilter(page_size=10)
        
        # Retrieve logs
        result = await log_manager.get_logs(filters)
        
        assert isinstance(result, LogListResponse)
        assert len(result.logs) == 1
        assert result.logs[0].message == "Integration test log"
        
        # Test deletion
        success = await log_manager.delete_log(log_entry.id)
        assert success is True
        
        # Verify deletion
        retrieved = await log_manager.get_log_by_id(log_entry.id)
        assert retrieved is None