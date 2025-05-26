# app/flow/planning.py
import json
import time
import re
import uuid
from enum import Enum
from typing import Dict, List, Optional, Union, Any, Tuple

from pydantic import Field, BaseModel

from app.agent.base import BaseAgent
from app.flow.base import BaseFlow
from app.llm import LLM, ModelPurpose
from app.logger import logger
from app.schema import AgentState, Message, ToolChoice, Role # Added Role
from app.tool.planning import PlanningTool # DRIM AI's PlanningTool (planning_manager)
from app.config import config as app_main_config
# Import planning prompts
from app.prompt.planning import PLANNING_SYSTEM_PROMPT, NEXT_STEP_PROMPT as PLANNING_NEXT_STEP_PROMPT

class PlanStepStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked" # Indicates an issue preventing progress

    @classmethod
    def get_all_statuses(cls) -> list[str]: return [s.value for s in cls]
    @classmethod
    def get_active_statuses(cls) -> list[str]: return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]
    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        return {
            cls.COMPLETED.value: "[X]",
            cls.IN_PROGRESS.value: "[->]",
            cls.BLOCKED.value: "[!]",
            cls.NOT_STARTED.value: "[ ]"
        }

class PlanningFlow(BaseFlow):
    llm: LLM = Field(default_factory=LLM)
    planning_tool: PlanningTool = Field(default_factory=PlanningTool) # This is planning_manager
    
    active_plan_id: str = Field(default_factory=lambda: f"drim_plan_{int(time.time())}_{uuid.uuid4().hex[:4]}")
    current_step_index: Optional[int] = Field(default=None, exclude=True)
    _executor_agent_keys: List[str] = Field(default_factory=list, exclude=True)

    plan_creation_llm_purpose: ModelPurpose = Field(default="simple", description="LLM purpose for initial plan creation.")
    plan_adaptation_llm_purpose: ModelPurpose = Field(default="simple", description="LLM purpose for plan adaptation if a step is blocked.")
    plan_finalization_llm_purpose: ModelPurpose = Field(default="simple", description="LLM purpose for final plan summarization.")

    max_adaptation_attempts: int = Field(default=2, description="Maximum attempts to adapt the plan if a step is blocked before halting.")

    def __init__(self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], 
                 executors: Optional[List[str]] = None,
                 plan_id: Optional[str] = None, **data: Any):
        if plan_id: data["active_plan_id"] = plan_id
        
        # Ensure planning_tool is an instance of DRIM AI's PlanningTool
        if "planning_tool" not in data or not isinstance(data["planning_tool"], PlanningTool):
            data["planning_tool"] = PlanningTool() # Default instantiation

        super().__init__(agents=agents, **data)
        
        if executors:
            self._executor_agent_keys = [key for key in executors if key in self.agents]
            if len(self._executor_agent_keys) != len(executors):
                logger.warning("DRIM AI PlanningFlow: Some specified executor keys not found in the provided agents.")
        else: 
            self._executor_agent_keys = list(self.agents.keys())

        if not self._executor_agent_keys and self.primary_agent_key:
             if self.primary_agent: self._executor_agent_keys = [str(self.primary_agent_key)]

        if not self._executor_agent_keys:
             raise ValueError("DRIM AI PlanningFlow requires at least one executor agent key that matches a provided agent.")
        logger.info(f"DRIM AI PlanningFlow initialized. Executors: {self._executor_agent_keys}. Plan ID: {self.active_plan_id}")

    def get_executor_agent(self, step_info: Optional[Dict[str, Any]] = None) -> BaseAgent:
        step_type_agent_key = step_info.get("type") if step_info else None
        if step_type_agent_key and step_type_agent_key in self._executor_agent_keys and step_type_agent_key in self.agents:
            logger.debug(f"DRIM AI PlanningFlow: Using executor '{step_type_agent_key}' based on step type.")
            return self.agents[step_type_agent_key]
        
        primary_agent_key_str = str(self.primary_agent_key) if self.primary_agent_key else None
        if primary_agent_key_str and primary_agent_key_str in self._executor_agent_keys and primary_agent_key_str in self.agents:
            logger.debug(f"DRIM AI PlanningFlow: Using primary agent '{primary_agent_key_str}' as executor.")
            return self.agents[primary_agent_key_str] 
        
        if self._executor_agent_keys and self._executor_agent_keys[0] in self.agents:
            first_executor_key = self._executor_agent_keys[0]
            logger.debug(f"DRIM AI PlanningFlow: Using first available executor '{first_executor_key}'.")
            return self.agents[first_executor_key]
        
        # Fallback if no specific executor found, try any agent (might not be ideal)
        if self.agents:
            first_available_agent_key = next(iter(self.agents))
            logger.warning(f"DRIM AI PlanningFlow: No specific executor found, falling back to first agent '{first_available_agent_key}'.")
            return self.agents[first_available_agent_key]
            
        raise RuntimeError("DRIM AI PlanningFlow: No suitable executor agent found.")

    async def _create_initial_plan_with_llm(self, user_request: str) -> None:
        logger.info(f"DRIM AI PlanningFlow: Creating initial plan (LLM Purpose: {self.plan_creation_llm_purpose}) for: '{user_request[:100]}...'")
        system_prompt_plan_creation = Message.system_message(PLANNING_SYSTEM_PROMPT)
        user_prompt_for_plan = Message.user_message(
            f"User Request: \"{user_request}\"\n\nBased on this request, please create a plan using the `{self.planning_tool.name}` tool with the `create` command. "
            f"The `plan_id` should be '{self.active_plan_id}'. Define a suitable `title` and a list of high-level `steps` (milestones)."
        )
        try:
            llm_response_message = await self.llm.ask_tool(
                messages=[user_prompt_for_plan],
                system_msgs=[system_prompt_plan_creation],
                tools=[self.planning_tool.to_param()], # Pass the tool schema
                tool_choice={"type": "function", "function": {"name": self.planning_tool.name}}, # Force use of planning_manager
                model_purpose=self.plan_creation_llm_purpose
            )
            
            if llm_response_message and llm_response_message.tool_calls:
                tool_call_processed = False
                for tool_call in llm_response_message.tool_calls:
                    if tool_call.function.name == self.planning_tool.name:
                        try:
                            args_str = tool_call.function.arguments
                            args = json.loads(args_str) if isinstance(args_str, str) else args_str
                            # Ensure command is 'create' and plan_id is correct
                            if args.get("command") != "create":
                                logger.warning(f"LLM tried to use command '{args.get('command')}' for initial plan creation. Forcing 'create'.")
                            args["command"] = "create" # Ensure it's a create command
                            args["plan_id"] = self.active_plan_id # Enforce the active plan ID
                            
                            logger.info(f"DRIM AI PlanningFlow: LLM proposed plan creation with args: {args}")
                            result = await self.planning_tool.execute(**args)
                            logger.info(f"DRIM AI PlanningFlow: Plan creation via tool result: {result.output if result and result.output else 'No output string'}")
                            tool_call_processed = True
                            break 
                        except Exception as e_tool:
                            logger.error(f"DRIM AI PlanningFlow: Error executing PlanningTool for plan creation: {e_tool}")
                if not tool_call_processed:
                     logger.warning("DRIM AI PlanningFlow: LLM responded but did not correctly use PlanningTool or tool call failed. Creating default plan.")
                     await self._create_default_plan(user_request)
            else:
                logger.warning("DRIM AI PlanningFlow: LLM did not use PlanningTool for initial plan. Creating default plan.")
                await self._create_default_plan(user_request)
        except Exception as e:
            logger.error(f"DRIM AI PlanningFlow: LLM failed to generate initial plan: {e}. Creating default plan.")
            await self._create_default_plan(user_request)

    async def _adapt_plan_with_llm(self, reason_for_adaptation: str) -> bool:
        """Attempts to adapt the current plan using the LLM if a step is blocked or an issue occurs."""
        logger.info(f"DRIM AI PlanningFlow: Attempting to adapt plan '{self.active_plan_id}' due to: {reason_for_adaptation} (LLM Purpose: {self.plan_adaptation_llm_purpose})")
        current_plan_text = await self._get_formatted_plan_text()
        if "Error: Plan ID" in current_plan_text or "not found" in current_plan_text: # Check if plan actually exists
            logger.error(f"DRIM AI PlanningFlow: Cannot adapt plan '{self.active_plan_id}' as it does not seem to exist or is not retrievable.")
            return False

        system_prompt_plan_adaptation = Message.system_message(PLANNING_SYSTEM_PROMPT)
        user_prompt_for_adaptation = Message.user_message(
            f"The current plan (ID: '{self.active_plan_id}') has encountered an issue: {reason_for_adaptation}\n\n"
            f"Current plan state:\n{current_plan_text}\n\n"
            f"Please analyze the situation and propose an update to the plan using the `{self.planning_tool.name}` tool with the `update` command. "
            f"You can modify the 'title' (if necessary) and 'steps'. Focus on how to overcome the current blockage or adjust the plan based on new information. "
            f"Ensure `plan_id` is '{self.active_plan_id}'."
        )

        try:
            llm_response_message = await self.llm.ask_tool(
                messages=[user_prompt_for_adaptation],
                system_msgs=[system_prompt_plan_adaptation],
                tools=[self.planning_tool.to_param()],
                tool_choice={"type": "function", "function": {"name": self.planning_tool.name}}, # Force use of planning_manager
                model_purpose=self.plan_adaptation_llm_purpose
            )

            if llm_response_message and llm_response_message.tool_calls:
                for tool_call in llm_response_message.tool_calls:
                    if tool_call.function.name == self.planning_tool.name:
                        try:
                            args_str = tool_call.function.arguments
                            args = json.loads(args_str) if isinstance(args_str, str) else args_str
                            if args.get("command") != "update":
                                logger.warning(f"LLM tried to use command '{args.get('command')}' for plan adaptation. Forcing 'update'.")
                            args["command"] = "update" # Ensure it's an update command
                            args["plan_id"] = self.active_plan_id # Enforce the active plan ID
                            
                            logger.info(f"DRIM AI PlanningFlow: LLM proposed plan adaptation with args: {args}")
                            result = await self.planning_tool.execute(**args)
                            logger.info(f"DRIM AI PlanningFlow: Plan adaptation via tool result: {result.output if result and result.output else 'No output string'}")
                            return True # Adaptation attempted
                        except Exception as e_tool:
                            logger.error(f"DRIM AI PlanningFlow: Error executing PlanningTool for plan adaptation: {e_tool}")
                            return False # Adaptation failed
            logger.warning(f"DRIM AI PlanningFlow: LLM did not use PlanningTool for plan adaptation.")
            return False # LLM didn't use the tool
        except Exception as e:
            logger.error(f"DRIM AI PlanningFlow: LLM failed to suggest plan adaptation: {e}")
            return False # LLM call itself failed

    async def _finalize_plan_with_llm(self) -> str:
        logger.info(f"DRIM AI PlanningFlow: Finalizing plan '{self.active_plan_id}' (LLM Purpose: {self.plan_finalization_llm_purpose}).")
        current_plan_text_final = await self._get_formatted_plan_text()
        try:
            system_finalization_prompt = Message.system_message(PLANNING_SYSTEM_PROMPT) # Re-use system prompt
            user_finalization_prompt = Message.user_message(
                f"The plan (ID: {self.active_plan_id}) has concluded. Current status:\n\n{current_plan_text_final}\n\n"
                "Please provide a concise summary of what was accomplished and any final thoughts based on the plan's outcome."
            )
            response_str = await self.llm.ask(
                messages=[user_finalization_prompt],
                system_msgs=[system_finalization_prompt],
                model_purpose=self.plan_finalization_llm_purpose
            )
            return f"DRIM AI Plan '{self.active_plan_id}' Conclusion:\n{response_str}"
        except Exception as e:
            logger.error(f"DRIM AI PlanningFlow: Error finalizing plan with LLM: {e}. Using agent fallback or plan text.")
            # Fallback to primary agent for summary if LLM fails
            primary_agent_for_summary = self.primary_agent
            if primary_agent_for_summary:
                try:
                    summary_prompt_for_agent = (
                        f"The plan (ID: {self.active_plan_id}) has been completed or halted. "
                        f"Final plan status:\n{current_plan_text_final}\n\n"
                        f"As the primary agent ({primary_agent_for_summary.name}), please provide a summary of what was accomplished and any final thoughts."
                    )
                    agent_summary = await primary_agent_for_summary.run(request=summary_prompt_for_agent)
                    return f"DRIM AI Plan '{self.active_plan_id}' Conclusion (via agent {primary_agent_for_summary.name}):\n{agent_summary}"
                except Exception as e2:
                    logger.error(f"DRIM AI PlanningFlow: Error finalizing plan with agent '{primary_agent_for_summary.name}': {e2}")
            return f"DRIM AI Plan '{self.active_plan_id}' concluded. Final status:\n{current_plan_text_final}"

    async def execute(self, input_text: str, **kwargs: Any) -> str:
        logger.info(f"DRIM AI PlanningFlow: Starting execution for request: '{input_text[:100]}...'")
        execution_summary_parts: List[str] = []
        adaptation_attempts_left = self.max_adaptation_attempts

        try:
            if not self.primary_agent and not self._executor_agent_keys : # Need at least one agent for the flow to function
                raise ValueError("DRIM AI PlanningFlow: No primary agent or executor agents configured.")
            
            if input_text: # Create plan if initial input is given
                await self._create_initial_plan_with_llm(input_text)
                if self.active_plan_id not in self.planning_tool.plans:
                    err_msg = f"DRIM AI PlanningFlow: Initial plan creation failed. Plan ID '{self.active_plan_id}' not found."
                    logger.error(err_msg)
                    return f"Failed to create plan for: {input_text}. Error: {err_msg}"
                execution_summary_parts.append(f"Initial plan created for: '{input_text}'. Plan ID: {self.active_plan_id}")
                plan_text = await self._get_formatted_plan_text()
                if plan_text: execution_summary_parts.append(f"Initial Plan:\n{plan_text}")

            loop_count = 0 
            # Determine a reasonable max_loops based on the number of agents or a configured default
            # Using a simple heuristic for now.
            max_loops = (self.agents[self._executor_agent_keys[0]].max_steps if self._executor_agent_keys and self._executor_agent_keys[0] in self.agents else 10) * 5 

            while loop_count < max_loops:
                loop_count += 1
                self.current_step_index, current_step_info = await self._get_next_pending_step_info()

                if self.current_step_index is None: # No more actionable (not_started or in_progress) steps
                    logger.info("DRIM AI PlanningFlow: No more actionable steps in the current plan.")
                    final_summary = await self._finalize_plan_with_llm()
                    execution_summary_parts.append(final_summary)
                    break 
                
                logger.info(f"DRIM AI PlanningFlow: Executing Step {self.current_step_index +1}: {current_step_info.get('text', 'N/A') if current_step_info else 'N/A'}")
                if not current_step_info: 
                    logger.error("DRIM AI PlanningFlow: Current step info is None. This indicates a critical error in plan state.")
                    execution_summary_parts.append("Error: Inconsistent plan state. Cannot proceed.")
                    break
                
                executor_agent = self.get_executor_agent(current_step_info)
                step_execution_result_summary = await self._execute_plan_step(executor_agent, current_step_info)
                execution_summary_parts.append(f"\n--- Step {self.current_step_index + 1} ('{current_step_info.get('text', '')[:50]}...') Result ---\n{step_execution_result_summary}")

                # Check current step status after execution attempt
                current_step_status = await self._get_step_status(self.current_step_index)

                if current_step_status == PlanStepStatus.BLOCKED:
                    logger.warning(f"DRIM AI PlanningFlow: Step {self.current_step_index + 1} is BLOCKED.")
                    if adaptation_attempts_left > 0:
                        adaptation_attempts_left -= 1
                        reason = f"Step {self.current_step_index + 1} ('{current_step_info.get('text','N/A')}') is blocked. Notes: {await self._get_step_notes(self.current_step_index)}"
                        logger.info(f"Attempting plan adaptation ({adaptation_attempts_left} attempts remaining). Reason: {reason}")
                        execution_summary_parts.append(f"Step blocked. Attempting to adapt plan. Reason: {reason}")
                        adaptation_succeeded = await self._adapt_plan_with_llm(reason)
                        if adaptation_succeeded:
                            plan_text_after_adapt = await self._get_formatted_plan_text()
                            execution_summary_parts.append(f"Plan adapted successfully. New Plan State:\n{plan_text_after_adapt}")
                            logger.info("Plan adapted. Continuing execution loop.")
                            continue # Re-evaluate next step with the adapted plan
                        else:
                            logger.error("Plan adaptation failed. Halting flow.")
                            execution_summary_parts.append("Plan adaptation failed. Halting execution.")
                            break
                    else:
                        logger.error("Max plan adaptation attempts reached. Halting flow.")
                        execution_summary_parts.append("Max plan adaptation attempts reached. Halting execution.")
                        break

                if executor_agent.state == AgentState.FINISHED: # Agent used Terminate
                    logger.info(f"DRIM AI PlanningFlow: Executor '{executor_agent.name}' finished the task (used Terminate). Ending flow.")
                    if self.current_step_index is not None and current_step_status != PlanStepStatus.COMPLETED : # Ensure step is marked if agent terminated
                         await self._mark_step_as_status(self.current_step_index, PlanStepStatus.COMPLETED, notes="Completed as agent terminated successfully.")
                    final_summary = await self._finalize_plan_with_llm() # Finalize based on current plan state
                    execution_summary_parts.append(final_summary)
                    break
                elif executor_agent.state == AgentState.ERROR:
                    logger.error(f"DRIM AI PlanningFlow: Executor '{executor_agent.name}' in ERROR state. Halting.")
                    execution_summary_parts.append(f"Error: Agent '{executor_agent.name}' encountered an error and halted.")
                    if self.current_step_index is not None and current_step_status != PlanStepStatus.BLOCKED:
                         await self._mark_step_as_status(self.current_step_index, PlanStepStatus.BLOCKED, notes="Agent error during execution.")
                    break
            
            if loop_count >= max_loops:
                logger.warning("DRIM AI PlanningFlow: Max execution loops reached. Finalizing.")
                execution_summary_parts.append("Warning: Flow reached maximum loop limit.")
                final_summary = await self._finalize_plan_with_llm()
                execution_summary_parts.append(final_summary)

            return "\n".join(execution_summary_parts)
        except Exception as e:
            logger.exception("DRIM AI PlanningFlow: Unhandled error during flow execution.")
            return f"DRIM AI PlanningFlow Execution failed unexpectedly: {str(e)}"

    async def _create_default_plan(self, request_text: str):
        default_plan_args = {
            "command": "create", 
            "plan_id": self.active_plan_id,
            "title": f"Default Plan for: {request_text[:50]}{'...' if len(request_text) > 50 else ''}",
            "steps": ["Understand user request", "Execute primary task based on request", "Verify task completion and finalize"]
        }
        try:
            result = await self.planning_tool.execute(**default_plan_args)
            logger.info(f"DRIM AI PlanningFlow: Default plan created. Result: {result.output if result and result.output else 'No output string'}")
        except Exception as e: 
            logger.error(f"DRIM AI PlanningFlow: Critical error creating default plan: {e}")
            # Manually create a very basic plan in memory if tool fails catastrophically
            self.planning_tool.plans[self.active_plan_id] = {
                "plan_id": self.active_plan_id, "title": default_plan_args["title"], "steps": default_plan_args["steps"],
                "step_statuses": ["not_started"] * len(default_plan_args["steps"]), 
                "step_notes": [""] * len(default_plan_args["steps"]), 
            }
            self.planning_tool.active_plan_id_internal = self.active_plan_id


    async def _get_next_pending_step_info(self) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        if not self.active_plan_id or self.active_plan_id not in self.planning_tool.plans:
            logger.error(f"DRIM AI PlanningFlow: Active plan '{self.active_plan_id}' not found in planning_tool.plans.")
            return None, None
        try:
            plan_data = self.planning_tool.plans[self.active_plan_id]
            steps_list: List[str] = plan_data.get("steps", [])
            step_statuses: List[str] = plan_data.get("step_statuses", [])
            
            for i, step_text in enumerate(steps_list):
                # Ensure status list is long enough, default to not_started if missing
                status = step_statuses[i] if i < len(step_statuses) else PlanStepStatus.NOT_STARTED.value
                if status in PlanStepStatus.get_active_statuses(): # Check if "not_started" or "in_progress"
                    step_info = {"text": step_text, "original_index": i}
                    # Try to extract step type from text like "[TYPE] Description"
                    match = re.search(r"^\s*\[([A-Za-z_]+)\]\s*(.*)", step_text) # Adjusted regex
                    if match: 
                        step_info["type"] = match.group(1).lower() # Agent key or type
                        step_info["text"] = match.group(2).strip() # Actual task text
                    
                    # Mark step as IN_PROGRESS only if it was NOT_STARTED
                    if status == PlanStepStatus.NOT_STARTED.value:
                        await self._mark_step_as_status(i, PlanStepStatus.IN_PROGRESS)
                    return i, step_info
            return None, None # No actionable steps found
        except Exception as e:
            logger.exception(f"DRIM AI PlanningFlow: Error finding next pending step for plan '{self.active_plan_id}'.")
            return None, None

    async def _execute_plan_step(self, executor_agent: BaseAgent, step_info: Dict[str, Any]) -> str:
        if self.current_step_index is None: return "Error: No current step index to execute."
        
        current_plan_text_for_context = await self._get_formatted_plan_text()
        step_text_to_execute = step_info.get("text", f"Unnamed Step {self.current_step_index + 1}")
        
        # Construct a more contextual prompt for the executor agent
        agent_task_prompt = (
            f"DRIM AI PlanningFlow Context:\n"
            f"Current Overall Plan Status (Plan ID: '{self.active_plan_id}'):\n{current_plan_text_for_context}\n\n"
            f"Your Assigned Task for DRIM AI:\n"
            f"You are now working on Step {self.current_step_index + 1} (0-indexed: {self.current_step_index}): \"{step_text_to_execute}\"\n"
            f"Please execute this specific step using your available tools.\n"
            f"Provide a clear summary of what you accomplished for this step.\n"
            f"If this step successfully completes the entire user request as outlined in the plan, use your '{Terminate().name}' tool with status 'success'.\n"
            f"If you encounter an issue you cannot resolve for this step, clearly explain the problem. The PlanningFlow may attempt to adapt the plan."
        )
        
        logger.info(f"DRIM AI PlanningFlow: Passing task to agent '{executor_agent.name}' for step {self.current_step_index + 1}: '{step_text_to_execute[:50]}...'")
        
        try:
            # Store current agent state to revert if it's not FINISHED or ERROR
            previous_agent_state = executor_agent.state
            if executor_agent.state != AgentState.IDLE: executor_agent.state = AgentState.IDLE # Ensure agent is ready

            step_outcome_summary = await executor_agent.run(request=agent_task_prompt)
            
            # If agent didn't set its state to FINISHED or ERROR, revert to its previous state or IDLE
            if executor_agent.state not in [AgentState.FINISHED, AgentState.ERROR]:
                executor_agent.state = previous_agent_state if previous_agent_state != AgentState.RUNNING else AgentState.IDLE


            if executor_agent.state != AgentState.ERROR and not str(step_outcome_summary).lower().startswith("error"):
                 # If agent used Terminate(success), its state would be FINISHED.
                 # If it just returned text, assume step is done.
                 await self._mark_step_as_status(self.current_step_index, PlanStepStatus.COMPLETED, notes=f"Outcome: {step_outcome_summary[:100]}")
            else: # Agent error or step_outcome_summary indicates error
                error_note = f"Agent {executor_agent.name} reported error or failed: {step_outcome_summary[:100]}"
                await self._mark_step_as_status(self.current_step_index, PlanStepStatus.BLOCKED, notes=error_note)

            return step_outcome_summary
        except Exception as e:
            logger.exception(f"DRIM AI PlanningFlow: Agent '{executor_agent.name}' raised an exception during step {self.current_step_index + 1}.")
            await self._mark_step_as_status(self.current_step_index, PlanStepStatus.BLOCKED, notes=f"Agent execution raised exception: {str(e)}")
            return f"Error executing step {self.current_step_index + 1} by agent '{executor_agent.name}': {str(e)}"

    async def _mark_step_as_status(self, step_idx: int, status: PlanStepStatus, notes: Optional[str] = None) -> None:
        if step_idx is None: 
            logger.warning("DRIM AI PlanningFlow: Attempted to mark step status with None index.")
            return
        
        logger.info(f"DRIM AI PlanningFlow: Marking step {step_idx + 1} (0-indexed: {step_idx}) in plan '{self.active_plan_id}' as '{status.value}'. Notes: {notes or 'None'}")
        try:
            # The PlanningTool's execute method is async
            await self.planning_tool.execute(
                command="mark_step", 
                plan_id=self.active_plan_id, 
                step_index=step_idx, # planning_tool expects 0-indexed
                step_status=status.value, 
                step_notes=notes
            )
        except Exception as e:
            logger.error(f"DRIM AI PlanningFlow: CRITICAL - Failed to update plan status via PlanningTool for step {step_idx} to {status.value}: {e}. Attempting manual update.")
            # Fallback: Manually update in-memory plan if tool call fails
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                if "step_statuses" in plan_data and 0 <= step_idx < len(plan_data["step_statuses"]):
                    plan_data["step_statuses"][step_idx] = status.value
                if notes and "step_notes" in plan_data and 0 <= step_idx < len(plan_data.get("step_notes",[])): # type: ignore
                    plan_data.get("step_notes", [])[step_idx] = notes # type: ignore
                logger.warning("DRIM AI PlanningFlow: Manually updated plan status in memory due to tool execution failure.")

    async def _get_step_status(self, step_idx: int) -> Optional[PlanStepStatus]:
        if step_idx is None or not self.active_plan_id or self.active_plan_id not in self.planning_tool.plans:
            return None
        plan_data = self.planning_tool.plans[self.active_plan_id]
        statuses = plan_data.get("step_statuses", [])
        if 0 <= step_idx < len(statuses):
            return PlanStepStatus(statuses[step_idx])
        return None

    async def _get_step_notes(self, step_idx: int) -> Optional[str]:
        if step_idx is None or not self.active_plan_id or self.active_plan_id not in self.planning_tool.plans:
            return None
        plan_data = self.planning_tool.plans[self.active_plan_id]
        notes_list = plan_data.get("step_notes", [])
        if 0 <= step_idx < len(notes_list):
            return notes_list[step_idx]
        return None

    async def _get_formatted_plan_text(self) -> str:
        try:
            # The PlanningTool's execute method is async
            result = await self.planning_tool.execute(command="get", plan_id=self.active_plan_id)
            if result and result.output and isinstance(result.output, str):
                return result.output
            logger.warning(f"DRIM AI PlanningFlow: PlanningTool 'get' for plan '{self.active_plan_id}' returned no string output. Result: {result}")
            return self._generate_plan_text_from_tool_storage() # Fallback
        except Exception as e:
            logger.error(f"DRIM AI PlanningFlow: Error getting plan text from PlanningTool: {e}. Generating from storage.")
            return self._generate_plan_text_from_tool_storage()

    def _generate_plan_text_from_tool_storage(self) -> str:
        # This is a synchronous fallback, used if the async tool call fails.
        if self.active_plan_id not in self.planning_tool.plans:
            return f"DRIM AI Error: Plan ID '{self.active_plan_id}' not found in tool's storage."
        try:
            plan_data = self.planning_tool.plans[self.active_plan_id]
            # Delegate to the tool's internal formatting method if it exists and is callable
            if hasattr(self.planning_tool, '_format_plan_for_display') and callable(getattr(self.planning_tool, '_format_plan_for_display')):
                 return self.planning_tool._format_plan_for_display(plan_data)
            else: # Basic fallback if tool's formatter isn't available
                return json.dumps(plan_data, indent=2)
        except Exception as e:
            logger.error(f"DRIM AI PlanningFlow: Error generating plan text from tool storage: {e}")
            return f"DRIM AI Error: Unable to retrieve/format plan '{self.active_plan_id}' from storage."