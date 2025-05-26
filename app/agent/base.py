# File: app/agent/base.py
import re
import asyncio
import json # <<< --- ADDED THIS IMPORT ---
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional, Any, Tuple # Added Tuple
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM, ModelPurpose
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message, ToolCall, Role
from app.config import config
from app.tool import Terminate


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
    duplicate_threshold: int = Field(default=2, description="Number of identical assistant messages to detect stuck state")
    
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
        now = datetime.now()
        request_lower = initial_request.lower()
        if "time" in request_lower:
            return f"The current time is {now.strftime('%I:%M:%S %p %Z (%A, %B %d, %Y')}."
        if "date" in request_lower:
            return f"Today's date is {now.strftime('%A, %B %d, %Y')}."
        return None

    async def _perform_final_synthesis(self, original_request: str, conversation_summary: str) -> str:
        logger.info(f"Agent '{self.name}': Performing final synthesis for request: '{original_request[:100]}...'")
        
        synthesis_prompt_messages = [
            Message.system_message(
                "You are a helpful AI assistant tasked with synthesizing information into a coherent, comprehensive, and well-structured final answer. "
                "The user's original request and a summary of gathered information/actions will be provided."
            ),
            Message.user_message(
                f"Original User Request:\n'''\n{original_request}\n'''\n\n"
                f"Summary of Gathered Information / Agent Actions:\n'''\n{conversation_summary}\n'''\n\n"
                f"Current Date for context: {datetime.now().strftime('%B %d, %Y at %I:%M:%S %p %Z')}\n\n"
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
            return f"Error during final synthesis: {str(e)}. Raw summary: {conversation_summary}"


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
                    step_results_log.append(f"Step {self.current_step}: {step_result_str}")
                    logger.info(f"Agent '{self.name}' step {self.current_step} result snippet: {str(step_result_str)[:100]}...")

                    if self.is_stuck():
                        self.handle_stuck_state() 
                        step_results_log.append("Agent detected stuck state and is attempting to recover by adjusting strategy.")
                        logger.warning(f"Agent '{self.name}' adjusted strategy due to stuck state.")
                        
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
                self.state = AgentState.FINISHED

        final_output_to_user: str
        conversation_summary_for_synthesis = "\n".join(step_results_log)

        if self.state == AgentState.FINISHED:
            last_assistant_message = next((msg for msg in reversed(self.memory.messages) if msg.role == Role.ASSISTANT and msg.tool_calls), None)
            terminate_message_content = None
            was_success_terminate = False

            if last_assistant_message and last_assistant_message.tool_calls:
                for tc in last_assistant_message.tool_calls:
                    if tc.function.name == Terminate().name:
                        try:
                            args = json.loads(tc.function.arguments or "{}") # Error was here
                            if args.get("status") == "success":
                                was_success_terminate = True
                                terminate_message_content = args.get("message", "") 
                                logger.info(f"Agent '{self.name}' terminated successfully via Terminate tool. LLM's message: '{terminate_message_content}'")
                            else:
                                terminate_message_content = f"Task failed or could not be completed. Reason: {args.get('message', 'No specific reason provided by agent.')}"
                                logger.info(f"Agent '{self.name}' terminated with failure via Terminate tool. LLM's message: '{args.get('message')}'")
                        except json.JSONDecodeError: # Catching the potential error
                            logger.warning(f"Could not parse Terminate tool arguments: {tc.function.arguments}")
                            was_success_terminate = False # Treat as non-success if args can't be parsed
                            terminate_message_content = "Task ended, but final status message from Terminate tool could not be parsed."
                        break 
            
            if was_success_terminate:
                if initial_user_request and not await self._is_simple_interaction(initial_user_request): 
                    context_for_synthesis = conversation_summary_for_synthesis
                    if terminate_message_content and len(terminate_message_content) > 50: 
                        context_for_synthesis = (
                            f"Agent's preliminary summary from Terminate tool: {terminate_message_content}\n\n"
                            f"Additional context from agent's actions:\n{conversation_summary_for_synthesis}"
                        )
                    final_output_to_user = await self._perform_final_synthesis(initial_user_request, context_for_synthesis)
                elif terminate_message_content: 
                    final_output_to_user = terminate_message_content
                else: 
                    final_output_to_user = "Task completed successfully."
            elif terminate_message_content: 
                 final_output_to_user = terminate_message_content
            elif self.state == AgentState.FINISHED and not was_success_terminate : 
                 final_output_to_user = f"Task concluded. Summary of actions:\n{conversation_summary_for_synthesis}"
            else: # Should ideally not be reached if state is FINISHED
                 final_output_to_user = conversation_summary_for_synthesis

        elif self.state == AgentState.ERROR:
            final_output_to_user = f"An error occurred. Summary of actions before error:\n{conversation_summary_for_synthesis}"
        else: 
            final_output_to_user = f"Interaction ended unexpectedly. Summary:\n{conversation_summary_for_synthesis}"
            if self.state != AgentState.IDLE: self.state = AgentState.IDLE

        if self.state == AgentState.FINISHED:
            self.state = AgentState.IDLE
        
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
            "1. Is the current web page/information source useful? If not, try a different one. "
            "2. Are your search queries effective? Try different keywords or be more specific. "
            "3. Is there an alternative tool or approach? "
            "4. If completely stuck, consider using the `ask_human` tool for guidance. "
            "Avoid repeating the exact same tool calls with the exact same arguments if they have failed previously."
        )
        self.update_memory(role=Role.SYSTEM, content=stuck_prompt_guidance)
        logger.warning(f"Agent '{self.name}' detected stuck state. Added system guidance to memory: '{stuck_prompt_guidance}'")

    def is_stuck(self) -> bool:
        if len(self.memory.messages) < (self.duplicate_threshold * 2): 
            return False

        assistant_outputs_for_stuck_check: List[Tuple[Optional[str], Optional[List[Dict]]]] = []
        for msg in reversed(self.memory.messages):
            if msg.role == Role.ASSISTANT:
                tool_calls_as_dicts = None
                if msg.tool_calls:
                    try:
                        # Exclude 'id' for comparison, sort by function name for consistent ordering
                        tool_calls_as_dicts = sorted(
                            [tc.model_dump(exclude={'id'}) for tc in msg.tool_calls], 
                            key=lambda x: x.get('function', {}).get('name', '')
                        )
                    except Exception as e_dump:
                        logger.error(f"Error dumping tool_calls for stuck check: {e_dump}")
                        # Fallback: use string representation of tool_calls if dumping fails
                        tool_calls_as_dicts = [str(tc) for tc in msg.tool_calls]


                assistant_outputs_for_stuck_check.append(
                    (msg.content, tool_calls_as_dicts)
                )
                if len(assistant_outputs_for_stuck_check) == self.duplicate_threshold:
                    break
        
        if len(assistant_outputs_for_stuck_check) < self.duplicate_threshold:
            return False 

        first_output_tuple = assistant_outputs_for_stuck_check[0]
        for i in range(1, len(assistant_outputs_for_stuck_check)):
            # Perform a more robust comparison for tool_calls if they are list of dicts
            if assistant_outputs_for_stuck_check[i][0] != first_output_tuple[0]: # Compare content
                return False
            
            # Compare tool_calls (which are now lists of dicts or strings)
            if isinstance(first_output_tuple[1], list) and isinstance(assistant_outputs_for_stuck_check[i][1], list):
                if len(first_output_tuple[1]) != len(assistant_outputs_for_stuck_check[i][1]):
                    return False
                # Assuming tool_calls_as_dicts are sorted lists of dicts (or strings if dump failed)
                if first_output_tuple[1] != assistant_outputs_for_stuck_check[i][1]:
                    return False
            elif first_output_tuple[1] != assistant_outputs_for_stuck_check[i][1]: # Handles None or string comparison
                 return False

        logger.warning(
            f"Agent '{self.name}' might be stuck. Last {self.duplicate_threshold} assistant outputs (thought + tool calls) are identical. "
            f"Content: {str(first_output_tuple[0])[:50]}..., Tool Calls: {str(first_output_tuple[1])[:100]}..."
        )
        return True

    @property
    def messages(self) -> List[Message]:
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        self.memory.messages = value
        if len(self.memory.messages) > self.memory.max_messages:
            self.memory.messages = self.memory.messages[-self.memory.max_messages:]