from typing import List # [Source: 87]

from pydantic import Field

from app.agent.toolcall import ToolCallAgent # [Source: 87]
# Ensure this prompt is suitable for Gemini and DRIM AI
from app.prompt.swe import SYSTEM_PROMPT as SWE_SYSTEM_PROMPT # [Source: 87]
from app.tool import Bash, StrReplaceEditor, Terminate, ToolCollection # [Source: 87]
from app.llm import LLM # Ensures it uses the DRIM AI (Gemini) LLM

class SWEAgent(ToolCallAgent): # [Source: 87]
    """
    A DRIM AI agent that implements the SWE-Agent paradigm for
    executing code and performing software engineering tasks via natural conversations
    and tool use. [Source: 87]
    """
    name: str = Field(default="drim_swe_agent") # Renamed for DRIM AI [Source: 87]
    description: str = Field(default="A DRIM AI autonomous programmer that interacts directly with the computer (shell, file editor) to solve software engineering tasks.") # [Source: 87]
    
    system_prompt: str = Field(default=SWE_SYSTEM_PROMPT) # [Source: 88]
    # next_step_prompt for SWEAgent in the PDF seems to be empty or not explicitly defined for the class,
    # meaning it would inherit ToolCallAgent's default next_step_prompt.
    # If SWE needs a specific one, it should be defined here or in app/prompt/swe.py and imported.
    # The PDF shows: next_step_prompt: str = "" [Source: 88] -> let's keep this.
    next_step_prompt: str = Field(default="") # An empty next_step_prompt might mean the system_prompt is very directive.

    available_tools: ToolCollection = Field( # [Source: 88]
        default_factory=lambda: ToolCollection(
            Bash(), 
            StrReplaceEditor(), 
            Terminate()
        )
    )
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name]) # [Source: 88]
    max_steps: int = Field(default=20) # [Source: 88]

    # Ensure LLM is the DRIM AI (Gemini) LLM
    llm: LLM = Field(default_factory=LLM)

# Role in the System (Updated for DRIM AI)
# As part of the agent subsystem, this script contributes to the core
# intelligence and decision-making capabilities of DRIM AI. [Source: 89, 90] The SWEAgent
# components specifically enable DRIM AI to understand software engineering tasks,
# formulate plans involving shell commands and file editing, and execute these actions. [Source: 90]