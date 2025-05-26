# File: app/tool/browser_use_tool.py
import asyncio
import base64
import json
from typing import Generic, Optional, TypeVar, List, Dict, Any, Union

from browser_use import Browser as BrowserUseBrowser # type: ignore
from browser_use import BrowserConfig # type: ignore
from browser_use.browser.context import BrowserContext, BrowserContextConfig # type: ignore
from pydantic import Field, field_validator, ConfigDict
from pydantic_core.core_schema import ValidationInfo
try:
    import markdownify
except ImportError:
    markdownify = None # type: ignore

from app.config import config as app_config
from app.llm import LLM, ModelPurpose
from app.tool.base import BaseTool, ToolResult, ToolFailure
from app.tool.web_search import WebSearch, WebSearchResponse
from app.schema import ToolChoice, Message, Role
from app.logger import logger

_BROWSER_TOOL_DESCRIPTION = """\
A powerful browser automation tool that allows interaction with web pages through various actions.
* This tool provides commands for controlling a browser session, navigating web pages, and extracting information.
* It maintains state across calls, keeping the browser session alive until explicitly closed.
* Use this when you need to browse websites, fill forms, click buttons, or perform web searches.
* To understand or extract information from a webpage, you MUST use the 'extract_content' action with a clear 'goal'.
* Each action requires specific parameters as defined in the tool's descriptions and runtime checks.
Key capabilities include:
* Navigation: Go to specific URLs, go back, search the web, or refresh pages.
* Interaction: Click elements, input text, select from dropdowns, send keyboard commands.
* Scrolling: Scroll up/down by pixel amount or scroll to specific text.
* Content extraction: `extract_content` for goal-oriented extraction of information from web pages.
* Tab management: Switch between tabs, open new tabs, or close tabs.
Note: When using element indices, refer to the numbered elements shown in the current browser state.
When using the 'web_search' action, it will return a list of search results (titles, URLs, snippets). You must then analyze these results in your thought process and use the 'go_to_url' action to visit a specific link that seems most promising.
"""

ContextT = TypeVar("ContextT")

