"""Admin API endpoints for key management and system administration."""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.key_manager import KeyManager, get_key_manager
from app.services.rotation import get_rotation_manager
from app.models.keys import (
    ClientKeyCreate, 
    ClientKeyResponse,
    OpenRouterKeyCreate,
    OpenRouterKeyResponse,
    BulkImportResponse
)
from app.models.admin import AdminDashboardData, AdminSession

logger = logging.getLogger(__name__)

# Create router for admin endpoints
router = APIRouter(prefix="/admin", tags=["admin"])

# Templates will be configured in main.py
templates = None


def setup_templates(template_instance: Jinja2Templates):
    """Setup templates instance for this router."""
    global templates
    templates = template_instance


def require_admin_auth(request: Request) -> AdminSession:
    """Dependency to require admin authentication."""
    if not getattr(request.state, 'admin_authenticated', False):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    
    admin_session = getattr(request.state, 'admin_session', None)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Invalid admin session")
    
    return admin_session


# Dashboard and main pages

@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Admin dashboard with system overview."""
    try:
        if not templates:
            raise HTTPException(status_code=500, detail="Templates not configured")
        
        # Gather dashboard data
        dashboard_data = await _get_dashboard_data(key_manager)
        
        context = {
            "request": request,
            "admin_session": admin_session,
            "dashboard_data": dashboard_data,
            "page_title": "Dashboard"
        }
        
        return templates.TemplateResponse("dashboard.html", context)
        
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {e}")
        raise HTTPException(status_code=500, detail="Failed to load dashboard")


# OpenRouter Key Management

@router.get("/openrouter-keys", response_class=HTMLResponse)
async def openrouter_keys_page(
    request: Request,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """OpenRouter keys management page."""
    try:
        if not templates:
            raise HTTPException(status_code=500, detail="Templates not configured")
        
        # Get all OpenRouter keys
        openrouter_keys = await key_manager.get_openrouter_keys()
        
        context = {
            "request": request,
            "admin_session": admin_session,
            "openrouter_keys": openrouter_keys,
            "page_title": "OpenRouter Keys"
        }
        
        return templates.TemplateResponse("openrouter_keys.html", context)
        
    except Exception as e:
        logger.error(f"Error loading OpenRouter keys page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load OpenRouter keys")


@router.get("/api/openrouter-keys")
async def list_openrouter_keys(
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
) -> List[OpenRouterKeyResponse]:
    """API endpoint to list all OpenRouter keys."""
    try:
        openrouter_keys = await key_manager.get_openrouter_keys()
        
        return [
            OpenRouterKeyResponse(
                key_hash=key.key_hash,
                added_at=key.added_at,
                is_active=key.is_active,
                is_healthy=key.is_healthy,
                failure_count=key.failure_count,
                usage_count=key.usage_count,
                last_used=key.last_used
            )
            for key in openrouter_keys
        ]
        
    except Exception as e:
        logger.error(f"Error listing OpenRouter keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to list OpenRouter keys")


@router.post("/api/openrouter-keys")
async def add_openrouter_key(
    key_data: OpenRouterKeyCreate,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
) -> OpenRouterKeyResponse:
    """Add a new OpenRouter API key."""
    try:
        key_hash = await key_manager.add_openrouter_key(key_data)
        
        if not key_hash:
            raise HTTPException(status_code=400, detail="Failed to add key (may already exist)")
        
        # Get the added key data
        openrouter_keys = await key_manager.get_openrouter_keys()
        added_key = next((k for k in openrouter_keys if k.key_hash == key_hash), None)
        
        if not added_key:
            raise HTTPException(status_code=500, detail="Key added but not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} added OpenRouter key {key_hash}")
        
        return OpenRouterKeyResponse(
            key_hash=added_key.key_hash,
            added_at=added_key.added_at,
            is_active=added_key.is_active,
            is_healthy=added_key.is_healthy,
            failure_count=added_key.failure_count,
            usage_count=added_key.usage_count,
            last_used=added_key.last_used
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding OpenRouter key: {e}")
        raise HTTPException(status_code=500, detail="Failed to add OpenRouter key")


@router.delete("/api/openrouter-keys/{key_hash}")
async def delete_openrouter_key(
    key_hash: str,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Delete an OpenRouter API key."""
    try:
        success = await key_manager.delete_openrouter_key(key_hash)
        
        if not success:
            raise HTTPException(status_code=404, detail="Key not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} deleted OpenRouter key {key_hash}")
        
        return {"success": True, "message": "Key deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting OpenRouter key {key_hash}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete OpenRouter key")


