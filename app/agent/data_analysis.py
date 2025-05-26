from pydantic import Field

from app.agent.toolcall import ToolCallAgent # [Source: 49]
from app.config import config as app_main_config # Renamed import [Source: 49]
# Ensure these prompts are suitable for Gemini and DRIM AI
from app.prompt.visualization import NEXT_STEP_PROMPT as VIZ_NEXT_STEP_PROMPT # [Source: 49]
from app.prompt.visualization import SYSTEM_PROMPT as VIZ_SYSTEM_PROMPT # [Source: 49]
from app.tool import Terminate, ToolCollection # [Source: 49]
from app.tool.chart_visualization.chart_prepare import VisualizationPrepare # [Source: 49]
from app.tool.chart_visualization.data_visualization import DataVisualization # [Source: 49]
from app.tool.chart_visualization.python_execute import NormalPythonExecute # [Source: 49]
from app.llm import LLM # Ensures it uses the DRIM AI (Gemini) LLM

class DataAnalysis(ToolCallAgent): # [Source: 50]
    """
    A data analysis agent that uses planning (implicitly through ToolCallAgent's loop)
    to solve various data analysis tasks. [Source: 50]
    This agent extends ToolCallAgent with a comprehensive set of tools and capabilities,
    including Data Analysis, Chart Visualization, and Data Reporting. [Source: 50]
    """
    name: str = Field(default="drim_data_analysis_agent") # Renamed for DRIM AI [Source: 51]
    description: str = Field(default="An analytical agent that utilizes multiple tools to solve diverse data analysis tasks, including chart generation and data reporting for DRIM AI.") # [Source: 51]

    system_prompt: str = Field(default=VIZ_SYSTEM_PROMPT.format(directory=str(app_main_config.workspace_root))) # [Source: 51] Ensure workspace_root is string
    next_step_prompt: str = Field(default=VIZ_NEXT_STEP_PROMPT) # [Source: 51]

    max_observe: int = Field(default=15000) # Max chars from tool observation [Source: 52]
    max_steps: int = Field(default=20) # [Source: 52]

    # Ensure LLM is the DRIM AI (Gemini) LLM, inherited from ToolCallAgent but can be specified
    llm: LLM = Field(default_factory=LLM)

    # Add general-purpose data analysis tools to the tool collection
    available_tools: ToolCollection = Field( # [Source: 52]
        default_factory=lambda: ToolCollection(
            NormalPythonExecute(),      # For general python execution, data prep
            VisualizationPrepare(),     # Prepares data for visualization
            DataVisualization(),        # Generates visualizations
            Terminate(),                # To end the task
            # Consider adding WebSearch if data analysis might involve fetching external datasets/info
            # from app.tool.web_search import WebSearch
            # WebSearch(),
            # Consider adding file operation tools if needed
            # from app.tool.str_replace_editor import StrReplaceEditor
            # StrReplaceEditor(), # If reports are generated as text files that need editing
        )
    )

    # special_tool_names is inherited from ToolCallAgent, typically [Terminate().name]

# Role in the System (Updated for DRIM AI)
# As part of the agent subsystem, this script contributes to the core
# intelligence and decision-making capabilities of DRIM AI. [Source: 53] The DataAnalysis
# agent enables the system to understand data-related tasks, formulate analysis plans,
# execute data processing and visualization steps, and report findings. [Source: 53]