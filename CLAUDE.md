# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an OpenRouter API middleware written in Python/FastAPI that provides secure key management and proxy functionality. The system acts as a gateway between clients and OpenRouter, managing API key rotation, client authentication, and admin access through a web interface.

## Project Documentation

**Quick Reference Links:**
- [README.md](README.md) - Complete project documentation and setup guide
- [PLAN.md](PLAN.md) - Original project specification and requirements (Portuguese)
- [.env.example](.env.example) - Environment configuration template
- [docker-compose.yml](docker-compose.yml) - Container orchestration setup

**Key Implementation Files:**
- [app/main.py](app/main.py) - FastAPI application with middleware stack
- [app/services/key_manager.py](app/services/key_manager.py) - Core key management logic
- [app/api/admin.py](app/api/admin.py) - Admin panel API endpoints
- [app/middleware/auth.py](app/middleware/auth.py) - Client authentication middleware
- [app/middleware/admin_auth.py](app/middleware/admin_auth.py) - Admin authentication middleware

## Development Commands

### Testing
- Run all tests: `pytest tests/ -v`
- Run tests with coverage: `pytest tests/ -v --cov=app --cov-report=term-missing`
- Run specific test file: `pytest tests/test_api/test_auth.py -v`
- Run tests in debug mode: `pytest -vvs tests/`
- Run tests with specific markers: `pytest -m "unit" -v` or `pytest -m "integration" -v`
- Run single test method: `pytest tests/test_services/test_key_manager.py::TestKeyManager::test_create_client_key -v`

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

## Task Completion Workflow
When completing a development task, run these commands in order:
1. `ruff check app/ --fix` - Fix linting issues
2. `mypy app/` - Check types
3. `bandit -r app/` - Security scan
4. `pytest tests/ -v --cov=app` - Run tests with coverage
5. Git commit if all checks pass

## Architecture

### Core Design Principles
This codebase follows a **layered architecture** with clear separation of concerns:
- **API Layer** (`app/api/`): HTTP endpoints and request/response handling
- **Service Layer** (`app/services/`): Business logic and external integrations
- **Core Layer** (`app/core/`): Configuration, database connections, security primitives
- **Models Layer** (`app/models/`): Pydantic data models for validation and serialization

### Key Architectural Patterns
- **Dependency Injection**: Services use factory functions (e.g., `get_key_manager()`, `get_redis_client()`)
- **Async Throughout**: Full async/await implementation for non-blocking I/O
- **Middleware Composition**: Ordered middleware stack for cross-cutting concerns
- **Repository Pattern**: Centralized data access through `RedisOperations`

### Critical Application Flow
1. **Startup**: `lifespan()` in `main.py` initializes Redis connections and background tasks
2. **Request Processing**: Middleware stack processes authentication, logging, security
3. **Key Management**: `KeyManager` handles CRUD operations with Redis storage
4. **Background Tasks**: `RotationManager` monitors key health and rotates unhealthy keys
5. **Proxy Flow**: Client requests → Auth → Key selection → OpenRouter forwarding

### Middleware Stack (Order Critical)
The middleware order in `main.py` is carefully designed:
1. **CORS**: Must be first to handle preflight requests
2. **Security Headers**: Applied to all responses
3. **Client Auth**: Validates API keys for `/v1/` and `/openrouter/` paths
4. **Admin Auth**: Session validation for `/admin/*` paths
5. **CSRF Protection**: Protects admin forms
6. **Session Timeout**: Manages session expiration
7. **Session**: Handles session data
8. **Request Logging**: Records all requests (must be last)

### Redis Data Architecture
All application state stored in Redis with specific key patterns:
- `clientkey:{hash}` - Client API key data and metadata
- `openrouter:{hash}` - OpenRouter API key data and health status
- `user_keys:{user_id}` - Set of keys owned by each user
- `key_stats:{key_hash}` - Usage statistics and rate limiting data
- Session data managed by Starlette SessionMiddleware

### Authentication & Authorization
**Dual Authentication System**:
- **Admin Users**: Session-based auth with CSRF protection for web interface
- **API Clients**: Header-based API key auth (`X-Client-API-Key`) for proxy endpoints
- **Key Hierarchy**: Admin keys can manage client keys; client keys can only access proxy

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

### Test Organization
Test structure mirrors the application structure with comprehensive coverage:
- `tests/test_api/` - API endpoint tests using FastAPI TestClient
- `tests/test_core/` - Core functionality (config, Redis, security) tests
- `tests/test_middleware/` - Middleware behavior and authentication tests
- `tests/test_models/` - Pydantic model validation tests
- `tests/test_services/` - Business logic and service integration tests
- `tests/test_integration/` - End-to-end workflow tests

### Testing Infrastructure
- **Async Support**: `pytest-asyncio` with `asyncio_mode = auto`
- **Redis Mocking**: `fakeredis` for isolated Redis operations
- **API Testing**: FastAPI TestClient for HTTP endpoint testing
- **Fixtures**: Shared test fixtures in `conftest.py` for common setup
- **Markers**: Use `@pytest.mark.unit`, `@pytest.mark.integration` for categorization

### Critical Testing Patterns
- **Service Dependencies**: All services accept Redis client for easy mocking
- **Middleware Testing**: Test authentication flows with proper request context
- **Async Testing**: All async functions properly tested with `@pytest.mark.asyncio`
- **Data Validation**: Pydantic models tested for both valid and invalid input

## Important Implementation Notes

### Error Handling Patterns
- Services return proper HTTP status codes via FastAPI exceptions
- Background tasks use structured logging for error tracking
- Redis operations include connection retry logic in `RedisOperations`
- All async operations properly handle timeouts and cancellation

### Security Considerations
- API keys are SHA-256 hashed before storage (never store plaintext)
- Session secrets must be at least 32 characters (validated in config)
- CSRF tokens protect all admin form submissions
- Rate limiting data stored per-key in Redis with TTL

### Performance Characteristics
- Full async/await throughout the stack for non-blocking I/O
- Redis connection pooling configured in `RedisManager`
- Background tasks use asyncio for concurrent key health checks
- Middleware stack designed for minimal latency impact

### Configuration Management
- All settings use Pydantic with environment variable support
- Settings validation occurs at startup (fail-fast principle)
- Debug mode controls API documentation exposure
- Docker profiles separate development/production configurations

## Deployment

- **Development**: Docker Compose with hot reload and Redis Insight
- **Production**: Docker Compose with Nginx reverse proxy profile
- **Monitoring**: Structured logging, health endpoints for Kubernetes
- **Data Persistence**: Redis data and logs mounted to host filesystem