import logging # [Source: 223]
import sys # [Source: 223]

# Basic logging setup for MCP server standalone execution, if not already configured by DRIM AI's main logger
# This ensures logs are visible if this script is run directly.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - DRIM_AI_MCP_SERVER - %(levelname)s - %(message)s", # Added prefix
    handlers=[logging.StreamHandler(sys.stderr)] # [Source: 223]
)

import argparse # [Source: 223]
import asyncio # [Source: 223]
import atexit # [Source: 223]
import json # [Source: 223]
from inspect import Parameter, Signature # [Source: 223]
from typing import Any, Dict, Optional, Callable # Added Callable

from mcp.server.fastmcp import FastMCP # type: ignore # [Source: 223] (Assuming mcp library is installed)

from app.logger import logger as drim_ai_logger # Use DRIM AI's main logger [Source: 223]
from app.tool.base import BaseTool # DRIM AI's BaseTool [Source: 223]
# Import DRIM AI's versions of the tools
from app.tool.bash import Bash # [Source: 223]
from app.tool.browser_use_tool import BrowserUseTool # [Source: 223]
from app.tool.str_replace_editor import StrReplaceEditor # [Source: 223]
from app.tool.terminate import Terminate # [Source: 223]
# Potentially add other DRIM AI tools to expose via MCP server

