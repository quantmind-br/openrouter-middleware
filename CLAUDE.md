# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an OpenRouter API middleware written in Python/FastAPI that provides secure key management and proxy functionality. The system acts as a gateway between clients and OpenRouter, managing API key rotation, client authentication, and admin access through a web interface.

## Development Commands

### Testing
- Run all tests: `pytest tests/ -v`
- Run tests with coverage: `pytest tests/ -v --cov=app --cov-report=term-missing`
- Run specific test file: `pytest tests/test_api/test_auth.py -v`
- Run tests in debug mode: `pytest -vvs tests/`

### Code Quality
- Lint code: `ruff check app/`
- Auto-fix linting issues: `ruff check app/ --fix`
- Type checking: `mypy app/`
- Security scanning: `bandit -r app/`

### Running the Application
- Development server: `python app/main.py`
- With uvicorn: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8080`
- Docker: `docker-compose up --build`
- Development with Redis Insight: `docker-compose --profile development up`
- Production: `docker-compose --profile production up`

## Architecture

### Core Components
- **FastAPI Application** (`app/main.py`): Main application with middleware stack and routing
- **Redis Manager** (`app/core/redis.py`): Async Redis connection management
- **Key Manager** (`app/services/key_manager.py`): Manages OpenRouter and client API keys
- **Proxy Service** (`app/services/proxy.py`): Handles request forwarding to OpenRouter
- **Rotation Manager** (`app/services/rotation.py`): Background key health monitoring and rotation

### Middleware Stack (Order Matters)
1. CORS middleware
2. Security headers middleware  
3. Client authentication middleware (for `/v1/`, `/openrouter/` paths)
4. Admin authentication middleware
5. CSRF protection middleware
6. Session timeout middleware
7. Session middleware
8. Request logging middleware

### Authentication
- **Admin Auth**: Session-based authentication for web admin panel (`/admin/*`)
- **Client Auth**: API key authentication via `X-Client-API-Key` header for proxy endpoints
- Credentials configured via environment variables in `.env` file

### Data Storage
- **Redis**: All key management, session storage, and caching
- Keys stored with health status, rate limiting data, and rotation metadata
- Session data for admin authentication

## Key Endpoints

### Admin Panel
- `/login` - Admin login page
- `/admin` - Main dashboard (requires authentication)
- `/admin/openrouter-keys` - Manage OpenRouter API keys
- `/admin/client-keys` - Manage client API keys

### Proxy Endpoints
- `/v1/*` - OpenRouter API proxy (requires client key)
- `/openrouter/*` - Alternative proxy path

### Health Checks
- `/health` - Application health with Redis and key status
- `/readiness` - Kubernetes readiness probe
- `/liveness` - Kubernetes liveness probe

## Configuration

Environment variables loaded from `.env` file:
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` - Admin credentials
- `SESSION_SECRET_KEY` - Session encryption key
- `REDIS_URL`, `REDIS_PASSWORD` - Redis connection
- `OPENROUTER_BASE_URL` - Target API base URL
- `DEBUG` - Debug mode toggle

## Testing Strategy

Test structure mirrors the application structure:
- `tests/test_api/` - API endpoint tests
- `tests/test_core/` - Core functionality tests  
- `tests/test_middleware/` - Middleware tests
- `tests/test_models/` - Data model tests
- `tests/test_services/` - Service layer tests
- `tests/test_integration/` - End-to-end tests

Uses pytest with async support, fakeredis for Redis mocking, and FastAPI TestClient for API testing.

## Deployment

- **Development**: Docker Compose with hot reload
- **Production**: Docker Compose with Nginx reverse proxy
- **Monitoring**: Structured logging, health endpoints, optional Prometheus metrics
- **Data Persistence**: Redis data and logs mounted to host filesystem