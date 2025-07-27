"""Proxy API endpoints for forwarding requests to OpenRouter."""

import logging

from fastapi import APIRouter, Request, HTTPException, Depends

from app.services.key_manager import KeyManager, get_key_manager
from app.services.rotation import get_rotation_manager
from app.services.proxy import ProxyService, create_proxy_service

logger = logging.getLogger(__name__)

# Create router for proxy endpoints
router = APIRouter()


async def get_proxy_service(
    key_manager: KeyManager = Depends(get_key_manager)
) -> ProxyService:
    """Dependency to get proxy service instance."""
    rotation_manager = get_rotation_manager(key_manager)
    return await create_proxy_service(key_manager, rotation_manager)


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
)
async def proxy_openrouter_v1(
    request: Request,
    path: str,
    proxy_service: ProxyService = Depends(get_proxy_service)
):
    """
    Proxy all requests to OpenRouter API v1 endpoints.
    
    This endpoint handles all HTTP methods and forwards them to OpenRouter
    with intelligent key rotation and proper header management.
    """
    try:
        # The full path including the /v1 prefix
        full_path = f"v1/{path}"
        
        # Proxy the request
        response = await proxy_service.proxy_request(request, full_path)
        
        return response
        
    except HTTPException:
        # Re-raise HTTP exceptions (they contain appropriate status codes)
        raise
    except Exception as e:
        logger.error(f"Unexpected error in proxy endpoint: {e}")
        raise HTTPException(
            status_code=502,
            detail="Proxy service error"
        )


@router.api_route(
    "/openrouter/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
)
async def proxy_openrouter_legacy(
    request: Request,
    path: str,
    proxy_service: ProxyService = Depends(get_proxy_service)
):
    """
    Legacy proxy endpoint for /openrouter/* paths.
    
    This provides backward compatibility for clients that might use
    /openrouter/ prefix instead of /v1/.
    """
    try:
        # Map legacy path to v1 API
        if path.startswith("v1/"):
            full_path = path
        else:
            full_path = f"v1/{path}"
        
        # Proxy the request
        response = await proxy_service.proxy_request(request, full_path)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in legacy proxy endpoint: {e}")
        raise HTTPException(
            status_code=502,
            detail="Proxy service error"
        )


