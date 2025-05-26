from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, Any # [Source: 144]

from pydantic import BaseModel, ConfigDict # [Source: 144]

from app.agent.base import BaseAgent # DRIM AI's BaseAgent [Source: 144]
from app.logger import logger

class BaseFlow(BaseModel, ABC): # [Source: 144]
    """
    Base class for DRIM AI execution flows, supporting one or more agents.
    Orchestrates sequences of agent actions to achieve broader goals.
    """
    agents: Dict[str, BaseAgent] = {} # Agent key to BaseAgent instance [Source: 144]
    # Tools here might refer to tools shared across the flow, or specific to flow logic,
    # distinct from tools an individual agent might have.
    # The PDF shows `tools: Optional[List] = None`. Type List[Any] or List[BaseTool]
    # if these are DRIM AI tools. For now, keeping as List[Any].
    shared_tools: Optional[List[Any]] = None # Renamed from 'tools' for clarity [Source: 144]
    primary_agent_key: Optional[str] = None # [Source: 144]

    model_config = ConfigDict(arbitrary_types_allowed=True) # [Source: 144] (Pydantic V2)

    def __init__(self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data: Any): # [Source: 144]
        # Pydantic V2 handles initialization differently.
        # We should use a model_validator or pass processed agents via data.
        # For now, let's process agents and pass them in `data` for super().__init__.
        
        agents_dict: Dict[str, BaseAgent]
        if isinstance(agents, BaseAgent): # [Source: 144]
            agents_dict = {"default_agent": agents} # Changed "default" to "default_agent" for clarity
        elif isinstance(agents, list): # [Source: 144]
            if not all(isinstance(ag, BaseAgent) for ag in agents):
                raise ValueError("All items in agents list must be BaseAgent instances.")
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)} # [Source: 144]
        elif isinstance(agents, dict): # [Source: 144]
            if not all(isinstance(ag, BaseAgent) for ag in agents.values()):
                raise ValueError("All values in agents dict must be BaseAgent instances.")
            agents_dict = agents
        else:
            raise TypeError(f"Unsupported type for 'agents': {type(agents)}. Expected BaseAgent, List[BaseAgent], or Dict[str, BaseAgent].")

        # If primary_agent_key is not provided in data, and not already set, determine it.
        primary_key_to_set = data.get("primary_agent_key", None) # [Source: 145]
        if not primary_key_to_set and agents_dict: # [Source: 145]
            primary_key_to_set = next(iter(agents_dict)) # [Source: 145]
        
        # Update data dictionary before calling super().__init__
        data_for_super = {**data, "agents": agents_dict}
        if primary_key_to_set:
            data_for_super["primary_agent_key"] = primary_key_to_set
            
        super().__init__(**data_for_super) # [Source: 146] (Pydantic will use these values)
        logger.info(f"DRIM AI BaseFlow initialized with agents: {list(self.agents.keys())}. Primary: {self.primary_agent_key}")


    @property
    def primary_agent(self) -> Optional[BaseAgent]: # [Source: 146]
        """Get the primary agent for the DRIM AI flow."""
        if self.primary_agent_key:
            return self.agents.get(self.primary_agent_key) # [Source: 146]
        # Fallback if primary_agent_key somehow not set but agents exist (should be handled in init)
        if self.agents:
            # This could be non-deterministic if dict order changes in older Pythons
            # but init should set primary_agent_key.
            logger.warning("DRIM AI BaseFlow: primary_agent_key not set, attempting to use first available agent as primary.")
            return next(iter(self.agents.values()), None)
        return None

    def get_agent(self, key: str) -> Optional[BaseAgent]: # [Source: 146]
        """Get a specific DRIM AI agent by key from the flow."""
        return self.agents.get(key) # [Source: 146]

    def add_agent(self, key: str, agent: BaseAgent) -> None: # [Source: 146]
        """Add a new DRIM AI agent to the flow."""
        if not isinstance(agent, BaseAgent):
            raise ValueError("Agent to add must be an instance of BaseAgent.")
        if key in self.agents:
            logger.warning(f"DRIM AI BaseFlow: Overwriting agent with key '{key}'.")
        self.agents[key] = agent # [Source: 146]
        if not self.primary_agent_key: # If no primary agent was set, make the first added one primary.
            self.primary_agent_key = key
            logger.info(f"DRIM AI BaseFlow: Agent '{key}' added and set as primary.")
        else:
            logger.info(f"DRIM AI BaseFlow: Agent '{key}' added.")


    @abstractmethod
    async def execute(self, input_text: str, **kwargs: Any) -> str: # [Source: 146] Added kwargs
        """
        Execute the DRIM AI flow with the given input text.
        Args:
            input_text: The initial input or request to start the flow.
            kwargs: Additional parameters specific to the flow's execution.
        Returns:
            A string summarizing the execution results or final output of the flow.
        """
        pass

# Role in the System (Updated for DRIM AI)
# As part of the DRIM AI flow subsystem, this script defines the BaseFlow class. [Source: 142, 147]
# It provides the foundational structure for orchestrating complex sequences of operations
# and interactions involving multiple DRIM AI agents. [Source: 143, 147] Flow management is
# essential for coordinating multi-step processes and ensuring that tasks
# progress logically from start to completion within the DRIM AI system. [Source: 147]