"""
Example skill: Web API documentation.

Provides knowledge about REST APIs, HTTP protocols, and common web services.
"""

from typing import Optional

from ..base import Skill, SkillMetadata, SkillType, StaticSkill


class WebAPISkill(StaticSkill):
    """Skill providing web API documentation."""

    def __init__(self, metadata: Optional[SkillMetadata] = None):
        if metadata is None:
            metadata = SkillMetadata(
                name="web_api",
                description="REST API documentation, HTTP protocols, and common web services",
                skill_type=SkillType.DOCUMENTATION,
                tags=["web", "api", "http", "rest", "network"],
                size_estimate=4000,
                cache_ttl=86400,
                dependencies=["python_api"],  # Depends on Python API for examples
            )

        content = """# Web API Documentation

## HTTP Protocol Basics

### HTTP Methods
- **GET**: Retrieve a resource
- **POST**: Create a new resource
- **PUT**: Update/replace a resource
- **PATCH**: Partial update of a resource
- **DELETE**: Remove a resource
- **HEAD**: Get headers only
- **OPTIONS**: Get supported methods

### HTTP Status Codes

#### 2xx Success
- **200 OK**: Request succeeded
- **201 Created**: Resource created
- **204 No Content**: Success, no body

#### 3xx Redirection
- **301 Moved Permanently**
- **302 Found** (Temporary redirect)
- **304 Not Modified** (Caching)

#### 4xx Client Errors
- **400 Bad Request**: Malformed request
- **401 Unauthorized**: Authentication required
- **403 Forbidden**: Authenticated but not authorized
- **404 Not Found**: Resource doesn't exist
- **429 Too Many Requests**: Rate limiting

#### 5xx Server Errors
- **500 Internal Server Error**
- **502 Bad Gateway**
- **503 Service Unavailable**
- **504 Gateway Timeout**

### HTTP Headers (Common)
- `Content-Type`: Media type of body (e.g., `application/json`)
- `Authorization`: Credentials for authentication
- `Accept`: Acceptable media types for response
- `User-Agent`: Client application identifier
- `Cache-Control`: Caching directives

## REST API Design Principles

### REST Constraints
1. **Client-Server Architecture**: Separation of concerns
2. **Statelessness**: Each request contains all necessary information
3. **Cacheability**: Responses must define cacheability
4. **Uniform Interface**: Consistent resource identification and manipulation
5. **Layered System**: Intermediary servers can be inserted
6. **Code on Demand** (optional): Clients can download and execute code

### Resource Naming Conventions
- Use nouns (not verbs) for resources: `/users`, `/orders`
- Use plural nouns for collections: `/users` not `/user`
- Use hierarchical relationships: `/users/{id}/orders`
- Use query parameters for filtering: `/users?active=true`
- Use HTTP methods for actions: POST to create, PUT to update

### Common REST Patterns

#### Collection Resource
```
GET    /users           # List users
POST   /users           # Create user
GET    /users/{id}      # Get user
PUT    /users/{id}      # Update user
DELETE /users/{id}      # Delete user
```

#### Sub-resource
```
GET    /users/{id}/orders    # Get user's orders
POST   /users/{id}/orders    # Create order for user
```

#### Actions (RPC-style when needed)
```
POST   /users/{id}/activate  # Activate user
POST   /users/{id}/deactivate # Deactivate user
```

## Authentication & Authorization

### API Keys
```http
GET /api/resource HTTP/1.1
X-API-Key: your-api-key-here
```

### Bearer Tokens (JWT)
```http
GET /api/resource HTTP/1.1
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### OAuth 2.0 Flows
1. **Authorization Code**: Web server applications
2. **Implicit**: Single-page applications (less secure)
3. **Client Credentials**: Machine-to-machine
4. **Resource Owner Password Credentials**: Legacy/trusted

### Basic Authentication
```http
GET /api/resource HTTP/1.1
Authorization: Basic dXNlcjpwYXNzd29yZA==
```

## Request/Response Examples

### JSON Request
```http
POST /users HTTP/1.1
Content-Type: application/json
{
  "name": "John Doe",
  "email": "john@example.com",
  "active": true
}
```

### JSON Response
```http
HTTP/1.1 201 Created
Content-Type: application/json
{
  "id": 123,
  "name": "John Doe",
  "email": "john@example.com",
  "active": true,
  "created_at": "2023-10-01T12:00:00Z"
}
```

### Error Response
```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
{
  "error": "Invalid request",
  "message": "Email is required",
  "code": "VALIDATION_ERROR"
}
```

## Common API Patterns

### Pagination
```http
GET /users?page=2&limit=20
```
Response:
```json
{
  "data": [...],
  "pagination": {
    "page": 2,
    "limit": 20,
    "total": 150,
    "pages": 8
  }
}
```

### Filtering
```http
GET /users?status=active&role=admin
```

### Sorting
```http
GET /users?sort=-created_at,name
```

### Field Selection
```http
GET /users?fields=id,name,email
```

## Rate Limiting

Common headers:
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 997
X-RateLimit-Reset: 1640995200
Retry-After: 60
```

## API Versioning

### URL Versioning
```
/api/v1/users
/api/v2/users
```

### Header Versioning
```http
GET /api/users HTTP/1.1
Accept: application/vnd.example.v1+json
```

### Query Parameter Versioning
```
/api/users?version=1
```

## Testing APIs

### Tools
- **cURL**: Command line HTTP client
- **Postman**: GUI API testing
- **Insomnia**: Alternative to Postman
- **HTTPie**: User-friendly CLI

### cURL Examples
```bash
# GET request
curl -X GET https://api.example.com/users

# POST with JSON
curl -X POST https://api.example.com/users \
  -H "Content-Type: application/json" \
  -d '{"name": "John"}'

# With authentication
curl -X GET https://api.example.com/users \
  -H "Authorization: Bearer token123"
```

## Security Best Practices

1. **Use HTTPS** for all API endpoints
2. **Validate all input** (size, type, format)
3. **Implement rate limiting** to prevent abuse
4. **Use proper authentication** and authorization
5. **Sanitize output** to prevent XSS
6. **Log security events** for monitoring
7. **Keep dependencies updated**
8. **Use API gateways** for additional security

This documentation provides essential web API knowledge for building and consuming RESTful services.
"""
        super().__init__(content, metadata)


def create_web_api_skill() -> WebAPISkill:
    """Create and return a web API skill instance."""
    return WebAPISkill()