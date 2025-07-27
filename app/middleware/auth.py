"""Client API key authentication middleware."""

import logging
import time
from typing import Callable

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.key_manager import get_key_manager
from app.models.keys import ClientKeyData

logger = logging.getLogger(__name__)


class ClientAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for validating client API keys."""
    
    def __init__(self, app, require_auth_paths: list = None):
        super().__init__(app)
        # Paths that require authentication (defaults to API endpoints)
        self.require_auth_paths = require_auth_paths or [
            "/v1/",
            "/api/v1/",
            "/openrouter/"
        ]
        # Paths that are excluded from authentication
        self.exclude_paths = [
            "/health",
            "/admin",
            "/login",
            "/logout",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/static/"
        ]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with client authentication."""
        start_time = time.time()
        
        try:
            # Check if this path requires authentication
            if not self._requires_auth(request.url.path):
                response = await call_next(request)
                return response
            
            # Extract API key from header
            api_key = request.headers.get("x-client-api-key") or request.headers.get("X-Client-API-Key")
            
            if not api_key:
                return self._create_error_response(
                    status_code=401,
                    error="missing_api_key",
                    message="API key is required. Include 'X-Client-API-Key' header."
                )
            
            # Validate API key
            key_manager = await get_key_manager()
            client_data = await key_manager.validate_client_key(api_key)
            
            if not client_data:
                return self._create_error_response(
                    status_code=401,
                    error="invalid_api_key",
                    message="Invalid or inactive API key."
                )
            
            # Check rate limiting
            if not await self._check_rate_limit(client_data, request):
                return self._create_error_response(
                    status_code=429,
                    error="rate_limit_exceeded",
                    message="Rate limit exceeded. Please slow down your requests."
                )
            
            # Add client data to request state for use in endpoints
            request.state.client_data = client_data
            request.state.authenticated = True
            
            # Process the request
            response = await call_next(request)
            
            # Add usage headers to response
            response.headers["X-RateLimit-Limit"] = str(client_data.rate_limit)
            response.headers["X-RateLimit-Remaining"] = str(
                max(0, client_data.rate_limit - self._get_current_usage(client_data))
            )
            
            # Log successful request
            duration = time.time() - start_time
            logger.info(
                f"Client request: {request.method} {request.url.path} "
                f"user={client_data.user_id} duration={duration:.3f}s status={response.status_code}"
            )
            
            return response
            
        except HTTPException as e:
            # Re-raise HTTP exceptions
            raise e
        except Exception as e:
            logger.error(f"Error in client auth middleware: {e}")
            return self._create_error_response(
                status_code=500,
                error="internal_error",
                message="Internal server error occurred."
            )
    
    def _requires_auth(self, path: str) -> bool:
        """Check if a path requires authentication."""
        # Check exclude paths first
        for exclude_path in self.exclude_paths:
            if path.startswith(exclude_path):
                return False
        
        # Check if path matches required auth patterns
        for auth_path in self.require_auth_paths:
            if path.startswith(auth_path):
                return True
        
        return False
    
    async def _check_rate_limit(self, client_data: ClientKeyData, request: Request) -> bool:
        """Check if client is within rate limits."""
        try:
            # For now, implement simple rate limiting
            # In production, you'd use Redis with sliding window
            current_usage = self._get_current_usage(client_data)
            return current_usage < client_data.rate_limit
            
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            # Allow request if rate limit check fails
            return True
    
    def _get_current_usage(self, client_data: ClientKeyData) -> int:
        """Get current usage for rate limiting."""
        # This is a simplified implementation
        # In production, you'd track usage in Redis with time windows
        return min(client_data.usage_count, client_data.rate_limit - 1)
    
    def _create_error_response(self, status_code: int, error: str, message: str) -> JSONResponse:
        """Create standardized error response."""
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "type": error,
                    "message": message,
                    "code": status_code
                }
            },
            headers={
                "X-Error-Type": error,
                "Content-Type": "application/json"
            }
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enhanced rate limiting middleware with Redis-based tracking."""
    
    def __init__(self, app, redis_client=None):
        super().__init__(app)
        self.redis_client = redis_client
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Apply rate limiting based on client data."""
        try:
            # Skip if not authenticated or no client data
            if not getattr(request.state, 'authenticated', False):
                return await call_next(request)
            
            client_data = getattr(request.state, 'client_data', None)
            if not client_data:
                return await call_next(request)
            
            # Check rate limit using Redis
            if self.redis_client and not await self._check_redis_rate_limit(client_data):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "type": "rate_limit_exceeded",
                            "message": "Rate limit exceeded. Please wait before making more requests.",
                            "code": 429
                        }
                    }
                )
            
            return await call_next(request)
            
        except Exception as e:
            logger.error(f"Error in rate limit middleware: {e}")
            return await call_next(request)
    
    async def _check_redis_rate_limit(self, client_data: ClientKeyData) -> bool:
        """Check rate limit using Redis sliding window."""
        try:
            if not self.redis_client:
                return True
            
            current_minute = int(time.time() // 60)
            rate_key = f"rate_limit:{client_data.user_id}:{current_minute}"
            
            # Use Redis pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            pipe.incr(rate_key)
            pipe.expire(rate_key, 60)  # Expire after 1 minute
            results = await pipe.execute()
            
            current_count = results[0]
            
            # Check against rate limit (per minute, not per hour for more granular control)
            per_minute_limit = max(1, client_data.rate_limit // 60)
            
            return current_count <= per_minute_limit
            
        except Exception as e:
            logger.error(f"Error checking Redis rate limit: {e}")
            # Allow request if Redis check fails
            return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware for adding security headers to responses."""
    
    def __init__(self, app):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to all responses."""
        response = await call_next(request)
        
        # Add security headers
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:",
        }
        
        # Only add HSTS for HTTPS
        if request.url.scheme == "https":
            security_headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests with structured logging."""
    
    def __init__(self, app):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request details."""
        start_time = time.time()
        
        # Extract basic request info
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Get client info if available
            client_data = getattr(request.state, 'client_data', None)
            user_id = client_data.user_id if client_data else "anonymous"
            
            # Log request
            logger.info(
                "Request processed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration": duration,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "user_id": user_id,
                    "authenticated": getattr(request.state, 'authenticated', False)
                }
            )
            
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            
            logger.error(
                "Request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration": duration,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "error": str(e)
                }
            )
            raise