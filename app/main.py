"""Main FastAPI application with middleware setup and router configuration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.redis import lifespan_redis, redis_manager
from app.middleware.auth import (
    ClientAuthMiddleware,
    SecurityHeadersMiddleware,
    RequestLoggingMiddleware
)
from app.middleware.admin_auth import (
    AdminAuthMiddleware,
    CSRFProtectionMiddleware,
    SessionTimeoutMiddleware
)
from app.api import auth, admin, proxy
from app.services.rotation import get_rotation_manager
from app.services.key_manager import get_key_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    try:
        # Initialize Redis connection
        async with lifespan_redis():
            logger.info("Redis connection initialized")
            
            # Initialize rotation manager background tasks
            key_manager = await get_key_manager()
            rotation_manager = get_rotation_manager(key_manager)
            rotation_manager.start_background_tasks()
            logger.info("Key rotation background tasks started")
            
            yield
            
            # Cleanup on shutdown
            await rotation_manager.stop_background_tasks()
            logger.info("Application shutdown completed")
            
    except Exception as e:
        logger.error(f"Error during application lifespan: {e}")
        raise


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Secure OpenRouter API key management and proxy platform",
    lifespan=lifespan,
    # Disable docs in production
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None
)

# Setup templates
templates = Jinja2Templates(directory="app/templates")

# Configure templates for routers
auth.setup_templates(templates)
admin.setup_templates(templates)

# Add middleware in proper order (order matters!)

# 1. CORS middleware (should be first for preflight requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.allow_credentials,
    allow_methods=settings.allowed_methods,
    allow_headers=settings.allowed_headers,
)

# 2. Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# 3. Client authentication middleware (for API endpoints) - first
app.add_middleware(
    ClientAuthMiddleware,
    require_auth_paths=["/v1/", "/openrouter/"]
)

# 4. Admin authentication middleware
app.add_middleware(AdminAuthMiddleware)

# 5. CSRF protection middleware
app.add_middleware(CSRFProtectionMiddleware)

# 6. Session timeout middleware
app.add_middleware(SessionTimeoutMiddleware, timeout_hours=24)

# 7. Session middleware (required for admin authentication) - must be last to be executed first
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    max_age=86400,  # 24 hours
    same_site="strict",
    https_only=not settings.debug  # Only use secure cookies in production
)

# 8. Request logging middleware (should be last)
app.add_middleware(RequestLoggingMiddleware)

# Include routers

# Auth routes (login/logout)
app.include_router(
    auth.router,
    tags=["authentication"]
)

# Admin routes
app.include_router(
    admin.router,
    tags=["admin"]
)

# Proxy routes (main functionality)
app.include_router(
    proxy.router,
    tags=["proxy"]
)

# Mount static files
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logger.warning(f"Could not mount static files: {e}")

# Root endpoints

@app.get("/")
async def root():
    """Root endpoint with basic information."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs" if settings.debug else "disabled",
        "admin": "/admin",
        "login": "/login"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    try:
        # Check Redis connection
        redis_healthy = await redis_manager.is_healthy()
        
        # Check if we have any healthy keys
        key_manager = await get_key_manager()
        healthy_keys = await key_manager.get_healthy_openrouter_keys()
        
        overall_status = "healthy" if redis_healthy and len(healthy_keys) > 0 else "degraded"
        
        return {
            "status": overall_status,
            "timestamp": "datetime.utcnow().isoformat()",
            "checks": {
                "redis": "healthy" if redis_healthy else "unhealthy",
                "openrouter_keys": len(healthy_keys),
                "service": "running"
            },
            "version": settings.app_version
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": "datetime.utcnow().isoformat()"
        }


@app.get("/readiness")
async def readiness_check():
    """Readiness check for Kubernetes."""
    try:
        # Check if application is ready to receive traffic
        redis_healthy = await redis_manager.is_healthy()
        
        if not redis_healthy:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail="Redis not ready")
        
        return {
            "status": "ready",
            "timestamp": "datetime.utcnow().isoformat()"
        }
        
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Service not ready")


@app.get("/liveness")
async def liveness_check():
    """Liveness check for Kubernetes."""
    return {
        "status": "alive",
        "timestamp": "datetime.utcnow().isoformat()"
    }


# Error handlers

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    if request.url.path.startswith("/admin"):
        # For admin routes, return a template or redirect
        return templates.TemplateResponse(
            "404.html", 
            {"request": request}, 
            status_code=404
        )
    else:
        # For API routes, return JSON
        return {
            "error": {
                "type": "not_found",
                "message": "The requested resource was not found",
                "code": 404
            }
        }


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Custom 500 handler."""
    logger.error(f"Internal server error: {exc}")
    
    if request.url.path.startswith("/admin"):
        return templates.TemplateResponse(
            "500.html",
            {"request": request},
            status_code=500
        )
    else:
        return {
            "error": {
                "type": "internal_error",
                "message": "An internal server error occurred",
                "code": 500
            }
        }


# Application startup and shutdown events (if needed beyond lifespan)

@app.on_event("startup")
async def startup_event():
    """Additional startup tasks."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"OpenRouter base URL: {settings.openrouter_base_url}")


@app.on_event("shutdown")
async def shutdown_event():
    """Additional shutdown tasks."""
    logger.info(f"Shutting down {settings.app_name}")


# Development server
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload and settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True
    )