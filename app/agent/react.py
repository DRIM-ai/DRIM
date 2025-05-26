from abc import ABC, abstractmethod # [Source: 81]
from typing import Optional

from pydantic import Field

from app.agent.base import BaseAgent # [Source: 81]
from app.llm import LLM # Ensures it uses the Gemini LLM
from app.schema import AgentState, Memory # [Source: 81]
from app.logger import logger

class ReActAgent(BaseAgent, ABC): # [Source: 81]
    # Fields are inherited from BaseAgent or explicitly defined if different defaults needed
    # name, description, system_prompt, next_step_prompt, llm, memory, state, max_steps, current_step
    # are already in BaseAgent. Explicitly re-listing them here might be for clarity or
    # if ReActAgent intends to have different default factories or descriptions.
    # Given the PDF, it seems to re-declare them.

    # Re-declaring with Pydantic Field if we want to override or set specific defaults for ReActAgent
    # If defaults are same as BaseAgent, these re-declarations can be omitted.
    # For safety and explicitness from PDF:
    name: str = Field(default="react_agent", description="Name of the ReAct agent") # Default name for ReAct type
    description: Optional[str] = Field(default="A ReAct agent that reasons and acts.", description="Description of the ReAct agent") # [Source: 81]
    system_prompt: Optional[str] = Field(default=None, description="System prompt for the ReAct agent") # [Source: 81]
    next_step_prompt: Optional[str] = Field(default="What should I think/do next?", description="Prompt for the next ReAct step") # [Source: 81]

    llm: LLM = Field(default_factory=LLM, description="LLM instance for ReAct agent") # [Source: 81]
    memory: Memory = Field(default_factory=Memory, description="Memory for ReAct agent") # [Source: 81]
    state: AgentState = Field(default=AgentState.IDLE, description="State of the ReAct agent") # [Source: 82]
    max_steps: int = Field(default=10, description="Max steps for ReAct agent") # [Source: 82]
    current_step: int = Field(default=0, description="Current step for ReAct agent") # [Source: 82]


    @abstractmethod
    async def think(self) -> bool: # [Source: 82]
        """
        Process current state and decide next action (reasoning step).
        Returns True if an action should be taken, False otherwise.
        This method should populate necessary information for the act() step,
        often by interacting with the LLM.
        """
        pass

    @abstractmethod
    async def act(self) -> str: # [Source: 82]
        """
        Execute decided actions based on the think() step.
        Returns a string summarizing the action's outcome.
        """
        pass

    async def step(self) -> str: # [Source: 83]
        """Execute a single step: think and act."""
        logger.info(f"Agent '{self.name}' (ReAct) thinking...")
        should_act = await self.think()

        if not should_act:
            # If think() determines no action is needed, it might mean the goal is reached
            # or it needs more user input, or it's waiting.
            # The ReAct loop usually expects an action if not finished.
            # This might be a place where an agent decides it's finished.
            logger.info(f"Agent '{self.name}' (ReAct) decided no action is needed after thinking.")
            # If self.state is not already FINISHED by think(), this means it's a pause or completion.
            if self.state != AgentState.FINISHED:
                 # If think didn't finish, but no action, it might be an issue or a deliberate pause.
                 # For now, we assume think() would set FINISHED if applicable.
                 pass
            return "Thinking complete, no immediate action to perform." # [Source: 83]

        logger.info(f"Agent '{self.name}' (ReAct) acting...")
        action_result = await self.act()
        return action_result

# Role in the System (Updated for DRIM AI)
# As part of the agent subsystem, this script contributes to the core
# intelligence and decision-making capabilities of DRIM AI. [Source: 84] The agent
# components collectively enable the system to understand tasks,
# formulate plans, and execute actions to achieve user goals. [Source: 84]