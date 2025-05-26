from app.tool.chart_visualization.python_execute import NormalPythonExecute # [Source: 496]
from app.tool.base import ToolResult
from app.logger import logger
from typing import Optional, Any

class VisualizationPrepare(NormalPythonExecute): # [Source: 496]
    """
    A DRIM AI tool used for preparing data and metadata specifically for chart generation.
    It leverages Python code execution (via NormalPythonExecute) to:
    1. Load and clean/transform data.
    2. Generate CSV files containing the data ready for visualization.
    3. Create JSON metadata describing the charts to be generated (e.g., title, path to CSV).
    4. For adding insights, it prepares JSON specifying which chart and which insights.
    """
    name: str = "visualization_data_preparation" # Renamed from visualization_preparation for clarity [Source: 496]
    description: str = ( # [Source: 496]
        "DRIM AI: Uses Python code to generate metadata (JSON info) and optionally cleaned CSV data files "
        "that are required by the 'data_visualization' tool. "
        "Outputs: 1) A JSON file path containing information for chart generation or insight addition. "
        "2. Optionally, cleaned CSV data file(s) if the 'visualization' code_type is used."
    )
    parameters: dict = { # [Source: 497]
        "type": "object",
        "properties": {
            "code_type": { # [Source: 497]
                "description": "The type of preparation: 'visualization' (to prepare data and metadata for new charts from CSVs) or 'insight' (to prepare metadata for adding LLM-generated insights to existing charts).", # [Source: 497]
                "type": "string",
                "default": "visualization",
                "enum": ["visualization", "insight"], # [Source: 497]
            },
            "code": { # [Source: 497]
                "type": "string",
                "description": ( # [Source: 497]
                    "Python code for data visualization preparation. Must `print()` the path to the output JSON file.\n"
                    "## For 'visualization' code_type:\n"
                    "1. Implement data loading logic (e.g., from provided strings, existing files in workspace).\n"
                    "2. Clean and transform data as needed for the desired chart(s).\n"
                    "3. For each chart to be generated, save the prepared data to a NEW .csv file in the workspace.\n"
                    "4. Create a list of dictionaries, where each dictionary contains:\n"
                    "   - `csvFilePath`: Relative path (from workspace root) to the generated .csv file for a chart.\n"
                    "   - `chartTitle`: A concise and clear title or description for that chart (e.g., 'Product Sales Distribution Q1', 'Monthly Revenue Trend'). [Source: 498]\n"
                    "5. Save this list of dictionaries as a JSON file (UTF-8 encoded) in the workspace.\n"
                    "6. CRITICAL: `print()` the absolute or workspace-relative path to this output JSON file (e.g., `print('path/to/your/output_metadata.json')`). This printed path is the tool's primary result.\n"
                    "## For 'insight' code_type:\n" # [Source: 498]
                    "1. Identify existing chart file(s) (e.g., .png, .html) in the workspace for which insights are desired.\n"
                    "2. For each chart, specify the insights to be added by their IDs (assuming insights were previously generated and indexed, or you'll describe them for new generation).\n"
                    "3. Create a list of dictionaries, where each dictionary contains:\n"
                    "   - `chartPath`: Relative path (from workspace root) to the existing chart file.\n"
                    "   - `insights_id`: A list of numerical IDs or descriptive strings for the insights to be added/associated with this chart. [Source: 499]\n"
                    "4. Save this list as a JSON file (UTF-8 encoded) in the workspace.\n"
                    "5. CRITICAL: `print()` the absolute or workspace-relative path to this output JSON file.\n"
                    "# General Notes for DRIM AI:\n"
                    "- You can prepare for one or multiple charts/insights in a single execution. [Source: 499]\n"
                    "- Ensure each chart's data (if generating CSVs) is clean, focused, and distinct for clarity. [Source: 500]\n"
                    "- The printed JSON file path is the key output this tool provides to the subsequent 'data_visualization' tool." # [Source: 500]
                ),
            },
            "timeout": {
                 "type": "integer",
                 "description": "(Optional) Execution timeout in seconds. Default: 60 seconds for data preparation.",
                 "default": 60, # Longer timeout for data prep scripts
            }
        },
        "required": ["code", "code_type"], # [Source: 497]
    }

    async def execute(self, code: str, code_type: str, timeout: int = 60, **kwargs: Any) -> ToolResult:
        logger.info(f"DRIM AI VisualizationPrepare (Type: {code_type}): Executing data preparation code. Timeout: {timeout}s.")
        # The result from super().execute (PythonExecute) will be a ToolResult
        # with 'output' containing the stdout from the executed code.
        # This stdout is expected to be the path to the JSON metadata file.
        execution_result: ToolResult = await super().execute(code=code, code_type=code_type, timeout=timeout) # Pass code_type for logging in parent

        if execution_result.error:
            return execution_result # Propagate error

        if execution_result.output and isinstance(execution_result.output, str):
            # The output should be the path to the JSON file.
            json_file_path = execution_result.output.strip()
            # Basic validation: check if the path ends with .json
            if not json_file_path.lower().endswith(".json"):
                err_msg = (f"DRIM AI VisualizationPrepare: Executed Python code did NOT print a .json file path as its last line of output. "
                           f"Actual output: '{json_file_path}'. Please ensure your Python code prints the path to the generated JSON metadata file.")
                logger.error(err_msg)
                return ToolResult(output=execution_result.output, error=err_msg) # Return original output with new error
            
            logger.info(f"DRIM AI VisualizationPrepare: Python code executed. Reported JSON metadata file path: '{json_file_path}'")
            # The tool's job is to return this path (or confirm file creation).
            # The actual reading of this JSON is done by the DataVisualization tool.
            return ToolResult(output=f"JSON metadata file path generated by script: {json_file_path}", system_message="Ensure this JSON file exists in the workspace and is correctly formatted for the 'data_visualization' tool.")
        else:
            err_msg = "DRIM AI VisualizationPrepare: Python code executed but produced no standard output (expected a JSON file path)."
            logger.error(err_msg)
            return ToolResult(error=err_msg)

# Role in the System (Updated for DRIM AI)
# Within DRIM AI's chart visualization toolkit, VisualizationPrepare is a specialized
# Python execution tool. [Source: 494] It allows DRIM AI to run scripts that prepare data (e.g., cleaning,
# transforming, saving to CSV) and generate crucial JSON metadata. This metadata, whose path
# is output by this tool, instructs the subsequent DataVisualization tool on how to render
# charts or associate insights. [Source: 495]