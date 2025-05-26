from contextlib import AsyncExitStack # [Source: 614]
from typing import Dict, List, Optional, Any
from pydantic import Field # MODIFIED: Added Field import

from mcp import ClientSession, StdioServerParameters # type: ignore # [Source: 614]
from mcp.client.sse import sse_client # type: ignore # [Source: 614]
from mcp.client.stdio import stdio_client # type: ignore # [Source: 614]
from mcp.types import ListToolsResult, TextContent, Tool as MCPToolType # type: ignore # Renamed Tool to MCPToolType to avoid conflict [Source: 614]

from app.logger import logger # [Source: 614]
from app.tool.base import BaseTool, ToolResult, ToolFailure # Added ToolFailure [Source: 614]
from app.tool.tool_collection import ToolCollection # [Source: 614]

class MCPClientTool(BaseTool): # [Source: 614]
    session: Optional[ClientSession] = None # [Source: 614]
    server_id: str = "" # [Source: 614]
    original_name: str = "" # [Source: 614]

    async def execute(self, **kwargs: Any) -> ToolResult: # [Source: 614]
        if not self.session: # [Source: 615]
            logger.error(f"DRIM AI MCPClientTool '{self.name}': Not connected to MCP server (session is None).")
            return ToolFailure(error=f"Tool '{self.name}' not connected to MCP server {self.server_id}.") # Used ToolFailure
        
        logger.info(f"DRIM AI MCPClientTool: Executing remote tool '{self.original_name}' on server '{self.server_id}' with args: {kwargs}")
        try:
            mcp_result = await self.session.call_tool(tool_name=self.original_name, args=kwargs) # [Source: 616]
            
            output_parts: List[str] = []
            base64_image_data: Optional[str] = None 

            if mcp_result.content:
                for item in mcp_result.content: # [Source: 616]
                    if isinstance(item, TextContent): # [Source: 616]
                        output_parts.append(item.text)
                    else:
                        try:
                            output_parts.append(str(item))
                        except Exception:
                            output_parts.append(f"[Unsupported MCP content part type: {type(item)}]")
            
            final_output = "\n".join(output_parts).strip() if output_parts else "MCP tool executed with no textual output." # [Source: 616]
            logger.info(f"DRIM AI MCPClientTool: Remote tool '{self.original_name}' executed. Output snippet: {final_output[:100]}...")
            return ToolResult(output=final_output, base64_image=base64_image_data) # [Source: 616]

        except Exception as e: # [Source: 616]
            logger.exception(f"DRIM AI MCPClientTool: Error executing remote tool '{self.original_name}' on server '{self.server_id}'.")
            return ToolFailure(error=f"Error executing MCP tool '{self.name}': {str(e)}") # Used ToolFailure


