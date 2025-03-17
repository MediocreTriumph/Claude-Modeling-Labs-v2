# Claude Modeling Labs

A proof of concept tool for automating Cisco Modeling Labs (CML) using Claude AI.

## ⚠️ Warning: Proof of Concept

**This project is currently a proof of concept and is still under development.** 

Features may be incomplete, contain bugs, or change significantly between versions. Use at your own risk in non-production environments only.

## Overview

Claude Modeling Labs provides a set of tools that enable Claude AI to interact with Cisco Modeling Labs (CML) via its API. This allows Claude to create, configure, and manage network simulations in response to natural language requests.

## New in This Version

- **Modular Architecture**: Code has been reorganized into logical modules for better maintainability
- **Console Tools**: New functions for interacting with device consoles
- **Diagnostic Tools**: Enhanced troubleshooting capabilities for verifying connectivity and protocols
- **Improved Error Handling**: More consistent error reporting and recovery

## Toolkit Modules

- **Authentication**: Client setup and API access management
- **Lab Management**: Create, list, start, and stop labs
- **Node Management**: Add and configure devices
- **Interface Management**: Manage device interfaces
- **Link Management**: Create connections between devices
- **Configuration Management**: Deploy and retrieve device configs
- **Console Tools**: Interact with device command lines
- **Diagnostics**: Troubleshoot labs and verify connectivity
- **Lab Templates**: Pre-built lab scenarios

## Installation

### Prerequisites
- Python 3.8 or higher
- Cisco Modeling Labs (CML) 2.0 or higher
- Access to Claude AI or Claude function calling

### Installation on macOS

1. **Install Python (if not already installed)**:
   ```bash
   brew install python
   ```

2. **Clone the repository**:
   ```bash
   git clone https://github.com/MediocreTriumph/Claude-Modeling-Labs-v2.git
   cd Claude-Modeling-Labs
   ```

3. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Install the MCP server**:
   ```bash
   fastmcp install cml_mcp.py --name "Claude Modeling Labs"
   ```

### Installation on Windows

1. **Install Python (if not already installed)**:
   - Download and install from [python.org](https://www.python.org/downloads/windows/)
   - Ensure "Add Python to PATH" is checked during installation

2. **Clone the repository**:
   ```cmd
   git clone https://github.com/MediocreTriumph/Claude-Modeling-Labs-v2.git
   cd Claude-Modeling-Labs
   ```

3. **Set up a virtual environment**:
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

4. **Install dependencies**:
   ```cmd
   pip install -r requirements.txt
   ```

5. **Install the MCP server**:
   ```cmd
   fastmcp install cml_mcp.py --name "Claude Modeling Labs"
   ```

## How It Works

This tool uses the FastMCP (Model Context Protocol) library to define a set of tools that Claude can use to interact with CML. These tools abstract the underlying API calls to provide a simpler interface for Claude to work with.

### Basic Usage Flow

1. **Connect to CML**: Initialize the connection to your CML server
2. **Create or Access Labs**: Create new labs or work with existing ones
3. **Add Network Devices**: Add routers, switches, and other devices to your lab
4. **Connect Devices**: Create links between device interfaces
5. **Configure Devices**: Apply configurations to devices
6. **Start the Lab**: Start the lab and wait for devices to boot
7. **Console Access**: Connect to device consoles and run commands
8. **Troubleshoot**: Use diagnostic tools to verify connectivity and configurations

## Example Use Cases

- Creating complex network topologies from natural language descriptions
- Automating OSPF, EIGRP, BGP, and STP lab creation for learning
- Troubleshooting network connectivity issues
- Deploying and testing network configurations
- Validating network designs and protocols

## Current Status

This project is still in early development. It successfully demonstrates the concept of allowing Claude to create and manage CML labs, but many features are still being refined.

## Limitations

- Error handling is basic
- Documentation is limited
- Not all CML features are exposed
- Security considerations are not fully addressed

## Next Steps

- Improve error handling and reporting
- Add more templates for common network scenarios
- Add support for more CML features
- Improve documentation
- Add proper authentication mechanisms

## Contributing

As this is a proof of concept, contributions are welcome but the project structure may change significantly. Please open an issue first to discuss any proposed changes.

## License

This project is available under the MIT License.
