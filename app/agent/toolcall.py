# File: app/agent/toolcall.py
import asyncio
import json
import re
import uuid
from typing import Any, List, Optional, Union

from pydantic import Field
from google.api_core import exceptions as google_api_core_exceptions # For ResourceExhausted

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded, ToolError, LLMResponseError, DRIMAIFrameworkError
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT as TOOLCALL_NEXT_STEP_PROMPT_TEMPLATE
from app.prompt.toolcall import SYSTEM_PROMPT as TOOLCALL_SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice, Function, Role
from app.tool import CreateChatCompletion, Terminate, ToolCollection, ToolResult, BrowserUseTool
from app.llm import LLM, ModelPurpose

TOOL_CALL_REQUIRED_ERROR_MSG = "Tool calls required by agent logic but none were provided by LLM"

class ToolCallAgent(ReActAgent):
    name: str = Field(default="drim_toolcall_agent")
    description: str = Field(default="A DRIM AI agent that can execute tool calls using an LLM.")
    
    system_prompt: str = Field(default=TOOLCALL_SYSTEM_PROMPT)
    next_step_prompt: str = Field(default=TOOLCALL_NEXT_STEP_PROMPT_TEMPLATE)

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(CreateChatCompletion(), Terminate(), BrowserUseTool())
    )
    tool_choices: TOOL_CHOICE_TYPE = Field(default=ToolChoice.AUTO) # type: ignore
    special_tool_names: List[str] = Field(
        default_factory=lambda: [Terminate().name]
    )
    
    current_tool_calls_internal: List[ToolCall] = Field(default_factory=list, exclude=True)
    current_base64_image_internal: Optional[str] = Field(default=None, exclude=True)
    
    max_steps: int = Field(default=15)
    max_observe: Optional[int] = Field(default=10000, description="Max characters of tool observation to keep.")

    llm: LLM = Field(default_factory=LLM)
    default_llm_purpose: ModelPurpose = Field(default="simple", description="Default model purpose for LLM calls in think().")

    async def think(self) -> bool:
        self.current_tool_calls_internal = []

        current_messages = self.memory.messages.copy()
        
        if self.next_step_prompt:
            current_prompt_message = Message.user_message(
                self.next_step_prompt,
                base64_image=self.current_base64_image_internal
            )
            current_messages.append(current_prompt_message)
            if self.current_base64_image_internal:
                logger.info(f"Agent '{self.name}': Including current screenshot with next step prompt to LLM.")
            self.current_base64_image_internal = None

        system_message_content = self.system_prompt
        system_messages_for_llm = [Message.system_message(system_message_content)] if system_message_content else None
        
        llm_response_message_from_api: Optional[Message] = None
        try:
            model_to_use_purpose = self.default_llm_purpose
            if current_messages and current_messages[-1].role == Role.USER and current_messages[-1].base64_image:
                model_to_use_purpose = "multimodal"
                logger.info(f"Agent '{self.name}': Image detected in prompt to LLM, using LLM purpose: {model_to_use_purpose}")

            logger.info(f"Agent '{self.name}' thinking with tools. Tool choice: {self.tool_choices}. LLM Purpose: {model_to_use_purpose}")
            llm_response_message_from_api = await self.llm.ask_tool(
                messages=current_messages,
                system_msgs=system_messages_for_llm,
                tools=self.available_tools.to_params(),
                tool_choice=self.tool_choices,
                model_purpose=model_to_use_purpose
            )

        except TokenLimitExceeded as e:
            logger.error(f"Token limit exceeded for agent '{self.name}': {e}")
            self.memory.add_message(Message.assistant_message(content=f"Token limit error: {str(e)}"))
            self.state = AgentState.FINISHED; return False
        except LLMResponseError as e:
            logger.error(f"LLM response error during think for agent '{self.name}': {e}")
            self.memory.add_message(Message.assistant_message(content=f"LLM Response Error: {str(e)}"))
            self.state = AgentState.ERROR; return False
        except DRIMAIFrameworkError as e:
             logger.exception(f"DRIM AI Framework error during LLM call for agent '{self.name}': {e}")
             self.memory.add_message(Message.assistant_message(content=f"LLM Error: {str(e)}"))
             self.state = AgentState.ERROR; return False
        except Exception as e:
            logger.exception(f"Unexpected LLM communication error during think for agent '{self.name}': {e}")
            self.memory.add_message(Message.assistant_message(content=f"LLM Error: {str(e)}"))
            self.state = AgentState.ERROR; return False

        if llm_response_message_from_api:
            direct_tool_calls = llm_response_message_from_api.tool_calls or []
            llm_textual_thought = llm_response_message_from_api.content or ""
            parsed_tool_calls_from_content: List[ToolCall] = []

            if not direct_tool_calls and llm_textual_thought:
                logger.debug(f"Agent '{self.name}' had no direct tool calls, checking thought content for JSON: {llm_textual_thought[:200]}...")
                try:
                    json_to_parse = llm_textual_thought
                    json_block_match = re.search(r"```json\s*(\{.*?\})\s*```", llm_textual_thought, re.DOTALL)
                    if json_block_match:
                        json_to_parse = json_block_match.group(1)
                    
                    parsed_llm_json_output = json.loads(json_to_parse)
                    llm_textual_thought = parsed_llm_json_output.get("thought", llm_textual_thought)
                    actions_list = parsed_llm_json_output.get("tool_calls", parsed_llm_json_output.get("actions", []))

                    if isinstance(actions_list, list):
                        for action_data in actions_list:
                            tool_name = action_data.get("name") or action_data.get("tool")
                            tool_args_dict = action_data.get("arguments")
                            if tool_args_dict is None and tool_name:
                                tool_args_dict = {k:v for k,v in action_data.items() if k not in ["tool", "name"]}
                            
                            if tool_name and tool_name in self.available_tools.tool_map:
                                tool_call_id = f"json_content_call_{uuid.uuid4().hex[:8]}"
                                parsed_tool_calls_from_content.append(
                                    ToolCall(id=tool_call_id, type="function",
                                             function=Function(name=tool_name, arguments=json.dumps(tool_args_dict or {})))
                                )
                            elif tool_name: logger.warning(f"LLM JSON thought specified unknown/unavailable tool: {tool_name}")
                except json.JSONDecodeError: logger.warning(f"Could not parse JSON actions from LLM thought content (JSONDecodeError). Thought: {llm_textual_thought[:250]}")
                except Exception as e_parse: logger.warning(f"Error attempting to parse actions from LLM thought content: {e_parse}. Thought: {llm_textual_thought[:250]}")

            # ** MODIFICATION START **
            final_tool_calls_for_memory: Optional[List[ToolCall]] = None
            if direct_tool_calls:
                final_tool_calls_for_memory = direct_tool_calls
                self.current_tool_calls_internal = direct_tool_calls # For act() method
                logger.info(f"Agent '{self.name}' using DIRECT tool calls from LLM.")
            elif parsed_tool_calls_from_content:
                final_tool_calls_for_memory = parsed_tool_calls_from_content
                self.current_tool_calls_internal = parsed_tool_calls_from_content # For act() method
                logger.info(f"Agent '{self.name}' using PARSED tool calls from LLM thought content.")
            else:
                self.current_tool_calls_internal = [] # For act() method
            
            assistant_message_to_memory = Message(
                role=Role.ASSISTANT,
                content=llm_textual_thought if llm_textual_thought and llm_textual_thought.strip() else None,
                tool_calls=final_tool_calls_for_memory
            )
            self.memory.add_message(assistant_message_to_memory)
            # ** MODIFICATION END **

            logger.info(f"Agent '{self.name}' (processed) thoughts: {llm_textual_thought if llm_textual_thought else 'No textual thought.'}")
            if self.current_tool_calls_internal: # Check the instance variable for logging and return decision
                logger.info(f"Agent '{self.name}' (final selection) has {len(self.current_tool_calls_internal)} tool(s) to execute: {[call.function.name for call in self.current_tool_calls_internal]}")
                for tc in self.current_tool_calls_internal: logger.debug(f"Tool: {tc.function.name}, Args: {tc.function.arguments}")
            else: logger.info(f"Agent '{self.name}' (final selection) selected no tools for this turn.")
            
            if self.tool_choices == ToolChoice.NONE and self.current_tool_calls_internal:
                logger.warning(f"Agent '{self.name}' LLM tried to use tools when tool_choice was 'none'. Ignoring calls."); self.current_tool_calls_internal = []; return bool(llm_textual_thought.strip())

            return bool(self.current_tool_calls_internal or (llm_textual_thought and llm_textual_thought.strip() and llm_textual_thought != "LLM provided no textual thought or response was not valid JSON."))
        else:
            logger.error(f"Agent '{self.name}' received no response message from LLM API call."); self.memory.add_message(Message.assistant_message(content="Error: No response from LLM API call.")); self.state = AgentState.ERROR; return False

    async def act(self) -> str:
        if not self.current_tool_calls_internal:
            last_msg = self.memory.messages[-1] if self.memory.messages else None
            if last_msg and last_msg.role == Role.ASSISTANT:
                return last_msg.content or "No content and no tool commands to execute."
            return "No tool commands to execute and no final assistant message found."

        results_summary: List[str] = []
        for tool_call_command in self.current_tool_calls_internal:
            self.current_base64_image_internal = None
            tool_execution_result_str = await self.execute_tool(tool_call_command)
            if self.max_observe and isinstance(tool_execution_result_str, str): tool_execution_result_str = tool_execution_result_str[:self.max_observe]
            logger.info(f"Tool '{tool_call_command.function.name}' executed. Result snippet: {tool_execution_result_str[:100]}...")
            tool_response_msg = Message.tool_message(content=tool_execution_result_str, tool_call_id=tool_call_command.id, name=tool_call_command.function.name, base64_image=self.current_base64_image_internal)
            self.memory.add_message(tool_response_msg); results_summary.append(tool_execution_result_str)
            self.current_base64_image_internal = None
            if self.state == AgentState.FINISHED: logger.info(f"Agent '{self.name}' processing halted by special tool '{tool_call_command.function.name}'."); break
        self.current_tool_calls_internal = []
        return "\n\n".join(results_summary) if results_summary else "No tool results."

    async def execute_tool(self, command: ToolCall) -> str:
        if not command or not command.function or not command.function.name: logger.error("Invalid tool command format received."); return "Error: Invalid command format"
        tool_name = command.function.name; tool_args_json_str = command.function.arguments or "{}"
        if tool_name not in self.available_tools.tool_map: logger.error(f"Unknown tool '{tool_name}' called."); return f"Error: Unknown tool '{tool_name}'"
        try:
            tool_input_args = json.loads(tool_args_json_str)
            logger.info(f"Agent '{self.name}' activating tool: '{tool_name}' with args: {tool_input_args}")
            tool_result_obj: Any = await self.available_tools.execute(name=tool_name, tool_input=tool_input_args)
            await self._handle_special_tool(name=tool_name, result=tool_result_obj)
            if hasattr(tool_result_obj, "base64_image") and tool_result_obj.base64_image: self.current_base64_image_internal = tool_result_obj.base64_image
            else: self.current_base64_image_internal = None
            observation = str(tool_result_obj)
            observation_str = observation if observation is not None else "Tool executed with no textual output."
            return f"Observed output of tool {tool_name}: \n{observation_str}" if observation_str.strip() else f"Tool {tool_name} completed with no significant output."
        except json.JSONDecodeError: error_msg = f"Error parsing arguments for tool {tool_name}: Invalid JSON. Args: {tool_args_json_str}"; logger.error(error_msg); return f"Error: {error_msg}"
        except ToolError as te: logger.error(f"Tool '{tool_name}' failed with ToolError: {te.message}"); return f"Error executing {tool_name}: {te.message}"
        except Exception as e: error_msg = f"Tool '{tool_name}' encountered an unexpected problem: {str(e)}"; logger.exception(error_msg); return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs: Any):
        if not self._is_special_tool(name): return
        if name.lower() == Terminate().name.lower():
            if self._should_finish_execution(name=name, result=result, **kwargs):
                logger.info(f"Special tool '{name}' indicates task completion. Agent '{self.name}' state set to FINISHED."); self.state = AgentState.FINISHED
        if isinstance(result, ToolResult) and result.base64_image:
            logger.info(f"Tool '{name}' returned an image. It has been associated with the tool's response message.")

    def _should_finish_execution(self, name:str, result: Any, **kwargs: Any) -> bool: 
        if name.lower() == Terminate().name.lower(): return True
        return False

    def _is_special_tool(self, name: str) -> bool:
        return name.lower() in [n.lower() for n in self.special_tool_names]

    async def cleanup(self):
        logger.info(f"Cleaning up resources for agent '{self.name}'...")
        if hasattr(self.available_tools, "cleanup_all") and callable(self.available_tools.cleanup_all):
            await self.available_tools.cleanup_all() # type: ignore
        else:
            for tool_name, tool_instance in self.available_tools.tool_map.items():
                if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(tool_instance.cleanup):
                    try: logger.debug(f"Cleaning up tool: {tool_name}"); await tool_instance.cleanup()
                    except Exception as e: logger.error(f"Error cleaning up tool '{tool_name}': {e}", exc_info=True)
        logger.info(f"Cleanup complete for agent '{self.name}'.")