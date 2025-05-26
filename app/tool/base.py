# app/tool/base.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import json # Make sure json is imported for deepcopy trick

from pydantic import BaseModel, Field, ConfigDict

def _remove_unsupported_fields_from_schema(schema_node: Any) -> Any:
    """
    Recursively removes unsupported fields (like 'default') from a JSON schema node
    and ensures enums are lists of strings if they are not already.
    Gemini specifically has issues with 'default' and expects 'enum' to be List[str].
    """
    if isinstance(schema_node, dict):
        cleaned_node = {}
        for key, value in schema_node.items():
            if key == 'default': # Skip the 'default' key
                continue
            if key == 'enum' and isinstance(value, list):
                # Ensure all enum values are strings, as Gemini expects List[str]
                cleaned_node[key] = [str(v) for v in value]
            else:
                cleaned_node[key] = _remove_unsupported_fields_from_schema(value)
        return cleaned_node
    elif isinstance(schema_node, list):
        return [_remove_unsupported_fields_from_schema(item) for item in schema_node]
    else:
        return schema_node

class BaseTool(ABC, BaseModel):
    name: str = Field(..., description="The unique name of the tool.")
    description: str = Field(..., description="A detailed description of what the tool does, its capabilities, and when to use it.")
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}, # Ensure parameters is always a dict
        description="JSON schema definition for the tool's input parameters. "
                    "Should follow the OpenAPI Specification format for objects."
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def __call__(self, **kwargs: Any) -> Any:
        return await self.execute(**kwargs)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        pass

    def to_param(self) -> Dict[str, Any]:
        """
        Convert tool to the parameter format expected by LLMs for function/tool calling.
        Removes "default" fields and ensures enum values are strings for Gemini compatibility.
        """
        # Ensure self.parameters is a valid schema, even if minimal
        current_params = self.parameters
        if not isinstance(current_params, dict) or current_params.get("type") != "object" or "properties" not in current_params :
            # If parameters are None or not a valid object schema, provide a minimal valid one.
            # This is a safeguard; tools should define their parameters correctly.
            current_params = {"type": "object", "properties": {}}
        
        # Deep copy to avoid modifying the original tool's schema definition
        # Using json loads/dumps is a common way for a simple deep copy of schema-like dicts
        try:
            schema_for_llm = json.loads(json.dumps(current_params))
        except Exception: # Fallback if params are not JSON serializable (should not happen for valid schemas)
            schema_for_llm = {"type": "object", "properties": {}} # Minimal valid

        # Clean unsupported fields from the copied schema
        schema_for_llm = _remove_unsupported_fields_from_schema(schema_for_llm)
            
        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema_for_llm,
        }

class ToolResult(BaseModel):
    output: Optional[Any] = Field(default=None, description="The primary output data from the tool execution.")
    error: Optional[str] = Field(default=None, description="Error message if the tool execution failed.")
    base64_image: Optional[str] = Field(default=None, description="Optional base64 encoded image if the tool produces visual output.")
    system_message: Optional[str] = Field(default=None, description="Optional system-level message related to the tool's execution (e.g., status change).")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __bool__(self) -> bool:
        return (self.output is not None or self.base64_image is not None or self.system_message is not None) and not self.error

    def __add__(self, other: "ToolResult") -> "ToolResult":
        def combine_fields(
            field1: Optional[Any], field2: Optional[Any], concatenate_str: bool = True
        ) -> Optional[Any]:
            if field1 is not None and field2 is not None:
                if isinstance(field1, str) and isinstance(field2, str) and concatenate_str:
                    return f"{field1}\\n{field2}"
                return field2 
            return field1 or field2

        new_output = self.output
        if isinstance(self.output, str) and isinstance(other.output, str):
            new_output = f"{self.output}\\n{other.output}".strip()
        elif other.output is not None:
            new_output = other.output 

        new_error = self.error
        if other.error: 
            new_error = f"{self.error}\\n{other.error}".strip() if self.error else other.error
            
        return ToolResult(
            output=new_output,
            error=new_error,
            base64_image=other.base64_image or self.base64_image, 
            system_message=combine_fields(self.system_message, other.system_message), 
        )

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        if self.output is not None:
            return str(self.output)
        if self.base64_image:
            return "Tool produced an image."
        if self.system_message:
            return f"System Message: {self.system_message}"
        return "Tool executed with no specific output or error."

    def to_tool_result_str(self) -> str:
        return str(self)

    def replace(self, **kwargs: Any) -> "ToolResult": 
        return self.model_copy(update=kwargs) 

class CLIResult(ToolResult): 
    def to_tool_result_str(self) -> str:
        res_str = ""
        if self.output:
            res_str += f"Output:\\n```\\n{str(self.output).strip()}\\n```\\n"
        if self.error:
            res_str += f"Error:\\n```\\n{str(self.error).strip()}\\n```\\n"
        if not res_str: 
            if self.system_message:
                return f"System Message: {self.system_message}"
            return "CLI tool executed with no significant output or error."
        return res_str.strip()

# MODIFIED ToolFailure class
class ToolFailure(Exception): 
    def __init__(self, error: str, output: Optional[Any] = None, base64_image: Optional[str] = None, system_message: Optional[str] = None, **kwargs: Any):
        super().__init__(error) # Pass error message to Exception parent
        self.error_message: str = error # Store the error message explicitly
        self.output: Optional[Any] = output
        self.base64_image: Optional[str] = base64_image
        self.system_message: Optional[str] = system_message
        # Store any other relevant kwargs if needed
        self.additional_info: Dict[str, Any] = kwargs

    def __str__(self) -> str:
        base_str = f"ToolFailure: {self.error_message}"
        if self.output:
            base_str += f"\\nPartial Output/Context: {str(self.output)}"
        if self.base64_image:
            base_str += "\\n(Image data was present)"
        if self.system_message:
            base_str += f"\\nSystem Message: {self.system_message}"
        return base_str

    def to_tool_result(self) -> ToolResult:
        """Converts this ToolFailure to a ToolResult object, useful for consistent handling."""
        return ToolResult(
            output=self.output,
            error=self.error_message,
            base64_image=self.base64_image,
            system_message=self.system_message
        )