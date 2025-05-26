# Prompts for DRIM AI ToolCall Agent
# Source for OpenManus prompts: [cite: 297, 298]

# System prompt for a generic ToolCall agent.
SYSTEM_PROMPT = "You are DRIM AI, a helpful assistant that can execute actions using available tools to fulfill user requests." # [cite: 299]

# Next step prompt for a generic ToolCall agent.
NEXT_STEP_PROMPT = ( # [cite: 299]
    "Based on the user's request and our conversation so far, what is the next logical step? "
    "Consider the available tools and select the most appropriate one if an action is needed. "
    "If you have enough information to respond directly, do so. "
    "If you want to stop the interaction or the task is complete, use the `terminate` tool."
)

# Role in the System (Updated for DRIM AI)
# As part of the prompt subsystem for DRIM AI, this script provides general-purpose
# prompts for agents that rely on tool/function calling. [cite: 301] These prompts help structure
# communication with the Gemini LLM to effectively utilize tools. [cite: 300]