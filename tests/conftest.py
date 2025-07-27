"""Pytest configuration and shared fixtures for OpenRouter Middleware tests."""

import asyncio
import os
import tempfile
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.config import Settings
from app.core.redis import RedisManager
from app.core.security import SecurityManager
from app.main import app as fastapi_app
from app.services.key_manager import KeyManager
from app.services.proxy import ProxyService
from app.services.rotation import KeyRotationManager


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with safe defaults."""
    return Settings(
        session_secret_key="test-session-key-at-least-32-characters-long",
        admin_username="test_admin",
        admin_password="test_password",
        redis_url="redis://localhost:6379/0",
        debug=True,
        log_level="DEBUG"
    )


@pytest.fixture
async def redis_manager(test_settings: Settings) -> AsyncGenerator[RedisManager, None]:
    """Create a Redis manager with fake Redis for testing."""
    # Use fake Redis to avoid needing a real Redis instance
    fake_redis = fake_aioredis.FakeRedis()
    
    manager = RedisManager(test_settings.redis_url, test_settings.redis_password)
    # Replace the real Redis connection with fake one
    manager._redis = fake_redis
    manager._pool = None
    
    yield manager
    
    # Cleanup
    await manager.close()


@pytest.fixture
def security_manager() -> SecurityManager:
    """Create a security manager for testing."""
    return SecurityManager()


@pytest.fixture
async def key_manager(redis_manager: RedisManager, security_manager: SecurityManager) -> KeyManager:
    """Create a key manager for testing."""
    return KeyManager(redis_manager, security_manager)


@pytest.fixture
def rotation_service(key_manager: KeyManager) -> KeyRotationManager:
    """Create a rotation service for testing."""
    return KeyRotationManager(key_manager)


@pytest.fixture
def proxy_service(rotation_service: KeyRotationManager) -> ProxyService:
    """Create a proxy service for testing."""
    return ProxyService(rotation_service)


@pytest.fixture
async def app(test_settings: Settings, redis_manager: RedisManager):
    """Create a FastAPI app instance for testing."""
    # Override the settings and Redis manager
    app = fastapi_app
    
    # Replace dependencies with test instances
    from app.main import get_settings, get_redis_manager
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_redis_manager] = lambda: redis_manager
    
    yield app
    
    # Clear overrides
    app.dependency_overrides.clear()


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI app."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def async_client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client for the FastAPI app."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_client_key_data() -> dict:
    """Sample client key data for testing."""
    return {
        "user_id": "test_user",
        "rate_limit": 1000,
        "permissions": ["chat.completions", "models.list"]
    }


@pytest.fixture
def sample_openrouter_key() -> str:
    """Sample OpenRouter API key for testing."""
    return "sk-or-test-key-1234567890abcdef"


@pytest.fixture
def sample_openrouter_keys() -> list[str]:
    """Sample list of OpenRouter API keys for testing."""
    return [
        "sk-or-test-key-1234567890abcdef",
        "sk-or-test-key-abcdef1234567890",
        "sk-or-test-key-fedcba0987654321"
    ]


@pytest.fixture
def mock_httpx_response():
    """Mock httpx response for testing proxy functionality."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.content = b'{"test": "response"}'
    mock_response.text = '{"test": "response"}'
    mock_response.json.return_value = {"test": "response"}
    mock_response.aiter_raw.return_value = [b'{"test": "response"}']
    mock_response.aclose = AsyncMock()
    return mock_response


@pytest.fixture
def authenticated_session(client: TestClient) -> TestClient:
    """Create an authenticated session for admin tests."""
    # Login as admin
    response = client.post("/auth/login", data={
        "username": "test_admin",
        "password": "test_password"
    })
    assert response.status_code in [200, 302]  # Success or redirect
    return client


@pytest.fixture
def temp_file() -> Generator[str, None, None]:
    """Create a temporary file for testing file uploads."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("sk-or-test-key-1234567890abcdef\n")
        f.write("sk-or-test-key-abcdef1234567890\n")
        f.write("sk-or-test-key-fedcba0987654321\n")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "async_test: mark test as an async test"
    )


# Async test utilities
pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()