class BrowserUseTool(BaseTool, Generic[ContextT]):
    name: str = Field(default="browser_use")
    description: str = Field(default=_BROWSER_TOOL_DESCRIPTION)
    parameters: Dict[str, Any] = Field(default={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_url", "click_element", "input_text", "scroll_down", "scroll_up",
                    "scroll_to_text", "send_keys", "get_dropdown_options", "select_dropdown_option",
                    "go_back", "web_search", "wait", "extract_content",
                    "switch_tab", "open_tab", "close_tab", "refresh_page",
                    "get_current_state_for_agent"
                ],
                "description": "The browser action to perform. To read or get information from a page, use 'extract_content' with a specific 'goal'. The 'web_search' action returns a list of results; use 'go_to_url' to visit one.",
            },
            "url": {"type": "string", "description": "URL for 'go_to_url' or 'open_tab' actions"},
            "index": {"type": "integer", "description": "Element index for interaction (e.g., 'click_element', 'input_text')."},
            "text": {"type": "string", "description": "Text for 'input_text', 'scroll_to_text', or 'select_dropdown_option' actions."},
            "scroll_amount": {"type": "integer", "description": "Pixels to scroll for 'scroll_down' or 'scroll_up' actions."},
            "tab_id": {"type": "integer", "description": "Tab ID for 'switch_tab' action."},
            "query": {"type": "string", "description": "Search query for 'web_search' action."},
            "num_results": {"type": "integer", "description": "(Optional for 'web_search') Number of search results to return. Default from tool: 5."},
            "goal": {"type": "string", "description": "Extraction goal for 'extract_content' action. This is REQUIRED when you need to understand or get information from a webpage. Be specific, e.g., 'Extract all news headlines and their timestamps from the Latest News section'."},
            "keys": {"type": "string", "description": "Keys to send for 'send_keys' action (e.g., 'Enter', 'ArrowDown')."},
            "seconds": {"type": "integer", "description": "Seconds to wait for 'wait' action."},
        },
        "required": ["action"],
    })

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    browser_instance: Optional[BrowserUseBrowser] = Field(default=None, exclude=True)
    browser_context: Optional[BrowserContext] = Field(default=None, exclude=True)

    web_search_dependency: WebSearch = Field(default_factory=WebSearch, exclude=True)
    llm_instance: LLM = Field(default_factory=LLM)

    tool_context: Optional[ContextT] = Field(default=None, exclude=True)

    @field_validator("parameters", mode="before")
    @classmethod
    def validate_parameters_definition(cls, v: Dict[str, Any], info: ValidationInfo) -> Dict[str, Any]:
        if not v or not v.get("properties") or not v.get("required"):
            raise ValueError("Tool parameters definition must be a valid JSON schema with properties and required fields.")
        return v

    async def _ensure_browser_initialized(self) -> BrowserContext:
        async with self.async_lock:
            if self.browser_instance is None or self.browser_context is None:
                logger.info(f"BrowserUseTool: Browser init needed (browser instance is None: {self.browser_instance is None}, context is None: {self.browser_context is None}). Initializing...")

                if self.browser_context is not None:
                    try:
                        await self.browser_context.close()
                        logger.info("BrowserUseTool: Cleaned up existing browser_context before re-init.")
                    except Exception as e_ctx_close:
                        logger.warning(f"Error closing existing browser_context during re-init: {e_ctx_close}")
                    finally:
                        self.browser_context = None

                if self.browser_instance is not None:
                    try:
                        await self.browser_instance.close()
                        logger.info("BrowserUseTool: Cleaned up existing browser_instance before re-init.")
                    except Exception as e_b_close:
                        logger.warning(f"Error closing existing browser_instance during re-init: {e_b_close}")
                    finally:
                        self.browser_instance = None

                browser_config_kwargs: Dict[str, Any] = {
                    "headless": True,
                    "disable_security": True
                }
                if app_config.browser:
                    from browser_use.browser.browser import ProxySettings as BrowserUseProxySettings
                    browser_settings = app_config.browser
                    browser_config_kwargs["headless"] = browser_settings.headless
                    browser_config_kwargs["disable_security"] = browser_settings.disable_security
                    if browser_settings.extra_chromium_args:
                        browser_config_kwargs["extra_chromium_args"] = browser_settings.extra_chromium_args
                    if browser_settings.chrome_instance_path:
                        browser_config_kwargs["executable_path"] = browser_settings.chrome_instance_path
                    if browser_settings.wss_url:
                        browser_config_kwargs["ws_endpoint_url"] = browser_settings.wss_url

                    if browser_settings.proxy and browser_settings.proxy.server:
                        proxy_data = {"server": browser_settings.proxy.server}
                        if browser_settings.proxy.username: proxy_data["username"] = browser_settings.proxy.username
                        if browser_settings.proxy.password: proxy_data["password"] = browser_settings.proxy.password
                        browser_config_kwargs["proxy"] = BrowserUseProxySettings(**proxy_data)

                try:
                    self.browser_instance = BrowserUseBrowser(BrowserConfig(**browser_config_kwargs))
                    logger.info("BrowserUseTool: BrowserUseBrowser instance created.")

                    context_config = BrowserContextConfig()
                    self.browser_context = await self.browser_instance.new_context(context_config)
                    logger.info("BrowserUseTool: BrowserContext created.")
                except Exception as e_init:
                    logger.exception("BrowserUseTool: Failed during browser/context initialization.")
                    if self.browser_instance:
                        try: await self.browser_instance.close()
                        except Exception: pass
                    self.browser_instance = None
                    self.browser_context = None
                    raise ToolFailure(error=f"Failed to initialize browser: {e_init}")

            if self.browser_context is None:
                logger.error("BrowserUseTool: browser_context is None after initialization logic.")
                raise ToolFailure(error="Browser context could not be established.")

            try:
                current_page = await self.browser_context.get_current_page()
                if not current_page or (hasattr(current_page, 'is_closed') and current_page.is_closed()):
                    logger.info("BrowserUseTool: No current page or page is closed. Creating new page.")
                    await self.browser_context.create_new_page_if_needed()
                    current_page = await self.browser_context.get_current_page()
                    if not current_page:
                        raise ToolFailure(error="Failed to obtain a valid page in the browser context.")
            except Exception as e_page_ops:
                logger.error(f"BrowserUseTool: Error during page management in _ensure_browser_initialized: {e_page_ops}")
                raise ToolFailure(error=f"Failed to ensure a valid page: {e_page_ops}")

            return self.browser_context

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[Any] = None,
        text: Optional[str] = None,
        scroll_amount: Optional[Any] = None,
        tab_id: Optional[Any] = None,
        query: Optional[str] = None,
        num_results: Optional[Any] = None,
        goal: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[Any] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            context = await self._ensure_browser_initialized()
            page = await context.get_current_page()
            if not page:
                 logger.error("BrowserUseTool.execute: Critical - No page available after ensuring browser initialization.")
                 return ToolFailure(error="Failed to get a valid browser page for action.")
            if hasattr(page, 'is_closed') and page.is_closed():
                 logger.warning("BrowserUseTool.execute: Page was found to be closed. Attempting to create a new one.")
                 await context.create_new_page_if_needed()
                 page = await context.get_current_page()
                 if not page or page.is_closed():
                     return ToolFailure(error="Failed to get/create a valid page after finding it closed.")

            max_content_length = (app_config.browser.max_content_length if app_config.browser else 20000)
            logger.info(f"BrowserUseTool executing action: '{action}' with relevant params: query='{query}', goal='{goal}', url='{url}', index='{index}'")

            if index is not None: index = int(float(index))
            if scroll_amount is not None: scroll_amount = int(float(scroll_amount))
            if tab_id is not None: tab_id = int(float(tab_id))

            if num_results is not None:
                num_results_int = int(float(num_results))
                if num_results_int <=0: num_results_int = 5
            else:
                num_results_int = 5

            if seconds is not None: seconds = int(float(seconds))

            if action == "go_to_url":
                if not url: return ToolFailure(error="URL is required for 'go_to_url' action")
                await page.goto(url)
                await page.wait_for_load_state()
                return ToolResult(output=f"Navigated to {url}")

            elif action == "go_back":
                await context.go_back()
                return ToolResult(output="Navigated back")
            elif action == "refresh_page":
                await context.refresh_page()
                return ToolResult(output="Refreshed current page")
            elif action == "click_element":
                if index is None: return ToolFailure(error="Index is required for 'click_element' action")
                try:
                    element_node = await context.get_dom_element_by_index(index)
                    if not element_node: return ToolFailure(error=f"Element with index {index} not found by the browser library, though it might have been listed.")
                    download_path = await context._click_element_node(element_node)
                    output_str_click = f"Clicked element at index {index}"
                    if download_path: output_str_click += f" - Downloaded file to {download_path}"
                    return ToolResult(output=output_str_click)
                except KeyError as e:
                    logger.error(f"BrowserUseTool: KeyError when trying to get element with index {index}. This means the index was not in the browser's internal map. Error: {e}")
                    try:
                        current_state_for_error = await self.get_current_state(context=context)
                        error_output = f"Failed to click element: Index {index} is invalid or not found in the current page's interactive elements. Review the current page state carefully. {current_state_for_error.output}"
                        return ToolFailure(error=f"Invalid element index: {index}. It was not found in the browser's internal map.", output=error_output, base64_image=current_state_for_error.base64_image)
                    except Exception as e_state:
                        logger.error(f"BrowserUseTool: Could not get current state during KeyError handling: {e_state}")
                        return ToolFailure(error=f"Invalid element index: {index}. It was not found in the browser's internal map. Additionally, failed to get current page state.")
                except Exception as e_click: # Catch other potential errors from _click_element_node
                    logger.error(f"BrowserUseTool: Error clicking element at index {index}: {e_click}")
                    return ToolFailure(error=f"Error clicking element at index {index}: {str(e_click)}")

            elif action == "input_text":
                if index is None or text is None: return ToolFailure(error="Index and text are required for 'input_text' action")
                try:
                    element_node = await context.get_dom_element_by_index(index)
                    if not element_node: return ToolFailure(error=f"Element with index {index} not found by the browser library, though it might have been listed.")
                    await context._input_text_element_node(element_node, text)
                    return ToolResult(output=f"Input '{text}' into element at index {index}")
                except KeyError as e:
                    logger.error(f"BrowserUseTool: KeyError when trying to get element with index {index} for input. Error: {e}")
                    try:
                        current_state_for_error = await self.get_current_state(context=context)
                        error_output = f"Failed to input into element: Index {index} is invalid or not found in the current page's interactive elements. Review the current page state carefully. {current_state_for_error.output}"
                        return ToolFailure(error=f"Invalid element index: {index} for input. It was not found in the browser's internal map.", output=error_output, base64_image=current_state_for_error.base64_image)
                    except Exception as e_state:
                        logger.error(f"BrowserUseTool: Could not get current state during KeyError handling for input: {e_state}")
                        return ToolFailure(error=f"Invalid element index: {index} for input. It was not found in the browser's internal map. Additionally, failed to get current page state.")
                except Exception as e_input: # Catch other potential errors
                    logger.error(f"BrowserUseTool: Error inputting text into element at index {index}: {e_input}")
                    return ToolFailure(error=f"Error inputting text into element at index {index}: {str(e_input)}")

            elif action == "scroll_down" or action == "scroll_up":
                direction = 1 if action == "scroll_down" else -1
                default_scroll = context.config.browser_window_size["height"] if context.config and hasattr(context.config, "browser_window_size") and context.config.browser_window_size else 500
                amount = scroll_amount if scroll_amount is not None else default_scroll
                await context.execute_javascript(f"window.scrollBy(0, {direction * amount});")
                return ToolResult(output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels")
            elif action == "scroll_to_text":
                if not text: return ToolFailure(error="Text is required for 'scroll_to_text' action")
                try:
                    locator = page.get_by_text(text, exact=False)
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    return ToolResult(output=f"Scrolled to text: '{text}'")
                except Exception as e_scroll:
                    logger.warning(f"BrowserUseTool: Failed to scroll to text '{text}': {e_scroll}")
                    return ToolFailure(error=f"Failed to scroll to text '{text}': Timeout or element not found.")
            elif action == "send_keys":
                if not keys: return ToolFailure(error="Keys are required for 'send_keys' action")
                await page.keyboard.press(keys)
                return ToolResult(output=f"Sent keys: {keys}")

            elif action == "web_search":
                if not query: return ToolFailure(error="Query is required for 'web_search' action")
                logger.info(f"BrowserUseTool.web_search: Calling WebSearch dependency with query='{query}', num_results={num_results_int}")
                search_response_obj: WebSearchResponse = await self.web_search_dependency.execute(
                    query=query, num_results=num_results_int, fetch_content=False
                )
                return search_response_obj

            elif action == "extract_content":
                if not goal: return ToolFailure(error="Parameter 'goal' is required for 'extract_content' action.")
                if not markdownify:
                     logger.error("BrowserUseTool: markdownify library is not available. 'extract_content' relies on it.")
                     return ToolFailure(error="Markdownify library not installed. Cannot use extract_content.")

                page_content_html = None
                selectors_to_try = ["article", "main", "div[role='main']", "body"]
                for selector in selectors_to_try:
                    try:
                        locator = page.locator(selector).first
                        if await locator.count() > 0:
                            page_content_html = await locator.inner_html(timeout=10000)
                            logger.info(f"BrowserUseTool: Found focused content using selector '{selector}' for extraction.")
                            break
                    except Exception as e_locator:
                        logger.debug(f"BrowserUseTool: Selector '{selector}' not found or error: {e_locator}")

                if not page_content_html:
                    logger.info("BrowserUseTool: No common focused selector found, using full page.content() for extraction.")
                    page_content_html = await page.content(timeout=15000)

                content_markdown = markdownify.markdownify(page_content_html)
                truncated_markdown = content_markdown[:max_content_length]
                if len(content_markdown) > max_content_length:
                    logger.warning(f"BrowserUseTool: Markdown content for extraction was truncated from {len(content_markdown)} to {max_content_length} chars.")

                extraction_tool_schema = [{
                    "name": "format_extracted_web_data",
                    "description": "Formats structured data extracted from webpage content based on a specific goal.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal_achieved": {
                                "type": "boolean",
                                "description": "True if the extraction goal was met and relevant information was found. False if the goal could not be met from the provided content (e.g., information not present)."
                            },
                            "extracted_text_summary": {
                                "type": "string",
                                "description": "Use for single text extractions or a concise summary if the goal was general or did not imply a list. Include this if relevant, even if list items are also extracted."
                            },
                            "extracted_list_items": {
                                "type": "array",
                                "description": "MUST use this if the goal implies extracting a LIST of multiple, distinct items (e.g., news headlines, product features, search results). Each item in the array should be an object. If no items matching the list criteria are found, this should be an empty array and goal_achieved might be false.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "item_title": {"type": "string", "description": "Primary identifier or title of the list item (e.g., headline, product name)."},
                                        "item_detail": {"type": "string", "description": "Supporting detail for the item (e.g., snippet, timestamp, price, short description)."},
                                        "item_url": {"type": "string", "description": "Associated URL if the item is a link."}
                                    },
                                    # "additionalProperties": {"type": "string"}, # Ensure this remains commented or handled if re-enabled
                                    "required": ["item_title"]
                                }
                            },
                            "reasoning_notes": {
                                "type": "string",
                                "description": "Briefly explain if goal_achieved is false, or provide any important context/notes about the extraction process or limitations of the extracted data."}
                        },
                        "required": ["goal_achieved"]
                    }
                }]

                extraction_prompt_text = (
                    f"You are an information extraction specialist. Your task is to meticulously analyze the provided webpage content (in Markdown format) "
                    f"and extract information to fulfill the specific extraction goal: '{goal}'.\n"
                    "Follow these instructions carefully:\n"
                    "1.  **Determine Output Format based on Goal:**\n"
                    "    * If the `goal` clearly asks for a LIST of multiple, distinct items (e.g., 'all news headlines and timestamps', 'key product features', 'names of committee members'), you MUST populate the `extracted_list_items` array. Each element in this array should be an object containing structured fields like `item_title`, `item_detail`, and `item_url` (if applicable). Extract ALL relevant items you can find that match the goal.\n"
                    "    * If the `goal` asks for a single piece of specific text (e.g., 'the contact email address', 'the mission statement') or a general summary of the page/section, populate the `extracted_text_summary` field.\n"
                    "2.  **Assess Goal Achievement (`goal_achieved` field):**\n"
                    "    * Set `goal_achieved` to `true` if you successfully extract information that directly addresses the `goal`.\n"
                    "    * Set `goal_achieved` to `false` if the provided content does NOT contain the information needed to meet the `goal` (e.g., asking for 'latest news' on a page that has no news section, or asking for specific data points not present).\n"
                    "3.  **Provide Reasoning/Notes (`reasoning_notes` field):**\n"
                    "    * If `goal_achieved` is `false`, briefly explain why the goal could not be met from the content (e.g., 'The requested section was not found on the page', 'No articles matched the time criteria').\n"
                    "    * If `goal_achieved` is `true`, you can use this field for any brief, important notes about the extraction (e.g., 'Extracted top 5 headlines as page is very long', 'Timestamp format was inconsistent').\n"
                    "4.  **Accuracy and Completeness:** Strive for accuracy. If extracting a list, try to be comprehensive for the specified sections or criteria in the `goal`.\n"
                    f"Webpage Content (Markdown - may be truncated if very long):\n```markdown\n{truncated_markdown}\n```"
                )

                llm_response_message = await self.llm_instance.ask_tool(
                    messages=[Message(role=Role.USER, content=extraction_prompt_text)],
                    tools=extraction_tool_schema,
                    tool_choice={"type": "function", "function": {"name": "format_extracted_web_data"}},
                    model_purpose="general"
                )

                if llm_response_message and llm_response_message.tool_calls:
                    tool_call = llm_response_message.tool_calls[0]
                    if tool_call.function.name == "format_extracted_web_data":
                        try:
                            args = json.loads(tool_call.function.arguments or "{}")
                            args["source_url_of_extraction"] = page.url

                            output_dict_for_agent = {"goal": goal, **args}
                            output_json_str = json.dumps(output_dict_for_agent, indent=2)

                            if args.get("goal_achieved") is False:
                                error_msg = f"Extraction goal not achieved by LLM. Reasoning: {args.get('reasoning_notes', 'N/A')}"
                                logger.warning(f"BrowserUseTool: {error_msg} for goal '{goal}'")
                                return ToolResult(output=output_json_str, error=error_msg)

                            logger.info(f"BrowserUseTool: Extraction for '{goal}'. Goal Achieved: {args.get('goal_achieved')}. List items: {len(args.get('extracted_list_items',[]))}. Text summary present: {bool(args.get('extracted_text_summary'))}.")
                            return ToolResult(output=output_json_str)
                        except json.JSONDecodeError as e_json:
                            logger.error(f"BrowserUseTool: Failed to parse JSON from format_extracted_web_data arguments: {tool_call.function.arguments}, Error: {e_json}")
                            return ToolFailure(error=f"Internal error parsing extraction results: {e_json}")

                logger.warning(f"Content extraction for goal '{goal}' did not use 'format_extracted_web_data' tool as expected.")
                return ToolFailure(
                    error=f"Extraction LLM for goal '{goal}' failed to use the required formatting tool.",
                    output=f"Raw content (first {min(500, max_content_length)} chars of focused/full markdown): {truncated_markdown[:500]}..."
                )

            elif action == "switch_tab":
                if tab_id is None: return ToolFailure(error="Tab ID is required for 'switch_tab' action")
                await context.switch_to_tab(tab_id)
                new_page = await context.get_current_page()
                if new_page: await new_page.wait_for_load_state()
                return ToolResult(output=f"Switched to tab {tab_id}")

            elif action == "open_tab":
                if not url: return ToolFailure(error="URL is required for 'open_tab' action")
                await context.create_new_tab(url)
                return ToolResult(output=f"Opened new tab with {url}")

            elif action == "close_tab":
                closed_tab_id = await context.close_current_tab()
                return ToolResult(output=f"Closed current tab (ID was {closed_tab_id if closed_tab_id else 'N/A'}). New current page might be active.")

            elif action == "wait":
                seconds_to_wait = seconds if seconds is not None and seconds > 0 else 3
                await asyncio.sleep(seconds_to_wait)
                return ToolResult(output=f"Waited for {seconds_to_wait} seconds")

            elif action == "get_current_state_for_agent":
                 return await self.get_current_state(context=context)

            else:
                return ToolFailure(error=f"Unknown browser action: {action}")

        except ToolFailure as tf:
            logger.error(f"BrowserUseTool action '{action}' resulted in ToolFailure: {tf.error_message}")
            return tf
        except Exception as e:
            logger.exception(f"BrowserUseTool action '{action}' failed unexpectedly.")
            return ToolFailure(error=f"Browser action '{action}' failed with unexpected error: {str(e)}")

    async def get_current_state(self, context: Optional[BrowserContext] = None) -> ToolResult:
        try:
            ctx_to_use = context
            if not ctx_to_use:
                logger.warning("BrowserUseTool.get_current_state: Context was None. Attempting to ensure initialization.")
                ctx_to_use = await self._ensure_browser_initialized()

            if not ctx_to_use:
                return ToolFailure(error="Browser context could not be initialized for get_current_state.")

            page = await ctx_to_use.get_current_page()
            if not page :
                 logger.warning("BrowserUseTool.get_current_state: Page was None. Attempting to create a new page.")
                 await ctx_to_use.create_new_page_if_needed()
                 page = await ctx_to_use.get_current_page()
                 if not page:
                     return ToolFailure(error="No active page in browser context for get_current_state after attempting to create one.")

            if hasattr(page, 'is_closed') and page.is_closed():
                 logger.warning("BrowserUseTool.get_current_state: Page is closed. Attempting to create a new page.")
                 await ctx_to_use.create_new_page_if_needed()
                 page = await ctx_to_use.get_current_page()
                 if not page or page.is_closed():
                     return ToolFailure(error="Page remains closed or invalid after attempting to create a new one.")

            await page.bring_to_front()
            await page.wait_for_load_state(timeout=10000)

            state_data = None
            screenshot_base64 = None
            try:
                async def _get_page_state(): return await ctx_to_use.get_state()
                async def _get_screenshot():
                    return base64.b64encode(await page.screenshot(full_page=False, type="jpeg", quality=75, timeout=10000)).decode("utf-8")

                results = await asyncio.gather(
                    _get_page_state(),
                    _get_screenshot(),
                    return_exceptions=True
                )
                if isinstance(results[0], Exception):
                    logger.error(f"BrowserUseTool: Error calling ctx_to_use.get_state(): {results[0]}")
                    raise results[0]
                state_data = results[0]

                if isinstance(results[1], Exception):
                    logger.warning(f"BrowserUseTool: Error taking screenshot: {results[1]}")
                    screenshot_base64 = None
                else:
                    screenshot_base64 = results[1]

            except Exception as e_get_state_or_ss:
                logger.error(f"BrowserUseTool: Error during get_state or screenshot: {e_get_state_or_ss}. Returning partial state.")
                page_url, page_title = "ErrorFetchingURL", "ErrorFetchingTitle"
                try:
                    if page and not (hasattr(page, 'is_closed') and page.is_closed()):
                        page_url = page.url or "N/A"; page_title = await page.title() or "N/A"
                except Exception: pass

                error_state_dict = {
                    "url": page_url, "title": page_title, "tabs": [], "current_tab_id": None,
                    "help_text": "[index] denotes interactive element ID. Use these IDs for actions.",
                    "interactive_elements": f"Error retrieving interactive elements: {e_get_state_or_ss}",
                    "scroll_info": {"pixels_above": 0, "pixels_below": 0, "total_height": 0},
                    "viewport_height": 0, "page_error": f"Failed to fully update browser state: {e_get_state_or_ss}"
                }
                if screenshot_base64 is None:
                    try:
                        if page and not (hasattr(page, 'is_closed') and page.is_closed()):
                            ss_bytes = await page.screenshot(full_page=False, type="jpeg", quality=75, timeout=5000)
                            screenshot_base64 = base64.b64encode(ss_bytes).decode("utf-8")
                    except Exception as e_ss_fallback:
                        logger.warning(f"Screenshot fallback also failed: {e_ss_fallback}")

                return ToolResult(output=json.dumps(error_state_dict, indent=2), base64_image=screenshot_base64, error=f"Partial state due to error: {e_get_state_or_ss}")

            viewport_height = getattr(state_data.viewport_info, 'height', 0) if hasattr(state_data, 'viewport_info') and state_data.viewport_info else 0
            if not viewport_height and hasattr(ctx_to_use.config, "browser_window_size") and ctx_to_use.config.browser_window_size:
                viewport_height = ctx_to_use.config.browser_window_size.get("height", 0)

            pixels_above = getattr(state_data, 'pixels_above', 0)
            pixels_below = getattr(state_data, 'pixels_below', 0)
            scroll_info_dict = {
                "pixels_above": pixels_above, "pixels_below": pixels_below,
                "total_height": pixels_above + pixels_below + viewport_height
            }

            state_info_dict = {
                "url": getattr(state_data, 'url', 'N/A'), "title": getattr(state_data, 'title', 'N/A'),
                "tabs": [tab.model_dump() for tab in getattr(state_data, 'tabs', []) if hasattr(tab, 'model_dump')],
                "current_tab_id": getattr(state_data, 'current_tab_id', None),
                "help_text": "[index] denotes interactive element ID. Use these IDs for actions like click or input.",
                "interactive_elements": state_data.element_tree.clickable_elements_to_string() if hasattr(state_data, 'element_tree') and state_data.element_tree else "No interactive elements information available.",
                "scroll_info": scroll_info_dict, "viewport_height": viewport_height,
            }
            if hasattr(state_data, "error_message") and state_data.error_message:
                state_info_dict["page_error"] = state_data.error_message

            return ToolResult(output=json.dumps(state_info_dict, indent=2), base64_image=screenshot_base64)
        except Exception as e:
            logger.exception("Failed to get browser current state")
            return ToolFailure(error=f"Major failure in get_current_state: {str(e)}")


    async def cleanup(self):
        logger.info("BrowserUseTool: Starting cleanup...")
        async with self.async_lock:
            if self.browser_context is not None:
                try:
                    await self.browser_context.close()
                    logger.info("BrowserUseTool: Context closed.")
                except Exception as e:
                    logger.error(f"BrowserUseTool: Error closing context: {e}")
                finally:
                    self.browser_context = None

            if self.browser_instance is not None:
                try:
                    await self.browser_instance.close()
                    logger.info("BrowserUseTool: Browser closed.")
                except Exception as e:
                    logger.error(f"BrowserUseTool: Error closing browser: {e}")
                finally:
                    self.browser_instance = None
        logger.info("BrowserUseTool: Cleanup complete.")

    def __del__(self):
        if (hasattr(self, 'browser_instance') and self.browser_instance is not None) or \
           (hasattr(self, 'browser_context') and self.browser_context is not None):
            logger.warning("BrowserUseTool: __del__ called with active browser/context. Ensure async cleanup() is called explicitly by the application.")

    @classmethod
    def create_with_context(cls, tool_context: ContextT) -> "BrowserUseTool[ContextT]":
        tool = cls()
        tool.tool_context = tool_context
        return tool