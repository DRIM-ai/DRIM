import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union # MODIFIED: Added Union

from app.config import config as app_main_config
from app.exceptions import ToolError
from app.logger import logger
from app.tool.base import BaseTool, ToolResult, ToolFailure # Added ToolFailure

# Define TASK_TYPE literal if not already globally available
TASK_TYPE_LITERAL = Literal["visualization", "insight"]
OUTPUT_TYPE_LITERAL = Literal["png", "html"]

# Default paths from the original script structure
# These might need adjustment based on your actual Node.js/TypeScript setup location
# For now, assuming chartVisualize.ts is in a 'scripts' subdir relative to project root
# and node_modules is at project root. This is a common pattern.
_NODE_MODULES_PATH = str(app_main_config.root_path / "node_modules")
_CHART_VISUALIZE_SCRIPT_PATH = str(
    app_main_config.root_path / "scripts" / "chartVisualize.ts"
)

# Ensure the script path is correct based on your project structure
if not Path(_CHART_VISUALIZE_SCRIPT_PATH).exists():
    logger.warning(
        f"Chart visualization script not found at default path: {_CHART_VISUALIZE_SCRIPT_PATH}. "
        "DataVisualization tool might fail. Please check configuration or script location."
    )
    # You might want to make this configurable or handle it more robustly


_DATA_VISUALIZATION_DESCRIPTION_DRIM_AI = """\
DRIM AI tool to generate data visualizations or update existing charts with insights using a Node.js script.
This tool takes chart metadata, dataset information, and user prompts to produce either PNG images or interactive HTML charts.
It can also add LLM-generated insights to existing charts.
All outputs (charts, JSON specs, insight markdowns) are saved in the DRIM AI workspace.
"""

