"""Tests for admin models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.admin import LoginRequest, AdminSession, SystemStatus


class TestLoginRequest:
    """Test the LoginRequest model."""
    
    def test_login_request_creation(self):
        """Test creating a valid login request."""
        request = LoginRequest(
            username="admin_user",
            password="secure_password"
        )
        
        assert request.username == "admin_user"
        assert request.password == "secure_password"
    
    def test_login_request_validation_errors(self):
        """Test validation errors for login request."""
        # Missing required fields
        with pytest.raises(ValidationError):
            LoginRequest()
        
        # Missing username
        with pytest.raises(ValidationError):
            LoginRequest(password="password")
        
        # Missing password
        with pytest.raises(ValidationError):
            LoginRequest(username="admin")
        
        # Empty username
        with pytest.raises(ValidationError):
            LoginRequest(username="", password="password")
        
        # Empty password
        with pytest.raises(ValidationError):
            LoginRequest(username="admin", password="")
    
    def test_login_request_string_types(self):
        """Test that username and password are strings."""
        request = LoginRequest(
            username="test_admin",
            password="test_password"
        )
        
        assert isinstance(request.username, str)
        assert isinstance(request.password, str)
    
    def test_login_request_whitespace_handling(self):
        """Test handling of whitespace in credentials."""
        # Leading/trailing whitespace should be preserved
        request = LoginRequest(
            username="  admin  ",
            password="  password  "
        )
        
        assert request.username == "  admin  "
        assert request.password == "  password  "
    
    def test_login_request_json_serialization(self):
        """Test JSON serialization (should exclude password)."""
        request = LoginRequest(
            username="admin",
            password="secret"
        )
        
        # Serialize to dict
        request_dict = request.model_dump()
        assert "username" in request_dict
        assert "password" in request_dict  # Note: This model doesn't exclude it
        
        # In a real app, you might want to exclude password from serialization
        # but this basic model includes all fields


class TestAdminSession:
    """Test the AdminSession model."""
    
    def test_admin_session_creation(self):
        """Test creating a valid admin session."""
        session = AdminSession(
            session_id="session_123456",
            username="admin_user",
            is_active=True
        )
        
        assert session.session_id == "session_123456"
        assert session.username == "admin_user"
        assert session.is_active is True
        assert isinstance(session.created_at, datetime)
        assert session.last_activity is None
    
    def test_admin_session_with_defaults(self):
        """Test creating admin session with default values."""
        session = AdminSession(
            session_id="session_456",
            username="admin"
        )
        
        assert session.is_active is True  # default
        assert session.last_activity is None  # default
        assert isinstance(session.created_at, datetime)
    
    def test_admin_session_validation_errors(self):
        """Test validation errors for admin session."""
        # Missing required fields
        with pytest.raises(ValidationError):
            AdminSession()
        
        # Missing session_id
        with pytest.raises(ValidationError):
            AdminSession(username="admin")
        
        # Missing username
        with pytest.raises(ValidationError):
            AdminSession(session_id="session_123")
        
        # Empty session_id
        with pytest.raises(ValidationError):
            AdminSession(session_id="", username="admin")
        
        # Empty username
        with pytest.raises(ValidationError):
            AdminSession(session_id="session_123", username="")
    
    def test_admin_session_datetime_handling(self):
        """Test datetime field handling."""
        now = datetime.now()
        session = AdminSession(
            session_id="session_time",
            username="admin",
            last_activity=now
        )
        
        assert session.last_activity == now
        assert isinstance(session.created_at, datetime)
        # created_at should be auto-generated and different from last_activity
        assert session.created_at != session.last_activity
    
    def test_admin_session_inactive_state(self):
        """Test creating inactive session."""
        session = AdminSession(
            session_id="inactive_session",
            username="admin",
            is_active=False,
            last_activity=datetime.now()
        )
        
        assert session.is_active is False
        assert session.last_activity is not None
    
    def test_admin_session_json_serialization(self):
        """Test JSON serialization/deserialization."""
        session = AdminSession(
            session_id="json_session",
            username="json_admin",
            is_active=True
        )
        
        # Serialize to dict
        session_dict = session.model_dump()
        assert isinstance(session_dict, dict)
        assert session_dict["session_id"] == "json_session"
        assert session_dict["username"] == "json_admin"
        assert session_dict["is_active"] is True
        
        # Deserialize from dict
        session_restored = AdminSession(**session_dict)
        assert session_restored.session_id == session.session_id
        assert session_restored.username == session.username
        assert session_restored.is_active == session.is_active


class TestSystemStatus:
    """Test the SystemStatus model."""
    
    def test_system_status_creation(self):
        """Test creating a valid system status."""
        status = SystemStatus(
            redis_healthy=True,
            total_client_keys=10,
            active_client_keys=8,
            total_openrouter_keys=5,
            healthy_openrouter_keys=4,
            total_requests_today=1000,
            failed_requests_today=50
        )
        
        assert status.redis_healthy is True
        assert status.total_client_keys == 10
        assert status.active_client_keys == 8
        assert status.total_openrouter_keys == 5
        assert status.healthy_openrouter_keys == 4
        assert status.total_requests_today == 1000
        assert status.failed_requests_today == 50
    
    def test_system_status_with_defaults(self):
        """Test system status with default values."""
        status = SystemStatus()
        
        assert status.redis_healthy is False  # default
        assert status.total_client_keys == 0  # default
        assert status.active_client_keys == 0  # default
        assert status.total_openrouter_keys == 0  # default
        assert status.healthy_openrouter_keys == 0  # default
        assert status.total_requests_today == 0  # default
        assert status.failed_requests_today == 0  # default
    
    def test_system_status_validation(self):
        """Test validation of system status."""
        # Negative values should fail
        with pytest.raises(ValidationError):
            SystemStatus(total_client_keys=-1)
        
        with pytest.raises(ValidationError):
            SystemStatus(active_client_keys=-1)
        
        with pytest.raises(ValidationError):
            SystemStatus(total_openrouter_keys=-1)
        
        with pytest.raises(ValidationError):
            SystemStatus(healthy_openrouter_keys=-1)
        
        with pytest.raises(ValidationError):
            SystemStatus(total_requests_today=-1)
        
        with pytest.raises(ValidationError):
            SystemStatus(failed_requests_today=-1)
    
    def test_system_status_logical_consistency(self):
        """Test logical consistency of status values."""
        # Active keys should not exceed total keys
        status = SystemStatus(
            total_client_keys=10,
            active_client_keys=5,  # Valid: less than total
            total_openrouter_keys=8,
            healthy_openrouter_keys=6  # Valid: less than total
        )
        
        assert status.active_client_keys <= status.total_client_keys
        assert status.healthy_openrouter_keys <= status.total_openrouter_keys
    
    def test_system_status_edge_cases(self):
        """Test edge cases for system status."""
        # All zeros
        status_empty = SystemStatus()
        assert status_empty.total_client_keys == 0
        assert status_empty.active_client_keys == 0
        
        # Equal values (all keys active/healthy)
        status_full = SystemStatus(
            total_client_keys=10,
            active_client_keys=10,
            total_openrouter_keys=5,
            healthy_openrouter_keys=5
        )
        assert status_full.active_client_keys == status_full.total_client_keys
        assert status_full.healthy_openrouter_keys == status_full.total_openrouter_keys
    
    def test_system_status_health_indicators(self):
        """Test health indicator patterns."""
        # Healthy system
        healthy_status = SystemStatus(
            redis_healthy=True,
            total_client_keys=100,
            active_client_keys=95,
            total_openrouter_keys=10,
            healthy_openrouter_keys=10,
            total_requests_today=10000,
            failed_requests_today=10  # Low failure rate
        )
        
        assert healthy_status.redis_healthy is True
        failure_rate = healthy_status.failed_requests_today / healthy_status.total_requests_today
        assert failure_rate < 0.01  # Less than 1% failure rate
        
        # Unhealthy system
        unhealthy_status = SystemStatus(
            redis_healthy=False,
            total_client_keys=100,
            active_client_keys=50,  # Many inactive
            total_openrouter_keys=10,
            healthy_openrouter_keys=3,  # Many unhealthy
            total_requests_today=1000,
            failed_requests_today=500  # High failure rate
        )
        
        assert unhealthy_status.redis_healthy is False
        if unhealthy_status.total_requests_today > 0:
            failure_rate = unhealthy_status.failed_requests_today / unhealthy_status.total_requests_today
            assert failure_rate > 0.1  # More than 10% failure rate
    
    def test_system_status_json_serialization(self):
        """Test JSON serialization/deserialization."""
        status = SystemStatus(
            redis_healthy=True,
            total_client_keys=50,
            active_client_keys=45,
            total_requests_today=5000,
            failed_requests_today=25
        )
        
        # Serialize to dict
        status_dict = status.model_dump()
        assert isinstance(status_dict, dict)
        assert status_dict["redis_healthy"] is True
        assert status_dict["total_client_keys"] == 50
        assert status_dict["active_client_keys"] == 45
        
        # Deserialize from dict
        status_restored = SystemStatus(**status_dict)
        assert status_restored.redis_healthy == status.redis_healthy
        assert status_restored.total_client_keys == status.total_client_keys
        assert status_restored.total_requests_today == status.total_requests_today