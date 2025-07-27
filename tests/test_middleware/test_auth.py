"""Tests for authentication middleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from app.middleware.auth import ClientAuthMiddleware
from app.models.keys import ClientAPIKey


class TestClientAuthMiddleware:
    """Test the ClientAuthMiddleware class."""
    
    @pytest.fixture
    def middleware(self, key_manager):
        """Create middleware instance for testing."""
        return ClientAuthMiddleware(key_manager)
    
    @pytest.mark.asyncio
    async def test_valid_api_key(self, middleware: ClientAuthMiddleware):
        """Test middleware with valid API key."""
        # Mock valid client key
        mock_key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="valid_hash",
            rate_limit=1000,
            is_active=True
        )
        
        # Mock key manager
        middleware.key_manager.get_client_key_by_hash = AsyncMock(return_value=mock_key)
        middleware.key_manager.update_client_key_usage = AsyncMock()
        
        # Create mock request with valid authorization
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer sk-or-valid-key"}
        mock_request.state = MagicMock()
        
        # Mock call_next
        mock_response = JSONResponse({"success": True})
        call_next = AsyncMock(return_value=mock_response)
        
        # Process request
        response = await middleware.dispatch(mock_request, call_next)
        
        # Should succeed
        assert response == mock_response
        call_next.assert_called_once_with(mock_request)
        
        # Should update usage
        middleware.key_manager.update_client_key_usage.assert_called_once()
        
        # Should set client info in request state
        assert hasattr(mock_request.state, 'client_key')
        assert mock_request.state.client_key == mock_key
    
    @pytest.mark.asyncio
    async def test_missing_authorization_header(self, middleware: ClientAuthMiddleware):
        """Test middleware with missing authorization header."""
        # Create mock request without authorization
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}
        
        call_next = AsyncMock()
        
        # Should return 401 error
        response = await middleware.dispatch(mock_request, call_next)
        
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        call_next.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_invalid_authorization_format(self, middleware: ClientAuthMiddleware):
        """Test middleware with invalid authorization format."""
        # Create mock request with invalid format
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Invalid format"}
        
        call_next = AsyncMock()
        
        # Should return 401 error
        response = await middleware.dispatch(mock_request, call_next)
        
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        call_next.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_nonexistent_api_key(self, middleware: ClientAuthMiddleware):
        """Test middleware with non-existent API key."""
        # Mock key manager to return None
        middleware.key_manager.get_client_key_by_hash = AsyncMock(return_value=None)
        
        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer sk-or-nonexistent-key"}
        
        call_next = AsyncMock()
        
        # Should return 401 error
        response = await middleware.dispatch(mock_request, call_next)
        
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        call_next.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_inactive_api_key(self, middleware: ClientAuthMiddleware):
        """Test middleware with inactive API key."""
        # Mock inactive client key
        mock_key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="inactive_hash",
            rate_limit=1000,
            is_active=False  # Inactive
        )
        
        middleware.key_manager.get_client_key_by_hash = AsyncMock(return_value=mock_key)
        
        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer sk-or-inactive-key"}
        
        call_next = AsyncMock()
        
        # Should return 401 error
        response = await middleware.dispatch(mock_request, call_next)
        
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        call_next.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, middleware: ClientAuthMiddleware):
        """Test rate limiting functionality."""
        # Mock client key with low rate limit
        mock_key = ClientAPIKey(
            user_id="rate_limited_user",
            api_key_hash="limited_hash",
            rate_limit=1,  # Very low limit
            usage_count=2,  # Already exceeded
            is_active=True
        )
        
        middleware.key_manager.get_client_key_by_hash = AsyncMock(return_value=mock_key)
        
        # Mock rate limit check to return True (exceeded)
        with pytest.mock.patch.object(middleware, '_check_rate_limit', return_value=True):
            # Create mock request
            mock_request = MagicMock(spec=Request)
            mock_request.headers = {"authorization": "Bearer sk-or-limited-key"}
            
            call_next = AsyncMock()
            
            # Should return 429 error
            response = await middleware.dispatch(mock_request, call_next)
            
            assert isinstance(response, JSONResponse)
            assert response.status_code == 429
            call_next.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_database_error_handling(self, middleware: ClientAuthMiddleware):
        """Test handling of database errors."""
        # Mock key manager to raise exception
        middleware.key_manager.get_client_key_by_hash = AsyncMock(
            side_effect=Exception("Database error")
        )
        
        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer sk-or-any-key"}
        
        call_next = AsyncMock()
        
        # Should return 500 error
        response = await middleware.dispatch(mock_request, call_next)
        
        assert isinstance(response, JSONResponse)
        assert response.status_code == 500
        call_next.assert_not_called()
    
    def test_extract_api_key_valid(self, middleware: ClientAuthMiddleware):
        """Test extracting API key from valid authorization header."""
        headers = {"authorization": "Bearer sk-or-test-key-123"}
        
        api_key = middleware._extract_api_key(headers)
        assert api_key == "sk-or-test-key-123"
    
    def test_extract_api_key_invalid_format(self, middleware: ClientAuthMiddleware):
        """Test extracting API key from invalid authorization header."""
        # Missing Bearer prefix
        headers = {"authorization": "sk-or-test-key-123"}
        api_key = middleware._extract_api_key(headers)
        assert api_key is None
        
        # Wrong prefix
        headers = {"authorization": "Basic sk-or-test-key-123"}
        api_key = middleware._extract_api_key(headers)
        assert api_key is None
        
        # Empty value
        headers = {"authorization": "Bearer "}
        api_key = middleware._extract_api_key(headers)
        assert api_key is None
    
    def test_extract_api_key_missing_header(self, middleware: ClientAuthMiddleware):
        """Test extracting API key when header is missing."""
        headers = {}
        
        api_key = middleware._extract_api_key(headers)
        assert api_key is None
    
    def test_check_rate_limit(self, middleware: ClientAuthMiddleware):
        """Test rate limit checking logic."""
        # Mock client key with rate limit
        mock_key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="test_hash",
            rate_limit=100,  # 100 per hour
            usage_count=50,  # Under limit
            is_active=True
        )
        
        # Should not be rate limited
        is_limited = middleware._check_rate_limit(mock_key)
        assert is_limited is False
        
        # Test with usage at limit
        mock_key.usage_count = 100
        is_limited = middleware._check_rate_limit(mock_key)
        assert is_limited is True
        
        # Test with usage over limit
        mock_key.usage_count = 150
        is_limited = middleware._check_rate_limit(mock_key)
        assert is_limited is True
    
    @pytest.mark.asyncio
    async def test_case_insensitive_header(self, middleware: ClientAuthMiddleware):
        """Test case-insensitive authorization header."""
        # Mock valid client key
        mock_key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="valid_hash",
            rate_limit=1000,
            is_active=True
        )
        
        middleware.key_manager.get_client_key_by_hash = AsyncMock(return_value=mock_key)
        middleware.key_manager.update_client_key_usage = AsyncMock()
        
        # Test different case variations
        headers_variations = [
            {"Authorization": "Bearer sk-or-test-key"},
            {"AUTHORIZATION": "Bearer sk-or-test-key"},
            {"authorization": "Bearer sk-or-test-key"},
        ]
        
        for headers in headers_variations:
            mock_request = MagicMock(spec=Request)
            mock_request.headers = headers
            mock_request.state = MagicMock()
            
            call_next = AsyncMock(return_value=JSONResponse({"success": True}))
            
            response = await middleware.dispatch(mock_request, call_next)
            
            # Should succeed for all variations
            call_next.assert_called_with(mock_request)
    
    @pytest.mark.asyncio
    async def test_middleware_preserves_request_state(self, middleware: ClientAuthMiddleware):
        """Test that middleware preserves existing request state."""
        # Mock valid client key
        mock_key = ClientAPIKey(
            user_id="test_user",
            api_key_hash="valid_hash",
            rate_limit=1000,
            is_active=True
        )
        
        middleware.key_manager.get_client_key_by_hash = AsyncMock(return_value=mock_key)
        middleware.key_manager.update_client_key_usage = AsyncMock()
        
        # Create mock request with existing state
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer sk-or-test-key"}
        mock_request.state = MagicMock()
        mock_request.state.existing_attribute = "existing_value"
        
        call_next = AsyncMock(return_value=JSONResponse({"success": True}))
        
        await middleware.dispatch(mock_request, call_next)
        
        # Should preserve existing state
        assert mock_request.state.existing_attribute == "existing_value"
        # Should add client key
        assert hasattr(mock_request.state, 'client_key')
        assert mock_request.state.client_key == mock_key