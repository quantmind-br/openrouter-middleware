"""Tests for core configuration module."""

import os
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


class TestSettings:
    """Test the Settings class and configuration validation."""
    
    def test_default_settings(self):
        """Test that default settings are valid."""
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password"
        )
        
        assert settings.app_name == "OpenRouter Middleware"
        assert settings.app_version == "1.0.0"
        assert settings.debug is False
        assert settings.host == "0.0.0.0"
        assert settings.port == 8080
        assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
        assert settings.default_rate_limit == 1000
        assert "http://localhost:3000" in settings.allowed_origins
    
    def test_session_secret_key_validation(self):
        """Test session secret key validation."""
        # Too short key should fail
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(
                session_secret_key="short",
                admin_username="test_admin",
                admin_password="test_password"
            )
        
        # Valid key should pass
        settings = Settings(
            session_secret_key="this-is-a-valid-32-character-key!!!",
            admin_username="test_admin",
            admin_password="test_password"
        )
        assert len(settings.session_secret_key) >= 32
    
    def test_admin_password_validation(self):
        """Test admin password validation."""
        # Too short password should fail
        with pytest.raises(ValidationError, match="at least 8 characters"):
            Settings(
                session_secret_key="test-session-key-at-least-32-characters-long",
                admin_username="test_admin",
                admin_password="short"
            )
        
        # Valid password should pass
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="valid_password"
        )
        assert len(settings.admin_password) >= 8
    
    def test_admin_username_validation(self):
        """Test admin username validation."""
        # Too short username should fail
        with pytest.raises(ValidationError, match="at least 3 characters"):
            Settings(
                session_secret_key="test-session-key-at-least-32-characters-long",
                admin_username="ab",
                admin_password="test_password"
            )
        
        # Valid username should pass
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password"
        )
        assert len(settings.admin_username) >= 3
    
    def test_redis_url_validation(self):
        """Test Redis URL validation."""
        # Invalid Redis URL should fail
        with pytest.raises(ValidationError, match="must start with redis://"):
            Settings(
                session_secret_key="test-session-key-at-least-32-characters-long",
                admin_username="test_admin",
                admin_password="test_password",
                redis_url="invalid://url"
            )
        
        # Valid Redis URL should pass
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password",
            redis_url="redis://localhost:6379/0"
        )
        assert settings.redis_url.startswith("redis://")
        
        # Valid secure Redis URL should pass
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password",
            redis_url="rediss://localhost:6380/0"
        )
        assert settings.redis_url.startswith("rediss://")
    
    def test_environment_variable_override(self, monkeypatch):
        """Test that environment variables override defaults."""
        # Set environment variables
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("DEFAULT_RATE_LIMIT", "2000")
        
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password"
        )
        
        assert settings.debug is True
        assert settings.port == 9000
        assert settings.log_level == "DEBUG"
        assert settings.default_rate_limit == 2000
    
    def test_cors_settings(self):
        """Test CORS configuration."""
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password"
        )
        
        assert "GET" in settings.allowed_methods
        assert "POST" in settings.allowed_methods
        assert "PUT" in settings.allowed_methods
        assert "DELETE" in settings.allowed_methods
        assert "OPTIONS" in settings.allowed_methods
        assert "*" in settings.allowed_headers
        assert settings.allow_credentials is True
    
    def test_get_settings_cached(self):
        """Test that get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()
        
        # Should be the same instance (cached)
        assert settings1 is settings2
    
    def test_optional_redis_password(self):
        """Test that Redis password is optional."""
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password",
            redis_password=None
        )
        
        assert settings.redis_password is None
        
        # With password
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password",
            redis_password="redis_pass"
        )
        
        assert settings.redis_password == "redis_pass"
    
    def test_rate_limiting_configuration(self):
        """Test rate limiting configuration."""
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password"
        )
        
        assert settings.default_rate_limit == 1000
        assert settings.rate_limit_window == 3600  # 1 hour in seconds
    
    def test_openrouter_configuration(self):
        """Test OpenRouter service configuration."""
        settings = Settings(
            session_secret_key="test-session-key-at-least-32-characters-long",
            admin_username="test_admin",
            admin_password="test_password"
        )
        
        assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
        assert settings.default_timeout == 30
        assert settings.max_retries == 3