# DRIM AI Prompts Package
# This package contains various prompt templates used by DRIM AI agents
# to interact with the Gemini LLM and guide its responses for specific tasks.

# Example: You could import specific prompts here to make them available as:
# from app.prompt import BROWSER_SYSTEM_PROMPT
# from .browser import SYSTEM_PROMPT as BROWSER_SYSTEM_PROMPT
# from .manus import SYSTEM_PROMPT as MANUS_SYSTEM_PROMPT
# ... and so on for other key prompts if desired for easier access.

# For now, this file primarily serves to make 'prompt' a package.
# Agents will import directly from the specific modules (e.g., from app.prompt.browser import ...).

# Description for DRIM AI, based on original source for OpenManus [cite: 231, 232]
# This module defines prompt templates used to structure the
# communication between the DRIM AI system and the underlying Gemini language
# model. [cite: 231] Well-crafted prompts are essential for guiding the model to
# produce useful and relevant outputs for DRIM AI. [cite: 232]