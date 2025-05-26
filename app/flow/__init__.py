# DRIM AI Flow Package
# This package contains components for managing and orchestrating
# complex multi-step processes and agent interactions within the DRIM AI system.

from app.flow.base import BaseFlow # [Source: 140] (Assuming BaseFlow will be defined)
from app.flow.flow_factory import FlowFactory, FlowType # [Source: 140] (Assuming these will be defined)
from app.flow.planning import PlanningFlow # [Source: 141] (Assuming PlanningFlow will be defined)

__all__ = [
    "BaseFlow",
    "FlowFactory",
    "FlowType",
    "PlanningFlow",
]

# Description for DRIM AI, based on original source for OpenManus
# This module is part of the flow system for DRIM AI, which manages the
# sequence and coordination of agent activities. [Source: 140, 141] Flow components handle the
# orchestration of complex multi-step processes and agent interactions. [Source: 141]