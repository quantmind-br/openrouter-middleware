"""Admin session authentication middleware."""

import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import validate_session_data
from app.models.admin import AdminSession

logger = logging.getLogger(__name__)


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for validating admin session authentication."""
    
    def __init__(self, app):
        super().__init__(app)
        # Paths that require admin authentication
        self.admin_paths = [
            "/admin",
        ]
        # Paths that are excluded from admin auth (but still under /admin)
        self.exclude_paths = [
            "/admin/login",  # Login page itself
            "/admin/static/", # Static files
        ]
        # Public paths that don't require any auth
        self.public_paths = [
            "/login",
            "/logout", 
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/static/",
            "/v1/",  # API endpoints use client auth, not admin auth
        ]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with admin authentication."""
        try:
            path = request.url.path
            
            # Skip authentication for public paths
            if self._is_public_path(path):
                return await call_next(request)
            
            # Skip authentication for excluded admin paths
            if self._is_excluded_admin_path(path):
                return await call_next(request)
            
            # Check if this path requires admin authentication
            if not self._requires_admin_auth(path):
                return await call_next(request)
            
            # Validate admin session
            session_data = await self._get_session_data(request)
            logger.info(f"Session data for {path}: {session_data}")
            
            if not session_data or not validate_session_data(session_data):
                logger.warning(f"Invalid session for {path}")
                return self._handle_unauthenticated(request)
            
            # Add session data to request state
            request.state.admin_session = AdminSession(**session_data)
            request.state.admin_authenticated = True
            
            # Process the request
            response = await call_next(request)
            
            # Update session activity
            await self._update_session_activity(request, response)
            
            return response
            
        except Exception as e:
            logger.error(f"Error in admin auth middleware: {e}")
            return self._handle_error(request)
    
    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        for public_path in self.public_paths:
            if path.startswith(public_path):
                return True
        return False
    
    def _is_excluded_admin_path(self, path: str) -> bool:
        """Check if path is excluded from admin auth."""
        for exclude_path in self.exclude_paths:
            if path.startswith(exclude_path):
                return True
        return False
    
    def _requires_admin_auth(self, path: str) -> bool:
        """Check if path requires admin authentication."""
        for admin_path in self.admin_paths:
            if path.startswith(admin_path):
                return True
        return False
    
    async def _get_session_data(self, request: Request) -> dict:
        """Extract session data from request."""
        try:
            # Try to get session from FastAPI session (requires SessionMiddleware)
            session = request.session
            
            if session and session.get('authenticated'):
                return {
                    'user_id': session.get('user_id'),
                    'authenticated': session.get('authenticated'),
                    'session_token': session.get('session_token'),
                    'created_at': session.get('created_at'),
                    'expires_at': session.get('expires_at'),
                    'csrf_token': session.get('csrf_token')
                }
            
            return None
            
        except Exception:
            # SessionMiddleware not properly installed or session not available
            return None
    
    def _handle_unauthenticated(self, request: Request) -> Response:
        """Handle unauthenticated admin requests."""
        path = request.url.path
        
        # For HTML requests (browser), redirect to login
        if self._is_html_request(request):
            # Store the original URL for redirect after login
            login_url = "/login"
            if path != "/admin":
                login_url += f"?next={path}"
            
            return RedirectResponse(
                url=login_url,
                status_code=302
            )
        
        # For API requests, return JSON error
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "type": "authentication_required",
                    "message": "Admin authentication required.",
                    "code": 401
                }
            }
        )
    
    def _handle_error(self, request: Request) -> Response:
        """Handle errors in authentication."""
        if self._is_html_request(request):
            return RedirectResponse(
                url="/login?error=auth_error",
                status_code=302
            )
        
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": "authentication_error",
                    "message": "Authentication system error.",
                    "code": 500
                }
            }
        )
    
    def _is_html_request(self, request: Request) -> bool:
        """Check if request expects HTML response."""
        accept_header = request.headers.get("accept", "")
        return "text/html" in accept_header or "application/json" not in accept_header
    
    async def _update_session_activity(self, request: Request, response: Response):
        """Update session activity timestamp."""
        try:
            if hasattr(request, 'session'):
                session = request.session
                if session and session.get('authenticated'):
                    # Update last activity timestamp
                    from datetime import datetime
                    session['last_activity'] = datetime.utcnow().isoformat()
                
        except Exception as e:
            logger.error(f"Error updating session activity: {e}")


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """Middleware for CSRF protection on admin forms."""
    
    def __init__(self, app):
        super().__init__(app)
        # Methods that require CSRF protection
        self.protected_methods = ["POST", "PUT", "PATCH", "DELETE"]
        # Paths that require CSRF protection
        self.protected_paths = [
            "/admin/",
            "/logout"
        ]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Apply CSRF protection to admin forms."""
        try:
            # Skip CSRF check for non-protected methods
            if request.method not in self.protected_methods:
                return await call_next(request)
            
            # Skip CSRF check for non-protected paths
            if not self._requires_csrf_protection(request.url.path):
                return await call_next(request)
            
            # Skip CSRF check for API requests with proper content-type
            if self._is_api_request(request):
                return await call_next(request)
            
            # Validate CSRF token
            if not await self._validate_csrf_token(request):
                return self._create_csrf_error_response(request)
            
            return await call_next(request)
            
        except Exception as e:
            logger.error(f"Error in CSRF protection middleware: {e}")
            return await call_next(request)
    
    def _requires_csrf_protection(self, path: str) -> bool:
        """Check if path requires CSRF protection."""
        for protected_path in self.protected_paths:
            if path.startswith(protected_path):
                return True
        return False
    
    def _is_api_request(self, request: Request) -> bool:
        """Check if request is an API request."""
        content_type = request.headers.get("content-type", "")
        return "application/json" in content_type
    
    async def _validate_csrf_token(self, request: Request) -> bool:
        """Validate CSRF token from form or header."""
        try:
            # Get expected CSRF token from session
            if not hasattr(request, 'session'):
                return False
            session = request.session
            expected_token = session.get('csrf_token')
            
            if not expected_token:
                logger.warning("No CSRF token in session")
                return False
            
            # Try to get CSRF token from form data
            if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                # Clone the request body to avoid consuming it
                body = await request.body()
                request._body = body  # Store for reuse
                
                # Parse form data manually to avoid consuming the stream
                from urllib.parse import parse_qs
                form_data = parse_qs(body.decode('utf-8'))
                csrf_token = form_data.get('csrf_token', [None])[0]
            else:
                # Try to get from header
                csrf_token = request.headers.get('X-CSRF-Token')
            
            is_valid = csrf_token == expected_token
            if not is_valid:
                logger.warning(f"CSRF token mismatch. Expected: {expected_token[:8]}..., Got: {csrf_token[:8] if csrf_token else 'None'}...")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error validating CSRF token: {e}")
            return False
    
    def _create_csrf_error_response(self, request: Request) -> Response:
        """Create CSRF error response."""
        if self._is_html_request(request):
            return RedirectResponse(
                url="/login?error=csrf_error",
                status_code=302
            )
        
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "type": "csrf_token_invalid",
                    "message": "CSRF token is missing or invalid.",
                    "code": 403
                }
            }
        )
    
    def _is_html_request(self, request: Request) -> bool:
        """Check if request expects HTML response."""
        accept_header = request.headers.get("accept", "")
        return "text/html" in accept_header


class AdminActivityLogMiddleware(BaseHTTPMiddleware):
    """Middleware for logging admin activities."""
    
    def __init__(self, app):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log admin activities."""
        response = await call_next(request)
        
        try:
            # Only log admin activities
            if not request.url.path.startswith("/admin"):
                return response
            
            # Only log if admin is authenticated
            admin_session = getattr(request.state, 'admin_session', None)
            if not admin_session:
                return response
            
            # Only log state-changing operations
            if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                await self._log_admin_activity(request, response, admin_session)
            
            return response
            
        except Exception as e:
            logger.error(f"Error in admin activity logging: {e}")
            return response
    
    async def _log_admin_activity(self, request: Request, response: Response, 
                                admin_session: AdminSession):
        """Log admin activity to audit trail."""
        try:
            from datetime import datetime
            
            activity_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "admin_user": admin_session.user_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "client_ip": request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("user-agent", "unknown"),
                "session_token": admin_session.session_token[:8] + "..."  # Truncated for logs
            }
            
            # Log the activity
            logger.info(
                "Admin activity",
                extra=activity_data
            )
            
            # TODO: Store in database or audit system for compliance
            
        except Exception as e:
            logger.error(f"Error logging admin activity: {e}")


class SessionTimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware for handling session timeouts."""
    
    def __init__(self, app, timeout_hours: int = 24):
        super().__init__(app)
        self.timeout_hours = timeout_hours
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check for session timeout and extend active sessions."""
        try:
            # Only check admin sessions
            if not request.url.path.startswith("/admin"):
                return await call_next(request)
            
            if not hasattr(request, 'session'):
                return await call_next(request)
                
            session = request.session
            
            if session and session.get('authenticated'):
                from datetime import datetime, timedelta
                
                # Check if session has expired
                expires_at_str = session.get('expires_at')
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    
                    if datetime.utcnow() > expires_at:
                        # Session expired - clear it
                        session.clear()
                        
                        if self._is_html_request(request):
                            return RedirectResponse(
                                url="/login?error=session_expired",
                                status_code=302
                            )
                        else:
                            return JSONResponse(
                                status_code=401,
                                content={
                                    "error": {
                                        "type": "session_expired",
                                        "message": "Session has expired. Please login again.",
                                        "code": 401
                                    }
                                }
                            )
                    else:
                        # Extend session expiration for active sessions
                        new_expiry = datetime.utcnow() + timedelta(hours=self.timeout_hours)
                        session['expires_at'] = new_expiry.isoformat()
            
            return await call_next(request)
            
        except Exception as e:
            logger.error(f"Error in session timeout middleware: {e}")
            return await call_next(request)
    
    def _is_html_request(self, request: Request) -> bool:
        """Check if request expects HTML response."""
        accept_header = request.headers.get("accept", "")
        return "text/html" in accept_header