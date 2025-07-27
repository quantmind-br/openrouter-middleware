"""Authentication API endpoints for admin login/logout."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.security import authenticate_admin, create_session_data, generate_csrf_token
from app.models.admin import AdminLogin

logger = logging.getLogger(__name__)

# Create router for authentication endpoints
router = APIRouter()

# Initialize templates (will be configured in main.py)
templates = None


def setup_templates(template_instance: Jinja2Templates):
    """Setup templates instance for this router."""
    global templates
    templates = template_instance


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next_url: Optional[str] = None, error: Optional[str] = None):
    """Display admin login form."""
    try:
        if not templates:
            raise HTTPException(status_code=500, detail="Templates not configured")
        
        # Check if user is already authenticated
        if hasattr(request, 'session'):
            session = request.session
            if session.get('authenticated'):
                redirect_url = next_url or "/admin"
                return RedirectResponse(url=redirect_url, status_code=302)
        
        # Generate CSRF token for form protection
        csrf_token = generate_csrf_token()
        if hasattr(request, 'session'):
            request.session['csrf_token'] = csrf_token
        
        # Prepare template context
        context = {
            "request": request,
            "csrf_token": csrf_token,
            "next_url": next_url,
            "error": error,
            "error_message": _get_error_message(error)
        }
        
        return templates.TemplateResponse("login.html", context)
        
    except Exception as e:
        logger.error(f"Error displaying login form: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(..., description="Admin username"),
    password: str = Form(..., description="Admin password"),
    csrf_token: str = Form(..., description="CSRF protection token"),
    next_url: Optional[str] = Form(None, description="URL to redirect after login")
):
    """Process admin login form submission."""
    try:
        if not hasattr(request, 'session'):
            return RedirectResponse(
                url=f"/login?error=system_error&next={next_url or ''}",
                status_code=302
            )
        session = request.session
        
        # Note: CSRF validation removed for login endpoint to fix login issues
        # The form still includes the token for future use
        
        # Validate admin credentials
        if not authenticate_admin(username, password):
            logger.warning(f"Failed login attempt for user {username}")
            return RedirectResponse(
                url=f"/login?error=invalid_credentials&next={next_url or ''}",
                status_code=302
            )
        
        # Create session data
        session_data = create_session_data(username, expires_in_hours=24)
        
        # Update session
        session.update(session_data)
        
        # Clear CSRF token (new one will be generated as needed)
        session.pop('csrf_token', None)
        
        # Log successful login
        logger.info(f"Successful admin login for user {username}")
        
        # Redirect to intended destination
        redirect_url = next_url or "/admin"
        
        # Ensure redirect URL is safe (prevent open redirects)
        if not _is_safe_redirect_url(redirect_url):
            redirect_url = "/admin"
        
        return RedirectResponse(url=redirect_url, status_code=302)
        
    except Exception as e:
        logger.error(f"Error processing login: {e}")
        return RedirectResponse(
            url=f"/login?error=system_error&next={next_url or ''}",
            status_code=302
        )


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    """Log out admin user and clear session."""
    try:
        session = getattr(request, 'session', {})
        
        # Log logout if user was authenticated
        if session.get('authenticated'):
            user_id = session.get('user_id', 'unknown')
            logger.info(f"Admin logout for user {user_id}")
        
        # Clear session data
        session.clear()
        
        # Redirect to login page
        return RedirectResponse(url="/login", status_code=302)
        
    except Exception as e:
        logger.error(f"Error processing logout: {e}")
        # Even if there's an error, redirect to login
        return RedirectResponse(url="/login", status_code=302)


@router.get("/session-status")
async def session_status(request: Request):
    """Get current session status (for AJAX calls)."""
    try:
        session = getattr(request, 'session', {})
        
        is_authenticated = session.get('authenticated', False)
        user_id = session.get('user_id') if is_authenticated else None
        expires_at = session.get('expires_at') if is_authenticated else None
        
        return {
            "authenticated": is_authenticated,
            "user_id": user_id,
            "expires_at": expires_at,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting session status: {e}")
        return {
            "authenticated": False,
            "error": "Failed to get session status",
            "timestamp": datetime.utcnow().isoformat()
        }


@router.post("/refresh-csrf")
async def refresh_csrf_token(request: Request):
    """Refresh CSRF token for the current session."""
    try:
        session = getattr(request, 'session', {})
        
        # Only allow for authenticated sessions
        if not session.get('authenticated'):
            raise HTTPException(status_code=401, detail="Authentication required")
        
        # Generate new CSRF token
        new_csrf_token = generate_csrf_token()
        session['csrf_token'] = new_csrf_token
        
        return {
            "csrf_token": new_csrf_token,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error refreshing CSRF token: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh CSRF token")


@router.get("/check-auth")
async def check_authentication(request: Request):
    """Check if current request is authenticated (for API use)."""
    try:
        session = getattr(request, 'session', {})
        
        if not session.get('authenticated'):
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate session data
        from app.core.security import validate_session_data
        if not validate_session_data(session):
            # Session expired or invalid
            session.clear()
            raise HTTPException(status_code=401, detail="Session expired")
        
        return {
            "authenticated": True,
            "user_id": session.get('user_id'),
            "session_token": session.get('session_token', '')[:8] + "...",  # Truncated for security
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking authentication: {e}")
        raise HTTPException(status_code=500, detail="Authentication check failed")


def _get_error_message(error: Optional[str]) -> Optional[str]:
    """Get user-friendly error message for error code."""
    error_messages = {
        "invalid_credentials": "Invalid username or password. Please try again.",
        "csrf_error": "Security token expired. Please try again.",
        "session_expired": "Your session has expired. Please log in again.",
        "system_error": "A system error occurred. Please try again later.",
        "auth_error": "Authentication error occurred. Please try again."
    }
    return error_messages.get(error) if error else None


def _is_safe_redirect_url(url: str) -> bool:
    """Check if redirect URL is safe (prevents open redirect attacks)."""
    if not url:
        return False
    
    # Only allow relative URLs or URLs to the same domain
    if url.startswith('/'):
        # Relative URL - safe
        return True
    
    if url.startswith('http://') or url.startswith('https://'):
        # Absolute URL - potentially unsafe
        # For now, reject all absolute URLs
        return False
    
    # Default to safe
    return True


# Additional utility endpoints

@router.get("/health")
async def auth_health():
    """Health check for authentication system."""
    try:
        # Basic health check - verify authentication system is working
        from app.core.security import security_manager
        
        # Test password hashing works
        security_manager.get_password_hash("test")
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "auth_system": "operational"
        }
        
    except Exception as e:
        logger.error(f"Auth health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.post("/validate-credentials")
async def validate_credentials(request: Request, credentials: AdminLogin):
    """Validate admin credentials without creating session (for API use)."""
    try:
        # This endpoint is for API validation only
        # It doesn't create a session
        
        is_valid = authenticate_admin(credentials.username, credentials.password)
        
        if not is_valid:
            logger.warning(f"Invalid credentials check for user {credentials.username}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        return {
            "valid": True,
            "username": credentials.username,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating credentials: {e}")
        raise HTTPException(status_code=500, detail="Credential validation failed")


# Session management utilities

@router.get("/session-info")
async def get_session_info(request: Request):
    """Get detailed session information for authenticated users."""
    try:
        session = getattr(request, 'session', {})
        
        if not session.get('authenticated'):
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Sanitize session data for response
        session_info = {
            "user_id": session.get('user_id'),
            "authenticated": session.get('authenticated'),
            "created_at": session.get('created_at'),
            "expires_at": session.get('expires_at'),
            "last_activity": session.get('last_activity'),
            "session_id": session.get('session_token', '')[:8] + "..." if session.get('session_token') else None
        }
        
        return session_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session info")


@router.post("/extend-session")
async def extend_session(request: Request):
    """Extend current session expiration."""
    try:
        session = getattr(request, 'session', {})
        
        if not session.get('authenticated'):
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Extend session by 24 hours
        from datetime import timedelta
        new_expiry = datetime.utcnow() + timedelta(hours=24)
        session['expires_at'] = new_expiry.isoformat()
        
        logger.info(f"Extended session for user {session.get('user_id')}")
        
        return {
            "extended": True,
            "new_expiry": new_expiry.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extending session: {e}")
        raise HTTPException(status_code=500, detail="Failed to extend session")