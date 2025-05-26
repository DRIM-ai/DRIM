from app.agent.base import BaseAgent # [Source: 19]
from app.agent.browser import BrowserAgent # [Source: 19]
from app.agent.mcp import MCPAgent # [Source: 19]
from app.agent.react import ReActAgent # [Source: 19]
from app.agent.swe import SWEAgent # [Source: 19]
from app.agent.toolcall import ToolCallAgent # [Source: 19]
from app.agent.data_analysis import DataAnalysis # Corrected class name
from app.agent.manus import Manus # Corrected class name

__all__ = [ # [Source: 19]
    "BaseAgent",
    "BrowserAgent",
    "ReActAgent",
    "SWEAgent",
    "ToolCallAgent",
    "MCPAgent",
    "DataAnalysis", # Corrected
    "Manus", # Corrected
]

# Description from original file, updated for DRIM AI
# This script is part of the agent module, which forms the core intelligence
# of the DRIM AI system. [Source: 17] The agent components handle reasoning,
# decision-making, and task execution capabilities. [Source: 18]