@router.post("/api/openrouter-keys/bulk-import")
async def bulk_import_openrouter_keys(
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager),
    file: UploadFile = File(..., description="Text file with one API key per line")
) -> BulkImportResponse:
    """Bulk import OpenRouter API keys from uploaded file."""
    try:
        # Validate file type
        if not file.filename.endswith('.txt'):
            raise HTTPException(status_code=400, detail="Only .txt files are supported")
        
        # Read file content
        content = await file.read()
        text_content = content.decode('utf-8')
        
        # Parse keys (one per line, strip whitespace)
        lines = [line.strip() for line in text_content.split('\n')]
        api_keys = [line for line in lines if line and not line.startswith('#')]
        
        if not api_keys:
            raise HTTPException(status_code=400, detail="No valid API keys found in file")
        
        if len(api_keys) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 keys per import")
        
        # Perform bulk import
        result = await key_manager.bulk_import_openrouter_keys(api_keys)
        
        # Log admin action
        logger.info(
            f"Admin {admin_session.user_id} bulk imported {result.successful_imports} "
            f"OpenRouter keys from file {file.filename}"
        )
        
        return result
        
    except HTTPException:
        raise
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be valid UTF-8 text")
    except Exception as e:
        logger.error(f"Error in bulk import: {e}")
        raise HTTPException(status_code=500, detail="Failed to import keys")


# Client Key Management