class DataVisualization(BaseTool):
    name: str = "data_visualization_generator" # Renamed to be more descriptive
    description: str = _DATA_VISUALIZATION_DESCRIPTION_DRIM_AI
    parameters: dict = {
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "enum": ["visualization", "insight"],
                "description": "Type of task: 'visualization' to generate a new chart, or 'insight' to add insights to an existing chart.",
            },
            "metadata_json_path": {
                "type": "string",
                "description": "(Required for 'visualization' task) Absolute path to the JSON file containing chart metadata and dataset reference, typically prepared by 'visualization_prepare' tool.",
            },
            "user_prompt": {
                "type": "string",
                "description": "(Optional for 'visualization' task, if metadata_json_path provides enough context) User's prompt describing the desired chart or analysis for a new visualization.",
            },
            "output_type": {
                "type": "string",
                "enum": ["png", "html"],
                "default": "png",
                "description": "Desired output format for the chart ('png' or 'html'). Default: 'png'.",
            },
            "file_name": {
                "type": "string",
                "description": "(Required) Base name for the output files (chart, spec, markdown). E.g., 'sales_report_q1'. Do not include extension.",
            },
            "insights_id": {
                "type": "array",
                "items": {"type": "integer"}, # Changed from Union[str,int] for simplicity, assuming integer IDs
                "description": "(Required for 'insight' task) List of 1-based integer IDs of insights to apply to the chart specified by 'file_name'.",
            },
            "width": {
                "type": "integer",
                "description": "(Optional) Width of the generated chart in pixels.",
            },
            "height": {
                "type": "integer",
                "description": "(Optional) Height of the generated chart in pixels.",
            },
            "language": {
                "type": "string",
                "enum": ["en", "zh"],
                "default": "en",
                "description": "(Optional) Language for chart generation and insights ('en' or 'zh'). Default: 'en'.",
            },
        },
        "required": ["task_type", "file_name"],
    }

    async def execute(
        self,
        *,
        task_type: TASK_TYPE_LITERAL,
        file_name: str,
        metadata_json_path: Optional[str] = None,
        user_prompt: Optional[str] = None,
        output_type: OUTPUT_TYPE_LITERAL = "png",
        insights_id: Optional[List[int]] = None, # Corrected type hint usage
        width: Optional[int] = None,
        height: Optional[int] = None,
        language: str = "en",
        **kwargs: Any,
    ) -> ToolResult:
        logger.info(
            f"DRIM AI DataVisualization: Task '{task_type}' for file '{file_name}'."
        )

        if task_type == "visualization":
            if not metadata_json_path:
                return ToolFailure(
                    error="`metadata_json_path` is required for 'visualization' task."
                )
            if not Path(metadata_json_path).is_absolute():
                 return ToolFailure(error=f"Path '{metadata_json_path}' for metadata_json_path must be absolute.")
            if not Path(metadata_json_path).exists():
                return ToolFailure(
                    error=f"Metadata JSON file not found at: {metadata_json_path}"
                )
            try:
                with open(metadata_json_path, "r", encoding="utf-8") as f:
                    chart_metadata = json.load(f)
                # Ensure dataset_json_str is present; user_prompt is optional if already in metadata
                if "dataset_json_str" not in chart_metadata and "dataset_csv_path" not in chart_metadata : # Check for either
                    return ToolFailure(error="Chart metadata must contain 'dataset_json_str' or 'dataset_csv_path'.")
            except Exception as e:
                return ToolFailure(
                    error=f"Failed to load or validate metadata from {metadata_json_path}: {e}"
                )
            
            # Allow user_prompt from execute args to override or supplement one from metadata
            final_user_prompt = user_prompt or chart_metadata.get("user_prompt", "Generate chart based on data.")


            # Handle if dataset is a path to CSV
            if "dataset_csv_path" in chart_metadata and "dataset_json_str" not in chart_metadata:
                csv_path_str = chart_metadata["dataset_csv_path"]
                if not Path(csv_path_str).is_absolute():
                    # Assume it's relative to workspace if not absolute
                    csv_path_abs = app_main_config.workspace_root / csv_path_str
                else:
                    csv_path_abs = Path(csv_path_str)

                if not csv_path_abs.exists():
                    return ToolFailure(error=f"Dataset CSV file not found at resolved path: {csv_path_abs}")
                try:
                    # Convert CSV to JSON string for VMind if that's what chartVisualize.ts expects
                    # This is a placeholder; actual conversion depends on VMind/chartVisualize.ts needs
                    # For simplicity, if chartVisualize.ts can read CSV path from input JSON, pass it.
                    # Here, chart_metadata still holds dataset_csv_path.
                    # The chartVisualize.ts script will need to be able to read this CSV.
                    # The alternative is to read CSV here and convert to JSON string.
                    # For now, assuming chartVisualize.ts can handle a CSV path in the input.
                    logger.info(f"Using CSV dataset path for visualization: {csv_path_abs}")
                    # dataset_json_str will be constructed from chart_metadata within the input_data for the script
                except Exception as e:
                    return ToolFailure(error=f"Failed to process CSV file {csv_path_abs}: {e}")


            input_data_to_script = {
                "task_type": "visualization",
                "dataset_json_str": chart_metadata.get("dataset_json_str"), # This might be None if CSV is used
                "dataset_csv_path": str(chart_metadata.get("dataset_csv_path")), # Pass CSV path if present
                "user_prompt": final_user_prompt,
                "directory": str(app_main_config.workspace_root), # Ensure it's a string
                "output_type": output_type,
                "file_name": file_name,
                "width": width,
                "height": height,
                "language": language,
                "llm_config": { # Pass Gemini LLM config for VMind if it can use it
                    "service_provider": "gemini", # Indicate Gemini
                    "api_key": app_main_config.gemini.api_key,
                    "model": app_main_config.gemini.primary_model, # Or a specific model for viz
                    # VMind might need a base_url or specific endpoint structure.
                    # This is a simplified passing of config. chartVisualize.ts needs to adapt.
                }
            }

        elif task_type == "insight":
            if not insights_id:
                return ToolFailure(
                    error="`insights_id` (list of integers) is required for 'insight' task."
                )
            if not all(isinstance(i, int) and i > 0 for i in insights_id):
                 return ToolFailure(error="`insights_id` must be a list of positive integers.")

            input_data_to_script = {
                "task_type": "insight",
                "directory": str(app_main_config.workspace_root),
                "output_type": output_type, # Output type for the updated chart
                "file_name": file_name, # Base name of the chart to update
                "insights_id": insights_id,
                "width": width, # Pass along if specified for re-rendering
                "height": height,
                "language": language, # Pass language for insight processing if relevant
                 "llm_config": { # Pass Gemini LLM config
                    "service_provider": "gemini",
                    "api_key": app_main_config.gemini.api_key,
                    "model": app_main_config.gemini.small_model or app_main_config.gemini.primary_model,
                }
            }
        else:
            return ToolFailure(error=f"Invalid task_type: {task_type}")

        # Command to execute the TypeScript script with ts-node
        # Ensure ts-node is installed globally or locally (npm i -g ts-node or npm i ts-node)
        # And TypeScript (npm i -g typescript or npm i typescript)
        # This also assumes NODE_PATH might need to be set if ts-node/modules are local
        node_command = [
            "node",
            "--loader", "ts-node/esm", # For ES Modules in TypeScript
            # Or: "ts-node", # For CommonJS
            _CHART_VISUALIZE_SCRIPT_PATH,
        ]
        logger.debug(f"Executing Node.js script: {' '.join(node_command)}")
        logger.debug(f"Input to script: {json.dumps(input_data_to_script, indent=2)[:500]}...")


        process = await asyncio.create_subprocess_exec(
            *node_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Set cwd if script relies on relative paths for node_modules not found via NODE_PATH
            # cwd=str(app_main_config.root_path), 
            env={**os.environ, "NODE_PATH": _NODE_MODULES_PATH} # Ensure local node_modules are found
        )
        
        stdout, stderr = await process.communicate(
            input=json.dumps(input_data_to_script).encode("utf-8")
        )

        if process.returncode != 0:
            error_message = stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                f"Chart visualization script failed for task '{task_type}', file '{file_name}'. "
                f"Return code: {process.returncode}. Error: {error_message}"
            )
            return ToolFailure(
                error=f"Chart script execution failed: {error_message}",
                output=stdout.decode("utf-8", errors="replace").strip() # Include stdout if any
            )

        try:
            script_output_json = stdout.decode("utf-8", errors="replace").strip()
            script_result = json.loads(script_output_json)
            if script_result.get("error"):
                logger.error(f"Chart script returned an error: {script_result['error']}")
                return ToolFailure(error=script_result["error"])

            output_message_parts = [f"DRIM AI DataVisualization task '{task_type}' for '{file_name}' completed."]
            if script_result.get("chart_path"):
                output_message_parts.append(f"Chart saved to: {script_result['chart_path']}")
            if script_result.get("insight_path"):
                output_message_parts.append(f"Insights saved to: {script_result['insight_path']}")
            if script_result.get("insight_md"):
                 output_message_parts.append(f"\nGenerated Insights:\n{script_result['insight_md']}")
            
            return ToolResult(output="\n".join(output_message_parts))

        except json.JSONDecodeError:
            raw_stdout = stdout.decode("utf-8", errors="replace").strip()
            logger.error(f"Failed to parse JSON output from chart script. Raw output: {raw_stdout}")
            return ToolFailure(
                error="Failed to parse JSON output from chart script.", output=raw_stdout
            )
        except Exception as e:
            logger.exception("Error processing chart script output.")
            return ToolFailure(error=f"Error processing chart script output: {str(e)}")