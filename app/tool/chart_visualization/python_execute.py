from app.config import config as app_main_config # [Source: 520]
from app.tool.python_execute import PythonExecute # Base class [Source: 520]
from app.tool.base import ToolResult # For return type consistency
from app.logger import logger
from typing import Optional, Any

class NormalPythonExecute(PythonExecute): # [Source: 520]
    """
    A DRIM AI tool for executing general-purpose Python code, often used for
    data processing, analysis, report generation, or other tasks not directly
    involving chart rendering itself but part of a broader data workflow.
    Inherits execution logic from the base PythonExecute tool.
    """
    name: str = "general_python_executor" # Renamed from "python_execute" to avoid clash if both are in same collection [Source: 520]
    description: str = ( # [Source: 520]
        "Executes Python code for tasks like in-depth data analysis, data report generation "
        "(e.g., creating textual summaries, conclusions), or other general scripting tasks "
        "that don't involve direct chart visualization output from this specific tool. "
        "Use print() for all outputs. Save any generated files (reports, processed data) "
        f"to the DRIM AI workspace: {str(app_main_config.workspace_root)}."
    )
    parameters: dict = { # [Source: 520]
        "type": "object",
        "properties": {
            "code_type": { # [Source: 520]
                "description": "Describes the purpose of the Python code. Options: 'data_processing', 'report_generation', 'general_scripting'. This helps in understanding the context.", # [Source: 520]
                "type": "string",
                "default": "data_processing", # Changed default
                "enum": ["data_processing", "report_generation", "general_scripting"], # Adjusted enum [Source: 520]
            },
            "code": { # [Source: 520]
                "type": "string",
                "description": ( # [Source: 521]
                    "The Python code to execute.\n"
                    "# Guidelines for DRIM AI:\n"
                    "1. For data reports, generate comprehensive text-based content including dataset overviews, column details, statistics, derived metrics, comparisons, outlier notes, and key insights. [Source: 521, 522]\n"
                    "2. Use `print()` for all outputs you want DRIM AI to see (e.g., analysis sections like 'Dataset Overview' or 'Preprocessing Results'). [Source: 522]\n"
                    f"3. Save any generated reports, processed data files, or intermediate analysis results in the DRIM AI workspace directory: '{str(app_main_config.workspace_root)}'. [Source: 522]\n" # [Source: 523]
                    "4. Data reports should be content-rich. If visualizations are part of the report, mention their file paths; this tool executes Python, another tool handles rendering charts. [Source: 522]\n"
                    "5. This tool can be invoked step-by-step for detailed data analysis, saving intermediate results or building up a comprehensive report. [Source: 523]"
                ),
            },
             "timeout": { # Inherited from base PythonExecute, but can be re-declared if different default needed
                 "type": "integer",
                 "description": "(Optional) Execution timeout in seconds. Default: 30 seconds for data tasks.",
                 "default": 30, # Slightly longer default for potentially more complex data scripts
            }
        },
        "required": ["code", "code_type"], # [Source: 523]
    }

    async def execute(self, code: str, code_type: Optional[str] = None, timeout: int = 30, **kwargs: Any) -> ToolResult: # [Source: 523]
        # code_type is mainly for contextual understanding by the LLM/agent,
        # the execution logic itself doesn't change based on it here.
        logger.info(f"DRIM AI NormalPythonExecute (Type: {code_type}): Executing code. Timeout: {timeout}s. Snippet: {code[:100]}...")
        # Call the base PythonExecute's execute method
        return await super().execute(code=code, timeout=timeout)

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, particularly for chart visualization workflows,
# this script provides NormalPythonExecute. This tool allows DRIM AI to run Python code
# for data preparation, analysis, and generating textual parts of reports, complementing
# the direct chart generation tools.