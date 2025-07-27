"""Proxy service for forwarding requests to OpenRouter with streaming support."""

import asyncio
import logging
from typing import Dict, Optional, Any, AsyncGenerator
from urllib.parse import urljoin

import httpx
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.core.config import get_settings
from app.services.key_manager import KeyManager
from app.services.rotation import KeyRotationManager

logger = logging.getLogger(__name__)
settings = get_settings()


class ProxyService:
    """Service for proxying requests to OpenRouter with intelligent key rotation."""
    
    def __init__(self, key_manager: KeyManager, rotation_manager: KeyRotationManager):
        self.key_manager = key_manager
        self.rotation_manager = rotation_manager
        self.base_url = settings.openrouter_base_url
        
        # Create reusable HTTP client with optimized settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,    # Connection timeout
                read=settings.default_timeout,      # Read timeout
                write=10.0,      # Write timeout
                pool=30.0        # Pool timeout
            ),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100
            ),
            follow_redirects=False,  # Don't follow redirects automatically
            verify=True              # Verify SSL certificates
        )
    
    async def proxy_request(self, request: Request, path: str) -> StreamingResponse:
        """Proxy a request to OpenRouter with intelligent key rotation."""
        max_retries = 3
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # Select an OpenRouter key
                key_selection = await self.rotation_manager.select_key()
                if not key_selection:
                    raise HTTPException(
                        status_code=503, 
                        detail="No healthy OpenRouter keys available"
                    )
                
                key_hash, key_data = key_selection
                
                # Get the actual API key (this would need secure key retrieval)
                # For now, we'll assume we have a method to get the key securely
                openrouter_api_key = await self._get_api_key_securely(key_hash)
                if not openrouter_api_key:
                    await self.rotation_manager.report_failure(
                        key_hash, "Failed to retrieve API key"
                    )
                    continue
                
                # Prepare the request
                target_url = urljoin(self.base_url, path)
                headers = self._prepare_headers(request, openrouter_api_key)
                
                # Handle request body
                request_body = await self._get_request_body(request)
                
                # Make the proxied request
                response = await self._make_request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=request_body,
                    params=dict(request.query_params)
                )
                
                # Check for rate limiting or other failures
                if response.status_code == 429:
                    await self.rotation_manager.report_failure(
                        key_hash, "Rate limited", is_rate_limit=True
                    )
                    await response.aclose()
                    continue
                elif response.status_code >= 500:
                    await self.rotation_manager.report_failure(
                        key_hash, f"Server error: {response.status_code}"
                    )
                    await response.aclose()
                    continue
                elif response.status_code >= 400:
                    # Client errors should be passed through without marking key as failed
                    pass
                else:
                    # Success
                    await self.rotation_manager.report_success(key_hash)
                
                # Return streaming response
                return self._create_streaming_response(response)
                
            except httpx.TimeoutException as e:
                last_exception = e
                if 'key_hash' in locals():
                    await self.rotation_manager.report_failure(
                        key_hash, f"Request timeout: {str(e)}"
                    )
                logger.warning(f"Request timeout on attempt {attempt + 1}: {e}")
                
            except httpx.ConnectError as e:
                last_exception = e
                if 'key_hash' in locals():
                    await self.rotation_manager.report_failure(
                        key_hash, f"Connection error: {str(e)}"
                    )
                logger.warning(f"Connection error on attempt {attempt + 1}: {e}")
                
            except Exception as e:
                last_exception = e
                if 'key_hash' in locals():
                    await self.rotation_manager.report_failure(
                        key_hash, f"Unexpected error: {str(e)}"
                    )
                logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            
            # Wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        
        # All retries exhausted
        logger.error(f"All proxy attempts failed. Last error: {last_exception}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to proxy request after {max_retries} attempts"
        )
    
    def _prepare_headers(self, request: Request, openrouter_api_key: str) -> Dict[str, str]:
        """Prepare headers for the proxied request."""
        # Start with original headers
        headers = dict(request.headers)
        
        # Remove hop-by-hop headers that shouldn't be forwarded
        hop_by_hop_headers = {
            'host', 'connection', 'upgrade', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding',
            'accept-encoding', 'content-length'  # Let httpx handle these
        }
        
        for header in hop_by_hop_headers:
            headers.pop(header, None)
        
        # Remove our internal headers
        headers.pop('x-client-api-key', None)
        
        # Add/modify necessary headers
        headers['authorization'] = f"Bearer {openrouter_api_key}"
        headers['x-forwarded-for'] = request.client.host if request.client else 'unknown'
        headers['user-agent'] = f"OpenRouter-Middleware/1.0 {headers.get('user-agent', '')}"
        
        # Ensure content-type is preserved for POST/PUT requests
        if request.method in ['POST', 'PUT', 'PATCH'] and 'content-type' not in headers:
            headers['content-type'] = 'application/json'
        
        return headers
    
    async def _get_request_body(self, request: Request) -> bytes:
        """Get request body safely."""
        try:
            if request.method in ['GET', 'HEAD', 'DELETE']:
                return b''
            
            # Read the body
            body = await request.body()
            return body
            
        except Exception as e:
            logger.error(f"Failed to read request body: {e}")
            return b''
    
    async def _make_request(self, method: str, url: str, headers: Dict[str, str], 
                          content: bytes, params: Dict[str, Any]) -> httpx.Response:
        """Make the actual HTTP request to OpenRouter."""
        try:
            response = await self.client.request(
                method=method,
                url=url,
                headers=headers,
                content=content,
                params=params,
                stream=True  # Enable streaming
            )
            return response
            
        except Exception as e:
            logger.error(f"Failed to make request to {url}: {e}")
            raise
    
    def _create_streaming_response(self, response: httpx.Response) -> StreamingResponse:
        """Create a FastAPI StreamingResponse from httpx response."""
        # Prepare response headers
        response_headers = dict(response.headers)
        
        # Remove hop-by-hop headers from response
        hop_by_hop_headers = {
            'connection', 'upgrade', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers'
        }
        
        for header in hop_by_hop_headers:
            response_headers.pop(header, None)
        
        # Create streaming response with proper cleanup
        return StreamingResponse(
            content=self._stream_response_content(response),
            status_code=response.status_code,
            headers=response_headers,
            background=BackgroundTask(response.aclose)  # Ensure response is closed
        )
    
    async def _stream_response_content(self, response: httpx.Response) -> AsyncGenerator[bytes, None]:
        """Stream response content from httpx response."""
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        except Exception as e:
            logger.error(f"Error streaming response content: {e}")
            # Don't re-raise here as it would break the stream
    
    async def _get_api_key_securely(self, key_hash: str) -> Optional[str]:
        """
        Securely retrieve the actual API key from storage.
        
        NOTE: This is a placeholder. In a real implementation, you would:
        1. Store encrypted keys in Redis or a secure vault
        2. Decrypt them only when needed
        3. Never store plain text keys in memory longer than necessary
        """
        # For this implementation, we'll simulate key retrieval
        # In production, this would involve secure key decryption
        try:
            # This is a placeholder - you would implement secure key storage/retrieval
            # For now, we'll generate a dummy key
            # Real implementation would decrypt from secure storage
            return f"sk-or-v1-{key_hash[:32]}"  # Placeholder format
            
        except Exception as e:
            logger.error(f"Failed to retrieve API key for {key_hash}: {e}")
            return None
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform a health check on the proxy service."""
        try:
            # Check if we have healthy keys
            healthy_keys = await self.key_manager.get_healthy_openrouter_keys()
            
            # Test connection to OpenRouter
            test_response = await self.client.get(
                f"{self.base_url}/models",
                timeout=5.0
            )
            
            return {
                "status": "healthy",
                "healthy_keys_count": len(healthy_keys),
                "openrouter_reachable": test_response.status_code < 500,
                "last_check": "utcnow().isoformat()"
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_check": "utcnow().isoformat()"
            }
    
    async def get_proxy_stats(self) -> Dict[str, Any]:
        """Get proxy service statistics."""
        try:
            # Get key statistics
            openrouter_keys = await self.key_manager.get_openrouter_keys()
            healthy_keys = [k for k in openrouter_keys if k.is_healthy and k.is_active]
            
            # Get circuit breaker status
            rotator = self.rotation_manager.get_rotator()
            circuit_status = rotator.get_circuit_breaker_status()
            
            return {
                "total_keys": len(openrouter_keys),
                "healthy_keys": len(healthy_keys),
                "unhealthy_keys": len(openrouter_keys) - len(healthy_keys),
                "circuit_breakers": {
                    "total": len(circuit_status),
                    "open": len([s for s in circuit_status.values() if s["state"] == "open"]),
                    "half_open": len([s for s in circuit_status.values() if s["state"] == "half_open"]),
                    "closed": len([s for s in circuit_status.values() if s["state"] == "closed"])
                },
                "current_strategy": self.rotation_manager.current_strategy.value
            }
            
        except Exception as e:
            logger.error(f"Failed to get proxy stats: {e}")
            return {"error": str(e)}
    
    async def close(self):
        """Close the proxy service and cleanup resources."""
        try:
            await self.client.aclose()
            logger.info("Proxy service closed successfully")
        except Exception as e:
            logger.error(f"Error closing proxy service: {e}")


# Factory function for dependency injection
async def create_proxy_service(key_manager: KeyManager, 
                             rotation_manager: KeyRotationManager) -> ProxyService:
    """Create a new proxy service instance."""
    return ProxyService(key_manager, rotation_manager)


# Health check utilities
class ProxyHealthChecker:
    """Utility for performing proxy health checks."""
    
    def __init__(self, proxy_service: ProxyService):
        self.proxy_service = proxy_service
        self._last_check: Optional[Dict[str, Any]] = None
        self._check_interval = 60  # seconds
    
    async def get_health_status(self, force_check: bool = False) -> Dict[str, Any]:
        """Get current health status with caching."""
        import time
        
        now = time.time()
        
        # Return cached result if recent and not forced
        if (not force_check and self._last_check and 
            now - self._last_check.get("timestamp", 0) < self._check_interval):
            return self._last_check
        
        # Perform new health check
        health_data = await self.proxy_service.health_check()
        health_data["timestamp"] = now
        
        self._last_check = health_data
        return health_data
    
    async def is_healthy(self) -> bool:
        """Quick health check."""
        try:
            health_data = await self.get_health_status()
            return health_data.get("status") == "healthy"
        except Exception:
            return False