@router.get("/client-keys", response_class=HTMLResponse)
async def client_keys_page(
    request: Request,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Client keys management page."""
    try:
        if not templates:
            raise HTTPException(status_code=500, detail="Templates not configured")
        
        # Get all client keys with hashes for deactivation functionality
        client_keys_with_hashes = await key_manager.get_client_keys_with_hashes()
        
        # Transform the data to dictionaries that include key_hash
        client_keys = []
        for key_hash, key_data in client_keys_with_hashes:
            # Create a dictionary with all key data plus the hash
            key_dict = {
                'key_hash': key_hash,
                'user_id': key_data.user_id,
                'created_at': key_data.created_at,
                'last_used': key_data.last_used,
                'is_active': key_data.is_active,
                'permissions': key_data.permissions,
                'usage_count': key_data.usage_count,
                'rate_limit': key_data.rate_limit
            }
            client_keys.append(key_dict)
        
        context = {
            "request": request,
            "admin_session": admin_session,
            "client_keys": client_keys,
            "page_title": "Client Keys"
        }
        
        return templates.TemplateResponse("client_keys.html", context)
        
    except Exception as e:
        logger.error(f"Error loading client keys page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load client keys")


@router.get("/api/client-keys")
async def list_client_keys(
    user_id: Optional[str] = None,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
) -> List[ClientKeyResponse]:
    """API endpoint to list client keys."""
    try:
        # We need to get the actual key hashes for deactivation functionality
        client_keys_with_hashes = await key_manager.get_client_keys_with_hashes(user_id)
        
        return [
            ClientKeyResponse(
                key_hash=key_hash,  # Use actual key hash for deactivation
                user_id=key.user_id,
                created_at=key.created_at,
                is_active=key.is_active,
                permissions=key.permissions,
                usage_count=key.usage_count,
                rate_limit=key.rate_limit
            )
            for key_hash, key in client_keys_with_hashes
        ]
        
    except Exception as e:
        logger.error(f"Error listing client keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to list client keys")


@router.post("/api/client-keys")
async def create_client_key(
    key_data: ClientKeyCreate,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
) -> dict:
    """Create a new client API key."""
    try:
        api_key, key_hash = await key_manager.create_client_key(key_data)
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} created client key for user {key_data.user_id}")
        
        return {
            "api_key": api_key,  # Only return the actual key once
            "key_hash": key_hash,
            "user_id": key_data.user_id,
            "created_at": datetime.utcnow().isoformat(),
            "message": "Client key created successfully. Save the API key securely - it won't be shown again."
        }
        
    except Exception as e:
        logger.error(f"Error creating client key: {e}")
        raise HTTPException(status_code=500, detail="Failed to create client key")


@router.patch("/api/client-keys/{key_hash}/deactivate")
async def deactivate_client_key(
    key_hash: str,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Deactivate a client API key."""
    try:
        success = await key_manager.deactivate_client_key(key_hash)
        
        if not success:
            raise HTTPException(status_code=404, detail="Key not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} deactivated client key {key_hash}")
        
        return {"success": True, "message": "Client key deactivated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating client key {key_hash}: {e}")
        raise HTTPException(status_code=500, detail="Failed to deactivate client key")


@router.delete("/api/client-keys/{key_hash}")
async def delete_client_key(
    key_hash: str,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Permanently delete a client API key."""
    try:
        success = await key_manager.delete_client_key(key_hash)
        
        if not success:
            raise HTTPException(status_code=404, detail="Key not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} deleted client key {key_hash}")
        
        return {"success": True, "message": "Client key deleted permanently"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting client key {key_hash}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete client key")


@router.patch("/api/client-keys/{key_hash}/reactivate")
async def reactivate_client_key(
    key_hash: str,
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Reactivate a deactivated client API key."""
    try:
        success = await key_manager.reactivate_client_key(key_hash)
        
        if not success:
            raise HTTPException(status_code=404, detail="Key not found")
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} reactivated client key {key_hash}")
        
        return {"success": True, "message": "Client key reactivated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reactivating client key {key_hash}: {e}")
        raise HTTPException(status_code=500, detail="Failed to reactivate client key")


# System Management

@router.get("/api/dashboard-data")
async def get_dashboard_data(
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
) -> AdminDashboardData:
    """Get dashboard data for admin panel."""
    try:
        return await _get_dashboard_data(key_manager)
        
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard data")


@router.get("/api/system-status")
async def get_system_status(
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Get comprehensive system status."""
    try:
        # Get key statistics
        openrouter_keys = await key_manager.get_openrouter_keys()
        client_keys = await key_manager.get_client_keys()
        healthy_keys = await key_manager.get_healthy_openrouter_keys()
        
        # Get Redis status
        from app.core.redis import redis_manager
        redis_healthy = await redis_manager.is_healthy()
        
        # Get rotation manager status
        rotation_manager = get_rotation_manager(key_manager)
        rotator = rotation_manager.get_rotator()
        circuit_status = rotator.get_circuit_breaker_status()
        
        return {
            "system": {
                "status": "healthy" if redis_healthy and len(healthy_keys) > 0 else "degraded",
                "timestamp": datetime.utcnow().isoformat()
            },
            "redis": {
                "status": "healthy" if redis_healthy else "unhealthy",
                "connected": redis_healthy
            },
            "keys": {
                "openrouter": {
                    "total": len(openrouter_keys),
                    "healthy": len(healthy_keys),
                    "active": len([k for k in openrouter_keys if k.is_active])
                },
                "client": {
                    "total": len(client_keys),
                    "active": len([k for k in client_keys if k.is_active])
                }
            },
            "circuit_breakers": {
                "total": len(circuit_status),
                "open": len([s for s in circuit_status.values() if s["state"] == "open"]),
                "closed": len([s for s in circuit_status.values() if s["state"] == "closed"])
            },
            "rotation": {
                "strategy": rotation_manager.current_strategy.value
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system status")


@router.post("/api/system/cleanup")
async def cleanup_system(
    admin_session: AdminSession = Depends(require_admin_auth),
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Perform system cleanup operations."""
    try:
        # Get rotation manager and perform cleanup
        rotation_manager = get_rotation_manager(key_manager)
        rotator = rotation_manager.get_rotator()
        
        # Cleanup expired rate limits
        await rotator.cleanup_expired_rate_limits()
        
        # Log admin action
        logger.info(f"Admin {admin_session.user_id} performed system cleanup")
        
        return {
            "success": True,
            "message": "System cleanup completed",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error performing system cleanup: {e}")
        raise HTTPException(status_code=500, detail="Failed to perform system cleanup")


# Utility functions

async def _get_dashboard_data(key_manager: KeyManager) -> AdminDashboardData:
    """Get dashboard data from various sources."""
    try:
        # Get key counts
        openrouter_keys = await key_manager.get_openrouter_keys()
        client_keys = await key_manager.get_client_keys()
        healthy_keys = await key_manager.get_healthy_openrouter_keys()
        
        # Calculate active keys
        active_client_keys = len([k for k in client_keys if k.is_active])
        
        # Get Redis status
        from app.core.redis import redis_manager
        redis_status = "healthy" if await redis_manager.is_healthy() else "unhealthy"
        
        # TODO: Implement actual request counting
        # For now, return placeholder values
        
        return AdminDashboardData(
            total_client_keys=len(client_keys),
            active_client_keys=active_client_keys,
            total_openrouter_keys=len(openrouter_keys),
            healthy_openrouter_keys=len(healthy_keys),
            total_requests_today=0,  # TODO: Implement request counting
            successful_requests_today=0,  # TODO: Implement request counting
            failed_requests_today=0,  # TODO: Implement request counting
            system_uptime="N/A",  # TODO: Implement uptime tracking
            redis_status=redis_status
        )
        
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        # Return empty dashboard data on error
        return AdminDashboardData()


# File upload utility endpoint

@router.post("/api/upload-keys-file")
async def upload_keys_file(
    admin_session: AdminSession = Depends(require_admin_auth),
    file: UploadFile = File(...)
):
    """Upload and validate keys file before import."""
    try:
        # Validate file
        if not file.filename.endswith('.txt'):
            raise HTTPException(status_code=400, detail="Only .txt files are supported")
        
        # Read and validate content
        content = await file.read()
        text_content = content.decode('utf-8')
        
        lines = [line.strip() for line in text_content.split('\n')]
        api_keys = [line for line in lines if line and not line.startswith('#')]
        
        return {
            "filename": file.filename,
            "total_lines": len(lines),
            "valid_keys": len(api_keys),
            "preview": api_keys[:5] if api_keys else [],  # Show first 5 keys
            "ready_for_import": len(api_keys) > 0
        }
        
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be valid UTF-8 text")
    except Exception as e:
        logger.error(f"Error processing uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to process file")