"""Authentication and security core with password hashing and session management."""

import hashlib
import secrets
from datetime import datetime, timedelta

from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# Password hashing context with bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityManager:
    """Security manager for authentication and session handling."""
    
    def __init__(self):
        self.settings = settings
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_password_hash(self, password: str) -> str:
        """Generate password hash using bcrypt."""
        return pwd_context.hash(password)
    
    def authenticate_admin(self, username: str, password: str) -> bool:
        """Authenticate admin user against environment variables."""
        if username != self.settings.admin_username:
            return False
        
        # For simplicity, we compare directly with env password
        # In production, you might want to store hashed passwords
        return password == self.settings.admin_password
    
    def generate_session_token(self) -> str:
        """Generate a secure session token."""
        return secrets.token_urlsafe(32)
    
    def generate_api_key(self) -> str:
        """Generate a new API key."""
        return secrets.token_urlsafe(32)
    
    def hash_api_key(self, api_key: str) -> str:
        """Generate SHA256 hash of API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def generate_csrf_token(self) -> str:
        """Generate CSRF token for form protection."""
        return secrets.token_urlsafe(32)
    
    def create_session_data(self, user_id: str, expires_in_hours: int = 24) -> dict:
        """Create session data with expiration."""
        now = datetime.utcnow()
        return {
            "user_id": user_id,
            "authenticated": True,
            "session_token": self.generate_session_token(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=expires_in_hours)).isoformat(),
        }
    
    def validate_session_data(self, session_data: dict) -> bool:
        """Validate session data for expiration and integrity."""
        if not session_data.get("authenticated"):
            return False
        
        expires_at = session_data.get("expires_at")
        if not expires_at:
            return False
        
        try:
            expiry_time = datetime.fromisoformat(expires_at)
            return datetime.utcnow() < expiry_time
        except (ValueError, TypeError):
            return False
    
    def is_strong_password(self, password: str) -> tuple[bool, str]:
        """Check if password meets security requirements."""
        errors = []
        
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long")
        
        if not any(c.isupper() for c in password):
            errors.append("Password must contain at least one uppercase letter")
        
        if not any(c.islower() for c in password):
            errors.append("Password must contain at least one lowercase letter")
        
        if not any(c.isdigit() for c in password):
            errors.append("Password must contain at least one number")
        
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            errors.append("Password must contain at least one special character")
        
        return len(errors) == 0, "; ".join(errors)


class APIKeyManager:
    """Manager for API key operations and validation."""
    
    def __init__(self):
        self.security = SecurityManager()
    
    def generate_client_key(self) -> tuple[str, str]:
        """Generate a new client API key and its hash."""
        api_key = self.security.generate_api_key()
        key_hash = self.security.hash_api_key(api_key)
        return api_key, key_hash
    
    def validate_api_key_format(self, api_key: str) -> bool:
        """Validate API key format (basic length and character check)."""
        if not api_key or not isinstance(api_key, str):
            return False
        
        # Basic validation: should be URL-safe base64 string
        import re
        pattern = r'^[A-Za-z0-9_-]+$'
        return bool(re.match(pattern, api_key)) and len(api_key) >= 20
    
    def hash_for_storage(self, api_key: str) -> str:
        """Hash API key for secure storage."""
        return self.security.hash_api_key(api_key)


class PermissionManager:
    """Manager for permission checking and role-based access."""
    
    def __init__(self):
        self.admin_permissions = {
            "manage_openrouter_keys",
            "manage_client_keys",
            "view_analytics",
            "manage_settings",
            "bulk_import"
        }
    
    def has_admin_permission(self, session_data: dict, permission: str) -> bool:
        """Check if session has admin permission."""
        if not session_data.get("authenticated"):
            return False
        
        # For now, all authenticated admin users have all permissions
        # In the future, this could be expanded for role-based access
        return permission in self.admin_permissions
    
    def get_admin_permissions(self) -> set:
        """Get all available admin permissions."""
        return self.admin_permissions.copy()


# Global instances
security_manager = SecurityManager()
api_key_manager = APIKeyManager()
permission_manager = PermissionManager()


# Convenience functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password using global security manager."""
    return security_manager.verify_password(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password using global security manager."""
    return security_manager.get_password_hash(password)


def authenticate_admin(username: str, password: str) -> bool:
    """Authenticate admin using global security manager."""
    return security_manager.authenticate_admin(username, password)


def generate_session_token() -> str:
    """Generate session token using global security manager."""
    return security_manager.generate_session_token()


def generate_api_key() -> str:
    """Generate API key using global security manager."""
    return security_manager.generate_api_key()


def hash_api_key(api_key: str) -> str:
    """Hash API key using global security manager."""
    return security_manager.hash_api_key(api_key)


def generate_csrf_token() -> str:
    """Generate CSRF token using global security manager."""
    return security_manager.generate_csrf_token()


def create_session_data(user_id: str, expires_in_hours: int = 24) -> dict:
    """Create session data using global security manager."""
    return security_manager.create_session_data(user_id, expires_in_hours)


def validate_session_data(session_data: dict) -> bool:
    """Validate session data using global security manager."""
    return security_manager.validate_session_data(session_data)