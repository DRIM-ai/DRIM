from app.tool.base import BaseTool, ToolResult # [Source: 426] (ToolResult can be used for more structured output if needed)
from app.logger import logger

class AskHuman(BaseTool): # [Source: 426]
    """A DRIM AI tool to pause and ask the human user for help or clarification."""
    name: str = "ask_human" # [Source: 426]
    description: str = ( # [Source: 426]
        "Use this tool when you need to ask the human user for specific input, "
        "clarification, a decision, or help to overcome an obstacle. "
        "Clearly formulate your question to the human."
    )
    parameters: dict = { # [Source: 427]
        "type": "object",
        "properties": {
            "question": { # MODIFIED: Renamed from "inquire" to "question"
                "type": "string",
                "description": "The specific question or request you want to pose to the human user.", # [Source: 427]
            }
        },
        "required": ["question"], # MODIFIED: Renamed from "inquire" to "question"
    }

    async def execute(self, question: str) -> str: # MODIFIED: Renamed parameter from "inquire" to "question"
        """
        Poses the question to the human and waits for their input.
        """
        logger.info(f"DRIM AI (AskHuman Tool) asking user: '{question}'") # MODIFIED: Used 'question'
        # The original PDF directly uses input(). For a more robust system,
        # this might integrate with a proper UI or a different input mechanism.
        # For now, keeping it simple as per the original.
        try:
            # Ensure the prompt to the human is clearly from DRIM AI
            response = input(f"\nDRIM AI needs your input: {question}\nYour response: ") # MODIFIED: Used 'question' [Source: 427]
            logger.info(f"DRIM AI (AskHuman Tool) received from user: '{response.strip()}'")
            return response.strip()
        except EOFError:
            logger.warning("DRIM AI (AskHuman Tool): EOFError received, likely no human input available (e.g., in a non-interactive script).")
            return "No human input received (EOF)."
        except KeyboardInterrupt:
            logger.warning("DRIM AI (AskHuman Tool): KeyboardInterrupt received during input. Assuming no input.")
            # Propagate the interrupt if the agent needs to handle it globally,
            # or return a specific message. For now, returning a message.
            # raise # Option to re-raise
            return "Human input interrupted."

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, this script implements the AskHuman tool. [Source: 424, 428]
# This tool allows DRIM AI agents to interact directly with the human user to ask for
# guidance, clarification, or missing information, which is crucial for handling
# ambiguous situations or tasks requiring human judgment. [Source: 425, 429]