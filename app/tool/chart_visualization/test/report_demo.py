import asyncio
from app.agent.data_analysis import DataAnalysis # [Source: 583]
# from app.agent.manus import Manus # Original had this commented out [Source: 583]
from app.logger import logger, define_log_level

# Define log level for test script visibility
define_log_level(print_level="INFO")

async def main(): # [Source: 583]
    logger.info("--- Starting DRIM AI Data Report Demo ---")
    
    # For DRIM AI, ensure DataAnalysis agent is correctly initialized
    drim_data_agent = DataAnalysis() # [Source: 583]
    # drim_agent = Manus() # If testing with Manus agent for this task

    report_request = """\
DRIM AI, please perform the following:
1. Analyze the provided data on team working hours.
2. Generate a comprehensive data report in HTML format discussing trends, comparisons, and any insights.
3. The report should include at least one visual chart (e.g., comparing total hours per team, or monthly trends).
4. Save all outputs (report, charts, intermediate CSVs/JSON if any) in the DRIM AI workspace.

Data:
Month | Team A | Team B | Team C
January | 1200 hours | 1350 hours | 1100 hours
February | 1250 hours | 1400 hours | 1150 hours
March | 1180 hours | 1300 hours | 1300 hours
April | 1220 hours | 1280 hours | 1400 hours
May | 1230 hours | 1320 hours | 1450 hours
June | 1200 hours | 1250 hours | 1500 hours 
""" # [Source: 584] (Adapted request for DRIM AI)

    logger.info(f"Sending request to DRIM AI DataAnalysis agent for report generation:\n{report_request[:300]}...")
    try:
        await drim_data_agent.run(report_request) # [Source: 584]
        logger.info("--- DRIM AI Data Report Demo: Request processing finished. Check workspace for outputs. ---")
    except Exception as e:
        logger.error("--- DRIM AI Data Report Demo: Error during report generation ---")
        logger.exception(e)
    
    logger.info("--- DRIM AI Data Report Demo Finished ---")

if __name__ == "__main__": # [Source: 585]
    asyncio.run(main())