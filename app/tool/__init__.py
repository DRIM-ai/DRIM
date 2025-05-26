# DRIM AI Tools Package
# This package contains implementations of various tools that DRIM AI agents can leverage.

from app.tool.base import BaseTool, ToolResult, CLIResult, ToolFailure #

# Core Tools
from app.tool.ask_human import AskHuman
from app.tool.bash import Bash #
from app.tool.browser_use_tool import BrowserUseTool # 
from app.tool.create_chat_completion import CreateChatCompletion #
from app.tool.file_operators import FileOperator, LocalFileOperator, SandboxFileOperator 
from app.tool.planning import PlanningTool #
from app.tool.python_execute import PythonExecute 
from app.tool.str_replace_editor import StrReplaceEditor #
from app.tool.terminate import Terminate #
from app.tool.tool_collection import ToolCollection #

# Search Tools
from app.tool.web_search import WebSearch, WebSearchResponse, SearchResult as WebSearchResult #
from app.tool.search import ( 
    WebSearchEngine,
    SearchItem, 
    GoogleCustomSearchEngine,
    GoogleScraperSearchEngine, # Added
    # BraveSearchEngine removed
)

# Chart Visualization Tools
from app.tool.chart_visualization import (
    DataVisualization,
    VisualizationPrepare,
    NormalPythonExecute, # This is chart_visualization.python_execute.NormalPythonExecute
)


__all__ = [ #
    "BaseTool", "ToolResult", "CLIResult", "ToolFailure",
    "AskHuman",
    "Bash",
    "BrowserUseTool",
    "CreateChatCompletion",
    "FileOperator", "LocalFileOperator", "SandboxFileOperator",
    "PlanningTool",
    "PythonExecute", # The general one from app.tool.python_execute
    "StrReplaceEditor",
    "Terminate",
    "ToolCollection",
    "WebSearch", "WebSearchResponse", "WebSearchResult",
    "WebSearchEngine", "SearchItem", 
    "GoogleCustomSearchEngine", "GoogleScraperSearchEngine", # Updated
    "DataVisualization", "VisualizationPrepare", 
    "NormalPythonExecute", # The one from chart_visualization
]

# Description for DRIM AI, based on original source for OpenManus
# As part of the tool subsystem for DRIM AI, this script and the containing package
# extend the agent's capabilities by providing concrete actions it can perform.
# Tools are essential for enabling DRIM AI to interact with its environment
# and accomplish real-world tasks beyond pure language processing.