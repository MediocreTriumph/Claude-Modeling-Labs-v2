"""
import sys
import os
print(f"Python executable: {sys.executable}", file=sys.stderr)
print(f"Python path: {sys.path}", file=sys.stderr)
print(f"Current working directory: {os.getcwd()}", file=sys.stderr)
try:
    import urllib3
    print(f"urllib3 version: {urllib3.__version__}", file=sys.stderr)
except ImportError as e:
    print(f"Error importing urllib3: {e}", file=sys.stderr)

CML Lab Builder - FastMCP server for Cisco Modeling Labs

This server provides tools for Claude to interact with Cisco Modeling Labs,
allowing it to create and configure network labs using natural language.
"""

import os
import sys
import httpx
import json
import warnings
import asyncio
from typing import Dict, List, Optional, Any, Union, Tuple
from fastmcp import FastMCP, Context, Image

# Import our fixed node and link creation functions
try:
    from cml_node_creation_fix import create_node, create_router, create_switch
    from cml_link_creation import create_link, connect_nodes, find_physical_interface
    print("Successfully imported fixed CML node and link creation functions", file=sys.stderr)
except ImportError as e:
    print(f"Warning: Failed to import fixed CML functions: {e}", file=sys.stderr)
    # We'll define fallback implementations later

# Import troubleshooting modules
try:
    from tshoot.console_access import ConsoleManager, ConsoleSession
    from tshoot.diagnostic_tools import NetworkDiagnostics
    from tshoot.troubleshooting_framework import TroubleshootingFramework
    print("Successfully imported troubleshooting modules", file=sys.stderr)
except ImportError as e:
    print(f"Warning: Failed to import troubleshooting modules: {e}", file=sys.stderr)
    # We'll still create stubs for the troubleshooting tools

# Create the MCP server
mcp = FastMCP(
    "CML Lab Builder",
    dependencies=["httpx>=0.26.0", "urllib3>=2.0.0"],
)

# Global state for CML client
cml_auth = None

# Global state for troubleshooting tools
console_manager = None
diagnostics = None
troubleshooting = None


