from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.mcp import (
    MULTIMEDIA_RESPONSE_PROMPT as MCP_MULTIMEDIA_RESPONSE_PROMPT,
    NEXT_STEP_PROMPT as MCP_NEXT_STEP_PROMPT,
    SYSTEM_PROMPT as MCP_SYSTEM_PROMPT,
)
from app.schema import AgentState, Message, Role
from app.tool.base import ToolResult
from app.tool.mcp import MCPClients, MCPClientTool
from app.llm import LLM

class MCPAgent(ToolCallAgent):
    name: str = Field(default="drim_mcp_agent")
    description: str = Field(default="A DRIM AI agent that connects to an MCP server and uses its tools.")

    system_prompt: str = Field(default=MCP_SYSTEM_PROMPT)
    next_step_prompt: str = Field(default=MCP_NEXT_STEP_PROMPT)

    mcp_clients: MCPClients = Field(default_factory=MCPClients)
    available_tools: Optional[MCPClients] = Field(default=None)

    max_steps: int = Field(default=20)
    connection_type: str = Field(default="stdio")

    # MODIFIED: Renamed fields
    tool_schemas_cache: Dict[str, Dict[str, Any]] = Field(default_factory=dict, exclude=True)
    refresh_tools_interval: int = Field(default=5, exclude=True) # Renamed

    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])
    llm: LLM = Field(default_factory=LLM)

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> None:
        if connection_type:
            self.connection_type = connection_type

        logger.info(f"DRIM MCPAgent: Initializing connection type '{self.connection_type}'...")
        
        if self.mcp_clients is None: 
            self.mcp_clients = MCPClients()

        if self.connection_type == "sse":
            if not server_url:
                raise ValueError("Server URL is required for SSE connection to MCP server.")
            await self.mcp_clients.connect_sse(server_url=server_url)
        elif self.connection_type == "stdio":
            if not command:
                raise ValueError("Command is required for stdio connection to MCP server.")
            await self.mcp_clients.connect_stdio(command=command, args=args or [])
        else:
            raise ValueError(f"Unsupported MCP connection type: {self.connection_type}")

        self.available_tools = self.mcp_clients

        await self._refresh_and_update_tool_schemas()

        tool_names = list(self.mcp_clients.tool_map.keys())
        tools_info = ", ".join(tool_names) if tool_names else "No tools currently available."
        
        self.memory.add_message(
            Message(
                role=Role.SYSTEM,
                content=f"Connected to MCP. Available MCP tools: {tools_info}"
            )
        )
        logger.info(f"DRIM MCPAgent initialized. Tools from MCP: {tools_info}")

    async def _refresh_and_update_tool_schemas(self) -> Tuple[List[str], List[str]]:
        if not self.mcp_clients or not self.mcp_clients.sessions:
            logger.warning("DRIM MCPAgent: No active MCP session to refresh tools from.")
            return [], []
        
        # MODIFIED: Use renamed field
        current_agent_tool_schemas = {
            tool.original_name if isinstance(tool, MCPClientTool) else tool.name : tool.parameters
            for tool in self.available_tools.tools 
        }

        # MODIFIED: Use renamed field
        current_names = set(current_agent_tool_schemas.keys())
        previous_names = set(self.tool_schemas_cache.keys()) # Use renamed field

        added_tools = list(current_names - previous_names)
        removed_tools = list(previous_names - current_names)
        
        changed_tools = []
        for name in current_names.intersection(previous_names):
            # MODIFIED: Use renamed field
            if current_agent_tool_schemas.get(name) != self.tool_schemas_cache.get(name): # Use renamed field
                changed_tools.append(name)

        # MODIFIED: Use renamed field
        self.tool_schemas_cache = current_agent_tool_schemas # Use renamed field

        if added_tools:
            logger.info(f"DRIM MCPAgent: Added MCP tools: {added_tools}")
            self.memory.add_message(Message(role=Role.SYSTEM, content=f"New MCP tools available: {', '.join(added_tools)}"))
        if removed_tools:
            logger.info(f"DRIM MCPAgent: Removed MCP tools: {removed_tools}")
            self.memory.add_message(Message(role=Role.SYSTEM, content=f"MCP tools no longer available: {', '.join(removed_tools)}"))
        if changed_tools:
            logger.info(f"DRIM MCPAgent: Changed MCP tool schemas: {changed_tools}")
            self.memory.add_message(Message(role=Role.SYSTEM, content=f"MCP tool schemas changed for: {', '.join(changed_tools)}"))

        return added_tools, removed_tools

    async def think(self) -> bool:
        if not self.mcp_clients or not self.mcp_clients.sessions or \
           (self.available_tools and not self.available_tools.tool_map):
            logger.info("DRIM MCPAgent: MCP service is no longer available or no tools. Ending interaction.")
            self.state = AgentState.FINISHED
            return False

        # MODIFIED: Use renamed field
        if self.current_step > 0 and self.current_step % self.refresh_tools_interval == 0: 
            logger.info("DRIM MCPAgent: Refreshing MCP tools...")
            await self._refresh_and_update_tool_schemas()
            if self.available_tools and not self.available_tools.tool_map:
                logger.info("DRIM MCPAgent: MCP service has shut down (all tools removed). Ending interaction.")
                self.state = AgentState.FINISHED
                return False
        
        return await super().think()

    async def _handle_special_tool(self, name: str, result: Any, **kwargs: Any) -> None:
        await super()._handle_special_tool(name, result, **kwargs)

        if isinstance(result, ToolResult) and result.base64_image:
            self.memory.add_message(
                Message(role=Role.SYSTEM, content=MCP_MULTIMEDIA_RESPONSE_PROMPT.format(tool_name=name))
            )
            logger.info(f"DRIM MCPAgent: Received multimedia response from tool '{name}'.")

    def _should_finish_execution(self, name: str, result: Any, **kwargs: Any) -> bool:
        if name.lower() in [stn.lower() for stn in self.special_tool_names]:
            return True
        return super()._should_finish_execution(name=name, result=result, **kwargs)

    async def cleanup(self) -> None:
        logger.info(f"Cleaning up DRIM MCPAgent '{self.name}'...")
        if self.mcp_clients and self.mcp_clients.sessions:
            await self.mcp_clients.disconnect()
            logger.info("DRIM MCPAgent: MCP connections closed.")
        
        await super().cleanup()
        logger.info(f"DRIM MCPAgent '{self.name}' cleanup complete.")

    async def run(self, request: Optional[str] = None) -> str:
        try:
            if not self.available_tools or (self.mcp_clients and not self.mcp_clients.sessions):
                 logger.warning("DRIM MCPAgent: Run called but not fully initialized (no MCP connection/tools). Ensure initialize() is called first.")
            result_str = await super().run(request)
            return result_str
        finally:
            pass # Cleanup is handled by BaseAgent's run