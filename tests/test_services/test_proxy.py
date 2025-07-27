"""Tests for proxy service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from app.services.proxy import ProxyService


class TestProxyService:
    """Test the ProxyService class."""
    
    def test_proxy_service_initialization(self, proxy_service: ProxyService):
        """Test proxy service initialization."""
        assert proxy_service.rotation_service is not None
        assert proxy_service.base_url == "https://openrouter.ai/api/v1"
        assert proxy_service.timeout == 30
    
    @pytest.mark.asyncio
    async def test_proxy_request_success(self, proxy_service: ProxyService, mock_httpx_response):
        """Test successful proxy request."""
        # Mock rotation service to return a key
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        
        # Mock httpx client
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_httpx_response
            
            # Create a mock request
            mock_request = MagicMock(spec=Request)
            mock_request.method = "POST"
            mock_request.url.path = "/chat/completions"
            mock_request.headers = {"content-type": "application/json"}
            mock_request.body.return_value = b'{"model": "gpt-3.5-turbo"}'
            
            # Make proxy request
            response = await proxy_service.proxy_request(mock_request)
            
            # Verify response
            assert isinstance(response, StreamingResponse)
            
            # Verify the request was made correctly
            mock_client_instance.request.assert_called_once()
            call_args = mock_client_instance.request.call_args
            
            # Check method and URL
            assert call_args[1]["method"] == "POST"
            assert "chat/completions" in call_args[1]["url"]
            
            # Check headers include authorization
            headers = call_args[1]["headers"]
            assert "Authorization" in headers
            assert headers["Authorization"] == "Bearer sk-or-test-key"
    
    @pytest.mark.asyncio
    async def test_proxy_request_no_available_keys(self, proxy_service: ProxyService):
        """Test proxy request when no keys are available."""
        # Mock rotation service to return None
        proxy_service.rotation_service.get_next_key = AsyncMock(return_value=None)
        
        # Create a mock request
        mock_request = MagicMock(spec=Request)
        
        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await proxy_service.proxy_request(mock_request)
        
        assert exc_info.value.status_code == 503
        assert "No API keys available" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_proxy_request_http_error(self, proxy_service: ProxyService):
        """Test proxy request with HTTP error from upstream."""
        # Mock rotation service
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        proxy_service.rotation_service.record_key_usage = AsyncMock()
        
        # Mock httpx client to raise HTTP error
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            # Create HTTP error response
            error_response = MagicMock()
            error_response.status_code = 429
            error_response.content = b'{"error": "Rate limit exceeded"}'
            error_response.headers = {"content-type": "application/json"}
            
            http_error = httpx.HTTPStatusError(
                "Rate limit exceeded", 
                request=MagicMock(), 
                response=error_response
            )
            mock_client_instance.request.side_effect = http_error
            
            # Create mock request
            mock_request = MagicMock(spec=Request)
            mock_request.method = "POST"
            mock_request.url.path = "/chat/completions"
            mock_request.headers = {}
            mock_request.body.return_value = b'{"model": "gpt-3.5-turbo"}'
            
            # Should raise HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await proxy_service.proxy_request(mock_request)
            
            assert exc_info.value.status_code == 429
            
            # Should record failure
            proxy_service.rotation_service.record_key_usage.assert_called_once_with(
                "sk-or-test-key", success=False
            )
    
    @pytest.mark.asyncio
    async def test_proxy_request_connection_error(self, proxy_service: ProxyService):
        """Test proxy request with connection error."""
        # Mock rotation service
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        proxy_service.rotation_service.record_key_usage = AsyncMock()
        
        # Mock httpx client to raise connection error
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.side_effect = httpx.ConnectError("Connection failed")
            
            # Create mock request
            mock_request = MagicMock(spec=Request)
            mock_request.method = "GET"
            mock_request.url.path = "/models"
            mock_request.headers = {}
            mock_request.body.return_value = b''
            
            # Should raise HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await proxy_service.proxy_request(mock_request)
            
            assert exc_info.value.status_code == 502
            assert "upstream server" in str(exc_info.value.detail).lower()
            
            # Should record failure
            proxy_service.rotation_service.record_key_usage.assert_called_once_with(
                "sk-or-test-key", success=False
            )
    
    @pytest.mark.asyncio
    async def test_proxy_request_timeout(self, proxy_service: ProxyService):
        """Test proxy request with timeout."""
        # Mock rotation service
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        proxy_service.rotation_service.record_key_usage = AsyncMock()
        
        # Mock httpx client to raise timeout
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.side_effect = httpx.TimeoutException("Request timeout")
            
            # Create mock request
            mock_request = MagicMock(spec=Request)
            mock_request.method = "POST"
            mock_request.url.path = "/chat/completions"
            mock_request.headers = {}
            mock_request.body.return_value = b'{"model": "gpt-4"}'
            
            # Should raise HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await proxy_service.proxy_request(mock_request)
            
            assert exc_info.value.status_code == 504
            assert "timeout" in str(exc_info.value.detail).lower()
            
            # Should record failure
            proxy_service.rotation_service.record_key_usage.assert_called_once_with(
                "sk-or-test-key", success=False
            )
    
    def test_build_upstream_url(self, proxy_service: ProxyService):
        """Test building upstream URL from request path."""
        # Test basic path
        url = proxy_service._build_upstream_url("/chat/completions")
        assert url == "https://openrouter.ai/api/v1/chat/completions"
        
        # Test path with query parameters
        url = proxy_service._build_upstream_url("/models?type=text")
        assert url == "https://openrouter.ai/api/v1/models?type=text"
        
        # Test root path
        url = proxy_service._build_upstream_url("/")
        assert url == "https://openrouter.ai/api/v1/"
    
    def test_prepare_headers(self, proxy_service: ProxyService):
        """Test header preparation for upstream request."""
        original_headers = {
            "content-type": "application/json",
            "user-agent": "test-client",
            "host": "localhost:8080",  # Should be removed
            "authorization": "Bearer old-key"  # Should be replaced
        }
        
        api_key = "sk-or-new-key"
        headers = proxy_service._prepare_headers(original_headers, api_key)
        
        # Should preserve content-type and user-agent
        assert headers["content-type"] == "application/json"
        assert headers["user-agent"] == "test-client"
        
        # Should remove host
        assert "host" not in headers
        
        # Should set new authorization
        assert headers["authorization"] == "Bearer sk-or-new-key"
    
    def test_prepare_headers_no_authorization(self, proxy_service: ProxyService):
        """Test header preparation when no authorization exists."""
        original_headers = {
            "content-type": "application/json"
        }
        
        api_key = "sk-or-test-key"
        headers = proxy_service._prepare_headers(original_headers, api_key)
        
        assert headers["authorization"] == "Bearer sk-or-test-key"
    
    @pytest.mark.asyncio
    async def test_different_http_methods(self, proxy_service: ProxyService, mock_httpx_response):
        """Test proxy with different HTTP methods."""
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        
        methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        
        for method in methods:
            with patch('httpx.AsyncClient') as mock_client:
                mock_client_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_client_instance
                mock_client_instance.request.return_value = mock_httpx_response
                
                # Create mock request
                mock_request = MagicMock(spec=Request)
                mock_request.method = method
                mock_request.url.path = "/test"
                mock_request.headers = {}
                mock_request.body.return_value = b'{"test": "data"}'
                
                # Make proxy request
                response = await proxy_service.proxy_request(mock_request)
                assert isinstance(response, StreamingResponse)
                
                # Verify correct method was used
                call_args = mock_client_instance.request.call_args
                assert call_args[1]["method"] == method
    
    @pytest.mark.asyncio
    async def test_request_body_handling(self, proxy_service: ProxyService, mock_httpx_response):
        """Test handling of request body."""
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_httpx_response
            
            # Create mock request with body
            test_body = b'{"model": "gpt-3.5-turbo", "messages": []}'
            mock_request = MagicMock(spec=Request)
            mock_request.method = "POST"
            mock_request.url.path = "/chat/completions"
            mock_request.headers = {"content-type": "application/json"}
            mock_request.body.return_value = test_body
            
            # Make proxy request
            await proxy_service.proxy_request(mock_request)
            
            # Verify body was passed through
            call_args = mock_client_instance.request.call_args
            assert call_args[1]["content"] == test_body
    
    @pytest.mark.asyncio
    async def test_response_streaming(self, proxy_service: ProxyService):
        """Test response streaming functionality."""
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        
        # Mock streaming response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aiter_raw.return_value = [b'{"chunk": 1}', b'{"chunk": 2}']
        mock_response.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_response
            
            # Create mock request
            mock_request = MagicMock(spec=Request)
            mock_request.method = "POST"
            mock_request.url.path = "/chat/completions"
            mock_request.headers = {}
            mock_request.body.return_value = b'{"stream": true}'
            
            # Make proxy request
            response = await proxy_service.proxy_request(mock_request)
            
            # Verify streaming response
            assert isinstance(response, StreamingResponse)
            assert response.status_code == 200
            
            # Verify headers are passed through
            # Note: StreamingResponse headers are set during initialization
    
    @pytest.mark.asyncio
    async def test_success_recording(self, proxy_service: ProxyService, mock_httpx_response):
        """Test that successful requests are recorded."""
        # Mock successful response
        mock_httpx_response.status_code = 200
        
        proxy_service.rotation_service.get_next_key = AsyncMock(
            return_value="sk-or-test-key"
        )
        proxy_service.rotation_service.record_key_usage = AsyncMock()
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            mock_client_instance.request.return_value = mock_httpx_response
            
            # Create mock request
            mock_request = MagicMock(spec=Request)
            mock_request.method = "GET"
            mock_request.url.path = "/models"
            mock_request.headers = {}
            mock_request.body.return_value = b''
            
            # Make proxy request
            await proxy_service.proxy_request(mock_request)
            
            # Should record success
            proxy_service.rotation_service.record_key_usage.assert_called_once_with(
                "sk-or-test-key", success=True
            )