# app/agent/browser.py
import json
from typing import TYPE_CHECKING, Optional, Dict, Any, List, Tuple

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent # Base for BrowserAgent
from app.logger import logger
from app.prompt.browser import NEXT_STEP_PROMPT as BROWSER_NEXT_STEP_PROMPT_TEMPLATE
from app.prompt.browser import SYSTEM_PROMPT as BROWSER_SYSTEM_PROMPT
from app.schema import Message, ToolChoice, AgentState, Role
# MODIFIED: Import ToolFailure explicitly for isinstance check
from app.tool import BrowserUseTool, Terminate, ToolCollection, ToolResult, ToolFailure
from app.llm import LLM
from app.config import config as app_main_config 

if TYPE_CHECKING:
    from app.agent.base import BaseAgent 

class BrowserContextHelper:
    def __init__(self, agent: Any): 
        self.agent = agent
        self._current_base64_image: Optional[str] = None

    async def _fetch_and_parse_browser_state(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        self._current_base64_image = None 
        if not hasattr(self.agent, 'available_tools'):
            logger.error("BrowserContextHelper's agent is missing 'available_tools'")
            return {"error": "Agent missing 'available_tools'"}, None
            
        browser_tool_instance = self.agent.available_tools.get_tool(BrowserUseTool().name)

        if not browser_tool_instance or not isinstance(browser_tool_instance, BrowserUseTool):
            logger.warning("BrowserUseTool not found or is not the correct type in agent's tools.")
            return {"error": "BrowserUseTool not found or invalid type"}, None
        
        if not hasattr(browser_tool_instance, "get_current_state"):
            logger.warning("BrowserUseTool instance doesn't have get_current_state method.")
            return {"error": "BrowserUseTool missing get_current_state method"}, None

        try:
            result_obj = await browser_tool_instance.get_current_state()
            
            image_data: Optional[str] = None
            if hasattr(result_obj, "base64_image") and result_obj.base64_image:
                image_data = result_obj.base64_image
            
            # MODIFIED: Correctly access error message from ToolFailure or ToolResult
            actual_error_message: Optional[str] = None
            output_for_error_context: Optional[Any] = None

            if isinstance(result_obj, ToolFailure):
                actual_error_message = result_obj.error_message
                output_for_error_context = result_obj.output # ToolFailure stores output
            elif hasattr(result_obj, 'error') and result_obj.error: # Should be ToolResult
                actual_error_message = result_obj.error
                output_for_error_context = result_obj.output

            if actual_error_message:
                logger.debug(f"Browser state error from tool: {actual_error_message}")
                return {"error": actual_error_message, "output": str(output_for_error_context) if output_for_error_context else None}, image_data

            # If no error, proceed to parse output
            if result_obj.output and isinstance(result_obj.output, str):
                parsed_state = json.loads(result_obj.output)
                return parsed_state, image_data
            elif isinstance(result_obj.output, dict): # If output is already a dict (e.g. from some ToolResults)
                return result_obj.output, image_data
            else:
                logger.warning(f"Browser state output is not a JSON string or dict: {type(result_obj.output)}")
                return {"error": "Browser state output is not a JSON string or dict", "output": str(result_obj.output)}, image_data

        except json.JSONDecodeError as e:
            error_output = getattr(result_obj, 'output', 'N/A') if 'result_obj' in locals() else 'N/A'
            logger.error(f"Failed to parse browser state JSON: {e}. Output was: {error_output}")
            return {"error": f"Failed to parse browser state JSON: {e}", "output": error_output}, None
        except Exception as e:
            logger.exception(f"Failed to get browser state via tool: {str(e)}") 
            return {"error": f"Failed to get browser state: {str(e)}"}, None

    async def get_state_parts_for_prompt(self) -> Tuple[Dict[str, str], Optional[str]]:
        browser_state_dict, image_data = await self._fetch_and_parse_browser_state()
        
        prompt_parts: Dict[str, str] = {
            "url_placeholder": "\n- Current URL: Unknown or N/A",
            "tabs_placeholder": "\n- Tab information: Unknown or N/A",
            "results_placeholder": "\n- Interactive Elements: Information unavailable or error retrieving.",
            "content_above_placeholder": "",
            "content_below_placeholder": ""
        }

        if browser_state_dict and not browser_state_dict.get("error"):
            url_value = browser_state_dict.get('url', 'N/A')
            title_value = browser_state_dict.get('title', 'N/A')
            prompt_parts["url_placeholder"] = f"\n- Current URL: {url_value}\n- Title: {title_value}"
            
            tabs = browser_state_dict.get("tabs", [])
            if tabs and isinstance(tabs, list):
                current_tab_id_val = browser_state_dict.get('current_tab_id', 'N/A')
                tab_details = []
                for t_idx, tab_item in enumerate(tabs[:5]): 
                    tab_title = tab_item.get('title', f'Tab {t_idx+1}')[:50] 
                    tab_id = tab_item.get('id', 'N/A')
                    active_marker = "*" if str(tab_id) == str(current_tab_id_val) else ""
                    tab_details.append(f"  {active_marker}[ID:{tab_id}] {tab_title}")
                tabs_summary = "\n".join(tab_details)
                if len(tabs) > 5:
                    tabs_summary += f"\n  ...and {len(tabs)-5} more tabs."

                prompt_parts["tabs_placeholder"] = f"\n- Open Tabs ({len(tabs)} total, current ID: {current_tab_id_val}):\n{tabs_summary}"
            else:
                prompt_parts["tabs_placeholder"] = "\n- No other tabs open or tab information unavailable."

            scroll_info = browser_state_dict.get("scroll_info", {})
            pixels_above = scroll_info.get("pixels_above", 0)
            pixels_below = scroll_info.get("pixels_below", 0)

            if pixels_above > 50: 
                prompt_parts["content_above_placeholder"] = f" (Note: ~{pixels_above}px of content scrollable above)"
            if pixels_below > 50: 
                prompt_parts["content_below_placeholder"] = f" (Note: ~{pixels_below}px of content scrollable below)"
            
            interactive_elements_str = browser_state_dict.get("interactive_elements", "No interactive elements found or information unavailable.")
            prompt_parts["results_placeholder"] = f"\n- Interactive Elements (use indices for actions):\n{interactive_elements_str}"
        
        elif browser_state_dict and browser_state_dict.get("error"):
            error_message = browser_state_dict.get('error', 'Unknown error retrieving browser state.')
            output_context = browser_state_dict.get('output', '')
            prompt_parts["results_placeholder"] = (
                f"\n- Note: Could not fully retrieve browser state. Error: {error_message}\n"
                f"  Context: {str(output_context)[:200]}" 
            )

        return prompt_parts, image_data

    async def cleanup_browser(self):
        if not hasattr(self.agent, 'available_tools'):
            return
        browser_tool_instance = self.agent.available_tools.get_tool(BrowserUseTool().name)
        if browser_tool_instance and hasattr(browser_tool_instance, "cleanup") and \
           callable(getattr(browser_tool_instance, "cleanup")):
            try:
                await browser_tool_instance.cleanup()
                logger.info("BrowserContextHelper: Browser resources cleaned up via tool.")
            except Exception as e:
                logger.error(f"BrowserContextHelper: Error during browser cleanup via tool: {e}")


class BrowserAgent(ToolCallAgent):
    name: str = Field(default="drim_browser_agent")
    description: str = Field(default="An AI agent that controls a web browser to accomplish tasks by navigating and interacting with web pages.")

    system_prompt_template: str = Field(default=BROWSER_SYSTEM_PROMPT, exclude=True) 
    system_prompt: str = Field(default="") 

    next_step_prompt_template: str = Field(default=BROWSER_NEXT_STEP_PROMPT_TEMPLATE, exclude=True) 
    next_step_prompt: str = Field(default="") 

    max_observe: int = Field(default=10000)
    max_steps: int = Field(default=20)

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(BrowserUseTool(), Terminate())
    )
    
    browser_context_helper: Optional[BrowserContextHelper] = Field(default=None, exclude=True)
    llm: LLM = Field(default_factory=LLM) 

    def __init__(self, **data: Any):
        super().__init__(**data)
        self.system_prompt = self.system_prompt_template.format(
            directory=str(app_main_config.workspace_root), 
            WINDOW="multiple", 
            max_actions="several" 
        )

    @model_validator(mode="after")
    def initialize_browser_agent_components(self) -> "BrowserAgent":
        if self.browser_context_helper is None:
            self.browser_context_helper = BrowserContextHelper(self)
        
        self.system_prompt = self.system_prompt_template.format(
            directory=str(app_main_config.workspace_root),
            WINDOW="multiple", 
            max_actions="several"
        )
        return self

    async def think(self) -> bool:
        if not self.browser_context_helper:
            logger.error("BrowserContextHelper not initialized in BrowserAgent. Cannot think.")
            self.state = AgentState.ERROR
            return False
            
        from datetime import datetime 
        current_date_str = datetime.now().strftime("%B %d, %Y")
        
        browser_prompt_parts, image_data = await self.browser_context_helper.get_state_parts_for_prompt()
        
        self.next_step_prompt = self.next_step_prompt_template.format(
            current_date=current_date_str,
            **browser_prompt_parts 
        )
        
        self.current_base64_image_internal = image_data 

        return await super().think()

    async def cleanup(self):
        logger.info(f"Cleaning up resources for BrowserAgent '{self.name}'...")
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()
        
        await super().cleanup() 
        logger.info(f"BrowserAgent '{self.name}' cleanup complete.")