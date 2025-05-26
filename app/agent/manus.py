# File: app/agent/manus.py
from typing import Dict, List, Optional, Any
from datetime import datetime

from pydantic import Field, model_validator

from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config as app_main_config
from app.logger import logger
# Uses the modified MANUS_SYSTEM_PROMPT_TEMPLATE and MANUS_NEXT_STEP_PROMPT_TEMPLATE
from app.prompt.manus import NEXT_STEP_PROMPT as MANUS_NEXT_STEP_PROMPT_TEMPLATE
from app.prompt.manus import SYSTEM_PROMPT as MANUS_SYSTEM_PROMPT_TEMPLATE
from app.tool import Terminate, ToolCollection
from app.tool.ask_human import AskHuman
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.mcp import MCPClients, MCPClientTool # Ensure this is app.tool.mcp
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor
from app.llm import LLM
from app.schema import Message, Role # Ensure Role is imported


class Manus(ToolCallAgent):
    name: str = Field(default="drim_manus_agent")
    description: str = Field(default="DRIM AI's versatile agent that can solve various tasks using multiple tools, including browser automation and optionally MCP-based tools.")

    system_prompt_template: str = Field(default=MANUS_SYSTEM_PROMPT_TEMPLATE, exclude=True)
    system_prompt: str = Field(default="") 

    next_step_prompt_template: str = Field(default=MANUS_NEXT_STEP_PROMPT_TEMPLATE, exclude=True)
    next_step_prompt: str = Field(default="") # This will be formatted in think()

    max_observe: int = Field(default=15000) # Increased from 10k to align with DataAnalysis agent
    max_steps: int = Field(default=25) # Default was 15, can be adjusted

    mcp_clients: Optional[MCPClients] = Field(
        default_factory=MCPClients if app_main_config.mcp and app_main_config.mcp.servers else lambda: None
    )
    
    llm: LLM = Field(default_factory=LLM)

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(),
            BrowserUseTool(),
            StrReplaceEditor(),
            AskHuman(),
            Terminate(),
            # WebSearch() could be added here if Manus should directly use it,
            # but current design is BrowserUseTool(action="web_search") handles it.
        )
    )
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    browser_context_helper: Optional[BrowserContextHelper] = Field(default=None, exclude=True)
    connected_servers: Dict[str, str] = Field(default_factory=dict) # server_id -> url/command
    components_initialized_flag: bool = Field(default=False, exclude=True) # Tracks if async create() has run

    def __init__(self, **data: Any):
        super().__init__(**data)
        # Initial formatting of system_prompt. It will be re-formatted in think() with current date.
        self.system_prompt = self.system_prompt_template.format(
            directory=str(app_main_config.workspace_root),
            current_date=datetime.now().strftime("%B %d, %Y")
        )

    @model_validator(mode="after")
    def initialize_manus_components(self) -> "Manus":
        # This validator runs after Pydantic model creation.
        # Async initializations (like MCP connection) should be in create().
        if self.browser_context_helper is None:
            self.browser_context_helper = BrowserContextHelper(self)
        
        # Add MCP tools to available_tools if mcp_clients is already populated
        # This is more for cases where Manus might be created with pre-configured MCPClients
        if self.mcp_clients and self.mcp_clients.tool_map:
            mcp_tools_to_add = [
                tool for tool in self.mcp_clients.tools if isinstance(tool, MCPClientTool)
            ]
            if mcp_tools_to_add:
                self.available_tools.add_tools(*mcp_tools_to_add)
                logger.info(f"Manus Agent '{self.name}': Added {len(mcp_tools_to_add)} MCP tools during model validation.")
        
        # Ensure system_prompt is formatted
        self.system_prompt = self.system_prompt_template.format(
            directory=str(app_main_config.workspace_root),
            current_date=datetime.now().strftime("%B %d, %Y")
        )
        return self

    @classmethod
    async def create(cls, **kwargs: Any) -> "Manus":
        """
        Asynchronous factory method to create and properly initialize a Manus instance,
        including any async components like MCP server connections.
        """
        # Ensure system_prompt is formatted during creation using the template
        system_prompt_template_to_use = kwargs.pop("system_prompt_template", MANUS_SYSTEM_PROMPT_TEMPLATE)
        current_date_for_create = datetime.now().strftime("%B %d, %Y")
        
        # We pass the formatted system_prompt and the template itself for later re-formatting
        kwargs["system_prompt"] = system_prompt_template_to_use.format(
            directory=str(app_main_config.workspace_root),
            current_date=current_date_for_create
        )
        kwargs["system_prompt_template"] = system_prompt_template_to_use

        # Same for next_step_prompt if it had static template parts
        next_step_template_to_use = kwargs.pop("next_step_prompt_template", MANUS_NEXT_STEP_PROMPT_TEMPLATE)
        kwargs["next_step_prompt_template"] = next_step_template_to_use
        # Actual next_step_prompt is formatted in think()

        instance = cls(**kwargs) # Calls __init__ and then model_validator

        # Initialize BrowserContextHelper if not done by validator (should be, but defensive)
        if instance.browser_context_helper is None:
            instance.browser_context_helper = BrowserContextHelper(instance)

        # Initialize MCP connections if configured
        if instance.mcp_clients and app_main_config.mcp and app_main_config.mcp.servers:
            await instance.initialize_mcp_servers() # This also adds MCP tools to available_tools

        instance.components_initialized_flag = True
        logger.info(f"Manus Agent '{instance.name}' created and async components initialized.")
        return instance

    async def initialize_mcp_servers(self) -> None:
        if not self.mcp_clients:
            logger.info(f"DRIM Manus Agent '{self.name}': MCP client not available (mcp_clients is None). Skipping MCP server initialization.")
            return
        if not app_main_config.mcp or not app_main_config.mcp.servers:
            logger.info(f"DRIM Manus Agent '{self.name}': No MCP servers defined in configuration. Skipping MCP server initialization.")
            return

        for server_id, server_config in app_main_config.mcp.servers.items():
            try:
                if server_config.type == "sse":
                    if server_config.url:
                        await self.connect_mcp_server(server_config.url, server_id)
                elif server_config.type == "stdio":
                    if server_config.command:
                        await self.connect_mcp_server(
                            server_config.command, server_id, use_stdio=True, stdio_args=server_config.args
                        )
            except Exception as e:
                logger.error(f"DRIM Manus Agent '{self.name}': Failed to connect to MCP server '{server_id}': {e}")

    async def connect_mcp_server(
        self, server_identifier: str, server_id: str = "", use_stdio: bool = False, stdio_args: Optional[List[str]] = None
    ) -> None:
        if not self.mcp_clients:
            logger.warning(f"DRIM Manus Agent '{self.name}': MCP clients not initialized, cannot connect to MCP server.")
            return
        
        effective_server_id = server_id or server_identifier
        logger.info(f"DRIM Manus Agent '{self.name}': Connecting to MCP server '{effective_server_id}' (Identifier: {server_identifier}, Stdio: {use_stdio})")

        if use_stdio:
            await self.mcp_clients.connect_stdio(command=server_identifier, args=stdio_args or [], server_id=effective_server_id)
        else:
            await self.mcp_clients.connect_sse(server_url=server_identifier, server_id=effective_server_id)
        
        self.connected_servers[effective_server_id] = server_identifier
        
        # Add newly connected server's tools to the agent's available_tools
        newly_added_mcp_tools = [
            tool for tool in self.mcp_clients.tools
            if isinstance(tool, MCPClientTool) and tool.server_id == effective_server_id
        ]
        if newly_added_mcp_tools:
            self.available_tools.add_tools(*newly_added_mcp_tools)
            logger.info(f"DRIM Manus Agent '{self.name}': Added {len(newly_added_mcp_tools)} tools from MCP server '{effective_server_id}'.")
        else:
            logger.info(f"DRIM Manus Agent '{self.name}': No new tools found for MCP server '{effective_server_id}' after connection (or tools already present).")


    async def disconnect_mcp_server(self, server_id_or_identifier: str = "") -> None:
        if not self.mcp_clients: return

        await self.mcp_clients.disconnect(server_id_or_identifier)
        
        server_id_to_remove = server_id_or_identifier
        if not server_id_or_identifier: # Disconnecting all
            self.connected_servers.clear()
        else:
             # Find the actual server_id if identifier was url/command
            if server_id_or_identifier not in self.connected_servers:
                for sid, identifier_val in list(self.connected_servers.items()): # Iterate over copy for safe removal
                    if identifier_val == server_id_or_identifier:
                        server_id_to_remove = sid
                        break
            self.connected_servers.pop(server_id_to_remove, None)

        # Rebuild available_tools: keep non-MCP tools, and MCP tools from still-connected servers
        base_tools_list = [
            tool for tool in self.available_tools.tools if not isinstance(tool, MCPClientTool)
        ]
        self.available_tools = ToolCollection(*base_tools_list)
        
        if self.mcp_clients.tools: 
            active_mcp_tools = [
                t for t in self.mcp_clients.tools 
                if isinstance(t, MCPClientTool) and t.server_id in self.connected_servers
            ]
            if active_mcp_tools:
                self.available_tools.add_tools(*active_mcp_tools)
        logger.info(f"DRIM Manus Agent '{self.name}': MCP server(s) disconnected. Available tools updated.")

    async def think(self) -> bool:
        if not self.components_initialized_flag:
            logger.warning(f"DRIM Manus Agent '{self.name}': think() called before full initialization via create(). Attempting lazy full init.")
            # Re-run parts of create() logic that might have been skipped
            if self.browser_context_helper is None:
                 self.browser_context_helper = BrowserContextHelper(self)
            if self.mcp_clients and app_main_config.mcp and app_main_config.mcp.servers and not self.connected_servers:
                await self.initialize_mcp_servers()
            self.components_initialized_flag = True
        
        current_date_str = datetime.now().strftime("%B %d, %Y at %I:%M:%S %p %Z") # More specific time
        
        # Always re-format system_prompt with the current date
        self.system_prompt = self.system_prompt_template.format(
            directory=str(app_main_config.workspace_root),
            current_date=current_date_str
        )
        
        browser_tool_name = BrowserUseTool().name
        browser_in_use_in_recent_history = False
        if self.memory and self.memory.messages:
            # Check if BrowserUseTool was the last tool called or its result was the last observation
            # More robust check: look at the last few assistant tool calls or tool responses
            recent_messages = self.memory.get_recent_messages(2) # Check last interaction cycle
            for msg in recent_messages:
                if msg.role == Role.ASSISTANT and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc.function.name == browser_tool_name:
                            browser_in_use_in_recent_history = True; break
                elif msg.role == Role.TOOL and msg.name == browser_tool_name:
                    browser_in_use_in_recent_history = True; break
                if browser_in_use_in_recent_history: break
        
        # If no browser use recently, but user's last message implies web task
        if not browser_in_use_in_recent_history and self.memory and self.memory.messages:
            last_user_msg = next((msg for msg in reversed(self.memory.messages) if msg.role == Role.USER), None)
            if last_user_msg and last_user_msg.content:
                web_keywords = ["search for", "find on the web", "browse to", "what is the latest on", "look up", "how many goals did", "what match"]
                if any(keyword in last_user_msg.content.lower() for keyword in web_keywords):
                    browser_in_use_in_recent_history = True # Trigger browser context for prompt

        prompt_parts_for_template: Dict[str, str] = {
            "current_date": current_date_str,
            # Default empty placeholders for browser parts
            "url_placeholder": "\n- Current URL: (Browser not actively used or state unavailable)",
            "tabs_placeholder": "\n- Tab information: (Browser not actively used or state unavailable)",
            "results_placeholder": "\n- Interactive Elements: (Browser not actively used or state unavailable)",
            "content_above_placeholder": "",
            "content_below_placeholder": ""
        }
        
        if browser_in_use_in_recent_history and self.browser_context_helper:
            logger.info(f"DRIM Manus Agent '{self.name}': Browser context is relevant, formatting next_step_prompt with browser state.")
            # Get formatted browser state parts from the helper
            browser_state_parts, image_data = await self.browser_context_helper.get_state_parts_for_prompt()
            prompt_parts_for_template.update(browser_state_parts) # Update dict with actual browser parts
            self.current_base64_image_internal = image_data # For ToolCallAgent to use
            if image_data:
                logger.info(f"DRIM Manus Agent '{self.name}': Screenshot data captured and will be sent with the next user prompt part to LLM.")
        else:
            self.current_base64_image_internal = None
            logger.info(f"DRIM Manus Agent '{self.name}': Browser context not actively used, using general next_step_prompt.")

        # Format the agent's next_step_prompt_template using all collected parts
        self.next_step_prompt = self.next_step_prompt_template.format(**prompt_parts_for_template)
        
        # Call parent's think method which uses self.system_prompt and the now fully formatted self.next_step_prompt
        think_result = await super().think()
        return think_result

    async def cleanup(self):
        logger.info(f"Cleaning up DRIM Manus Agent '{self.name}'...")
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()
        
        if self.components_initialized_flag and self.mcp_clients: # Only try to disconnect if MCP was initialized
            # Disconnect from all MCP servers explicitly if Manus managed them
            server_ids_to_disconnect = list(self.connected_servers.keys()) # Iterate over a copy
            for sid in server_ids_to_disconnect:
                try:
                    await self.disconnect_mcp_server(sid) 
                except Exception as e_mcp_cleanup:
                    logger.error(f"Error disconnecting MCP server '{sid}' during Manus cleanup: {e_mcp_cleanup}")
            
            # Final check if any sessions remain in mcp_clients (e.g., if not tracked by connected_servers)
            if self.mcp_clients.sessions:
                 await self.mcp_clients.disconnect() # Disconnect any remaining
            logger.info(f"DRIM Manus Agent '{self.name}': All MCP connections attempted to close during cleanup.")
        
        self.components_initialized_flag = False # Reset flag
        # Call super().cleanup() from ToolCallAgent for its specific tool cleanup
        await super().cleanup()
        logger.info(f"DRIM Manus Agent '{self.name}' cleanup complete.")