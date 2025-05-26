from typing import Any, List, Optional, Type, Union, get_args, get_origin, Dict # [Source: 590]
from pydantic import BaseModel, Field, ConfigDict # [Source: 590]

from app.tool.base import BaseTool, ToolResult # [Source: 590]
from app.logger import logger

class CreateChatCompletion(BaseTool): # [Source: 590]
    """
    A DRIM AI tool that defines a desired structure for an LLM's response.
    The agent provides this tool's schema (parameters) to the LLM, instructing the LLM
    to generate content matching this structure. The 'execute' method of this tool
    then simply processes/returns the arguments provided by the LLM's tool call.
    """
    name: str = "structured_response_formatter" # Renamed for clarity of its function [Source: 590]
    description: str = ( # [Source: 590]
        "Formats the response according to a specified data structure or type. "
        "Use this when you need the AI to provide information in a specific, structured format."
    )

    # Pydantic V2: model_config
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Type mapping for JSON schema generation (OpenAPI types) [Source: 590]
    _type_mapping: Dict[type, str] = { # [Source: 590] Made private-like
        str: "string", int: "integer", float: "number",
        bool: "boolean", dict: "object", list: "array",
    }
    
    response_model: Optional[Type[BaseModel]] = None # Store Pydantic model if provided
    response_type_hint: Optional[Type] = None      # Store basic type hint if model not provided
    
    # The 'parameters' field of BaseTool will be dynamically built.
    # We need to call super().__init__ correctly after dynamic fields are set.

    def __init__(self, response_type: Type = str, response_model_pydantic: Optional[Type[BaseModel]] = None, **data: Any): # [Source: 591]
        """
        Initialize with a specific response type or a Pydantic model for the desired output structure.
        Args:
            response_type: The Python type hint for the expected response (e.g., str, List[int], Dict[str, Any]).
                           Used if response_model_pydantic is None.
            response_model_pydantic: A Pydantic model defining the desired output structure. Takes precedence.
        """
        # We need to set these before super().__init__ so _build_parameters can use them if called by BaseTool's Pydantic validation.
        # However, BaseTool's 'parameters' is also a field. This requires careful initialization order.
        # One way: initialize `name` and `description` via `data`, then set dynamic fields, then build params.
        
        # Temporarily store these for _build_parameters
        self._temp_response_type = response_type
        self._temp_response_model_pydantic = response_model_pydantic
        
        # Initialize BaseTool fields (name, description, parameters)
        # 'parameters' will be built by _build_parameters, called by Pydantic during BaseTool init
        # if 'parameters' is not provided in 'data'. If 'parameters' is in 'data', it's used.
        # To ensure our dynamic build is used, we shouldn't pass 'parameters' in data here.
        
        # Default name and description if not provided in data
        final_data = {
            "name": data.pop("name", "structured_response_formatter"),
            "description": data.pop("description", 
                "Formats the response according to a specified data structure. "
                "The AI should fill the arguments of this tool with the structured data."),
            **data # Pass through other BaseTool fields if any
        }
        super().__init__(**final_data) # This will call _build_parameters via Pydantic if needed

        # Now permanently set the response type/model after BaseTool init
        self.response_type_hint = self._temp_response_type
        self.response_model = self._temp_response_model_pydantic
        del self._temp_response_type # Clean up temp attrs
        del self._temp_response_model_pydantic

        # If parameters were not built by BaseTool's Pydantic validation (e.g. if it was None by default)
        # ensure it's built now. BaseTool defines parameters = None initially.
        if self.parameters is None:
            self.parameters = self._build_parameters()


    def _build_parameters(self) -> Dict[str, Any]: # [Source: 591]
        """Build parameters schema based on response_type or response_model_pydantic."""
        # Use the temp attributes during initial Pydantic validation pass by BaseTool
        response_model_to_use = getattr(self, '_temp_response_model_pydantic', self.response_model)
        response_type_to_use = getattr(self, '_temp_response_type', self.response_type_hint)

        if response_model_to_use and issubclass(response_model_to_use, BaseModel): # [Source: 591]
            # Generate schema from Pydantic model
            # We want the 'properties' and 'required' fields of the model to be the tool's parameters.
            schema = response_model_to_use.model_json_schema()
            # The tool's parameters should be the properties of the response model.
            # The LLM will then fill these properties as arguments to the tool call.
            return {
                "type": "object", # Standard for tool parameters
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            }
        elif response_type_to_use: # [Source: 592]
            # Generate schema for a basic Python type or generic type hint
            # The tool will have a single parameter named 'response_data' holding this type.
            type_schema = self._create_schema_for_type_hint(response_type_to_use)
            return {
                "type": "object",
                "properties": {
                    "response_data": {
                        **type_schema,
                        "description": f"The structured response data of type '{str(response_type_to_use)}'."
                    }
                },
                "required": ["response_data"],
            }
        else: # Fallback if no type/model specified (should not happen with constructor defaults)
            return {
                "type": "object",
                "properties": {"response_data": {"type": "string", "description": "A generic textual response."}},
                "required": ["response_data"],
            }

    def _create_schema_for_type_hint(self, type_hint: Type) -> Dict[str, Any]: # [Source: 592] Renamed from _create_type_schema
        """Create a JSON schema fragment for a given Python type hint."""
        origin = get_origin(type_hint) # [Source: 592]
        args = get_args(type_hint) # [Source: 592]

        if origin is None: # Primitive type or a non-generic class [Source: 592]
            if type_hint in self._type_mapping:
                return {"type": self._type_mapping[type_hint]}
            elif isinstance(type_hint, type) and issubclass(type_hint, BaseModel): # Nested Pydantic model
                # Return reference or inline. For simplicity, inline, but refs are better for complex schemas.
                return type_hint.model_json_schema() # type: ignore
            else: # Default to string for unknown types
                logger.warning(f"DRIM AI CreateChatCompletion: Unknown type '{type_hint}', defaulting to string schema.")
                return {"type": "string"}
        
        if origin is list or origin is List: # [Source: 593]
            item_type = args[0] if args else Any
            return {"type": "array", "items": self._create_schema_for_type_hint(item_type)}
        
        if origin is dict or origin is Dict: # [Source: 593]
            # JSON schema for dict usually means 'object'.
            # If keys are fixed, it's properties. If arbitrary keys, additionalProperties.
            # Assuming arbitrary string keys for simplicity here.
            # key_type = args[0] if args else str # Typically str for JSON keys
            value_type = args[1] if len(args) > 1 else Any
            return {"type": "object", "additionalProperties": self._create_schema_for_type_hint(value_type)}
            
        if origin is Union: # [Source: 593]
            # OpenAPI 'anyOf' for Union types
            return {"anyOf": [self._create_schema_for_type_hint(t) for t in args]}
            
        logger.warning(f"DRIM AI CreateChatCompletion: Unsupported complex type hint '{type_hint}', defaulting to string schema.")
        return {"type": "string"} # Fallback for other complex types


    async def execute(self, **kwargs: Any) -> Any: # [Source: 596]
        """
        Processes the arguments provided by the LLM (which should match the generated schema).
        If a Pydantic response_model was set, it attempts to parse kwargs into that model.
        Otherwise, it returns the 'response_data' field or the whole kwargs dict.
        """
        logger.debug(f"DRIM AI {self.name}: Executing with received LLM arguments: {kwargs}")
        if self.response_model and issubclass(self.response_model, BaseModel): # [Source: 596]
            try:
                # The LLM's arguments (kwargs) should directly map to the fields of the Pydantic model.
                return self.response_model(**kwargs) # [Source: 596]
            except Exception as e: # Catch Pydantic validation errors etc.
                logger.error(f"DRIM AI {self.name}: Error parsing LLM output into Pydantic model '{self.response_model.__name__}': {e}. Raw args: {kwargs}")
                # Return raw kwargs or raise error, depending on desired strictness
                return ToolResult(error=f"Failed to parse LLM output into {self.response_model.__name__}: {e}", output=kwargs)

        elif "response_data" in kwargs: # If schema was for a basic type wrapped in 'response_data' [Source: 596]
            # Here, self.response_type_hint could be used for type conversion if needed, e.g. int(kwargs["response_data"])
            # For now, returning the data as is, assuming LLM provided it correctly.
            # The original code had type conversion logic [Source: 597]
            data_to_convert = kwargs["response_data"]
            if self.response_type_hint and self.response_type_hint != Any:
                try:
                    # Basic type conversion, might not work for complex generics like List[int] directly
                    if get_origin(self.response_type_hint) is None and self.response_type_hint not in [str, dict, list, bool]: # Primitives other than str/collections
                         return self.response_type_hint(data_to_convert)
                    return data_to_convert # For str, list, dict, bool, or complex types, return as is
                except (ValueError, TypeError) as e:
                    logger.warning(f"DRIM AI {self.name}: Could not convert '{data_to_convert}' to type '{self.response_type_hint}': {e}. Returning raw.")
                    return data_to_convert
            return data_to_convert
        else: # Fallback: return all arguments received from LLM if no specific structure matched.
            logger.debug(f"DRIM AI {self.name}: No specific response model or 'response_data' key. Returning all kwargs.")
            return kwargs # [Source: 596]

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, this script implements the CreateChatCompletion tool
# (renamed to StructuredResponseFormatter for clarity). [Source: 588] This tool's primary function is to
# define a specific JSON schema that is provided to the Gemini LLM. The LLM is then instructed
# to return its response in the form of arguments matching this schema. The tool's 'execute'
# method then receives these structured arguments from the agent, effectively allowing DRIM AI
# to obtain structured data from the LLM instead of just free-form text. [Source: 589, 598, 599]