class MCPClients(ToolCollection): # [Source: 616]
    sessions: Dict[str, ClientSession] = Field(default_factory=dict) # [Source: 616]
    exit_stacks: Dict[str, AsyncExitStack] = Field(default_factory=dict) # [Source: 616]
    
    def __init__(self, *initial_tools: BaseTool): 
        super().__init__(*initial_tools) # [Source: 616]
        logger.info("DRIM AI MCPClients manager initialized.")

    async def connect_sse(self, server_url: str, server_id: Optional[str] = None) -> None: # [Source: 617]
        if not server_url: # [Source: 617]
            raise ValueError("DRIM AI MCPClients: Server URL is required for SSE connection.")
        
        effective_server_id = server_id or server_url # [Source: 617]
        if effective_server_id in self.sessions: # [Source: 617]
            logger.warning(f"DRIM AI MCPClients: Already connected to SSE server '{effective_server_id}'. Disconnecting first.")
            await self.disconnect(effective_server_id) # [Source: 617]
        
        logger.info(f"DRIM AI MCPClients: Connecting to SSE MCP server '{effective_server_id}' at {server_url}...")
        exit_stack = AsyncExitStack() # [Source: 617]
        try:
            streams_context = sse_client(url=server_url) # [Source: 617]
            streams = await exit_stack.enter_async_context(streams_context) # [Source: 617]
            session = await exit_stack.enter_async_context(ClientSession(*streams)) # [Source: 617]
            
            self.exit_stacks[effective_server_id] = exit_stack
            self.sessions[effective_server_id] = session
            await self._initialize_session_and_list_tools(effective_server_id) # [Source: 618]
        except Exception as e:
            logger.error(f"DRIM AI MCPClients: Failed to connect to SSE MCP server '{effective_server_id}': {e}")
            await exit_stack.aclose() 
            raise

    async def connect_stdio(self, command: str, args: Optional[List[str]] = None, server_id: Optional[str] = None) -> None: # [Source: 618]
        if not command: # [Source: 618]
            raise ValueError("DRIM AI MCPClients: Server command is required for stdio connection.")
        
        effective_server_id = server_id or command # [Source: 618]
        if effective_server_id in self.sessions: # [Source: 618]
            logger.warning(f"DRIM AI MCPClients: Already connected to stdio server '{effective_server_id}'. Disconnecting first.")
            await self.disconnect(effective_server_id) # [Source: 618]

        logger.info(f"DRIM AI MCPClients: Connecting to stdio MCP server '{effective_server_id}' (cmd: {command})...")
        exit_stack = AsyncExitStack() # [Source: 618]
        try:
            server_params = StdioServerParameters(command=command, args=args or []) # [Source: 618]
            stdio_transport = await exit_stack.enter_async_context(stdio_client(server_params)) # [Source: 618]
            read_stream, write_stream = stdio_transport # [Source: 618]
            session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream)) # [Source: 618]
            
            self.exit_stacks[effective_server_id] = exit_stack
            self.sessions[effective_server_id] = session
            await self._initialize_session_and_list_tools(effective_server_id) # [Source: 618]
        except Exception as e:
            logger.error(f"DRIM AI MCPClients: Failed to connect to stdio MCP server '{effective_server_id}': {e}")
            await exit_stack.aclose() 
            raise

    async def _initialize_session_and_list_tools(self, server_id: str) -> None: # [Source: 619]
        session = self.sessions.get(server_id)
        if not session: # [Source: 619]
            raise RuntimeError(f"DRIM AI MCPClients: Session not found for server_id '{server_id}' during initialization.")
        
        await session.initialize() # [Source: 619]
        response: ListToolsResult = await session.list_tools() # [Source: 619]
        
        server_tools_added_names = []
        for mcp_tool_def in response.tools: # mcp_tool_def is of type mcp.types.Tool [Source: 619]
            original_tool_name = mcp_tool_def.name # [Source: 619]
            tool_instance_name = f"mcp_tool::{server_id}::{original_tool_name}" # [Source: 619] 

            tool_instance = MCPClientTool( # [Source: 620]
                name=tool_instance_name,
                description=mcp_tool_def.description, # [Source: 620]
                parameters=mcp_tool_def.inputSchema, # [Source: 620]
                session=session, # [Source: 620]
                server_id=server_id, # [Source: 620]
                original_name=original_tool_name, # [Source: 620]
            )
            self.add_tool(tool_instance) 
            server_tools_added_names.append(original_tool_name)
        
        logger.info( # [Source: 620]
            f"DRIM AI MCPClients: Connected to server '{server_id}'. Tools registered: {server_tools_added_names if server_tools_added_names else 'None'}."
        )

    async def list_tools(self) -> ListToolsResult: 
        all_mcp_tools: List[MCPToolType] = [] # Use aliased MCPToolType [Source: 620]
        for server_id, session in self.sessions.items(): # [Source: 620]
            try:
                response = await session.list_tools() # [Source: 620]
                all_mcp_tools.extend(response.tools) # [Source: 620]
            except Exception as e:
                logger.error(f"DRIM AI MCPClients: Error listing tools from MCP server '{server_id}': {e}")
        return ListToolsResult(tools=all_mcp_tools) # [Source: 620]

    async def disconnect(self, server_id_to_disconnect: Optional[str] = None) -> None: # [Source: 620] 
        servers_to_process: List[str] = []
        if server_id_to_disconnect: # [Source: 621]
            if server_id_to_disconnect in self.sessions:
                servers_to_process.append(server_id_to_disconnect)
            else:
                logger.warning(f"DRIM AI MCPClients: Attempted to disconnect from unknown or already disconnected server '{server_id_to_disconnect}'.")
                return
        else: # [Source: 621]
            servers_to_process = list(self.sessions.keys())
            logger.info("DRIM AI MCPClients: Disconnecting from all MCP servers...")

        for sid in servers_to_process:
            logger.info(f"DRIM AI MCPClients: Disconnecting from MCP server '{sid}'...")
            exit_stack = self.exit_stacks.pop(sid, None) # [Source: 621]
            session = self.sessions.pop(sid, None) # [Source: 621] # noqa: F841 (session might not be used explicitly after pop if exit_stack handles it)
            
            if exit_stack:
                try:
                    await exit_stack.aclose() # [Source: 621] 
                except RuntimeError as e: # [Source: 621]
                    if "cancel scope" in str(e).lower(): # [Source: 621]
                        logger.warning(f"DRIM AI MCPClients: Expected 'cancel scope' error during disconnect from '{sid}', continuing: {e}") # [Source: 621]
                    else:
                        logger.error(f"DRIM AI MCPClients: Runtime error during exit_stack.aclose() for '{sid}': {e}") # [Source: 621]
                except Exception as e:
                    logger.error(f"DRIM AI MCPClients: Error during exit_stack.aclose() for '{sid}': {e}")
            
            tools_after_removal = [
                tool for tool in self.tools 
                if not (isinstance(tool, MCPClientTool) and tool.server_id == sid)
            ]
            self.tools = tuple(tools_after_removal)
            self.tool_map = {t.name: t for t in self.tools} # [Source: 622]
            logger.info(f"DRIM AI MCPClients: Disconnected from MCP server '{sid}' and removed its tools.")

        if not server_id_to_disconnect: 
            logger.info("DRIM AI MCPClients: All MCP server connections closed.") # [Source: 622]

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, this script implements MCPClients
# and MCPClientTool. [Source: 612, 623] These components enable DRIM AI agents to connect to
# Model Context Protocol (MCP) servers, discover tools exposed by these servers,
# and execute them remotely. This extends DRIM AI's capabilities by allowing it
# to leverage external, specialized functionalities. [Source: 613, 624]