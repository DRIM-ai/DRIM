from enum import Enum
from typing import Dict, List, Union, Any # [Source: 150]

from app.agent.base import BaseAgent # DRIM AI's BaseAgent [Source: 150]
from app.flow.base import BaseFlow # DRIM AI's BaseFlow [Source: 150]
from app.flow.planning import PlanningFlow # DRIM AI's PlanningFlow [Source: 150]
from app.logger import logger

class FlowType(str, Enum): # [Source: 150]
    """Enum defining available DRIM AI flow types."""
    PLANNING = "planning_flow" # Renamed from "planning" for clarity [Source: 150]
    # Add other DRIM AI flow types here, e.g.:
    # SIMPLE_CONVERSATION = "simple_conversation_flow"
    # MULTI_AGENT_DEBATE = "multi_agent_debate_flow"

class FlowFactory: # [Source: 150]
    """
    Factory for creating different types of DRIM AI execution flows.
    Supports initializing flows with single or multiple agents. [Source: 150]
    """
    
    _flow_registry: Dict[FlowType, type[BaseFlow]] = { # Private registry
        FlowType.PLANNING: PlanningFlow, # [Source: 151]
        # Register other flow types here
    }

    @classmethod # Changed from @staticmethod to @classmethod to potentially access _flow_registry via cls
    def register_flow(cls, flow_type_enum: FlowType, flow_class: type[BaseFlow]):
        """Allows dynamic registration of new flow types for DRIM AI."""
        if not issubclass(flow_class, BaseFlow):
            raise TypeError(f"Flow class {flow_class.__name__} must be a subclass of BaseFlow.")
        if flow_type_enum in cls._flow_registry:
            logger.warning(f"DRIM AI FlowFactory: Overwriting registered flow for type '{flow_type_enum.value}'.")
        cls._flow_registry[flow_type_enum] = flow_class
        logger.info(f"DRIM AI FlowFactory: Registered flow type '{flow_type_enum.value}' with class {flow_class.__name__}.")


    @classmethod # Changed from @staticmethod
    def create_flow( # [Source: 150]
        cls,
        flow_type: FlowType,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], # [Source: 150]
        **kwargs: Any, # For additional flow-specific parameters [Source: 150]
    ) -> BaseFlow:
        """
        Creates and returns an instance of the specified DRIM AI flow type.
        Args:
            flow_type: The type of flow to create (from FlowType enum).
            agents: The agent(s) to be used by the flow.
            **kwargs: Additional arguments to be passed to the flow's constructor.
        Returns:
            An instance of a BaseFlow subclass.
        Raises:
            ValueError: If the specified flow_type is unknown.
        """
        logger.info(f"DRIM AI FlowFactory: Creating flow of type '{flow_type.value}'.")
        flow_class = cls._flow_registry.get(flow_type) # [Source: 151]

        if not flow_class: # [Source: 151]
            logger.error(f"DRIM AI FlowFactory: Unknown flow type requested: {flow_type.value}")
            raise ValueError(f"Unknown DRIM AI flow type: {flow_type.value}. Available types: {[ft.value for ft in cls._flow_registry.keys()]}") # [Source: 151]
        
        # The BaseFlow constructor now handles the 'agents' argument processing.
        try:
            return flow_class(agents=agents, **kwargs) # [Source: 152]
        except Exception as e:
            logger.exception(f"DRIM AI FlowFactory: Error instantiating flow '{flow_type.value}'.")
            raise ValueError(f"Could not create DRIM AI flow '{flow_type.value}': {e}")


# Role in the System (Updated for DRIM AI)
# As part of the DRIM AI flow subsystem, this script provides the FlowFactory. [Source: 148, 152]
# This factory is essential for creating instances of different predefined flow types
# (like PlanningFlow), allowing DRIM AI to dynamically select and instantiate
# appropriate orchestration logic for various complex tasks. [Source: 149, 153]