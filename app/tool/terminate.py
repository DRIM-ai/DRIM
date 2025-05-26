from app.tool.base import BaseTool, ToolResult # [Source: 752]

_TERMINATE_DESCRIPTION_DRIM_AI = """\
Use this tool to conclude the current interaction with DRIM AI.
Call this when the user's request has been fully met, OR if you determine that you cannot proceed further with the task due to insurmountable issues or lack of capability.
Clearly state the final status (success or failure) and provide a concise summary if appropriate.
""" # Adapted from [Source: 752]

class Terminate(BaseTool): # [Source: 752]
    """A DRIM AI tool to formally end the current interaction or task."""
    name: str = "terminate" # [Source: 752]
    description: str = _TERMINATE_DESCRIPTION_DRIM_AI # [Source: 752]
    parameters: dict = { # [Source: 752]
        "type": "object",
        "properties": {
            "status": { # [Source: 752]
                "type": "string",
                "description": "The final status of the interaction. Indicate 'success' if the primary goal was achieved, or 'failure' if it was not or could not be completed.", # [Source: 752]
                "enum": ["success", "failure"], # [Source: 752]
            },
            "message": {
                "type": "string",
                "description": "(Optional) A final message or summary detailing the outcome, why the task is ending, or any concluding remarks for the user.",
            }
        },
        "required": ["status"], # [Source: 752]
    }

    async def execute(self, status: str, message: str = "") -> str: # [Source: 752] Changed to return str for direct LLM observation as per original
        """
        Signals the end of the agent's execution with a status.
        The agent's main loop will see this tool and set its state to FINISHED.
        """
        final_message = f"DRIM AI interaction has been completed with status: {status}." # [Source: 752]
        if message:
            final_message += f" Final message: {message}"
        
        # This tool itself doesn't stop the agent; it signals the agent's control loop.
        # The string returned is what the agent observes from the tool call.
        return final_message

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, this script implements the Terminate tool. [Source: 750, 753]
# This tool is crucial for enabling DRIM AI agents to gracefully conclude their tasks,
# signaling whether the objective was met successfully or if the interaction ended
# due to other reasons. [Source: 751, 754, 755]