class CMLAuth:
    """Authentication and request handling for Cisco Modeling Labs"""
    
    def __init__(self, base_url: str, username: str, password: str, verify_ssl: bool = True):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
        self.verify_ssl = verify_ssl
        self.client = httpx.AsyncClient(base_url=base_url, verify=verify_ssl)
        
        # Suppress SSL warnings if verify_ssl is False
        if not verify_ssl:
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except ImportError:
                print("urllib3 not available, SSL warning suppression disabled", file=sys.stderr)
    
    async def authenticate(self) -> str:
        """Authenticate with CML and get a token"""
        print(f"Authenticating with CML at {self.base_url}", file=sys.stderr)
        response = await self.client.post(
            "/api/v0/authenticate",
            json={"username": self.username, "password": self.password}
        )
        response.raise_for_status()
        self.token = response.text.strip('"')  # Remove any quotes from the token
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        
        # Verify the token works
        try:
            auth_check = await self.client.get("/api/v0/authok")
            auth_check.raise_for_status()
            print(f"Authentication successful, token verified", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Token verification failed: {str(e)}", file=sys.stderr)
            
        return self.token
    
    async def request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Make an authenticated request to CML API"""
        if not self.token:
            await self.authenticate()
        
        # Print debug info to help troubleshoot
        print(f"Making {method} request to {endpoint}", file=sys.stderr)
        
        # Ensure headers contain the token
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        
        # Ensure the Authorization header is set with the current token
        kwargs["headers"]["Authorization"] = f"Bearer {self.token}"
        
        # Make the request
        try:
            response = await self.client.request(method, endpoint, **kwargs)
            
            # If unauthorized, try to re-authenticate once
            if response.status_code == 401:
                print(f"Got 401 response, re-authenticating...", file=sys.stderr)
                await self.authenticate()
                kwargs["headers"]["Authorization"] = f"Bearer {self.token}"
                response = await self.client.request(method, endpoint, **kwargs)
            
            response.raise_for_status()
            return response
        except Exception as e:
            print(f"Request error: {str(e)}", file=sys.stderr)
            raise


# Authentication Tools

@mcp.tool()
async def initialize_client(base_url: str, username: str, password: str, verify_ssl: bool = True) -> str:
    """
    Initialize the CML client with authentication credentials
    
    Args:
        base_url: Base URL of the CML server (e.g., https://cml-server)
        username: Username for CML authentication
        password: Password for CML authentication
        verify_ssl: Whether to verify SSL certificates (set to False for self-signed certificates)
    
    Returns:
        A success message if authentication is successful
    """
    global cml_auth, console_manager, diagnostics, troubleshooting
    
    # Fix URL if it doesn't have a scheme
    if not base_url.startswith(('http://', 'https://')):
        base_url = f"https://{base_url}"
    
    print(f"Initializing CML client with base_url: {base_url}", file=sys.stderr)
    cml_auth = CMLAuth(base_url, username, password, verify_ssl)
    
    try:
        token = await cml_auth.authenticate()
        print(f"Token received: {token[:10]}...", file=sys.stderr)  # Only print first 10 chars for security
        
        # Initialize troubleshooting tools if modules were imported successfully
        if 'ConsoleManager' in globals() and cml_auth:
            console_manager = ConsoleManager(cml_auth)
            diagnostics = NetworkDiagnostics(console_manager)
            troubleshooting = TroubleshootingFramework(console_manager)
            print("Troubleshooting tools initialized", file=sys.stderr)
            
        ssl_status = "enabled" if verify_ssl else "disabled (accepting self-signed certificates)"
        return f"Successfully authenticated with CML at {base_url} (SSL verification: {ssl_status})"
    except httpx.HTTPStatusError as e:
        return f"Authentication failed: {str(e)}"
    except Exception as e:
        print(f"Error connecting to CML: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error connecting to CML: {str(e)}"


# Lab Management Tools

@mcp.tool()
async def list_labs() -> str:
    """
    List all labs in CML
    
    Returns:
        A formatted list of all available labs
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        print("Attempting to list labs...", file=sys.stderr)
        response = await cml_auth.request("GET", "/api/v0/labs")
        labs = response.json()
        
        print(f"Found {len(labs)} labs", file=sys.stderr)
        
        if not labs:
            return "No labs found in CML."
        
        # Format the response nicely
        result = "Available Labs:\n\n"
        for lab_id, lab_info in labs.items():
            result += f"- {lab_info.get('title', 'Untitled')} (ID: {lab_id})\n"
            if lab_info.get('description'):
                result += f"  Description: {lab_info['description']}\n"
            result += f"  State: {lab_info.get('state', 'unknown')}\n"
        
        return result
    except Exception as e:
        print(f"Error listing labs: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error listing labs: {str(e)}"


@mcp.tool()
async def create_lab(title: str, description: str = "") -> Dict[str, str]:
    """
    Create a new lab in CML
    
    Args:
        title: Title of the new lab
        description: Optional description for the lab
    
    Returns:
        Dictionary containing lab ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        print(f"Creating lab with title: {title}", file=sys.stderr)
        
        response = await cml_auth.request(
            "POST", 
            "/api/v0/labs",
            json={"title": title, "description": description}
        )
        
        lab_data = response.json()
        print(f"Lab creation response: {lab_data}", file=sys.stderr)
        
        lab_id = lab_data.get("id")
        
        if not lab_id:
            return {"error": "Failed to create lab, no lab ID returned"}
        
        return {
            "lab_id": lab_id,
            "message": f"Created lab '{title}' with ID: {lab_id}",
            "status": "success"
        }
    except Exception as e:
        print(f"Error creating lab: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating lab: {str(e)}"}


@mcp.tool()
async def get_lab_details(lab_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific lab
    
    Args:
        lab_id: ID of the lab to get details for
    
    Returns:
        Dictionary containing lab details
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        response = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}")
        lab_details = response.json()
        return lab_details
    except Exception as e:
        return {"error": f"Error getting lab details: {str(e)}"}


@mcp.tool()
async def delete_lab(lab_id: str) -> str:
    """
    Delete a lab from CML
    
    Args:
        lab_id: ID of the lab to delete
    
    Returns:
        Confirmation message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        # First check if the lab is running
        lab_details = await get_lab_details(lab_id)
        if isinstance(lab_details, dict) and lab_details.get("state") == "STARTED":
            # Stop the lab first
            await stop_lab(lab_id)
        
        response = await cml_auth.request("DELETE", f"/api/v0/labs/{lab_id}")
        return f"Lab {lab_id} deleted successfully"
    except Exception as e:
        return f"Error deleting lab: {str(e)}"


# Node Management Tools

@mcp.tool()
async def list_node_definitions() -> Union[Dict[str, Any], str]:
    """
    List all available node definitions in CML
    
    Returns:
        Dictionary of available node definitions or error message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("GET", "/api/v0/node_definitions")
        node_defs = response.json()
        
        # If the response is a list, convert it to a dictionary
        if isinstance(node_defs, list):
            print(f"Converting node definitions list to dictionary", file=sys.stderr)
            result = {}
            for node_def in node_defs:
                node_id = node_def.get("id")
                if node_id:
                    result[node_id] = node_def
            return result
        
        # Format the result to be more readable
        result = {}
        for node_id, node_info in node_defs.items():
            result[node_id] = {
                "description": node_info.get("description", ""),
                "type": node_info.get("type", ""),
                "interfaces": node_info.get("interfaces", []),
            }
        
        return result
    except Exception as e:
        return f"Error listing node definitions: {str(e)}"


@mcp.tool()
async def get_lab_nodes(lab_id: str) -> Union[Dict[str, Any], str]:
    """
    Get all nodes in a specific lab
    
    Args:
        lab_id: ID of the lab
    
    Returns:
        Dictionary of nodes in the lab or error message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/nodes")
        nodes = response.json()
        
        # If the response is a list, convert it to a dictionary
        if isinstance(nodes, list):
            print(f"Converting nodes list to dictionary", file=sys.stderr)
            result = {}
            for node in nodes:
                node_id = node.get("id")
                if node_id:
                    result[node_id] = node
            return result
        
        return nodes
    except Exception as e:
        return f"Error getting lab nodes: {str(e)}"


@mcp.tool()
async def add_node(
    lab_id: str, 
    label: str, 
    node_definition: str, 
    x: int = 0, 
    y: int = 0,
    populate_interfaces: bool = True,
    ram: Optional[int] = None,
    cpu_limit: Optional[int] = None,
    parameters: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Add a node to the specified lab
    
    Args:
        lab_id: ID of the lab
        label: Label for the new node
        node_definition: Type of node (e.g., 'iosv', 'csr1000v')
        x: X coordinate for node placement
        y: Y coordinate for node placement
        populate_interfaces: Whether to automatically create interfaces
        ram: RAM allocation for the node (optional)
        cpu_limit: CPU limit for the node (optional)
        parameters: Node-specific parameters (optional)
    
    Returns:
        Dictionary with node ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Use the fixed implementation if available
        if 'create_node' in globals():
            return await create_node(cml_auth, lab_id, label, node_definition, x, y, populate_interfaces, ram, cpu_limit, parameters)
        
        # Fall back to a simplified implementation if the fixed version isn't available
        # Based on the format observed in API screenshots
        node_data = {
            "label": label,
            "node_definition": node_definition,
            "x": x,
            "y": y,
            "parameters": parameters or {}
        }
        
        # Add optional parameters if provided
        if ram is not None:
            node_data["ram"] = ram
        
        if cpu_limit is not None:
            node_data["cpu_limit"] = cpu_limit
            
        # Default empty values
        node_data["tags"] = []
        node_data["hide_links"] = False
        
        # Add populate_interfaces as a query parameter if needed
        endpoint = f"/api/v0/labs/{lab_id}/nodes"
        if populate_interfaces:
            endpoint += "?populate_interfaces=true"
        
        # Make the API request with explicit Content-Type header
        headers = {"Content-Type": "application/json"}
        response = await cml_auth.request(
            "POST",
            endpoint,
            json=node_data,
            headers=headers
        )
        
        # Process the response
        result = response.json()
        node_id = result.get("id")
        
        if not node_id:
            return {"error": "Failed to create node, no node ID returned", "response": result}
        
        return {
            "node_id": node_id,
            "message": f"Added node '{label}' with ID: {node_id}",
            "status": "success",
            "details": result
        }
    except Exception as e:
        print(f"Error adding node: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error adding node: {str(e)}"}


@mcp.tool()
async def get_node_interfaces(lab_id: str, node_id: str) -> Union[Dict[str, Any], str, List[str]]:
    """
    Get interfaces for a specific node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
    
    Returns:
        Dictionary of node interfaces or error message or list of interface IDs
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/nodes/{node_id}/interfaces")
        interfaces = response.json()
        
        # Check if the response is a list of interface IDs (sometimes happens with CML API)
        if isinstance(interfaces, list):
            # Return the list directly
            print(f"Got list of interface IDs: {interfaces}", file=sys.stderr)
            return interfaces
        elif isinstance(interfaces, str):
            # If it's a string, it might be a concatenated list of UUIDs
            print(f"Got string of interface IDs: {interfaces}", file=sys.stderr)
            # Parse as UUIDs (36 characters per UUID)
            if len(interfaces) % 36 == 0:
                return [interfaces[i:i+36] for i in range(0, len(interfaces), 36)]
            else:
                return interfaces
        else:
            # If it's a dictionary, return it as is
            return interfaces
    except Exception as e:
        print(f"Error getting node interfaces: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error getting node interfaces: {str(e)}"


# Link Management Tools

@mcp.tool()
async def get_physical_interfaces(lab_id: str, node_id: str) -> Union[Dict[str, Any], List[Dict[str, Any]], str]:
    """
    Get all physical interfaces for a specific node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
    
    Returns:
        List of physical interfaces or error message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        # Use the enhanced function if available
        if 'get_filtered_interfaces' in globals():
            return await get_filtered_interfaces(cml_auth, lab_id, node_id, "physical")
        
        # First get all interfaces
        interfaces_response = await get_node_interfaces(lab_id, node_id)
        
        # Handle different return types
        interface_ids = []
        if isinstance(interfaces_response, str) and "Error" in interfaces_response:
            return interfaces_response
        elif isinstance(interfaces_response, list):
            interface_ids = interfaces_response
        elif isinstance(interfaces_response, str):
            # Parse as UUIDs if needed
            if len(interfaces_response) % 36 == 0:
                interface_ids = [interfaces_response[i:i+36] for i in range(0, len(interfaces_response), 36)]
            else:
                return f"Unexpected interface response format: {interfaces_response}"
        elif isinstance(interfaces_response, dict):
            interface_ids = list(interfaces_response.keys())
        else:
            return f"Unexpected interface response type: {type(interfaces_response)}"
        
        # Get details for each interface and filter for physical interfaces
        physical_interfaces = []
        for interface_id in interface_ids:
            interface_details = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/interfaces/{interface_id}")
            interface_data = interface_details.json()
            
            # Check if it's a physical interface
            is_physical = interface_data.get("type") == "physical"
            
            # If type is not present, check other attributes that might indicate a physical interface
            if "type" not in interface_data:
                # Most physical interfaces have a slot number
                if "slot" in interface_data:
                    is_physical = True
            
            if is_physical:
                physical_interfaces.append(interface_data)
        
        if not physical_interfaces:
            return f"No physical interfaces found for node {node_id}"
        
        return physical_interfaces
    except Exception as e:
        print(f"Error getting physical interfaces: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error getting physical interfaces: {str(e)}"


@mcp.tool()
async def get_lab_links(lab_id: str) -> Union[Dict[str, Any], str]:
    """
    Get all links in a specific lab
    
    Args:
        lab_id: ID of the lab
    
    Returns:
        Dictionary of links in the lab or error message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/links")
        links = response.json()
        
        # If the response is a list, convert it to a dictionary
        if isinstance(links, list):
            print(f"Converting links list to dictionary", file=sys.stderr)
            result = {}
            for link in links:
                link_id = link.get("id")
                if link_id:
                    result[link_id] = link
            return result
        
        return links
    except Exception as e:
        return f"Error getting lab links: {str(e)}"


@mcp.tool()
async def create_interface(lab_id: str, node_id: str, slot: int = 4) -> Dict[str, Any]:
    """
    Create an interface on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        slot: Slot number for the interface (default: 0)
    
    Returns:
        Dictionary with interface ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Check if the lab is running
        lab_details = await get_lab_details(lab_id)
        if isinstance(lab_details, dict) and lab_details.get("state") == "STARTED":
            return {"error": "Cannot create interfaces while the lab is running. Please stop the lab first."}
        
        print(f"Creating interface on node {node_id}, slot {slot}", file=sys.stderr)
        
        # Construct the proper payload format
        interface_data = {
            "node": node_id,
            "slot": slot
        }
        
        print(f"Interface creation payload: {interface_data}", file=sys.stderr)
        
        # Make the API request
        response = await cml_auth.request(
            "POST", 
            f"/api/v0/labs/{lab_id}/interfaces",
            json=interface_data
        )
        
        # Process the response
        result = response.json()
        print(f"Interface creation response: {result}", file=sys.stderr)
        
        # Handle different response formats
        if isinstance(result, list) and len(result) > 0:
            # Sometimes the API returns a list of created interfaces
            interface_id = result[0].get("id")
            interface_label = result[0].get("label")
            return {
                "interface_id": interface_id,
                "message": f"Created interface {interface_label} on node {node_id}, slot {slot}",
                "status": "success",
                "details": result
            }
        elif isinstance(result, dict):
            # Sometimes it returns a single object
            interface_id = result.get("id")
            interface_label = result.get("label")
            if interface_id:
                return {
                    "interface_id": interface_id,
                    "message": f"Created interface {interface_label} on node {node_id}, slot {slot}",
                    "status": "success",
                    "details": result
                }
        
        return {"error": "Failed to create interface, unexpected response format", "response": result}
    except Exception as e:
        print(f"Error creating interface: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating interface: {str(e)}"}


@mcp.tool()
async def create_link_v3(lab_id: str, interface_id_a: str, interface_id_b: str) -> Dict[str, Any]:
    """
    Create a link between two interfaces in a lab (alternative format)
    
    Args:
        lab_id: ID of the lab
        interface_id_a: ID of the first interface
        interface_id_b: ID of the second interface
    
    Returns:
        Dictionary with link ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Use the enhanced function if available
        if 'create_link_with_retry' in globals():
            return await create_link_with_retry(cml_auth, lab_id, interface_id_a, interface_id_b)
        
        print(f"Creating link between interfaces {interface_id_a} and {interface_id_b}", file=sys.stderr)
        
        # Try first payload format (i1, i2)
        print("Trying link creation with format {i1, i2}", file=sys.stderr)
        link_data_1 = {
            "i1": interface_id_a,
            "i2": interface_id_b
        }
        
        try:
            response = await cml_auth.request(
                "POST", 
                f"/api/v0/labs/{lab_id}/links",
                json=link_data_1
            )
            
            result = response.json()
            print(f"Link creation response (format 1): {result}", file=sys.stderr)
            
            # Extract the link ID from the response
            link_id = result.get("id")
            if link_id:
                return {
                    "link_id": link_id,
                    "message": f"Created link between interfaces {interface_id_a} and {interface_id_b}",
                    "status": "success",
                    "details": result
                }
        except Exception as e:
            print(f"First link format failed: {str(e)}", file=sys.stderr)
            # Continue to try the next format
        
        # Try second payload format (src_int, dst_int)
        print("Trying link creation with format {src_int, dst_int}", file=sys.stderr)
        link_data_2 = {
            "src_int": interface_id_a,
            "dst_int": interface_id_b
        }
        
        try:
            response = await cml_auth.request(
                "POST", 
                f"/api/v0/labs/{lab_id}/links",
                json=link_data_2
            )
            
            result = response.json()
            print(f"Link creation response (format 2): {result}", file=sys.stderr)
            
            # Extract the link ID from the response
            link_id = result.get("id")
            if link_id:
                return {
                    "link_id": link_id,
                    "message": f"Created link between interfaces {interface_id_a} and {interface_id_b}",
                    "status": "success",
                    "details": result
                }
        except Exception as e:
            print(f"Second link format failed: {str(e)}", file=sys.stderr)
        
        # If all formats failed, return an error
        return {"error": "Failed to create link - all payload formats were tried and failed"}
    except Exception as e:
        print(f"Error creating link: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating link: {str(e)}"}


@mcp.tool()
async def link_nodes(lab_id: str, node_id_a: str, node_id_b: str) -> Dict[str, Any]:
    """
    Create a link between two nodes by automatically selecting appropriate interfaces
    
    Args:
        lab_id: ID of the lab
        node_id_a: ID of the first node
        node_id_b: ID of the second node
    
    Returns:
        Dictionary with link ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Use the fixed implementation if available
        if 'connect_nodes' in globals():
            return await connect_nodes(cml_auth, lab_id, node_id_a, node_id_b)
            
        # Fall back to a simplified implementation if the fixed version isn't available
        # Get interfaces for both nodes with operational=true to get interface details
        interfaces_a_response = await cml_auth.request(
            "GET", 
            f"/api/v0/labs/{lab_id}/nodes/{node_id_a}/interfaces?operational=true"
        )
        interfaces_a = interfaces_a_response.json()
        
        interfaces_b_response = await cml_auth.request(
            "GET", 
            f"/api/v0/labs/{lab_id}/nodes/{node_id_b}/interfaces?operational=true"
        )
        interfaces_b = interfaces_b_response.json()
        
        # Ensure we have arrays of interfaces
        if not isinstance(interfaces_a, list):
            # If it returned UUIDs as strings, convert to list
            if isinstance(interfaces_a, str):
                interfaces_a = interfaces_a.split()
            # If it's a dictionary, get keys as list
            elif isinstance(interfaces_a, dict):
                interfaces_a = list(interfaces_a.keys())
        
        if not isinstance(interfaces_b, list):
            # If it returned UUIDs as strings, convert to list
            if isinstance(interfaces_b, str):
                interfaces_b = interfaces_b.split()
            # If it's a dictionary, get keys as list
            elif isinstance(interfaces_b, dict):
                interfaces_b = list(interfaces_b.keys())
        
        # Make sure we have interfaces to work with
        if not interfaces_a:
            return {"error": f"No interfaces found for node {node_id_a}"}
        
        if not interfaces_b:
            return {"error": f"No interfaces found for node {node_id_b}"}
        
        # Find first available physical interface for each node
        src_interface_id = None
        for interface_id in interfaces_a:
            # Get detailed info for this interface
            interface_detail = await cml_auth.request(
                "GET", 
                f"/api/v0/labs/{lab_id}/interfaces/{interface_id}?operational=true"
            )
            interface_data = interface_detail.json()
            
            # Check if physical and not connected
            if (interface_data.get("type") == "physical" and 
                interface_data.get("is_connected") == False):
                src_interface_id = interface_id
                break
        
        if not src_interface_id:
            return {"error": f"No available physical interface found for node {node_id_a}"}
        
        dst_interface_id = None
        for interface_id in interfaces_b:
            # Get detailed info for this interface
            interface_detail = await cml_auth.request(
                "GET", 
                f"/api/v0/labs/{lab_id}/interfaces/{interface_id}?operational=true"
            )
            interface_data = interface_detail.json()
            
            # Check if physical and not connected
            if (interface_data.get("type") == "physical" and 
                interface_data.get("is_connected") == False):
                dst_interface_id = interface_id
                break
        
        if not dst_interface_id:
            return {"error": f"No available physical interface found for node {node_id_b}"}
        
        # Create the link using the identified interfaces
        # Using the exact format from the API screenshots
        link_data = {
            "src_int": src_interface_id,
            "dst_int": dst_interface_id
        }
        
        print(f"Creating link with payload: {json.dumps(link_data, indent=2)}", file=sys.stderr)
        
        # Make the API request with explicit Content-Type header
        headers = {"Content-Type": "application/json"}
        response = await cml_auth.request(
            "POST",
            f"/api/v0/labs/{lab_id}/links",
            json=link_data,
            headers=headers
        )
        
        # Process the response
        result = response.json()
        print(f"Link creation response: {result}", file=sys.stderr)
        
        # Extract the link ID from the response
        link_id = result.get("id")
        if not link_id:
            return {"error": "Failed to create link, no link ID returned", "response": result}
        
        return {
            "link_id": link_id,
            "message": f"Created link between nodes {node_id_a} and {node_id_b}",
            "status": "success",
            "details": result
        }
    except Exception as e:
        print(f"Error linking nodes: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error linking nodes: {str(e)}"}


@mcp.tool()
async def delete_link(lab_id: str, link_id: str) -> str:
    """
    Delete a link from a lab
    
    Args:
        lab_id: ID of the lab
        link_id: ID of the link to delete
    
    Returns:
        Confirmation message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("DELETE", f"/api/v0/labs/{lab_id}/links/{link_id}")
        return f"Link {link_id} deleted successfully"
    except Exception as e:
        return f"Error deleting link: {str(e)}"


# Configuration Management Tools

@mcp.tool()
async def configure_node(lab_id: str, node_id: str, config: str) -> str:
    """
    Configure a node with the specified configuration
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node to configure
        config: Configuration text to apply
    
    Returns:
        Confirmation message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request(
            "PUT",
            f"/api/v0/labs/{lab_id}/nodes/{node_id}/config",
            content=config
        )
        
        return f"Configuration applied to node {node_id}"
    except Exception as e:
        return f"Error configuring node: {str(e)}"


@mcp.tool()
async def get_node_config(lab_id: str, node_id: str) -> str:
    """
    Get the current configuration of a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
    
    Returns:
        Node configuration text or error message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/nodes/{node_id}/config")
        config = response.text
        return config
    except Exception as e:
        return f"Error getting node configuration: {str(e)}"


# Lab Control Tools

@mcp.tool()
async def start_lab(lab_id: str) -> str:
    """
    Start the specified lab
    
    Args:
        lab_id: ID of the lab to start
    
    Returns:
        Confirmation message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("PUT", f"/api/v0/labs/{lab_id}/start")
        return f"Lab {lab_id} started successfully"
    except Exception as e:
        return f"Error starting lab: {str(e)}"


@mcp.tool()
async def wait_for_lab_nodes(lab_id: str, timeout: int = 60) -> str:
    """
    Wait for all nodes in a lab to reach the STARTED state
    
    Args:
        lab_id: ID of the lab
        timeout: Maximum time to wait in seconds (default: 60)
    
    Returns:
        Status message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        # Check if the lab is running
        lab_details = await get_lab_details(lab_id)
        if not isinstance(lab_details, dict) or lab_details.get("state") != "STARTED":
            return "Lab is not in STARTED state. Start the lab first."
        
        print(f"Waiting for nodes in lab {lab_id} to initialize...", file=sys.stderr)
        
        # Get nodes
        nodes = await get_lab_nodes(lab_id)
        if isinstance(nodes, str) and "Error" in nodes:
            return nodes
        
        start_time = asyncio.get_event_loop().time()
        all_ready = False
        
        while not all_ready and (asyncio.get_event_loop().time() - start_time) < timeout:
            all_ready = True
            
            for node_id, node in nodes.items():
                node_info = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/nodes/{node_id}")
                node_data = node_info.json()
                
                state = node_data.get("state", "UNKNOWN")
                print(f"Node {node_data.get('label', 'unknown')} state: {state}", file=sys.stderr)
                
                if state != "STARTED":
                    all_ready = False
            
            if not all_ready:
                await asyncio.sleep(5)  # Wait 5 seconds before checking again
        
        if all_ready:
            return "All nodes in the lab are initialized and ready"
        else:
            return f"Timeout reached ({timeout} seconds). Some nodes may not be fully initialized."
    except Exception as e:
        print(f"Error waiting for nodes: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error waiting for nodes: {str(e)}"


@mcp.tool()
async def stop_lab(lab_id: str) -> str:
    """
    Stop the specified lab
    
    Args:
        lab_id: ID of the lab to stop
    
    Returns:
        Confirmation message
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        response = await cml_auth.request("PUT", f"/api/v0/labs/{lab_id}/stop")
        return f"Lab {lab_id} stopped successfully"
    except Exception as e:
        return f"Error stopping lab: {str(e)}"


@mcp.tool()
async def get_lab_topology(lab_id: str, ctx: Context) -> str:
    """
    Get a detailed summary of the lab topology
    
    Args:
        lab_id: ID of the lab
    
    Returns:
        Formatted summary of the lab topology
    """
    if not cml_auth:
        return "Error: You must initialize the client first with initialize_client()"
    
    try:
        # Get lab details
        lab_details = await get_lab_details(lab_id)
        if isinstance(lab_details, dict) and "error" in lab_details:
            return lab_details["error"]
        
        # Get nodes
        nodes = await get_lab_nodes(lab_id)
        if isinstance(nodes, str) and "Error" in nodes:
            return nodes
        
        # Get links
        links = await get_lab_links(lab_id)
        if isinstance(links, str) and "Error" in links:
            return links
        
        # Create a topology summary
        result = f"Lab Topology: {lab_details.get('title', 'Untitled')}\n"
        result += f"State: {lab_details.get('state', 'unknown')}\n"
        result += f"Description: {lab_details.get('description', 'None')}\n\n"
        
        # Add nodes
        result += "Nodes:\n"
        for node_id, node in nodes.items():
            result += f"- {node.get('label', 'Unnamed')} (ID: {node_id})\n"
            result += f"  Type: {node.get('node_definition', 'unknown')}\n"
            result += f"  State: {node.get('state', 'unknown')}\n"
        
        # Add links
        result += "\nLinks:\n"
        for link_id, link in links.items():
            src_node_id = link.get('src_node')
            dst_node_id = link.get('dst_node')
            
            if src_node_id in nodes and dst_node_id in nodes:
                src_node = nodes[src_node_id].get('label', src_node_id)
                dst_node = nodes[dst_node_id].get('label', dst_node_id)
                result += (f"- Link {link_id}: {src_node} ({link.get('src_int', 'unknown')}) → "
                           f"{dst_node} ({link.get('dst_int', 'unknown')})\n")
            else:
                result += f"- Link {link_id}: {src_node_id}:{link.get('src_int')} → {dst_node_id}:{link.get('dst_int')}\n"
        
        return result
    except Exception as e:
        return f"Error getting lab topology: {str(e)}"


@mcp.tool()
async def create_router(
    lab_id: str,
    label: str,
    x: int = 0,
    y: int = 0
) -> Dict[str, Any]:
    """
    Create a router with the 'iosv' node definition
    
    Args:
        lab_id: ID of the lab
        label: Label for the new router
        x: X coordinate for node placement
        y: Y coordinate for node placement
    
    Returns:
        Dictionary with node ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    # Use the imported create_router function if available
    if 'create_node' in globals():
        return await create_node(cml_auth, lab_id, label, "iosv", x, y, True)
    
    # Otherwise use the add_node function with router node definition
    return await add_node(lab_id, label, "iosv", x, y, True)


@mcp.tool()
async def create_switch(
    lab_id: str,
    label: str,
    x: int = 0,
    y: int = 0
) -> Dict[str, Any]:
    """
    Create a switch with the 'iosvl2' node definition
    
    Args:
        lab_id: ID of the lab
        label: Label for the new switch
        x: X coordinate for node placement
        y: Y coordinate for node placement
    
    Returns:
        Dictionary with node ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    # Use the imported create_node function if available
    if 'create_node' in globals():
        return await create_node(cml_auth, lab_id, label, "iosvl2", x, y, True)
    
    # Otherwise use the add_node function with switch node definition
    return await add_node(lab_id, label, "iosvl2", x, y, True)


@mcp.tool()
async def create_switch_with_interfaces(
    lab_id: str,
    label: str,
    num_interfaces: int = 8,
    x: int = 0,
    y: int = 0
) -> Dict[str, Any]:
    """
    Create a switch with a specified number of interfaces
    
    Args:
        lab_id: ID of the lab
        label: Label for the new switch
        num_interfaces: Number of interfaces to create (default: 8)
        x: X coordinate for node placement
        y: Y coordinate for node placement
    
    Returns:
        Dictionary with node ID and confirmation message
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Use the imported create_node function if available
        if 'create_node' in globals():
            # When using create_node from cml_node_creation_fix, we need to include
            # parameters for interface configuration
            return await create_node(
                cml_auth, 
                lab_id, 
                label, 
                "iosvl2", 
                x, 
                y, 
                True,  # populate_interfaces
                ram=None,
                cpu_limit=None,
                parameters={"slot1": str(num_interfaces)}  # Configure the number of interfaces
            )
        
        # Otherwise use add_node directly
        node_data = {
            "label": label,
            "node_definition": "iosvl2",
            "x": x,
            "y": y,
            "parameters": {"slot1": str(num_interfaces)},  # Configure the number of interfaces
            "tags": [],
            "hide_links": False
        }
        
        # Add populate_interfaces as a query parameter
        endpoint = f"/api/v0/labs/{lab_id}/nodes?populate_interfaces=true"
        
        # Make the API request with explicit Content-Type header
        headers = {"Content-Type": "application/json"}
        response = await cml_auth.request(
            "POST",
            endpoint,
            json=node_data,
            headers=headers
        )
        
        # Process the response
        result = response.json()
        node_id = result.get("id")
        
        if not node_id:
            return {"error": "Failed to create switch, no node ID returned", "response": result}
        
        return {
            "node_id": node_id,
            "message": f"Added switch '{label}' with {num_interfaces} interfaces (ID: {node_id})",
            "status": "success",
            "details": result
        }
    except Exception as e:
        print(f"Error creating switch: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating switch: {str(e)}"}


@mcp.tool()
async def create_simple_network(
    title: str = "Simple Network",
    description: str = "A simple network with a router and switch"
) -> Dict[str, Any]:
    """
    Create a simple network lab with a router and switch
    
    Args:
        title: Title for the new lab
        description: Optional description for the lab
    
    Returns:
        Dictionary with lab details
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Create the lab
        lab_response = await cml_auth.request(
            "POST", 
            "/api/v0/labs",
            json={"title": title, "description": description}
        )
        
        lab_data = lab_response.json()
        lab_id = lab_data.get("id")
        
        if not lab_id:
            return {"error": "Failed to create lab, no lab ID returned"}
        
        # Create router and switch
        router_result = await create_router(lab_id, "Router1", 50, 50)
        if "error" in router_result:
            return {"error": f"Failed to create router: {router_result['error']}"}
        
        switch_result = await create_switch(lab_id, "Switch1", 50, 150)
        if "error" in switch_result:
            return {"error": f"Failed to create switch: {switch_result['error']}"}
        
        # Connect the devices
        link_result = await link_nodes(lab_id, router_result["node_id"], switch_result["node_id"])
        
        return {
            "lab_id": lab_id,
            "title": title,
            "router_id": router_result["node_id"],
            "switch_id": switch_result["node_id"],
            "link_status": "success" if "link_id" in link_result else "failed",
            "link_details": link_result
        }
    except Exception as e:
        print(f"Error creating simple network: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating simple network: {str(e)}"}


@mcp.tool()
async def generate_switch_stp_config(
    switch_name: str,
    stp_mode: str = "mst",  # Options: "mst", "rapid-pvst", "pvst"
    role: str = "root",  # Options: "root", "secondary", "normal"
    vlans: List[int] = [1, 10, 20, 30, 40],
    mst_instance_mapping: Optional[Dict[int, List[int]]] = None
) -> str:
    """
    Generate Spanning Tree Protocol configuration for a switch
    
    Args:
        switch_name: Name of the switch
        stp_mode: STP mode to configure ("mst", "rapid-pvst", or "pvst")
        role: Role of the switch ("root", "secondary", or "normal")
        vlans: List of VLANs to configure
        mst_instance_mapping: For MST mode, mapping of MST instances to VLANs
        
    Returns:
        Configuration text for the switch
    """
    
    config_lines = [
        f"! {switch_name} Configuration",
        "!",
        f"hostname {switch_name}",
        "!",
        "! VLANs Configuration"
    ]
    
    # Create VLANs
    for vlan_id in vlans:
        if vlan_id == 1:
            continue  # Skip default VLAN 1
        config_lines.extend([
            f"vlan {vlan_id}",
            f" name VLAN{vlan_id}",
            "!"
        ])
    
    # STP Mode Configuration
    config_lines.append("! Spanning-tree Configuration")
    
    if stp_mode == "mst":
        config_lines.append("spanning-tree mode mst")
        
        # Configure MST region and instances
        config_lines.extend([
            "!",
            "! Configure MST instance to VLAN mapping",
            "spanning-tree mst configuration",
            f" name {switch_name}-REGION",
            " revision 1"
        ])
        
        # Add instance to VLAN mappings
        if mst_instance_mapping:
            for instance, mapped_vlans in mst_instance_mapping.items():
                vlan_list = ",".join(map(str, mapped_vlans))
                config_lines.append(f" instance {instance} vlan {vlan_list}")
        else:
            # Default mapping if none provided
            config_lines.extend([
                " instance 1 vlan 10, 20",
                " instance 2 vlan 30, 40"
            ])
        
        # Configure priorities based on role
        if role == "root":
            config_lines.extend([
                "!",
                "! Set as MST root for instance 0 (CST)",
                "spanning-tree mst 0 priority 4096",
                "spanning-tree mst 1 priority 4096",
                "spanning-tree mst 2 priority 4096"
            ])
        elif role == "secondary":
            config_lines.extend([
                "!",
                "! Set as MST secondary root",
                "spanning-tree mst 0 priority 8192",
                "spanning-tree mst 1 priority 8192",
                "spanning-tree mst 2 priority 8192"
            ])
        else:
            # Normal role with higher priority
            config_lines.extend([
                "!",
                "! Normal switch (not root)",
                "spanning-tree mst 0 priority 32768",
                "spanning-tree mst 1 priority 32768",
                "spanning-tree mst 2 priority 32768"
            ])
    
    elif stp_mode == "rapid-pvst":
        config_lines.append("spanning-tree mode rapid-pvst")
        
        # Configure priorities per VLAN based on role
        if role == "root":
            for vlan_id in vlans:
                config_lines.append(f"spanning-tree vlan {vlan_id} priority 4096")
        elif role == "secondary":
            for vlan_id in vlans:
                config_lines.append(f"spanning-tree vlan {vlan_id} priority 8192")
        else:
            # Normal role with higher priority for specific VLANs
            for vlan_id in vlans:
                config_lines.append(f"spanning-tree vlan {vlan_id} priority 32768")
    
    else:  # PVST (default)
        config_lines.append("spanning-tree mode pvst")
        
        # Configure priorities per VLAN based on role
        if role == "root":
            for vlan_id in vlans:
                config_lines.append(f"spanning-tree vlan {vlan_id} priority 4096")
        elif role == "secondary":
            for vlan_id in vlans:
                config_lines.append(f"spanning-tree vlan {vlan_id} priority 8192")
        else:
            # Normal role with higher priority
            for vlan_id in vlans:
                config_lines.append(f"spanning-tree vlan {vlan_id} priority 32768")
    
    # Common STP settings regardless of mode
    config_lines.extend([
        "!",
        "! Common STP features",
        "spanning-tree extend system-id",
        "spanning-tree portfast edge default",
        "spanning-tree portfast bpduguard default"
    ])
    
    # Interface configuration
    config_lines.extend([
        "!",
        "! Configure interfaces",
        "!",
        "interface range GigabitEthernet0/0 - 7",
        " switchport trunk encapsulation dot1q",
        " switchport mode trunk",
        " switchport trunk allowed vlan all",
        " no shutdown"
    ])
    
    # Management VLAN interface 
    config_lines.extend([
        "!",
        "! Management interface",
        "interface Vlan1",
        f" ip address 10.0.0.{vlans[0]} 255.255.255.0",
        " no shutdown",
        "!",
        "! End of configuration"
    ])
    
    return "\n".join(config_lines)


@mcp.tool()
async def create_stp_lab(
    title: str = "STP Test Lab",
    description: str = "Spanning Tree Protocol test lab with multiple STP versions",
    num_switches: int = 6,
    interfaces_per_switch: int = 8
) -> Dict[str, Any]:
    """
    Create a comprehensive Spanning Tree Protocol test lab
    
    Args:
        title: Title for the lab
        description: Description for the lab
        num_switches: Number of switches to create (default: 6)
        interfaces_per_switch: Number of interfaces per switch (default: 8)
    
    Returns:
        Dictionary with lab details and node IDs
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Create the lab
        lab_response = await create_lab(title, description)
        if "error" in lab_response:
            return lab_response
        
        lab_id = lab_response["lab_id"]
        
        # Create the switches with enhanced interface count
        switches = []
        
        # Core switches (top row)
        sw1_result = await create_switch_with_interfaces(
            lab_id, 
            "SW1-Core", 
            interfaces_per_switch, 
            x=100, 
            y=100
        )
        switches.append({"name": "SW1-Core", "id": sw1_result["node_id"], "layer": "core"})
        
        sw2_result = await create_switch_with_interfaces(
            lab_id, 
            "SW2-Core", 
            interfaces_per_switch, 
            x=300, 
            y=100
        )
        switches.append({"name": "SW2-Core", "id": sw2_result["node_id"], "layer": "core"})
        
        # Distribution switches (middle row) if we have more than 2 switches
        if num_switches > 2:
            sw3_result = await create_switch_with_interfaces(
                lab_id, 
                "SW3-Distribution", 
                interfaces_per_switch, 
                x=50, 
                y=200
            )
            switches.append({"name": "SW3-Distribution", "id": sw3_result["node_id"], "layer": "distribution"})
            
            sw4_result = await create_switch_with_interfaces(
                lab_id, 
                "SW4-Distribution", 
                interfaces_per_switch, 
                x=350, 
                y=200
            )
            switches.append({"name": "SW4-Distribution", "id": sw4_result["node_id"], "layer": "distribution"})
        
        # Access switches (bottom row) if we have more than 4 switches
        if num_switches > 4:
            sw5_result = await create_switch_with_interfaces(
                lab_id, 
                "SW5-Access", 
                interfaces_per_switch, 
                x=150, 
                y=300
            )
            switches.append({"name": "SW5-Access", "id": sw5_result["node_id"], "layer": "access"})
            
            sw6_result = await create_switch_with_interfaces(
                lab_id, 
                "SW6-Access", 
                interfaces_per_switch, 
                x=250, 
                y=300
            )
            switches.append({"name": "SW6-Access", "id": sw6_result["node_id"], "layer": "access"})
        
        # Create links between switches to form a redundant topology
        links = []
        
        # Connect core switches
        if len(switches) >= 2:
            link1 = await link_nodes(lab_id, switches[0]["id"], switches[1]["id"])
            links.append({"from": switches[0]["name"], "to": switches[1]["name"], "id": link1.get("link_id")})
        
        # Connect distribution to core (if we have distribution switches)
        if len(switches) >= 4:
            # Connect SW1-Core to both distribution switches
            link2 = await link_nodes(lab_id, switches[0]["id"], switches[2]["id"])
            links.append({"from": switches[0]["name"], "to": switches[2]["name"], "id": link2.get("link_id")})
            
            link3 = await link_nodes(lab_id, switches[0]["id"], switches[3]["id"])
            links.append({"from": switches[0]["name"], "to": switches[3]["name"], "id": link3.get("link_id")})
            
            # Connect SW2-Core to both distribution switches
            link4 = await link_nodes(lab_id, switches[1]["id"], switches[2]["id"])
            links.append({"from": switches[1]["name"], "to": switches[2]["name"], "id": link4.get("link_id")})
            
            link5 = await link_nodes(lab_id, switches[1]["id"], switches[3]["id"])
            links.append({"from": switches[1]["name"], "to": switches[3]["name"], "id": link5.get("link_id")})
            
            # Connect distribution switches to each other
            link6 = await link_nodes(lab_id, switches[2]["id"], switches[3]["id"])
            links.append({"from": switches[2]["name"], "to": switches[3]["name"], "id": link6.get("link_id")})
        
        # Connect access switches (if we have them)
        if len(switches) >= 6:
            # Connect distribution to access
            link7 = await link_nodes(lab_id, switches[2]["id"], switches[4]["id"])
            links.append({"from": switches[2]["name"], "to": switches[4]["name"], "id": link7.get("link_id")})
            
            link8 = await link_nodes(lab_id, switches[2]["id"], switches[5]["id"])
            links.append({"from": switches[2]["name"], "to": switches[5]["name"], "id": link8.get("link_id")})
            
            link9 = await link_nodes(lab_id, switches[3]["id"], switches[4]["id"])
            links.append({"from": switches[3]["name"], "to": switches[4]["name"], "id": link9.get("link_id")})
            
            link10 = await link_nodes(lab_id, switches[3]["id"], switches[5]["id"])
            links.append({"from": switches[3]["name"], "to": switches[5]["name"], "id": link10.get("link_id")})
            
            # Connect access switches to each other
            link11 = await link_nodes(lab_id, switches[4]["id"], switches[5]["id"])
            links.append({"from": switches[4]["name"], "to": switches[5]["name"], "id": link11.get("link_id")})
        
        return {
            "lab_id": lab_id,
            "title": title,
            "switches": switches,
            "links": links,
            "status": "success",
            "message": f"Created STP lab with {len(switches)} switches, each having {interfaces_per_switch} interfaces"
        }
    except Exception as e:
        print(f"Error creating STP lab: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating STP lab: {str(e)}"}


@mcp.tool()
async def create_ospf_lab(title: str = "OSPF Network Lab", description: str = "Two routers connected via OSPF") -> Dict[str, Any]:
    """
    Create a complete OSPF lab with two routers properly configured
    
    Args:
        title: Title for the lab (default: "OSPF Network Lab")
        description: Lab description (default: "Two routers connected via OSPF")
    
    Returns:
        Dictionary with lab ID, router IDs, and access instructions
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    try:
        # Create the lab
        lab_response = await cml_auth.request(
            "POST", 
            "/api/v0/labs",
            json={"title": title, "description": description}
        )
        
        lab_data = lab_response.json()
        lab_id = lab_data.get("id")
        
        if not lab_id:
            return {"error": "Failed to create lab, no lab ID returned"}
        
        # Create two routers
        router1_result = await create_router(lab_id, "Router1", 50, 50)
        if "error" in router1_result:
            return {"error": f"Failed to create Router1: {router1_result['error']}"}
        
        router2_result = await create_router(lab_id, "Router2", 200, 50)
        if "error" in router2_result:
            return {"error": f"Failed to create Router2: {router2_result['error']}"}
        
        # Connect the routers
        link_result = await link_nodes(lab_id, router1_result["node_id"], router2_result["node_id"])
        if "error" in link_result:
            return {"error": f"Failed to link routers: {link_result['error']}"}
        
        # Configure Router1 with OSPF
        router1_config = """
! Basic Router1 Configuration with OSPF
!
hostname Router1
!
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
"""
        
        await configure_node(lab_id, router1_result["node_id"], router1_config)
        
        # Configure Router2 with OSPF
        router2_config = """
! Basic Router2 Configuration with OSPF
!
hostname Router2
!
interface GigabitEthernet0/0
 ip address 10.0.0.2 255.255.255.0
 no shutdown
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
"""
        
        await configure_node(lab_id, router2_result["node_id"], router2_config)
        
        return {
            "lab_id": lab_id,
            "title": title,
            "router1_id": router1_result["node_id"],
            "router2_id": router2_result["node_id"],
            "link_id": link_result.get("link_id"),
            "status": "success",
            "instructions": "Lab created with OSPF routing between Router1 (10.0.0.1) and Router2 (10.0.0.2). Start the lab to test connectivity."
        }
    except Exception as e:
        print(f"Error creating OSPF lab: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error creating OSPF lab: {str(e)}"}


# Configuration Templates

@mcp.resource("cml://templates/basic-router")
def basic_router_template() -> str:
    """Basic router configuration template"""
    return """
! Basic Router Configuration Template
!
hostname {{hostname}}
!
interface GigabitEthernet0/0
 ip address {{interface_ip}} {{interface_mask}}
 no shutdown
!
"""


@mcp.resource("cml://templates/basic-switch")
def basic_switch_template() -> str:
    """Basic switch configuration template"""
    return """
! Basic Switch Configuration Template
!
hostname {{hostname}}
!
vlan {{vlan_id}}
 name {{vlan_name}}
!
"""


@mcp.resource("cml://templates/ospf-config")
def ospf_template() -> str:
    """OSPF configuration template"""
    return """
! OSPF Configuration Template
!
router ospf {{process_id}}
 network {{network_address}} {{wildcard_mask}} area {{area_id}}
!
"""


@mcp.prompt("cml-describe-topology")
def describe_topology_prompt(lab_id: str) -> str:
    """Prompt for describing a lab topology"""
    return f"""Please analyze the following network topology from Cisco Modeling Labs (Lab ID: {lab_id}).
Describe the network elements, their connections, and the overall architecture.
Suggest any improvements or potential issues with the design.
"""


@mcp.prompt("cml-create-lab")
def create_lab_prompt() -> str:
    """Prompt for creating a new lab"""
    return """I need you to help me create a network lab in Cisco Modeling Labs.

Please design a lab that meets the following requirements:
{{requirements}}

For each device, specify:
1. Device type (router, switch, etc.)
2. Basic configuration
3. Network connections

After designing the topology, you'll need to:
1. Create the lab in CML
2. Add the nodes
3. Create the links between nodes
4. Configure each node
5. Start the lab

Please walk through this process step by step.
"""


# Troubleshooting Tools - Console Access

@mcp.tool()
async def open_console_session(lab_id: str, node_id: str) -> Dict[str, Any]:
    """
    Open a console session to a node in the lab
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node to access
    
    Returns:
        Dictionary with session information
    """
    if not cml_auth:
        return {"error": "You must initialize the client first with initialize_client()"}
    
    if not console_manager:
        return {"error": "Troubleshooting tools not initialized. Check import of console_access module."}
    
    try:
        result = await console_manager.open_session(lab_id, node_id)
        if isinstance(result, str) and result.startswith("Error"):
            return {"error": result}
        
        return {
            "status": "success",
            "message": f"Console session opened for node {node_id} in lab {lab_id}",
            "details": result
        }
    except Exception as e:
        print(f"Error opening console session: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error opening console session: {str(e)}"}


@mcp.tool()
async def close_console_session(lab_id: str, node_id: str) -> Dict[str, Any]:
    """
    Close a console session to a node in the lab
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node with an open session
    
    Returns:
        Dictionary with operation status
    """
    if not console_manager:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await console_manager.close_session(lab_id, node_id)
        if isinstance(result, str) and result.startswith("Error"):
            return {"error": result}
        
        return {
            "status": "success",
            "message": f"Console session closed for node {node_id} in lab {lab_id}"
        }
    except Exception as e:
        print(f"Error closing console session: {str(e)}", file=sys.stderr)
        return {"error": f"Error closing console session: {str(e)}"}


@mcp.tool()
async def send_console_command(lab_id: str, node_id: str, command: str) -> Dict[str, Any]:
    """
    Send a command to a node console
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        command: Command to send
    
    Returns:
        Dictionary with command output
    """
    if not console_manager:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        # Get console session
        session = await console_manager.get_session(lab_id, node_id)
        if isinstance(session, str):
            # If error message is returned, try to open a new session
            await console_manager.open_session(lab_id, node_id)
            session = await console_manager.get_session(lab_id, node_id)
            if isinstance(session, str):
                return {"error": f"Could not open console session: {session}"}
        
        # Send command
        output = await session.send_command(command)
        
        # Try to parse structured output
        try:
            parsed = await session.parse_command_output(command, output)
            return {
                "status": "success",
                "command": command,
                "raw_output": output,
                "structured": parsed if parsed else None
            }
        except Exception as parse_error:
            # If parsing fails, just return the raw output
            return {
                "status": "success",
                "command": command,
                "raw_output": output,
                "parse_error": str(parse_error)
            }
    except Exception as e:
        print(f"Error sending console command: {str(e)}", file=sys.stderr)
        return {"error": f"Error sending console command: {str(e)}"}


@mcp.tool()
async def send_multiple_commands(lab_id: str, node_id: str, commands: List[str]) -> Dict[str, Any]:
    """
    Send multiple commands to a node console
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        commands: List of commands to send
    
    Returns:
        Dictionary with command outputs
    """
    if not console_manager:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        # Get console session
        session = await console_manager.get_session(lab_id, node_id)
        if isinstance(session, str):
            # If error message is returned, try to open a new session
            await console_manager.open_session(lab_id, node_id)
            session = await console_manager.get_session(lab_id, node_id)
            if isinstance(session, str):
                return {"error": f"Could not open console session: {session}"}
        
        # Send commands
        results = await session.send_commands(commands)
        
        # Process results
        processed_results = {}
        for cmd, output in results.items():
            try:
                parsed = await session.parse_command_output(cmd, output)
                processed_results[cmd] = {
                    "raw_output": output,
                    "structured": parsed if parsed else None
                }
            except Exception as parse_error:
                processed_results[cmd] = {
                    "raw_output": output,
                    "parse_error": str(parse_error)
                }
        
        return {
            "status": "success",
            "results": processed_results
        }
    except Exception as e:
        print(f"Error sending multiple commands: {str(e)}", file=sys.stderr)
        return {"error": f"Error sending multiple commands: {str(e)}"}


# Troubleshooting Tools - Diagnostics

@mcp.tool()
async def test_connectivity(lab_id: str, source_node_id: str, destination_ip: str, count: int = 5) -> Dict[str, Any]:
    """
    Test connectivity from a source node to a destination IP
    
    Args:
        lab_id: ID of the lab
        source_node_id: ID of the source node
        destination_ip: Destination IP address to ping
        count: Number of ping packets to send (default: 5)
    
    Returns:
        Dictionary with ping test results
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.ping_test(lab_id, source_node_id, destination_ip, count)
        return result
    except Exception as e:
        print(f"Error testing connectivity: {str(e)}", file=sys.stderr)
        return {"error": f"Error testing connectivity: {str(e)}"}


@mcp.tool()
async def trace_route(lab_id: str, source_node_id: str, destination_ip: str) -> Dict[str, Any]:
    """
    Perform a traceroute from a source node to a destination IP
    
    Args:
        lab_id: ID of the lab
        source_node_id: ID of the source node
        destination_ip: Destination IP address to trace
    
    Returns:
        Dictionary with traceroute results
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.traceroute_test(lab_id, source_node_id, destination_ip)
        return result
    except Exception as e:
        print(f"Error running traceroute: {str(e)}", file=sys.stderr)
        return {"error": f"Error running traceroute: {str(e)}"}


@mcp.tool()
async def check_interfaces(lab_id: str, node_id: str, interface_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Check interface status on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        interface_name: Optional specific interface to check (check all if not specified)
    
    Returns:
        Dictionary with interface status
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.get_interface_status(lab_id, node_id, interface_name)
        return result
    except Exception as e:
        print(f"Error checking interfaces: {str(e)}", file=sys.stderr)
        return {"error": f"Error checking interfaces: {str(e)}"}


@mcp.tool()
async def check_routing(lab_id: str, node_id: str, destination: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze routing table on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        destination: Optional specific destination to check routes for
    
    Returns:
        Dictionary with routing table analysis
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.analyze_routing_table(lab_id, node_id, destination)
        return result
    except Exception as e:
        print(f"Error checking routing: {str(e)}", file=sys.stderr)
        return {"error": f"Error checking routing: {str(e)}"}


@mcp.tool()
async def check_ospf(lab_id: str, node_id: str) -> Dict[str, Any]:
    """
    Verify OSPF state on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
    
    Returns:
        Dictionary with OSPF state information
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.verify_ospf_state(lab_id, node_id)
        return result
    except Exception as e:
        print(f"Error checking OSPF: {str(e)}", file=sys.stderr)
        return {"error": f"Error checking OSPF: {str(e)}"}


@mcp.tool()
async def check_bgp(lab_id: str, node_id: str) -> Dict[str, Any]:
    """
    Verify BGP state on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
    
    Returns:
        Dictionary with BGP state information
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.verify_bgp_state(lab_id, node_id)
        return result
    except Exception as e:
        print(f"Error checking BGP: {str(e)}", file=sys.stderr)
        return {"error": f"Error checking BGP: {str(e)}"}


@mcp.tool()
async def check_spanning_tree(lab_id: str, node_id: str, vlan: Optional[int] = None) -> Dict[str, Any]:
    """
    Verify spanning tree state on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        vlan: Optional specific VLAN to check spanning tree for
    
    Returns:
        Dictionary with spanning tree state information
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.verify_spanning_tree(lab_id, node_id, vlan)
        return result
    except Exception as e:
        print(f"Error checking spanning tree: {str(e)}", file=sys.stderr)
        return {"error": f"Error checking spanning tree: {str(e)}"}


@mcp.tool()
async def validate_config(lab_id: str, node_id: str, config_section: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate configuration on a node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node
        config_section: Optional specific section of config to validate (e.g., "ospf", "interfaces", "bgp")
    
    Returns:
        Dictionary with configuration validation results
    """
    if not diagnostics:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        result = await diagnostics.validate_configuration(lab_id, node_id, config_section)
        return result
    except Exception as e:
        print(f"Error validating configuration: {str(e)}", file=sys.stderr)
        return {"error": f"Error validating configuration: {str(e)}"}


# Troubleshooting Tools - Structured Troubleshooting

@mcp.tool()
async def troubleshoot_node(lab_id: str, node_id: str, issue_area: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a structured troubleshooting process on a specific node
    
    Args:
        lab_id: ID of the lab
        node_id: ID of the node to troubleshoot
        issue_area: Optional specific area to focus on (connectivity, routing, ospf, bgp, interfaces, etc.)
    
    Returns:
        Dictionary with troubleshooting report
    """
    if not troubleshooting:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        report = await troubleshooting.begin_troubleshooting(lab_id, node_id, issue_area)
        
        # If a specific issue area was provided, run focused diagnostics
        if issue_area:
            issue_area = issue_area.lower()
            if issue_area == "connectivity":
                await troubleshooting.diagnose_connectivity_issues(lab_id, node_id)
            elif issue_area == "interfaces":
                await troubleshooting.diagnose_interface_issues(lab_id, node_id)
            elif issue_area == "routing":
                await troubleshooting.diagnose_routing_issues(lab_id, node_id)
            elif issue_area == "ospf":
                await troubleshooting.diagnose_ospf_issues(lab_id, node_id)
            elif issue_area == "bgp":
                await troubleshooting.diagnose_bgp_issues(lab_id, node_id)
            elif issue_area == "spanning-tree":
                await troubleshooting.diagnose_spanning_tree_issues(lab_id, node_id)
            elif issue_area == "configuration":
                await troubleshooting.diagnose_configuration_issues(lab_id, node_id)
            else:
                # If unknown area, run comprehensive diagnostics
                await troubleshooting.run_comprehensive_diagnostics(lab_id, node_id)
        else:
            # If no specific area, run comprehensive diagnostics
            await troubleshooting.run_comprehensive_diagnostics(lab_id, node_id)
        
        return troubleshooting.report
    except Exception as e:
        print(f"Error troubleshooting node: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error troubleshooting node: {str(e)}"}


@mcp.tool()
async def troubleshoot_lab(
    lab_id: str, 
    nodes: Optional[List[str]] = None,
    issue_area: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run a structured troubleshooting process on an entire lab
    
    Args:
        lab_id: ID of the lab to troubleshoot
        nodes: Optional list of specific node IDs to focus on (all nodes if not specified)
        issue_area: Optional specific area to focus on (connectivity, routing, ospf, bgp, etc.)
    
    Returns:
        Dictionary with troubleshooting report
    """
    if not troubleshooting or not cml_auth:
        return {"error": "Troubleshooting tools not initialized or CML client not authenticated"}
    
    try:
        # Get all nodes in the lab if not specified
        if not nodes:
            response = await cml_auth.request("GET", f"/api/v0/labs/{lab_id}/nodes")
            lab_nodes = response.json()
            nodes = list(lab_nodes.keys())
            
        if not nodes:
            return {"error": "No nodes found in the lab"}
            
        # Start lab-wide troubleshooting
        report = await troubleshooting.begin_troubleshooting(lab_id)
        
        # Iterate through each node
        for node_id in nodes:
            try:
                print(f"Troubleshooting node {node_id}", file=sys.stderr)
                # Run targeted or comprehensive diagnostics for each node
                if issue_area:
                    issue_area = issue_area.lower()
                    if issue_area == "connectivity":
                        await troubleshooting.diagnose_connectivity_issues(lab_id, node_id)
                    elif issue_area == "interfaces":
                        await troubleshooting.diagnose_interface_issues(lab_id, node_id)
                    elif issue_area == "routing":
                        await troubleshooting.diagnose_routing_issues(lab_id, node_id)
                    elif issue_area == "ospf":
                        await troubleshooting.diagnose_ospf_issues(lab_id, node_id)
                    elif issue_area == "bgp":
                        await troubleshooting.diagnose_bgp_issues(lab_id, node_id)
                    elif issue_area == "spanning-tree":
                        await troubleshooting.diagnose_spanning_tree_issues(lab_id, node_id)
                    elif issue_area == "configuration":
                        await troubleshooting.diagnose_configuration_issues(lab_id, node_id)
                    else:
                        await troubleshooting.run_comprehensive_diagnostics(lab_id, node_id)
                else:
                    await troubleshooting.run_comprehensive_diagnostics(lab_id, node_id)
            except Exception as node_error:
                print(f"Error troubleshooting node {node_id}: {str(node_error)}", file=sys.stderr)
                troubleshooting.add_diagnostic_step(
                    f"Troubleshooting node {node_id}",
                    {"status": "error", "error": str(node_error)}
                )
                
        return troubleshooting.report
    except Exception as e:
        print(f"Error troubleshooting lab: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": f"Error troubleshooting lab: {str(e)}"}


@mcp.tool()
async def get_diagnostic_recommendations(lab_id: str, report_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get recommendations based on a troubleshooting report
    
    Args:
        lab_id: ID of the lab
        report_data: Optional report data from a previous troubleshooting run
    
    Returns:
        Dictionary with recommendations
    """
    if not troubleshooting:
        return {"error": "Troubleshooting tools not initialized"}
    
    try:
        if report_data:
            # Reuse existing report data
            troubleshooting.report = report_data
        else:
            # If no report data provided, check if there's a current report for this lab
            if troubleshooting.report.get("lab_id") != lab_id:
                return {"error": "No troubleshooting report available for this lab. Run troubleshoot_node or troubleshoot_lab first."}
        
        # Extract and format recommendations
        recommendations = troubleshooting.report.get("recommendations", [])
        problems = troubleshooting.report.get("problems_found", [])
        actions = troubleshooting.report.get("actions_taken", [])
        
        # Add a timestamp to the recommendations
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            "timestamp": timestamp,
            "lab_id": lab_id,
            "summary": f"Found {len(problems)} problems with {len(recommendations)} recommendations",
            "problems": problems,
            "recommendations": recommendations,
            "actions_taken": actions
        }
    except Exception as e:
        print(f"Error getting diagnostic recommendations: {str(e)}", file=sys.stderr)
        return {"error": f"Error getting diagnostic recommendations: {str(e)}"}


# Main entry point
if __name__ == "__main__":
    mcp.run()
