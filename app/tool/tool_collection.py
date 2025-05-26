# [Source: 758]
"""Collection classes for managing multiple DRIM AI tools."""
from typing import Any, Dict, List, Tuple, Iterator, Optional # MODIFIED: Added Optional

from app.exceptions import ToolError # [Source: 758]
from app.logger import logger # [Source: 758]
from app.tool.base import BaseTool, ToolFailure, ToolResult # [Source: 758]

class ToolCollection: # [Source: 758]
    def __init__(self, *tools: BaseTool): # [Source: 758]
        self.tools: Tuple[BaseTool, ...] = tools 
        self.tool_map: Dict[str, BaseTool] = {tool.name: tool for tool in tools} 

    def __iter__(self) -> Iterator[BaseTool]: # [Source: 758]
        return iter(self.tools)

    def to_params(self) -> List[Dict[str, Any]]: # [Source: 758]
        """Converts all tools in the collection to the parameter format for LLM tool calling."""
        return [tool.to_param() for tool in self.tools]

    async def execute( # [Source: 758]
        self, *, name: str, tool_input: Optional[Dict[str, Any]] = None
    ) -> ToolResult: 
        """
        Executes a specific tool by name from the collection.
        Args:
            name: The name of the tool to execute.
            tool_input: A dictionary of arguments for the tool.
        Returns:
            A ToolResult object representing the outcome.
        """
        tool = self.tool_map.get(name) # [Source: 758]
        if not tool: # [Source: 758]
            logger.error(f"DRIM AI ToolCollection: Tool '{name}' not found in collection.")
            return ToolFailure(error=f"Tool {name} is invalid or not found in the collection.") # [Source: 758]
        
        logger.info(f"DRIM AI ToolCollection: Executing tool '{name}' with input: {tool_input if tool_input else '{}'}")
        try:
            result_any = await tool(**(tool_input or {})) # [Source: 759]
            
            if isinstance(result_any, ToolResult):
                return result_any
            elif isinstance(result_any, str): 
                return ToolResult(output=result_any)
            elif isinstance(result_any, dict) and ("output" in result_any or "error" in result_any): 
                 return ToolResult(**result_any)
            else: 
                logger.warning(f"DRIM AI ToolCollection: Tool '{name}' returned an unexpected type '{type(result_any)}'. Coercing to string.")
                return ToolResult(output=str(result_any))

        except ToolError as te: # [Source: 759] 
            logger.error(f"DRIM AI ToolCollection: ToolError from '{name}': {te.message}")
            return ToolFailure(error=te.message) # [Source: 759]
        except Exception as e:
            logger.exception(f"DRIM AI ToolCollection: Unexpected error executing tool '{name}'.")
            return ToolFailure(error=f"Unexpected error executing tool {name}: {str(e)}")

    async def execute_all(self) -> List[ToolResult]: # [Source: 759]
        """Executes all tools in the collection sequentially (if they take no input or have defaults)."""
        results: List[ToolResult] = []
        logger.info("DRIM AI ToolCollection: Executing all tools in collection...")
        for tool in self.tools: # [Source: 759]
            try:
                result_any = await tool() # Call with no arguments [Source: 759]
                if isinstance(result_any, ToolResult):
                    results.append(result_any)
                else:
                    results.append(ToolResult(output=str(result_any)))
            except ToolError as te: # [Source: 759]
                logger.error(f"DRIM AI ToolCollection: ToolError from '{tool.name}' during execute_all: {te.message}")
                results.append(ToolFailure(error=te.message)) # [Source: 759]
            except Exception as e:
                logger.exception(f"DRIM AI ToolCollection: Unexpected error executing tool '{tool.name}' during execute_all.")
                results.append(ToolFailure(error=f"Unexpected error executing tool {tool.name}: {str(e)}"))
        return results

    def get_tool(self, name: str) -> Optional[BaseTool]: # [Source: 759] 
        return self.tool_map.get(name)

    def add_tool(self, tool: BaseTool) -> "ToolCollection": # [Source: 759]
        """Add a single tool to the collection.
        If a tool with the same name already exists, it will be skipped and a warning will be logged.
        """
        if tool.name in self.tool_map: # [Source: 759]
            logger.warning(f"DRIM AI ToolCollection: Tool '{tool.name}' already exists in collection. Skipping addition.") # [Source: 759]
            return self
        
        new_tools_list = list(self.tools)
        new_tools_list.append(tool)
        self.tools = tuple(new_tools_list)
        self.tool_map[tool.name] = tool # [Source: 760]
        logger.info(f"DRIM AI ToolCollection: Added tool '{tool.name}'.")
        return self

    def add_tools(self, *new_tools: BaseTool) -> "ToolCollection": # [Source: 760] 
        """Add multiple tools to the collection.
        If any tool has a name conflict with an existing tool, it will be skipped and a warning logged. [Source: 761]
        """
        for tool_to_add in new_tools: # [Source: 761]
            self.add_tool(tool_to_add) # [Source: 761]
        return self
    
    def get_tool_names(self) -> List[str]:
        """Returns a list of names of all tools in the collection."""
        return list(self.tool_map.keys())

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, this script provides the ToolCollection
# class. [Source: 756, 762] This class is essential for managing, organizing, and executing
# groups of tools that DRIM AI agents can use, facilitating the dynamic extension
# of an agent's capabilities. [Source: 757, 763, 764]