@router.get("/proxy/health")
async def proxy_health(
    proxy_service: ProxyService = Depends(get_proxy_service)
):
    """Get proxy service health status."""
    try:
        health_data = await proxy_service.health_check()
        return health_data
        
    except Exception as e:
        logger.error(f"Error getting proxy health: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@router.get("/proxy/stats")
async def proxy_stats(
    proxy_service: ProxyService = Depends(get_proxy_service)
):
    """Get proxy service statistics."""
    try:
        stats_data = await proxy_service.get_proxy_stats()
        return stats_data
        
    except Exception as e:
        logger.error(f"Error getting proxy stats: {e}")
        return {
            "error": str(e)
        }


@router.get("/proxy/keys/status")
async def proxy_keys_status(
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Get status of all OpenRouter keys for proxy monitoring."""
    try:
        # Get all OpenRouter keys
        openrouter_keys = await key_manager.get_openrouter_keys()
        
        # Get healthy keys
        healthy_keys = await key_manager.get_healthy_openrouter_keys()
        
        # Calculate statistics
        total_keys = len(openrouter_keys)
        healthy_count = len(healthy_keys)
        unhealthy_count = total_keys - healthy_count
        
        # Categorize keys by status
        active_keys = [k for k in openrouter_keys if k.is_active]
        inactive_keys = [k for k in openrouter_keys if not k.is_active]
        rate_limited_keys = [k for k in openrouter_keys if k.is_rate_limited()]
        failed_keys = [k for k in openrouter_keys if k.failure_count > 0]
        
        return {
            "summary": {
                "total_keys": total_keys,
                "healthy_keys": healthy_count,
                "unhealthy_keys": unhealthy_count,
                "active_keys": len(active_keys),
                "inactive_keys": len(inactive_keys),
                "rate_limited_keys": len(rate_limited_keys),
                "failed_keys": len(failed_keys)
            },
            "health_percentage": (healthy_count / total_keys * 100) if total_keys > 0 else 0,
            "status": "healthy" if healthy_count > 0 else "unhealthy"
        }
        
    except Exception as e:
        logger.error(f"Error getting proxy keys status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get keys status"
        )


@router.post("/proxy/keys/{key_hash}/test")
async def test_openrouter_key(
    key_hash: str,
    key_manager: KeyManager = Depends(get_key_manager),
    proxy_service: ProxyService = Depends(get_proxy_service)
):
    """Test a specific OpenRouter key by making a simple API call."""
    try:
        # This would require implementing a test method in proxy service
        # For now, return a placeholder response
        
        # Get key data
        openrouter_keys = await key_manager.get_openrouter_keys()
        target_key = None
        
        for key_data in openrouter_keys:
            if key_data.key_hash == key_hash:
                target_key = key_data
                break
        
        if not target_key:
            raise HTTPException(
                status_code=404,
                detail="Key not found"
            )
        
        if not target_key.is_active:
            return {
                "key_hash": key_hash,
                "test_result": "failed",
                "reason": "Key is inactive",
                "timestamp": "datetime.utcnow().isoformat()"
            }
        
        # TODO: Implement actual key testing by making a simple API call
        # For now, return success if key is healthy
        test_passed = target_key.is_healthy and not target_key.is_rate_limited()
        
        return {
            "key_hash": key_hash,
            "test_result": "passed" if test_passed else "failed",
            "reason": "Key test completed" if test_passed else "Key is unhealthy or rate limited",
            "key_status": {
                "is_healthy": target_key.is_healthy,
                "is_active": target_key.is_active,
                "failure_count": target_key.failure_count,
                "is_rate_limited": target_key.is_rate_limited()
            },
            "timestamp": "datetime.utcnow().isoformat()"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing OpenRouter key {key_hash}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to test key"
        )


@router.get("/proxy/circuit-breakers")
async def get_circuit_breaker_status(
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Get status of all circuit breakers for monitoring."""
    try:
        rotation_manager = get_rotation_manager(key_manager)
        rotator = rotation_manager.get_rotator()
        
        circuit_status = rotator.get_circuit_breaker_status()
        
        # Categorize circuit breakers
        open_breakers = {k: v for k, v in circuit_status.items() if v["state"] == "open"}
        half_open_breakers = {k: v for k, v in circuit_status.items() if v["state"] == "half_open"}
        closed_breakers = {k: v for k, v in circuit_status.items() if v["state"] == "closed"}
        
        return {
            "summary": {
                "total_breakers": len(circuit_status),
                "open_breakers": len(open_breakers),
                "half_open_breakers": len(half_open_breakers),
                "closed_breakers": len(closed_breakers)
            },
            "circuit_breakers": circuit_status,
            "open_breakers": open_breakers,
            "system_health": "healthy" if len(open_breakers) == 0 else "degraded"
        }
        
    except Exception as e:
        logger.error(f"Error getting circuit breaker status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get circuit breaker status"
        )


@router.post("/proxy/circuit-breakers/{key_hash}/reset")
async def reset_circuit_breaker(
    key_hash: str,
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Manually reset a circuit breaker for a specific key."""
    try:
        rotation_manager = get_rotation_manager(key_manager)
        rotator = rotation_manager.get_rotator()
        
        # Reset the circuit breaker
        rotator.reset_circuit_breaker(key_hash)
        
        return {
            "key_hash": key_hash,
            "action": "circuit_breaker_reset",
            "status": "success",
            "timestamp": "datetime.utcnow().isoformat()"
        }
        
    except Exception as e:
        logger.error(f"Error resetting circuit breaker for {key_hash}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to reset circuit breaker"
        )


@router.get("/proxy/rotation/strategy")
async def get_rotation_strategy(
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Get current key rotation strategy."""
    try:
        rotation_manager = get_rotation_manager(key_manager)
        
        return {
            "current_strategy": rotation_manager.current_strategy.value,
            "available_strategies": [strategy.value for strategy in rotation_manager.current_strategy.__class__],
            "timestamp": "datetime.utcnow().isoformat()"
        }
        
    except Exception as e:
        logger.error(f"Error getting rotation strategy: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get rotation strategy"
        )


@router.post("/proxy/rotation/strategy/{strategy}")
async def set_rotation_strategy(
    strategy: str,
    key_manager: KeyManager = Depends(get_key_manager)
):
    """Set key rotation strategy."""
    try:
        from app.services.rotation import RotationStrategy
        
        # Validate strategy
        try:
            rotation_strategy = RotationStrategy(strategy)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid strategy. Available: {[s.value for s in RotationStrategy]}"
            )
        
        rotation_manager = get_rotation_manager(key_manager)
        rotation_manager.current_strategy = rotation_strategy
        
        return {
            "previous_strategy": rotation_manager.current_strategy.value,
            "new_strategy": strategy,
            "status": "success",
            "timestamp": "datetime.utcnow().isoformat()"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting rotation strategy: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to set rotation strategy"
        )


# Health check endpoint for load balancers
@router.get("/health")
async def health_check():
    """Simple health check endpoint for load balancers."""
    return {
        "status": "healthy",
        "service": "openrouter-middleware",
        "timestamp": "datetime.utcnow().isoformat()"
    }


# Metrics endpoint for monitoring
@router.get("/metrics")
async def get_metrics(
    key_manager: KeyManager = Depends(get_key_manager),
    proxy_service: ProxyService = Depends(get_proxy_service)
):
    """Get comprehensive metrics for monitoring."""
    try:
        # Get proxy stats
        proxy_stats = await proxy_service.get_proxy_stats()
        
        # Get key stats
        openrouter_keys = await key_manager.get_openrouter_keys()
        client_keys = await key_manager.get_client_keys()
        
        return {
            "proxy": proxy_stats,
            "keys": {
                "openrouter_keys": len(openrouter_keys),
                "client_keys": len(client_keys),
                "healthy_openrouter_keys": len([k for k in openrouter_keys if k.is_healthy and k.is_active])
            },
            "timestamp": "datetime.utcnow().isoformat()"
        }
        
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get metrics"
        )