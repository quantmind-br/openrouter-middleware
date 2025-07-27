# OpenRouter Middleware

**Secure API key management and proxy platform for OpenRouter**

A FastAPI-based middleware that provides secure key management, intelligent rotation, and proxy functionality for OpenRouter API access. The system acts as a gateway between clients and OpenRouter, managing API key pools with health monitoring and rotation while offering a comprehensive web admin panel.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Redis 6.0+
- Docker & Docker Compose (recommended)

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/openrouter-middleware.git
   cd openrouter-middleware
   ```

2. **Create environment configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start with Docker Compose**
   ```bash
   # Development mode with hot reload
   docker-compose up --build
   
   # With Redis Insight for development
   docker-compose --profile development up
   ```

4. **Or run locally**
   ```bash
   # Install dependencies
   pip install -r requirements.txt
   
   # Start Redis (required)
   redis-server
   
   # Run the application
   python app/main.py
   ```

### Access Points
- **Admin Panel**: http://localhost:8080/admin
- **Login**: http://localhost:8080/login
- **API Docs**: http://localhost:8080/docs (development only)
- **Health Check**: http://localhost:8080/health

## 📋 Features

### 🔐 **Dual Authentication System**
- **Admin Authentication**: Session-based login for web admin panel
- **Client Authentication**: API key-based authentication for proxy endpoints
- Configurable session timeouts and security headers

### 🔑 **Intelligent Key Management**
- **OpenRouter Key Pool**: Automatic health monitoring and rotation
- **Client Key System**: Generate and manage client access keys
- **Bulk Import**: Upload `.txt` files with multiple OpenRouter keys
- **Health Monitoring**: Circuit breaker pattern for failed keys

### 🌐 **Transparent Proxy**
- **Full API Compatibility**: Complete OpenRouter API proxy
- **Header Preservation**: Maintains all original request headers
- **Intelligent Routing**: Automatic key selection and rotation
- **Error Handling**: Graceful fallback and error reporting

### 🎛️ **Admin Web Panel**
- **Dashboard**: System overview with key statistics
- **Key Management**: CRUD operations for all key types
- **System Status**: Real-time health monitoring
- **Bulk Operations**: Mass import and management tools

### 🛡️ **Security & Reliability**
- **CSRF Protection**: Built-in CSRF middleware
- **Rate Limiting**: Per-key rate limit tracking
- **Session Security**: Secure cookie configuration
- **Health Checks**: Kubernetes-ready health endpoints

## 🏗️ Architecture

### Core Components

```
📦 OpenRouter Middleware
├── 🌐 FastAPI Application (app/main.py)
│   ├── Middleware Stack (8 layers)
│   ├── Router Configuration
│   └── Lifespan Management
│
├── 🔧 Core Services
│   ├── 🔑 Key Manager (app/services/key_manager.py)
│   ├── 🔄 Rotation Manager (app/services/rotation.py)
│   ├── 🌐 Proxy Service (app/services/proxy.py)
│   └── 📊 Redis Operations (app/core/redis.py)
│
├── 🛡️ Security Layer
│   ├── 👤 Client Auth Middleware
│   ├── 🔐 Admin Auth Middleware
│   ├── 🛡️ CSRF Protection
│   └── 📝 Security Headers
│
├── 🎯 API Endpoints
│   ├── 🔐 Authentication (/login, /logout)
│   ├── 🎛️ Admin Panel (/admin/*)
│   └── 🌐 Proxy Routes (/v1/*, /openrouter/*)
│
└── 📊 Data Layer
    ├── 🔴 Redis Storage
    ├── 🔑 Key Management
    └── 📈 Usage Statistics
```

### Middleware Stack (Order Matters)
1. **CORS Middleware** - Cross-origin request handling
2. **Security Headers** - Security header injection
3. **Client Authentication** - API key validation for `/v1/`, `/openrouter/`
4. **Admin Authentication** - Session validation for admin routes
5. **CSRF Protection** - Cross-site request forgery protection
6. **Session Timeout** - Automatic session expiration
7. **Session Middleware** - Session management (must be last)
8. **Request Logging** - Request/response logging

### Data Architecture
- **Redis Key Patterns**:
  - `clientkey:{hash}` - Client API key data
  - `openrouter:{hash}` - OpenRouter key data
  - `user_keys:{user_id}` - User's key sets
  - `openrouter:active` - Active OpenRouter keys

## 🔧 Configuration

### Environment Variables

```bash
# Admin Credentials
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password

# Security
SESSION_SECRET_KEY=your_session_secret_key

# Redis Configuration
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=your_redis_password

# OpenRouter Configuration
OPENROUTER_BASE_URL=https://openrouter.ai/api

# Application Settings
DEBUG=false
HOST=0.0.0.0
PORT=8080
```

### Docker Configuration

```yaml
# docker-compose.yml profiles:
# - default: Basic production setup
# - development: Includes Redis Insight
# - production: Production optimizations
```

## 📡 API Reference

### Admin Endpoints

#### Authentication
```http
POST   /login                    # Admin login
POST   /logout                   # Admin logout
GET    /admin                    # Dashboard (requires auth)
```

#### OpenRouter Key Management
```http
GET    /admin/openrouter-keys           # Management page
GET    /admin/api/openrouter-keys       # List all keys
POST   /admin/api/openrouter-keys       # Add new key
DELETE /admin/api/openrouter-keys/{hash} # Delete key
POST   /admin/api/openrouter-keys/bulk-import # Bulk import
```

#### Client Key Management
```http
GET    /admin/client-keys               # Management page
GET    /admin/api/client-keys           # List all keys
POST   /admin/api/client-keys           # Create new key
PATCH  /admin/api/client-keys/{hash}/deactivate # Deactivate
PATCH  /admin/api/client-keys/{hash}/reactivate # Reactivate
DELETE /admin/api/client-keys/{hash}    # Delete permanently
```

#### System Management
```http
GET    /admin/api/dashboard-data        # Dashboard statistics
GET    /admin/api/system-status         # Comprehensive status
POST   /admin/api/system/cleanup        # System maintenance
```

### Proxy Endpoints

```http
# OpenRouter API Proxy (requires X-Client-API-Key header)
ANY    /v1/*                    # Primary proxy path
ANY    /openrouter/*           # Alternative proxy path

# Health Checks
GET    /health                  # Application health
GET    /readiness              # Kubernetes readiness
GET    /liveness               # Kubernetes liveness
```

### Authentication Headers

```http
# For admin API calls (after login)
Cookie: session=<session_token>

# For proxy endpoints
X-Client-API-Key: <your_client_api_key>
```

## 🧪 Testing

### Run Tests
```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Specific test categories
pytest tests/test_api/ -v                    # API tests
pytest tests/test_services/ -v               # Service tests
pytest tests/test_middleware/ -v             # Middleware tests

# Integration tests
pytest tests/test_integration/ -v

# Debug mode
pytest -vvs tests/
```

### Test Structure
```
tests/
├── test_api/           # API endpoint tests
├── test_core/          # Core functionality tests
├── test_middleware/    # Middleware tests
├── test_models/        # Data model tests
├── test_services/      # Service layer tests
└── test_integration/   # End-to-end tests
```

## 🔧 Development

### Code Quality
```bash
# Linting
ruff check app/
ruff check app/ --fix        # Auto-fix issues

# Type checking
mypy app/

# Security scanning
bandit -r app/
```

### Development Workflow
1. Create feature branch
2. Implement changes
3. Run tests: `pytest tests/ -v`
4. Check code quality: `ruff check app/ && mypy app/`
5. Security scan: `bandit -r app/`
6. Commit and push

### Project Structure
```
openrouter-middleware/
├── app/                    # Application code
│   ├── api/               # API route handlers
│   ├── core/              # Core functionality
│   ├── middleware/        # Custom middleware
│   ├── models/            # Pydantic models
│   ├── services/          # Business logic
│   └── templates/         # Jinja2 templates
├── tests/                 # Test suite
├── static/                # Static web assets
├── docker-compose.yml     # Container orchestration
├── Dockerfile            # Container definition
├── requirements.txt      # Python dependencies
└── pytest.ini           # Test configuration
```

## 🚀 Deployment

### Docker Production
```bash
# Production deployment
docker-compose --profile production up -d

# With custom environment
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Kubernetes
```yaml
# Health check endpoints ready
readinessProbe:
  httpGet:
    path: /readiness
    port: 8080

livenessProbe:
  httpGet:
    path: /liveness
    port: 8080
```

### Monitoring
- **Structured Logging**: JSON format for log aggregation
- **Health Endpoints**: `/health`, `/readiness`, `/liveness`
- **Metrics**: Usage statistics and performance monitoring
- **Alerting**: Redis connectivity and key pool health

## 🔒 Security

### Security Features
- **Session-based Authentication** for admin panel
- **API Key Authentication** for client access
- **CSRF Protection** on all state-changing operations
- **Secure Headers** (HSTS, CSP, X-Frame-Options)
- **Rate Limiting** per API key
- **Input Validation** with Pydantic models

### Security Best Practices
- Store admin credentials in environment variables
- Use secure session cookies in production
- Regularly rotate OpenRouter API keys
- Monitor failed authentication attempts
- Keep dependencies updated

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

### Development Guidelines
- Follow existing code style and patterns
- Write comprehensive tests
- Update documentation for new features
- Use type hints consistently
- Follow security best practices

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

### Troubleshooting

**Common Issues:**
- **Redis Connection Failed**: Ensure Redis is running and accessible
- **Admin Login Failed**: Check `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env`
- **Key Rotation Issues**: Verify OpenRouter keys are valid and active
- **Session Timeout**: Check `SESSION_SECRET_KEY` configuration

**Debug Mode:**
```bash
# Enable debug logging
DEBUG=true python app/main.py
```

### Getting Help
- Check the [documentation](docs/)
- Review [existing issues](../../issues)
- Create a [new issue](../../issues/new) for bugs or feature requests

---

**Built with FastAPI, Redis, and modern Python practices**