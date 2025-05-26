#!/usr/bin/env python # [Source: 805]
import argparse # [Source: 805]
import asyncio # [Source: 805]
import sys # [Source: 805]
from pathlib import Path

project_root_run_mcp = Path(__file__).resolve().parent
if str(project_root_run_mcp) not in sys.path:
    sys.path.insert(0, str(project_root_run_mcp))

from app.agent.mcp import MCPAgent as DrimMCPAgent # [Source: 805]
from app.config import config as drim_ai_config # [Source: 805]
from app.logger import logger, define_log_level # [Source: 805]

class DrimMCPRunner: # Renamed class [Source: 805]
    """Runner class for DRIM AI's MCPAgent."""
    def __init__(self): # [Source: 805]
        self.mcp_settings = drim_ai_config.mcp # [Source: 805]
        if not self.mcp_settings:
            from app.config import MCPSettings as DrimMCPSettings # type: ignore
            self.mcp_settings = DrimMCPSettings() # Fallback
            logger.warning("DRIM AI MCPRunner: MCP settings not found in config, using defaults. Functionality may be limited.")
        
        self.server_reference_module = self.mcp_settings.server_reference # [Source: 805]
        self.agent = DrimMCPAgent() # [Source: 805]
        # If MCPAgent needs a specific default_llm_purpose, set it here:
        # self.agent.default_llm_purpose = "simple" # Example

    async def initialize_agent_connection(self, connection_type: str, server_url: Optional[str] = None) -> None: # [Source: 805]
        logger.info(f"DRIM AI MCPRunner: Initializing MCPAgent with {connection_type} connection...") # [Source: 805]
        if connection_type == "stdio": # [Source: 806]
            python_executable = sys.executable
            # Command to run the DRIM AI MCP server module
            command_args = ["-m", self.server_reference_module, "--transport=stdio"] # Ensure server also uses stdio [Source: 806]
            # Add server_name if your server parse_args expects it
            # command_args.extend(["--server-name", "drim_mcp_stdio_server"])
            await self.agent.initialize(connection_type="stdio", command=python_executable, args=command_args) # [Source: 806]
        elif connection_type == "sse": # [Source: 806]
            if not server_url: raise ValueError("DRIM AI MCPRunner: Server URL is required for SSE.")
            await self.agent.initialize(connection_type="sse", server_url=server_url) # [Source: 806]
        else: raise ValueError(f"DRIM AI MCPRunner: Unsupported connection type '{connection_type}'.")
        logger.info(f"DRIM AI MCPRunner: MCPAgent connection via {connection_type} established.") # [Source: 806]

    async def run_interactive_mode(self) -> None: # [Source: 806]
        print("\n--- DRIM AI MCP Agent Interactive Mode --- (type 'exit' or 'quit' to end)\n") # [Source: 806]
        while True:
            try:
                user_input = input("You (to DRIM AI MCP Agent): ").strip() # [Source: 806]
                if user_input.lower() in ["exit", "quit", "q"]: logger.info("Exiting interactive."); break # [Source: 806]
                if not user_input: continue
                response = await self.agent.run(user_input) # [Source: 806]
                print(f"DRIM AI MCP Agent: {response}\n") # [Source: 806]
            except EOFError: logger.info("EOF received, exiting."); break
            except KeyboardInterrupt: logger.info("Interrupted, exiting."); break

    async def run_with_single_prompt(self, prompt: str) -> None: # [Source: 806]
        logger.info(f"DRIM AI MCPRunner: Single prompt: '{prompt[:100]}...'")
        response = await self.agent.run(prompt) # [Source: 807]
        print(f"DRIM AI MCP Agent Response:\n{response}")
        logger.info("DRIM AI MCPRunner: Single prompt execution complete.") # [Source: 807]

    async def run_default_prompt_mode(self) -> None: # [Source: 807]
        prompt = input("Enter prompt for DRIM AI MCPAgent: ").strip() # [Source: 807]
        if not prompt: logger.warning("Empty prompt. Exiting."); return # [Source: 807]
        logger.info(f"DRIM AI MCPRunner: Processing: '{prompt[:100]}...'") # [Source: 807]
        response = await self.agent.run(prompt) # [Source: 807]
        print(f"DRIM AI MCP Agent Response:\n{response}")
        logger.info("DRIM AI MCPRunner: Request complete.") # [Source: 807]

    async def perform_cleanup(self) -> None: # [Source: 807]
        logger.info("DRIM AI MCPRunner: Cleaning up MCPAgent resources...")
        await self.agent.cleanup() # [Source: 807]
        logger.info("DRIM AI MCPRunner: Session ended and resources cleaned.") # [Source: 807]

def parse_cli_args_mcp_client() -> argparse.Namespace: # Renamed [Source: 807]
    parser = argparse.ArgumentParser(description="Run the DRIM AI MCP Agent Client") # [Source: 807]
    parser.add_argument("--connection", "-c", choices=["stdio", "sse"], default="stdio", help="Connection type to MCP server (default: stdio)") # [Source: 808]
    parser.add_argument("--server-url", "-s", default="http://127.0.0.1:8001/sse", help="URL for SSE connection (if MCP server runs on port 8001)") # [Source: 808] Adjusted port
    parser.add_argument("--interactive", "-i", action="store_true", help="Run in interactive mode") # [Source: 808]
    parser.add_argument("--prompt", "-p", help="Single prompt to execute and then exit") # [Source: 808]
    return parser.parse_args()

async def main_mcp_client_runner(): # Renamed [Source: 808]
    define_log_level(print_level="INFO", logfile_level="DEBUG", name="DRIM_AI_MCPClientRunner")
    args = parse_cli_args_mcp_client()
    runner = DrimMCPRunner()
    try:
        await runner.initialize_agent_connection(args.connection, args.server_url) # [Source: 808]
        if args.prompt: await runner.run_with_single_prompt(args.prompt) # [Source: 808]
        elif args.interactive: await runner.run_interactive_mode() # [Source: 808]
        else: await runner.run_default_prompt_mode() # [Source: 808]
    except KeyboardInterrupt: logger.info("DRIM AI MCPRunner: Program interrupted by user.") # [Source: 808]
    except ValueError as ve: logger.error(f"DRIM AI MCPRunner: Configuration/Argument Error: {ve}"); sys.exit(1)
    except Exception as e: logger.exception("DRIM AI MCPRunner: An error occurred running MCPAgent."); sys.exit(1) # [Source: 808]
    finally: await runner.perform_cleanup() # [Source: 808]

if __name__ == "__main__": # [Source: 808]
    try: asyncio.run(main_mcp_client_runner())
    except KeyboardInterrupt: logger.info("DRIM AI MCPClientRunner terminated by user at asyncio.run.")