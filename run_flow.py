import asyncio
import time
import sys
from pathlib import Path

project_root_run_flow = Path(__file__).resolve().parent
if str(project_root_run_flow) not in sys.path:
    sys.path.insert(0, str(project_root_run_flow))

from app.agent.manus import Manus as DrimManusAgent # [Source: 801]
# from app.agent.data_analysis import DataAnalysis as DrimDataAnalysisAgent # If another agent is needed
from app.flow.flow_factory import FlowFactory, FlowType # [Source: 801]
from app.logger import logger, define_log_level # [Source: 801]
from app.config import config as drim_ai_config # [Source: 801]

async def run_drim_ai_planning_flow(): # Renamed function more specifically
    define_log_level(print_level="INFO", logfile_level="DEBUG", name="DRIM_AI_PlanningFlowRunner")
    logger.info("--- Starting DRIM AI Planning Flow Runner ---")
    logger.info(f"DRIM AI Workspace Root: {drim_ai_config.workspace_root}")

    manus_agent_for_flow = None
    try:
        # For PlanningFlow, agents passed to it will use their own default_llm_purpose.
        # PlanningFlow itself uses specific model_purpose for plan creation/finalization.
        manus_agent_for_flow = await DrimManusAgent.create()
        # Example: If Manus for this flow should use a 'simple' model by default for its thinking steps
        # manus_agent_for_flow.default_llm_purpose = "simple" # Overriding default from ToolCallAgent
        logger.info("DRIM AI Manus agent for flow created.")
    except Exception as e:
        logger.exception("DRIM AI PlanningFlowRunner: Failed to create agents for the flow.")
        return

    agents_in_flow = {
        "primary_executor": manus_agent_for_flow, # Key for the agent
    }

    try:
        prompt = input("DRIM AI PlanningFlowRunner ready. Enter your complex task prompt (or type 'exit'): ").strip() # [Source: 801]
        if not prompt or prompt.lower() == 'exit': # [Source: 801]
            logger.info("No prompt or exit command. Exiting DRIM AI PlanningFlowRunner.")
            return

        drim_planning_flow = FlowFactory.create_flow( # [Source: 801]
            flow_type=FlowType.PLANNING,
            agents=agents_in_flow,
            primary_agent_key="primary_executor", # Explicitly set which agent key is primary for the flow
            # executors=["primary_executor"], # PlanningFlow's __init__ takes 'executors'
            # Override default model purposes for planning flow's own LLM calls if needed:
            # plan_creation_llm_purpose="simple",
            # plan_finalization_llm_purpose="simple",
        )
        logger.info(f"DRIM AI PlanningFlow created. Processing task: '{prompt[:150]}...'") # [Source: 801]
        
        flow_timeout_seconds = 3600  # 1 hour [Source: 801]
        start_time = time.time() # [Source: 801]
        try:
            result = await asyncio.wait_for(
                drim_planning_flow.execute(prompt), # [Source: 801]
                timeout=flow_timeout_seconds,
            )
            elapsed_time = time.time() - start_time # [Source: 802]
            logger.info(f"DRIM AI PlanningFlowRunner: Task processed in {elapsed_time:.2f} seconds.") # [Source: 802]
            logger.info(f"--- Final Flow Output ---\n{result}") # [Source: 802]
        except asyncio.TimeoutError: # [Source: 802]
            logger.error(f"DRIM AI PlanningFlowRunner: Task processing timed out after {flow_timeout_seconds / 60:.0f} minutes.") # [Source: 802]
        except KeyboardInterrupt: # [Source: 802]
            logger.info("DRIM AI PlanningFlowRunner: Task cancelled by user.") # [Source: 802]
        except Exception as e: # [Source: 802]
            logger.exception("DRIM AI PlanningFlowRunner: An error occurred during flow execution.") # [Source: 802]

    finally:
        logger.info("DRIM AI PlanningFlowRunner: Shutting down. Cleaning up flow agent resources...")
        if manus_agent_for_flow:
            await manus_agent_for_flow.cleanup()
        logger.info("--- DRIM AI Planning Flow Runner Finished ---")

if __name__ == "__main__": # [Source: 802]
    try:
        asyncio.run(run_drim_ai_planning_flow())
    except KeyboardInterrupt:
        logger.info("DRIM AI PlanningFlowRunner terminated by user at asyncio.run level.")
    except Exception as e:
        logger.critical(f"DRIM AI PlanningFlowRunner: Critical error during asyncio.run: {e}", exc_info=True)