# CML Tools API

A modular API for interacting with Cisco Modeling Labs, with support for AI assistants like Claude.

## Features

- **REST API**: Access all CML operations via a REST API
- **Claude Integration**: Seamless integration with AI assistants via specialized endpoints
- **Modular Architecture**: Easy to extend with new features
- **Async Support**: Fully asynchronous for optimal performance
- **Comprehensive Documentation**: Auto-generated API documentation

## Installation

1. Clone the repository:
   ```
   git clone <your-repo-url>
   cd cml-tools
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run the API server:
   ```
   python -m app.main
   ```

The API will be available at http://localhost:8000.

## API Documentation

Once the server is running, you can access the auto-generated API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Usage

### Authentication

Before using any other endpoints, you need to authenticate with the CML server:

```python
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/auth",
            json={
                "base_url": "https://your-cml-server",
                "username": "your-username",
                "password": "your-password",
                "verify_ssl": False  # For self-signed certificates
            }
        )
        
        print(response.json())
```

### Creating a Lab

```python
async def create_lab():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/labs",
            json={
                "title": "My Lab",
                "description": "Sample lab created via API"
            }
        )
        
        lab_data = response.json()
        lab_id = lab_data["lab_id"]
        print(f"Created lab with ID: {lab_id}")
        return lab_id
```

## Claude Integration

The API includes special endpoints for integration with Claude:

- `/claude/tools` - Get a list of available tools in Claude-compatible format
- `/claude/run-tool` - Execute a tool with parameters

### Example Claude Plugin

```json
{
  "schema_version": "v1",
  "name": "cml_tools",
  "description": "Cisco Modeling Labs tools",
  "auth": {
    "type": "none"
  },
  "api": {
    "type": "openapi",
    "url": "http://localhost:8000/openapi.json"
  },
  "endpoints": [
    {
      "name": "get_tools",
      "url": "http://localhost:8000/claude/tools",
      "description": "Get available CML tools"
    },
    {
      "name": "run_tool",
      "url": "http://localhost:8000/claude/run-tool",
      "description": "Run a CML tool with parameters"
    }
  ]
}
```

## Migration Guide

If you're migrating from the FastMCP implementation, here's how to transition your code:

1. **Authentication**: Replace `initialize_client()` with a direct call to `/auth`
2. **Lab Management**: Use `/labs` endpoints instead of individual tool functions
3. **Node Management**: Use `/labs/{lab_id}/nodes` endpoints instead of direct function calls
4. **Configuration**: Use REST API patterns instead of direct function calls
5. **Claude Integration**: Update your AI assistant to use the new tool manifest format

### Before (FastMCP):

```python
result = await mcp.call("initialize_client", base_url="https://cml", username="admin", password="password")
lab_id = await mcp.call("create_lab", title="My Lab", description="Description")
```

### After (CML Tools API):

```python
auth_response = await client.post("/auth", json={"base_url": "https://cml", "username": "admin", "password": "password"})
lab_response = await client.post("/labs", json={"title": "My Lab", "description": "Description"})
lab_id = lab_response.json()["lab_id"]
```

## Architecture

The codebase is organized as follows:

- `app/` - Main application package
  - `core/` - Core functionality (auth, client)
  - `models/` - Pydantic models for data validation
  - `tools/` - API endpoints organized by functionality
  - `claude/` - Claude integration components
  - `main.py` - Application entry point

## Extending

To add new functionality:

1. Create a new module in the `tools/` directory
2. Define Pydantic models in the `models/` directory
3. Create an APIRouter and define your endpoints
4. Include your router in `main.py`

Example:

```python
# app/tools/custom.py
from fastapi import APIRouter, Depends
from app.core.auth import CMLAuth
from app.tools.lab import get_cml_client

router = APIRouter(prefix="/custom", tags=["custom"])

@router.get("/", summary="Custom endpoint")
async def custom_function(cml_auth: CMLAuth = Depends(get_cml_client)):
    # Your implementation here
    return {"result": "success"}
```

Then in `main.py`:

```python
from app.tools.custom import router as custom_router
app.include_router(custom_router)
```

## License

[MIT License](LICENSE) 
