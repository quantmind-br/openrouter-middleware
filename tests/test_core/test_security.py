"""Tests for security management."""

import hashlib
import secrets
from unittest.mock import patch

import pytest
import bcrypt

from app.core.security import SecurityManager


class TestSecurityManager:
    """Test the SecurityManager class."""
    
    def test_security_manager_initialization(self):
        """Test security manager initialization."""
        manager = SecurityManager()
        assert manager is not None
    
    def test_hash_password(self, security_manager):
        """Test password hashing."""
        password = "test_password"
        hashed = security_manager.hash_password(password)
        
        # Should return a string
        assert isinstance(hashed, str)
        
        # Should not be the original password
        assert hashed != password
        
        # Should be bcrypt hash (starts with $2b$)
        assert hashed.startswith("$2b$")
        
        # Should verify correctly
        assert bcrypt.checkpw(password.encode(), hashed.encode())
    
    def test_verify_password_correct(self, security_manager):
        """Test password verification with correct password."""
        password = "test_password"
        hashed = security_manager.hash_password(password)
        
        result = security_manager.verify_password(password, hashed)
        assert result is True
    
    def test_verify_password_incorrect(self, security_manager):
        """Test password verification with incorrect password."""
        password = "test_password"
        wrong_password = "wrong_password"
        hashed = security_manager.hash_password(password)
        
        result = security_manager.verify_password(wrong_password, hashed)
        assert result is False
    
    def test_verify_password_invalid_hash(self, security_manager):
        """Test password verification with invalid hash."""
        password = "test_password"
        invalid_hash = "invalid_hash"
        
        result = security_manager.verify_password(password, invalid_hash)
        assert result is False
    
    def test_generate_api_key(self, security_manager):
        """Test API key generation."""
        api_key = security_manager.generate_api_key()
        
        # Should return a string
        assert isinstance(api_key, str)
        
        # Should have correct format (starts with sk-or-)
        assert api_key.startswith("sk-or-")
        
        # Should be long enough (at least 40 characters)
        assert len(api_key) >= 40
        
        # Should be unique (generate multiple and compare)
        api_key2 = security_manager.generate_api_key()
        assert api_key != api_key2
    
    def test_hash_api_key(self, security_manager):
        """Test API key hashing."""
        api_key = "sk-or-test-key-123456789"
        hashed = security_manager.hash_api_key(api_key)
        
        # Should return a string
        assert isinstance(hashed, str)
        
        # Should be SHA256 hash (64 hex characters)
        assert len(hashed) == 64
        assert all(c in "0123456789abcdef" for c in hashed)
        
        # Should be deterministic
        hashed2 = security_manager.hash_api_key(api_key)
        assert hashed == hashed2
        
        # Should match manual SHA256
        expected = hashlib.sha256(api_key.encode()).hexdigest()
        assert hashed == expected
    
    def test_generate_session_token(self, security_manager):
        """Test session token generation."""
        token = security_manager.generate_session_token()
        
        # Should return a string
        assert isinstance(token, str)
        
        # Should be URL-safe (only contains valid characters)
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in valid_chars for c in token)
        
        # Should be reasonably long (at least 20 characters)
        assert len(token) >= 20
        
        # Should be unique
        token2 = security_manager.generate_session_token()
        assert token != token2
    
    def test_api_key_format_validation(self, security_manager):
        """Test that generated API keys follow expected format."""
        for _ in range(10):  # Test multiple generations
            api_key = security_manager.generate_api_key()
            
            # Should start with sk-or-
            assert api_key.startswith("sk-or-")
            
            # Should have the right length (prefix + 32 chars)
            assert len(api_key) == len("sk-or-") + 32
            
            # Should only contain valid characters (base64url safe)
            suffix = api_key[6:]  # Remove sk-or- prefix
            valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
            assert all(c in valid_chars for c in suffix)
    
    def test_password_hash_different_each_time(self, security_manager):
        """Test that password hashes are different each time (salt)."""
        password = "test_password"
        
        hash1 = security_manager.hash_password(password)
        hash2 = security_manager.hash_password(password)
        
        # Should be different due to salt
        assert hash1 != hash2
        
        # But both should verify correctly
        assert security_manager.verify_password(password, hash1)
        assert security_manager.verify_password(password, hash2)
    
    def test_api_key_hash_consistency(self, security_manager):
        """Test that API key hashes are consistent (no salt)."""
        api_key = "sk-or-test-key-123456789"
        
        hash1 = security_manager.hash_api_key(api_key)
        hash2 = security_manager.hash_api_key(api_key)
        
        # Should be the same (no salt for API keys)
        assert hash1 == hash2
    
    def test_session_token_length(self, security_manager):
        """Test session token length configuration."""
        # Default length
        token = security_manager.generate_session_token()
        assert len(token) >= 20
        
        # Should be URL-safe base64 encoded
        import base64
        try:
            # Should be valid base64
            decoded = base64.urlsafe_b64decode(token + "===")  # Add padding
            assert len(decoded) > 0
        except Exception:
            # If not valid base64, should still be URL-safe characters
            valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
            assert all(c in valid_chars for c in token)
    
    @patch('secrets.token_urlsafe')
    def test_generate_api_key_uses_secrets(self, mock_token_urlsafe, security_manager):
        """Test that API key generation uses secrets module."""
        mock_token_urlsafe.return_value = "mock_random_string"
        
        api_key = security_manager.generate_api_key()
        
        # Should call secrets.token_urlsafe with 24 bytes (32 base64 chars)
        mock_token_urlsafe.assert_called_once_with(24)
        assert api_key == "sk-or-mock_random_string"
    
    @patch('secrets.token_urlsafe')
    def test_generate_session_token_uses_secrets(self, mock_token_urlsafe, security_manager):
        """Test that session token generation uses secrets module."""
        mock_token_urlsafe.return_value = "mock_session_token"
        
        token = security_manager.generate_session_token()
        
        # Should call secrets.token_urlsafe
        mock_token_urlsafe.assert_called_once()
        assert token == "mock_session_token"
    
    def test_hash_empty_api_key(self, security_manager):
        """Test hashing empty API key."""
        hashed = security_manager.hash_api_key("")
        
        # Should still return a valid hash
        assert isinstance(hashed, str)
        assert len(hashed) == 64
        
        # Should match SHA256 of empty string
        expected = hashlib.sha256("".encode()).hexdigest()
        assert hashed == expected
    
    def test_verify_password_empty_strings(self, security_manager):
        """Test password verification with empty strings."""
        # Empty password should not verify against any hash
        assert security_manager.verify_password("", "any_hash") is False
        
        # Any password should not verify against empty hash
        assert security_manager.verify_password("password", "") is False
        
        # Both empty should not verify
        assert security_manager.verify_password("", "") is False