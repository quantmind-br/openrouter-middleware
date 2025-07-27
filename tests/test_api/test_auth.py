"""Tests for authentication API endpoints."""

import pytest
from fastapi.testclient import TestClient


class TestAuthAPI:
    """Test authentication API endpoints."""
    
    def test_login_page(self, client: TestClient):
        """Test login page renders correctly."""
        response = client.get("/auth/login")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "login" in response.text.lower()
    
    def test_login_success(self, client: TestClient, test_settings):
        """Test successful login."""
        response = client.post("/auth/login", data={
            "username": test_settings.admin_username,
            "password": test_settings.admin_password
        })
        
        # Should redirect to dashboard
        assert response.status_code == 302
        assert response.headers["location"] == "/"
        
        # Should set session cookie
        assert "session" in response.cookies
    
    def test_login_invalid_credentials(self, client: TestClient):
        """Test login with invalid credentials."""
        response = client.post("/auth/login", data={
            "username": "wrong_user",
            "password": "wrong_password"
        })
        
        # Should redirect back to login with error
        assert response.status_code == 302
        assert "login" in response.headers["location"]
    
    def test_login_missing_fields(self, client: TestClient):
        """Test login with missing fields."""
        # Missing password
        response = client.post("/auth/login", data={
            "username": "admin"
        })
        assert response.status_code == 422
        
        # Missing username
        response = client.post("/auth/login", data={
            "password": "password"
        })
        assert response.status_code == 422
    
    def test_logout(self, authenticated_session: TestClient):
        """Test logout functionality."""
        response = authenticated_session.post("/auth/logout")
        
        # Should redirect to login
        assert response.status_code == 302
        assert "login" in response.headers["location"]
        
        # Session should be cleared
        # Note: In a real test, you'd verify the session is invalidated
    
    def test_logout_unauthenticated(self, client: TestClient):
        """Test logout when not authenticated."""
        response = client.post("/auth/logout")
        
        # Should still redirect to login
        assert response.status_code == 302
        assert "login" in response.headers["location"]
    
    def test_protected_route_without_auth(self, client: TestClient):
        """Test accessing protected route without authentication."""
        response = client.get("/")
        
        # Should redirect to login
        assert response.status_code == 302
        assert "login" in response.headers["location"]
    
    def test_protected_route_with_auth(self, authenticated_session: TestClient):
        """Test accessing protected route with authentication."""
        response = authenticated_session.get("/")
        
        # Should access dashboard
        assert response.status_code == 200
        assert "dashboard" in response.text.lower()


class TestAPIKeyValidation:
    """Test API key validation for client requests."""
    
    def test_api_request_without_key(self, client: TestClient):
        """Test API request without API key."""
        response = client.get("/api/models")
        
        assert response.status_code == 401
        assert "authorization" in response.json()["detail"].lower()
    
    def test_api_request_invalid_key_format(self, client: TestClient):
        """Test API request with invalid key format."""
        response = client.get("/api/models", headers={
            "Authorization": "Invalid format"
        })
        
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_api_request_valid_key(self, async_client, key_manager):
        """Test API request with valid API key."""
        # Create a test client key
        result = await key_manager.create_client_key(
            user_id="test_api_user",
            rate_limit=1000
        )
        api_key = result["api_key"]
        
        # Make request with valid key
        response = await async_client.get("/api/models", headers={
            "Authorization": f"Bearer {api_key}"
        })
        
        # Should be allowed (even if the actual endpoint doesn't exist)
        # The middleware should pass it through
        assert response.status_code != 401  # Not unauthorized
    
    @pytest.mark.asyncio
    async def test_api_request_inactive_key(self, async_client, key_manager):
        """Test API request with inactive API key."""
        # Create and then deactivate a key
        result = await key_manager.create_client_key(
            user_id="inactive_user",
            rate_limit=1000
        )
        api_key = result["api_key"]
        
        # Manually deactivate the key in Redis
        key_hash = key_manager.security_manager.hash_api_key(api_key)
        client_key = await key_manager.get_client_key_by_hash(key_hash)
        client_key.is_active = False
        
        # Update in Redis
        import json
        redis = await key_manager.redis_manager.get_redis()
        await redis.hset("client_keys", key_hash, json.dumps(client_key.model_dump(), default=str))
        
        # Make request with inactive key
        response = await async_client.get("/api/models", headers={
            "Authorization": f"Bearer {api_key}"
        })
        
        assert response.status_code == 401