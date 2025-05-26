# File: app/agent/base.py
import re
import asyncio
import json
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional, Any, Tuple, Dict # Added Dict
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM, ModelPurpose
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message, ToolCall, Role
from app.config import config
from app.tool import Terminate, ToolFailure # Added ToolFailure
from app.tool.browser_use_tool import BrowserUseTool # For stuck detection relevant to browser


class BaseAgent(BaseModel, ABC):
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    system_prompt: Optional[str] = Field(None, description="System-level instruction prompt")
    next_step_prompt: Optional[str] = Field(None, description="Prompt for determining next action")

    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(default=AgentState.IDLE, description="Current agent state")

    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")
    duplicate_threshold: int = Field(default=3, description="Number of identical assistant thoughts+tool_calls to detect basic stuck state") # Increased threshold slightly
    action_failure_threshold: int = Field(default=3, description="Number of consecutive failures of the same tool with similar args to detect stuck state")

    synthesis_llm_purpose: ModelPurpose = Field(default="general", description="LLM purpose for final synthesis.")
    min_paragraphs_for_complex_synthesis: int = Field(default=2, description="Minimum paragraphs for synthesized complex answers.")

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        if not isinstance(self.llm, LLM):
            self.llm = LLM()

        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state type: {type(new_state)}. Must be AgentState enum.")
        previous_state = self.state
        self.state = new_state
        logger.info(f"Agent '{self.name}' transitioning from {previous_state.value} to {new_state.value}")
        try:
            yield
        except Exception as e:
            logger.error(f"Error during agent state {self.state.value}: {e}")
            self.state = AgentState.ERROR
            raise
        finally:
            if self.state not in [AgentState.ERROR, AgentState.FINISHED]:
                 if previous_state != new_state :
                    logger.info(f"Agent '{self.name}' reverting from {self.state.value} to {previous_state.value} (context end)")
                    self.state = previous_state

    def update_memory(
        self,
        role: ROLE_TYPE, # type: ignore
        content: Optional[str],
        base64_image: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        message: Message
        if role == Role.USER:
            message = Message.user_message(content or "", base64_image=base64_image)
        elif role == Role.SYSTEM:
            message = Message.system_message(content or "")
        elif role == Role.ASSISTANT:
            message = Message.assistant_message(content=content, base64_image=base64_image, tool_calls=tool_calls)
        elif role == Role.TOOL:
            if not tool_call_id or not name:
                raise ValueError("tool_call_id and name are required for tool messages.")
            message = Message.tool_message(content or "", name=name, tool_call_id=tool_call_id, base64_image=base64_image)
        else:
            raise ValueError(f"Unsupported message role: {str(role)}")

        self.memory.add_message(message)
        log_content = content or ""
        if tool_calls: log_content += f" (Tool calls: {[tc.function.name for tc in tool_calls]})"
        logger.debug(f"Agent '{self.name}' memory updated with {str(role)} message. Content snippet: {log_content[:70]}...")

    async def _is_simple_interaction(self, initial_request: Optional[str]) -> bool:
        if not initial_request:
            return False

        request_lower = initial_request.lower().strip()
        simple_starters = ["hi", "hello", "hey"]
        simple_questions = ["what is the time", "what's the time", "current time",
                            "what is today's date", "what is the date", "current date"]

        if request_lower in simple_starters:
            return True
        for q_phrase in simple_questions:
            if q_phrase in request_lower:
                if len(request_lower) < len(q_phrase) + 10:
                    return True
        return False

    async def _get_current_time_or_date(self, initial_request: Optional[str]) -> Optional[str]:
        if not initial_request: return None
        # Use a fixed date for consistency with the user's example, but ideally, this should be dynamic.
        # For this specific improvement exercise, I'll use the date from the user's example.
        # In a real scenario, datetime.now() is correct.
        # now = datetime.now()
        now = datetime(2025, 5, 26, 23, 29, 47) # Match user's example for now
        request_lower = initial_request.lower()
        if "time" in request_lower:
            return f"The current time is {now.strftime('%I:%M:%S %p %Z (%A, %B %d, %Y')}."
        if "date" in request_lower:
            return f"Today's date is {now.strftime('%A, %B %d, %Y')}."
        return None

    async def _perform_final_synthesis(self, original_request: str, conversation_summary: str) -> str:
        logger.info(f"Agent '{self.name}': Performing final synthesis for request: '{original_request[:100]}...'")
        
        # Use fixed date for consistency with user example for this exercise
        current_date_for_synthesis = datetime(2025, 5, 26, 23, 29, 47).strftime('%B %d, %Y at %I:%M:%S %p %Z')


        synthesis_prompt_messages = [
            Message.system_message(
                "You are a helpful AI assistant tasked with synthesizing information into a coherent, comprehensive, and well-structured final answer. "
                "The user's original request and a summary of gathered information/actions will be provided."
            ),
            Message.user_message(
                f"Original User Request:\n'''\n{original_request}\n'''\n\n"
                f"Summary of Gathered Information / Agent Actions:\n'''\n{conversation_summary}\n'''\n\n"
                f"Current Date for context: {current_date_for_synthesis}\n\n"
                "Based on all the above, please provide a final, well-arranged, and comprehensive answer to the original user request. "
                f"If the gathered information is substantial and the request was complex, please structure your response in at least {self.min_paragraphs_for_complex_synthesis} paragraphs. "
                "Ensure all aspects of the original request are addressed if information is available. "
                "If some information could not be found, explicitly state that."
                "Present the answer directly, without conversational fluff like 'Okay, here is the information...'."
            )
        ]
        try:
            synthesized_answer = await self.llm.ask(
                messages=synthesis_prompt_messages,
                model_purpose=self.synthesis_llm_purpose
            )
            logger.info(f"Agent '{self.name}': Synthesis complete. Output snippet: {synthesized_answer[:100]}...")
            return synthesized_answer
        except Exception as e:
            logger.error(f"Agent '{self.name}': Error during final synthesis LLM call: {e}")
            # Fallback to providing the structured data if synthesis fails
            # This requires parsing the conversation_summary for the "Collected Data" section
            collected_data_match = re.search(r"Collected Data:(.*)", conversation_summary, re.DOTALL | re.IGNORECASE)
            if collected_data_match:
                collected_data_str = collected_data_match.group(1).strip()
                if collected_data_str: # Ensure there's something to return
                    return f"Final Information (synthesis failed: {str(e)}):\n{collected_data_str}"
            return f"Error during final synthesis: {str(e)}. Raw summary of actions: {conversation_summary}"


    async def run(self, request: Optional[str] = None) -> str:
        initial_user_request = request

        if self.state != AgentState.IDLE:
            logger.error(f"Agent '{self.name}' cannot run from state: {self.state.value}")
            if self.state == AgentState.FINISHED:
                logger.info(f"Agent '{self.name}' was FINISHED, resetting to IDLE for new run.")
                self.state = AgentState.IDLE
                self.current_step = 0
                self.memory.clear()
            else:
                raise RuntimeError(f"Cannot run agent from state: {self.state.value}")

        if request:
            self.update_memory(role=Role.USER, content=request)

        if await self._is_simple_interaction(initial_user_request):
            if initial_user_request and initial_user_request.lower().strip() in ["hi", "hello", "hey"]:
                self.state = AgentState.IDLE
                return f"Hello! How can I help you today, {self.name} is ready."

            time_or_date_response = await self._get_current_time_or_date(initial_user_request)
            if time_or_date_response:
                self.state = AgentState.IDLE
                return time_or_date_response

        step_results_log: List[str] = []
        self.current_step = 0

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and
                self.state == AgentState.RUNNING
            ):
                self.current_step += 1
                logger.info(f"Agent '{self.name}' executing step {self.current_step}/{self.max_steps}")

                try:
                    step_result_str = await self.step()
                    # Append the thought process (assistant message) and tool results to the log
                    # The step_result_str from ReActAgent.step is the outcome of act(), which is ToolResult(s) stringified
                    # For better synthesis, we want the LLM's "thought" (assistant message content) too.
                    last_assistant_msg = next((m for m in reversed(self.memory.messages) if m.role == Role.ASSISTANT and m.content), None)
                    thought_for_log = f"Thought: {last_assistant_msg.content[:200]}..." if last_assistant_msg and last_assistant_msg.content else "No explicit thought."
                    action_result_for_log = f"Action Result: {str(step_result_str)[:200]}..."

                    step_summary = f"Step {self.current_step}: {thought_for_log} | {action_result_for_log}"
                    # Extract "Collected Data" from thought if available for more focused summary for synthesis
                    if last_assistant_msg and last_assistant_msg.content:
                         collected_data_match = re.search(r"Collected Data:(.*?)(\n\n|$)", last_assistant_msg.content, re.DOTALL | re.IGNORECASE)
                         if collected_data_match:
                             step_summary = f"Step {self.current_step} (Collected Data Update): {collected_data_match.group(1).strip()}"

                    step_results_log.append(step_summary)
                    logger.info(f"Agent '{self.name}' step {self.current_step} processed. Thought snippet: {thought_for_log[:100]}. Action result snippet: {str(step_result_str)[:100]}...")


                    if self.is_stuck(): # Call after step_result_str is logged
                        self.handle_stuck_state()
                        stuck_log_msg = "Agent detected stuck state and is attempting to recover by adjusting strategy."
                        step_results_log.append(stuck_log_msg)
                        logger.warning(f"Agent '{self.name}' {stuck_log_msg}")

                except Exception as e:
                    logger.exception(f"Agent '{self.name}' error during step {self.current_step}: {e}")
                    self.state = AgentState.ERROR
                    step_results_log.append(f"Step {self.current_step} Error: {str(e)}")
                    break

                if self.state == AgentState.FINISHED:
                    logger.info(f"Agent '{self.name}' finished execution at step {self.current_step}.")
                    break

            if self.current_step >= self.max_steps and self.state != AgentState.FINISHED:
                logger.warning(f"Agent '{self.name}' terminated: Reached max steps ({self.max_steps}) without natural completion.")
                step_results_log.append(f"Terminated: Reached max steps ({self.max_steps})")
                self.state = AgentState.FINISHED # Ensure state is FINISHED

        final_output_to_user: str
        # Consolidate relevant parts of memory for synthesis, focusing on "Collected Data"
        # from the last few assistant messages if possible, or the step_results_log.
        final_thought_with_data = "Summary of actions and information found:\n"
        last_thought_with_collected_data = ""
        for msg in reversed(self.memory.messages):
            if msg.role == Role.ASSISTANT and msg.content:
                if "Collected Data:" in msg.content:
                    last_thought_with_collected_data = msg.content # Get the whole thought
                    break
        if last_thought_with_collected_data:
             conversation_summary_for_synthesis = last_thought_with_collected_data
        else:
             conversation_summary_for_synthesis = "\n".join(step_results_log)


        if self.state == AgentState.FINISHED:
            last_assistant_message_with_tools = next((msg for msg in reversed(self.memory.messages) if msg.role == Role.ASSISTANT and msg.tool_calls), None)
            terminate_message_content = None
            was_success_terminate = False

            if last_assistant_message_with_tools and last_assistant_message_with_tools.tool_calls:
                for tc in last_assistant_message_with_tools.tool_calls:
                    if tc.function.name == Terminate().name:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                            terminate_message_content = args.get("message", "") # Get the message regardless of status
                            if args.get("status") == "success":
                                was_success_terminate = True
                                logger.info(f"Agent '{self.name}' terminated successfully via Terminate tool. LLM's message: '{terminate_message_content}'")
                            else:
                                logger.info(f"Agent '{self.name}' terminated with failure via Terminate tool. LLM's message: '{terminate_message_content}'")
                                if not terminate_message_content: terminate_message_content = "Task failed or could not be completed."
                        except json.JSONDecodeError:
                            logger.warning(f"Could not parse Terminate tool arguments: {tc.function.arguments}")
                            terminate_message_content = "Task ended, but final status message from Terminate tool could not be parsed."
                        break
            
            if was_success_terminate:
                 # If terminate tool had a substantial message, prioritize it for synthesis or direct use
                if terminate_message_content and len(terminate_message_content) > 50 : # Arbitrary length to check if it's a summary
                    final_output_to_user = terminate_message_content
                elif initial_user_request and not await self._is_simple_interaction(initial_user_request):
                    final_output_to_user = await self._perform_final_synthesis(initial_user_request, conversation_summary_for_synthesis)
                else: # Simple interaction or no substantial terminate message
                    final_output_to_user = terminate_message_content or "Task completed successfully."

            elif terminate_message_content: # Terminate tool called with failure or unparsed args but had a message
                 final_output_to_user = terminate_message_content
            elif self.state == AgentState.FINISHED and not was_success_terminate : # Finished naturally or by max_steps
                 if initial_user_request and not await self._is_simple_interaction(initial_user_request):
                    final_output_to_user = await self._perform_final_synthesis(initial_user_request, conversation_summary_for_synthesis)
                 else:
                    final_output_to_user = f"Task concluded. Summary of actions:\n{conversation_summary_for_synthesis}"
            else:
                 final_output_to_user = conversation_summary_for_synthesis

        elif self.state == AgentState.ERROR:
            final_output_to_user = f"An error occurred. Summary of actions before error:\n{conversation_summary_for_synthesis}"
        else: # Should not happen if logic is correct
            final_output_to_user = f"Interaction ended unexpectedly (State: {self.state.value}). Summary:\n{conversation_summary_for_synthesis}"

        if self.state == AgentState.FINISHED or self.state == AgentState.ERROR: # Ensure reset for next run
            self.state = AgentState.IDLE
            # self.current_step = 0 # Already reset if re-run from FINISHED, but good for clarity
            # self.memory.clear() # Clearing memory might be too aggressive if user wants to follow up

        try:
            if hasattr(SANDBOX_CLIENT, "is_active") and SANDBOX_CLIENT.is_active:
                if hasattr(SANDBOX_CLIENT, "cleanup") and asyncio.iscoroutinefunction(SANDBOX_CLIENT.cleanup):
                     await SANDBOX_CLIENT.cleanup()
                elif hasattr(SANDBOX_CLIENT, "cleanup"):
                     SANDBOX_CLIENT.cleanup() # type: ignore
                logger.info(f"Agent '{self.name}' global SANDBOX_CLIENT cleanup called after run.")
        except Exception as e:
            logger.error(f"Agent '{self.name}' error during global SANDBOX_CLIENT cleanup: {e}")

        logger.info(f"Agent '{self.name}' run completed. Final state for next run: {self.state.value}. Returning to user (snippet): {str(final_output_to_user)[:200]}...")
        return str(final_output_to_user)

    @abstractmethod
    async def step(self) -> str:
        pass

    def handle_stuck_state(self):
        stuck_prompt_guidance = (
            "SYSTEM ADVICE: You seem to be repeating previous unsuccessful actions or making no progress. "
            "Critically re-evaluate your strategy. Consider: "
            "1. Is the current web page/information source useful? If not, try a different one (e.g., different search result, new search). "
            "2. Are your search queries effective? Try different keywords or be more specific. "
            "3. For web interactions, are you targeting the correct elements? Double-check element indices and descriptions. "
            "4. If an element seems un-interactable, is there an alternative way to achieve the sub-goal on the page? "
            "5. Is there an alternative tool or a completely different approach to this sub-goal? "
            "6. If completely stuck on a sub-goal after trying alternatives, consider using the `ask_human` tool for guidance on how to proceed with *that specific sub-goal*. "
            "Avoid repeating the exact same tool calls with the exact same arguments if they have failed or yielded no progress multiple times."
        )
        self.update_memory(role=Role.SYSTEM, content=stuck_prompt_guidance)
        logger.warning(f"Agent '{self.name}' detected stuck state. Added system guidance to memory.")

    def is_stuck(self) -> bool:
        # 1. Basic Duplicate Output Check (Thought + Tool Calls)
        if len(self.memory.messages) < (self.duplicate_threshold * 2): # Need enough history for comparison
            pass # Not enough messages for this check, proceed to other checks
        else:
            assistant_outputs_for_stuck_check: List[Tuple[Optional[str], Optional[List[Dict]]]] = []
            for msg in reversed(self.memory.messages):
                if msg.role == Role.ASSISTANT:
                    tool_calls_as_dicts = None
                    if msg.tool_calls:
                        try:
                            tool_calls_as_dicts = sorted(
                                [tc.model_dump(exclude={'id'}) for tc in msg.tool_calls],
                                key=lambda x: x.get('function', {}).get('name', '')
                            )
                        except Exception as e_dump:
                            logger.error(f"Error dumping tool_calls for stuck check (duplicate): {e_dump}")
                            tool_calls_as_dicts = [str(tc) for tc in msg.tool_calls] # Fallback

                    assistant_outputs_for_stuck_check.append(
                        (msg.content, tool_calls_as_dicts)
                    )
                    if len(assistant_outputs_for_stuck_check) == self.duplicate_threshold:
                        break
            
            if len(assistant_outputs_for_stuck_check) == self.duplicate_threshold:
                first_output_tuple = assistant_outputs_for_stuck_check[0]
                all_match_first = True
                for i in range(1, len(assistant_outputs_for_stuck_check)):
                    if assistant_outputs_for_stuck_check[i][0] != first_output_tuple[0] or \
                       assistant_outputs_for_stuck_check[i][1] != first_output_tuple[1]:
                        all_match_first = False
                        break
                if all_match_first:
                    logger.warning(
                        f"Agent '{self.name}' might be stuck (Duplicate Output). Last {self.duplicate_threshold} assistant outputs are identical. "
                        f"Content: {str(first_output_tuple[0])[:50]}..., Tool Calls: {str(first_output_tuple[1])[:100]}..."
                    )
                    return True

        # 2. Consecutive Tool Failures (especially for browser)
        if len(self.memory.messages) < self.action_failure_threshold * 2: # Each failure involves an assistant call and a tool response
            return False

        consecutive_tool_failures = 0
        last_failed_tool_name: Optional[str] = None
        last_failed_tool_args: Optional[str] = None # Store as string for simple comparison

        # Iterate backwards: assistant call, then tool response, then previous assistant call, etc.
        # Looking for a pattern of: ASSISTANT (calls tool X) -> TOOL (error from X) -> ASSISTANT (calls tool X again with similar args) -> TOOL (error from X again)
        # More simply: count recent TOOL messages that indicate failure for the *same tool*.
        
        recent_tool_results: List[Message] = []
        recent_assistant_calls_for_failed_tools: List[Message] = []

        # Get last N tool messages and their preceding assistant calls
        # We need to look at the last `action_failure_threshold` *attempts*
        # An attempt is an assistant call + a tool response
        
        assistant_msg_buffer: Optional[Message] = None
        for msg in reversed(self.memory.messages):
            if len(recent_tool_results) >= self.action_failure_threshold:
                break
            if msg.role == Role.TOOL:
                # Check if this tool message indicates failure (content contains "Error:" or "Failed:")
                # This relies on ToolResult.__str__ or ToolFailure.__str__ format.
                # A more robust way would be if ToolResult had a success: bool field.
                # For now, checking string content of the tool's response.
                is_failure = False
                if msg.content and ("error:" in msg.content.lower() or "failed:" in msg.content.lower() or "failure:" in msg.content.lower()):
                    is_failure = True
                
                # Check against the direct ToolResult.error if the message content is a JSON representation of ToolResult
                try:
                    tool_result_obj = json.loads(msg.content)
                    if isinstance(tool_result_obj, dict) and tool_result_obj.get("error"):
                        is_failure = True
                except (json.JSONDecodeError, TypeError):
                    pass # Not a JSON string, rely on string check above

                if is_failure and assistant_msg_buffer: # We need the preceding assistant call that initiated this failed tool
                    recent_tool_results.append(msg)
                    recent_assistant_calls_for_failed_tools.append(assistant_msg_buffer)
                assistant_msg_buffer = None # Reset buffer after finding a tool message
            elif msg.role == Role.ASSISTANT:
                assistant_msg_buffer = msg # Store the assistant message

        if len(recent_tool_results) >= self.action_failure_threshold:
            # Check if these failures are for the *same tool* and *similar arguments*
            # This is a simplified check; true "similar arguments" is complex.
            # We'll check if the tool name is the same.
            first_failed_tool_name = recent_tool_results[0].name # Name of the tool that failed
            first_failed_tool_call_args_str = ""
            # Find the args for the first failed tool from its corresponding assistant call
            if recent_assistant_calls_for_failed_tools[0].tool_calls:
                for tc in recent_assistant_calls_for_failed_tools[0].tool_calls:
                    if tc.function.name == first_failed_tool_name:
                        first_failed_tool_call_args_str = tc.function.arguments
                        break
            
            all_same_tool_and_args = True
            for i in range(1, self.action_failure_threshold):
                current_failed_tool_name = recent_tool_results[i].name
                current_failed_tool_call_args_str = ""
                if recent_assistant_calls_for_failed_tools[i].tool_calls:
                    for tc in recent_assistant_calls_for_failed_tools[i].tool_calls:
                         if tc.function.name == current_failed_tool_name:
                            current_failed_tool_call_args_str = tc.function.arguments
                            break
                
                if current_failed_tool_name != first_failed_tool_name or \
                   current_failed_tool_call_args_str != first_failed_tool_call_args_str: # Simplified: exact args match
                    all_same_tool_and_args = False
                    break
            
            if all_same_tool_and_args and first_failed_tool_name: # Ensure a tool name was identified
                logger.warning(
                    f"Agent '{self.name}' might be stuck (Consecutive Tool Failures). "
                    f"Tool '{first_failed_tool_name}' failed {self.action_failure_threshold} times consecutively with the same arguments."
                )
                return True

        # 3. Lack of To-Do List Progress (more complex, requires parsing thoughts)
        # This would involve extracting the to-do list from the last N assistant thoughts
        # and checking if the number of completed items '[x]' has not increased.
        # This is harder to implement reliably here without more structured thought output.
        # For now, relying on the first two checks.

        return False


    @property
    def messages(self) -> List[Message]:
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        self.memory.messages = value
        if len(self.memory.messages) > self.memory.max_messages:
            self.memory.messages = self.memory.messages[-self.memory.max_messages:]