class MCPServer: # [Source: 223]
    """DRIM AI MCP Server implementation with tool registration and management."""

    def __init__(self, server_name: str = "drim_ai_mcp_server"): # [Source: 223] Renamed default name
        self.server = FastMCP(name=server_name) # [Source: 223]
        self.tools_to_register: Dict[str, BaseTool] = {} # Stores tool instances [Source: 223]
        self._registered_tool_methods: Dict[str, Callable] = {} # To keep track of async wrappers

        # Initialize standard DRIM AI tools to be exposed by this server
        # Ensure these are DRIM AI's adapted tools
        self._add_tool_for_registration(Bash()) # [Source: 224]
        self._add_tool_for_registration(BrowserUseTool()) # [Source: 224]
        self._add_tool_for_registration(StrReplaceEditor()) # [Source: 224]
        self._add_tool_for_registration(Terminate()) # [Source: 224]
        drim_ai_logger.info(f"DRIM AI MCPServer: Initialized with tools: {list(self.tools_to_register.keys())}")

    def _add_tool_for_registration(self, tool_instance: BaseTool):
        """Adds a tool instance to the list for registration."""
        if tool_instance.name in self.tools_to_register:
            drim_ai_logger.warning(f"DRIM AI MCPServer: Tool '{tool_instance.name}' already added for registration. Overwriting.")
        self.tools_to_register[tool_instance.name] = tool_instance


    def register_tool_with_mcp(self, tool_instance: BaseTool) -> None: # [Source: 224] Renamed from register_tool
        """
        Registers a DRIM AI BaseTool instance with the FastMCP server.
        It creates an async wrapper for the tool's execute method.
        """
        # Use the tool's actual name as defined in its instance for MCP registration
        mcp_tool_name = tool_instance.name # [Source: 224]
        
        # Get the parameter schema from the DRIM AI tool instance
        # The tool_instance.to_param() returns a dict: {"name": ..., "description": ..., "parameters": SCHEMA_OBJ}
        # FastMCP expects function, description, and parameters (schema) separately.
        tool_param_definition = tool_instance.to_param() # [Source: 224]
        tool_description = tool_param_definition.get("description", tool_instance.description)
        tool_parameters_schema = tool_param_definition.get("parameters") # This is the JSON schema object [Source: 225]

        # Define the async wrapper function to be registered with FastMCP
        async def mcp_tool_method_wrapper(**kwargs: Any) -> Any: # [Source: 224]
            drim_ai_logger.info(f"DRIM AI MCPServer: Executing tool '{mcp_tool_name}' via MCP call with args: {kwargs}") # [Source: 224]
            # Call the DRIM AI tool's execute method
            tool_result_obj = await tool_instance.execute(**kwargs) # This should return a ToolResult
            
            drim_ai_logger.info(f"DRIM AI MCPServer: Result of '{mcp_tool_name}': {str(tool_result_obj)[:200]}...") # [Source: 224]

            # FastMCP expects a return type that can be serialized (e.g., JSON string, dict, basic types).
            # We need to convert our ToolResult to a format FastMCP can handle.
            # The original PDF uses json.dumps(result.model_dump()) or json.dumps(result) [Source: 224]
            if hasattr(tool_result_obj, 'model_dump_json'): # Pydantic V2
                return tool_result_obj.model_dump_json()
            elif hasattr(tool_result_obj, 'model_dump'): # Pydantic V2
                return tool_result_obj.model_dump()
            elif isinstance(tool_result_obj, dict): # [Source: 224]
                return tool_result_obj
            elif isinstance(tool_result_obj, str):
                 return tool_result_obj # Return string directly
            else: # Fallback
                return str(tool_result_obj) # [Source: 224]

        # Set metadata on the wrapper function for FastMCP
        mcp_tool_method_wrapper.__name__ = mcp_tool_name # [Source: 225] (FastMCP uses function name)
        mcp_tool_method_wrapper.__doc__ = self._build_docstring_from_schema(tool_description, tool_parameters_schema) # [Source: 225]
        
        # Build Signature object for FastMCP from the tool's parameter schema
        mcp_tool_method_wrapper.__signature__ = self._build_signature_from_schema(tool_parameters_schema) # [Source: 225]

        # Store the schema directly for reference if needed (as in PDF [Source: 225])
        # setattr(mcp_tool_method_wrapper, 'parameter_schema', tool_parameters_schema) 
        # Not strictly needed if FastMCP uses __signature__ and __doc__.

        # Register with FastMCP server
        self.server.tool()(mcp_tool_method_wrapper) # [Source: 226]
        self._registered_tool_methods[mcp_tool_name] = mcp_tool_method_wrapper # Keep a reference
        drim_ai_logger.info(f"DRIM AI MCPServer: Registered tool '{mcp_tool_name}' with MCP.") # [Source: 226]

    def _build_docstring_from_schema(self, description: str, parameters_schema: Optional[Dict[str, Any]]) -> str: # [Source: 226]
        """Build a formatted docstring from tool description and parameter schema."""
        docstring = description # [Source: 226]
        if parameters_schema and parameters_schema.get("properties"): # [Source: 226]
            docstring += "\n\nParameters:\n"
            props = parameters_schema.get("properties", {})
            required_params = parameters_schema.get("required", []) # [Source: 226]
            for param_name, param_details in props.items(): # [Source: 226]
                param_type = param_details.get("type", "any") # [Source: 226]
                param_desc = param_details.get("description", "") # [Source: 226]
                req_marker = "(required)" if param_name in required_params else "(optional)" # [Source: 226]
                docstring += f"  {param_name} ({param_type}) {req_marker}: {param_desc}\n" # [Source: 227]
        return docstring

    def _build_signature_from_schema(self, parameters_schema: Optional[Dict[str, Any]]) -> Signature: # [Source: 227]
        """Build a Python function Signature object from a JSON schema for parameters."""
        sig_parameters: List[Parameter] = []
        if parameters_schema and parameters_schema.get("properties"):
            props = parameters_schema.get("properties", {}) # [Source: 227]
            required_params = parameters_schema.get("required", []) # [Source: 227]

            # JSON Schema type to Python type mapping (simplified) [Source: 228]
            type_map = {"string": str, "integer": int, "number": float, "boolean": bool, "object": dict, "array": list}

            for param_name, param_details in props.items(): # [Source: 228]
                py_annotation = type_map.get(param_details.get("type", "string"), Any) # [Source: 228]
                default_val = Parameter.empty if param_name in required_params else None # [Source: 228]
                
                sig_parameters.append(Parameter( # [Source: 228]
                    name=param_name,
                    kind=Parameter.KEYWORD_ONLY, # All MCP tool args are kwargs
                    default=default_val,
                    annotation=py_annotation,
                ))
        return Signature(parameters=sig_parameters) # [Source: 228]

    async def cleanup_tool_resources(self) -> None: # [Source: 228] Renamed from cleanup
        """Clean up resources used by the registered DRIM AI tools (e.g., browser instance)."""
        drim_ai_logger.info("DRIM AI MCPServer: Cleaning up tool resources...") # [Source: 228]
        for tool_name, tool_instance in self.tools_to_register.items(): # [Source: 228]
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(tool_instance.cleanup):
                try:
                    drim_ai_logger.info(f"DRIM AI MCPServer: Cleaning up resources for tool '{tool_name}'.")
                    await tool_instance.cleanup()
                except Exception as e:
                    drim_ai_logger.error(f"DRIM AI MCPServer: Error cleaning up tool '{tool_name}': {e}")
            # Specifically for BrowserUseTool, if not covered by generic cleanup
            # if isinstance(tool_instance, BrowserUseTool): # [Source: 228]
            #     await tool_instance.cleanup()


    def register_all_defined_tools(self) -> None: # [Source: 229] Renamed from register_all_tools
        """Register all DRIM AI tools (added via _add_tool_for_registration) with the MCP server."""
        drim_ai_logger.info("DRIM AI MCPServer: Registering all defined tools...")
        for tool_instance in self.tools_to_register.values(): # [Source: 229]
            self.register_tool_with_mcp(tool_instance) # [Source: 229]

    def run(self, transport: str = "stdio") -> None: # [Source: 229]
        """Run the DRIM AI MCP server."""
        self.register_all_defined_tools() # [Source: 229]

        # Register cleanup for tool resources on exit
        # atexit might not work well with async cleanup in all scenarios.
        # Consider a more explicit shutdown mechanism if issues arise.
        async def _atexit_cleanup_wrapper(): # Wrapper for async cleanup
            await self.cleanup_tool_resources()
        
        # For atexit with async, ensure it can run the async function
        # This is a simplified approach. For robust async cleanup, a signal handler might be better.
        # atexit.register(lambda: asyncio.run(self.cleanup_tool_resources())) # [Source: 229] Original was like this
        # A potentially safer way for async if the loop might be closed:
        def run_async_cleanup():
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.cleanup_tool_resources(), loop=loop)
                else:
                    loop.run_until_complete(self.cleanup_tool_resources())
            except Exception as e:
                drim_ai_logger.error(f"DRIM AI MCPServer: Error in atexit async cleanup: {e}")
        atexit.register(run_async_cleanup)


        drim_ai_logger.info(f"Starting DRIM AI MCP Server (name: {self.server.name}, transport: {transport} mode)...") # [Source: 230]
        try:
            self.server.run(transport=transport) # This is a blocking call from FastMCP [Source: 230]
        except KeyboardInterrupt:
            drim_ai_logger.info("DRIM AI MCP Server shutting down (KeyboardInterrupt).")
        finally:
            # Ensure cleanup is attempted, though atexit should also fire.
            # Explicit call might be good if atexit doesn't run in all shutdown scenarios.
            # However, self.server.run() is blocking, so this finally might only run after it exits.
            drim_ai_logger.info("DRIM AI MCP Server run method finished.")
            # asyncio.run(self.cleanup_tool_resources()) # Redundant if atexit works

def parse_cli_args() -> argparse.Namespace: # [Source: 230] Renamed from parse_args
    """Parse command line arguments for DRIM AI MCP Server."""
    parser = argparse.ArgumentParser(description="DRIM AI MCP Server") # [Source: 230]
    parser.add_argument( # [Source: 230]
        "--transport", choices=["stdio", "http"], default="stdio", # Added http as an option if FastMCP supports it
        help="Communication method: stdio or http (default: stdio)", # [Source: 230]
    )
    # Add other arguments if needed (e.g., port for http)
    parser.add_argument("--server-name", default="drim_ai_mcp_server", help="Name for the MCP server instance.")
    return parser.parse_args() # [Source: 230]

if __name__ == "__main__": # [Source: 230]
    cli_args = parse_cli_args() # [Source: 230]
    
    # Use DRIM AI logger if running as main
    drim_ai_logger.info(f"DRIM AI MCP Server starting with args: {cli_args}")
    
    # Create and run DRIM AI MCP server
    drim_mcp_server = MCPServer(server_name=cli_args.server_name) # [Source: 230]
    drim_mcp_server.run(transport=cli_args.transport) # [Source: 230]