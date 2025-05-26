import asyncio
from app.agent.data_analysis import DataAnalysis # [Source: 575]
from app.logger import logger, define_log_level # [Source: 575]

# Define log level for test script visibility
define_log_level(print_level="INFO")

DRIM_AI_CHART_PREFIX = "DRIM AI, please help me generate charts and save them locally. Specifically:" # [Source: 575] (Adapted prefix)

tasks = [ # [Source: 575]
    {
        "prompt": "Show the sales of different products in different regions", # [Source: 575]
        "data": """Product Name,Region,Sales
Coke,South,2350
Coke,East,1027
Coke,West,1027
Coke,North,1027
Sprite,South,215
Sprite,East,654
Sprite,West,159
Sprite,North,28
Fanta,South,345
Fanta,East,654
Fanta,West,2100
Fanta,North,1679
Xingmu,South,1476
Xingmu,East,830
Xingmu,West,532
Xingmu,North,498
""", # [Source: 576]
    },
    {
        "prompt": "Show market share of each brand", # [Source: 576]
        "data": """Brand Name,Market Share,Average Price,Net Profit
Apple,0.5,7068,314531
Samsung,0.2,6059,362345
Vivo,0.05,3406,234512
Nokia,0.01,1064,-1345
Xiaomi,0.1,4087,131345""", # [Source: 576]
    },
    # ... other tasks from PDF [Source: 576-580] can be included here ...
    {
        "prompt": "Show data flow between nodes", # [Source: 579]
        "data": """Origin,Destination,value
Node A,Node 1,10
Node A,Node 2,5
Node B,Node 2,8
Node B,Node 3,2
Node C,Node 2,4
Node A,Node C,2
Node C,Node 1,2""", # [Source: 580]
    },
]

async def main(): # [Source: 580]
    logger.info("--- Starting DRIM AI Chart Demo ---")
    for index, item in enumerate(tasks): # [Source: 580]
        task_number = index + 1
        logger.info(f"--- DRIM AI Chart Demo: Begin Task {task_number} / {len(tasks)} ---")
        logger.info(f"Task Description: {item['prompt']}")
        
        # For DRIM AI, ensure DataAnalysis agent is correctly initialized
        # (uses Gemini LLM by default via its ToolCallAgent inheritance)
        drim_data_agent = DataAnalysis() # [Source: 580]
        
        # Construct the full request for the agent
        # The agent will use VisualizationPrepare (Python code to make JSON with CSV paths)
        # then DataVisualization (calls TS script with that JSON path)
        full_request = (
            f"{DRIM_AI_CHART_PREFIX}\n"
            f"Chart Description: {item['prompt']}\n"
            f"Data (CSV format):\n{item['data']}"
        )
        
        logger.info(f"Sending request to DRIM AI DataAnalysis agent:\n{full_request[:300]}...")
        try:
            await drim_data_agent.run(full_request) # [Source: 580]
            logger.info(f"--- DRIM AI Chart Demo: Finished Task {task_number}: {item['prompt']} ---")
        except Exception as e:
            logger.error(f"--- DRIM AI Chart Demo: Error in Task {task_number}: {item['prompt']} ---")
            logger.exception(e)
        logger.info("-" * 50)

    logger.info("--- DRIM AI Chart Demo Finished ---")

if __name__ == "__main__": # [Source: 580]
    asyncio.run(main())