# File: main.py
import asyncio
import sys
from pathlib import Path

# Ensure app module is discoverable
project_root_main = Path(__file__).resolve().parent
if str(project_root_main) not in sys.path:
    sys.path.insert(0, str(project_root_main))

from app.agent.manus import Manus as DrimManusAgent # [Source: 796]
from app.logger import logger, define_log_level # [Source: 796]
from app.config import config as drim_ai_config # [Source: 796]

async def main_drim_ai_execution(): # Renamed main function
    # Configure logging for DRIM AI main execution
    define_log_level(print_level="INFO", logfile_level="DEBUG", name="DRIM_AI_Core_Execution")
    logger.info("--- Starting DRIM AI Core Execution ---")
    logger.info(f"DRIM AI Workspace Root: {drim_ai_config.workspace_root}") #
    logger.info(f"DRIM AI Using Gemini Primary Model: {drim_ai_config.gemini.primary_model}") #
    if drim_ai_config.gemini.small_model:
        logger.info(f"DRIM AI Using Gemini Small Model: {drim_ai_config.gemini.small_model}") #
    logger.info(f"DRIM AI Using Gemini Multimodal Model: {drim_ai_config.gemini.multimodal_model}") #
    logger.info(f"DRIM AI Primary Search Engine: {drim_ai_config.search.primary_engine}") #


    agent = None  # Initialize agent to None for cleanup scope
    try:
        # The Manus.create() method handles its internal async initializations (like MCP, browser helper)
        agent = await DrimManusAgent.create() # [Source: 796]
        logger.info("DRIM AI Manus Agent created and initialized successfully.")
    except Exception as e:
        logger.exception("DRIM AI: Critical error - Failed to create or initialize the Manus agent.")
        return

    try:
        while True:
            prompt = input("\nDRIM is ready. Enter your prompt (or type 'exit' or 'quit' to end): ").strip() # [Source: 796] **MODIFIED for prefix**
            if prompt.lower() in ['exit', 'quit']: # [Source: 796]
                logger.info("DRIM: Exit command received. Shutting down.") # **MODIFIED for prefix**
                break
            if not prompt:
                logger.info("DRIM: Empty prompt received. Please enter a command or 'exit'.") # **MODIFIED for prefix**
                continue

            logger.info(f"DRIM: Processing your request: '{prompt[:150]}...'") # [Source: 796] **MODIFIED for prefix**
            
            agent_run_summary = await agent.run(prompt) # [Source: 796]
            
            # **MODIFICATION START for prefix**
            print(f"\nDRIM:\n{agent_run_summary}\n")
            # **MODIFICATION END**
            
            logger.info("DRIM: Request processing cycle complete. Ready for next prompt.") # **MODIFIED for prefix**

    except KeyboardInterrupt: # [Source: 796]
        logger.warning("DRIM: Operation interrupted by user (KeyboardInterrupt).") # [Source: 796] **MODIFIED for prefix**
    except EOFError:
        logger.info("DRIM: EOF received, exiting.") # Handle piped input scenarios **MODIFIED for prefix**
    except Exception as e:
        logger.exception("DRIM: An unexpected error occurred during the main execution loop.") # **MODIFIED for prefix**
    finally:
        logger.info("DRIM: Shutting down gracefully. Cleaning up agent resources...") # **MODIFIED for prefix**
        if agent: # Ensure agent was successfully initialized before cleanup
            await agent.cleanup() # [Source: 796]
        logger.info("--- DRIM Core Execution Finished ---") # **MODIFIED for prefix**

if __name__ == "__main__": # [Source: 796]
    try:
        asyncio.run(main_drim_ai_execution())
    except KeyboardInterrupt:
        logger.info("DRIM terminated by user before full startup or during shutdown.") # **MODIFIED for prefix**
    except Exception as e:
        logger.critical(f"DRIM: Critical error at asyncio.run level: {e}", exc_info=True) # **MODIFIED for prefix**