# coding: utf-8 # [Source: 811]
# Shortcut to launch DRIM AI's MCP server. [Source: 811]
import sys
from pathlib import Path

project_root_run_mcp_server = Path(__file__).resolve().parent
if str(project_root_run_mcp_server) not in sys.path:
    sys.path.insert(0, str(project_root_run_mcp_server))

from app.mcp.server import MCPServer as DrimMCPServer, parse_cli_args as parse_mcp_server_cli_args # [Source: 812] (Aliased parser)
from app.logger import define_log_level, logger # Use DRIM AI logger

def main_mcp_server(): # Wrapped in a main function
    # Define log level for this specific server runner
    # The MCPServer class itself also sets up basic logging if run directly,
    # but this ensures DRIM AI's logger is configured.
    define_log_level(print_level="INFO", logfile_level="DEBUG", name="DRIM_AI_MCPServer_Instance")
    
    server_cli_args = parse_mcp_server_cli_args() # [Source: 812]
    
    logger.info("--- Starting DRIM AI MCP Server (via run_mcp_server.py script) ---")
    server_name_arg = getattr(server_cli_args, 'server_name', "drim_ai_mcp_server_default") # Get server_name if arg exists
    transport_arg = server_cli_args.transport

    logger.info(f"DRIM AI MCP Server: Transport: {transport_arg}, Server Name: {server_name_arg}")

    # Create and run DRIM AI's MCP server instance
    drim_server = DrimMCPServer(server_name=server_name_arg) # [Source: 812]
    drim_server.run(transport=transport_arg) # [Source: 812]
    
    logger.info("--- DRIM AI MCP Server (via run_mcp_server.py script) has shut down ---")

if __name__ == "__main__": # [Source: 812]
    main_mcp_server()