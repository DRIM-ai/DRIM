import asyncio
import os
import signal # For process group termination
from typing import Optional, Tuple, Any # MODIFIED: Added Any

from app.exceptions import ToolError 
from app.tool.base import BaseTool, CLIResult 
from app.logger import logger

_BASH_TOOL_DESCRIPTION_DRIM_AI = """\
Executes a bash command in the DRIM AI agent's local terminal environment.
USE WITH CAUTION: Commands are executed directly on the host system where DRIM AI is running.
Consider security implications before enabling or using this tool extensively, especially in untrusted environments.
For sandboxed execution, a different tool or modification would be required.

Features:
* Long running commands: For commands that may run indefinitely (e.g., starting a server), it's best to run them in the background and redirect output to a file (e.g., `python3 app.py > server.log 2>&1 &`). The tool itself might not be suitable for managing very long-lived background processes directly without specific design for it.
* Interactive-like behavior: If a bash command (process within the session) is not yet finished, subsequent calls with an empty `command` might retrieve additional logs (depending on session implementation), or send text to STDIN, or `ctrl+c` to attempt interruption. The PDF's original `_BashSession` implementation has specific logic for this.
* Timeout: Commands are subject to a timeout. If a command times out, the session might need restarting.
""" 

class _BashSession: 
    _process: Optional[asyncio.subprocess.Process] = None 
    _command_to_start_shell: str = "/bin/bash" 
    _output_read_delay_seconds: float = 0.1 
    _command_timeout_seconds: float = 120.0 
    _sentinel_value: str 

    def __init__(self):
        self._is_started: bool = False 
        self._has_timed_out: bool = False 
        self._sentinel_value = f"<<DRIM_BASH_CMD_END_{os.urandom(4).hex()}>>"

    async def start(self) -> None: 
        if self._is_started:
            return
        logger.info("DRIM AI BashTool: Starting new local bash session...")
        try:
            self._process = await asyncio.create_subprocess_shell( 
                self._command_to_start_shell,
                stdin=asyncio.subprocess.PIPE, 
                stdout=asyncio.subprocess.PIPE, 
                stderr=asyncio.subprocess.PIPE, 
                shell=True, 
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
                creationflags=asyncio.subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            )
            self._is_started = True
            logger.info(f"DRIM AI BashTool: Local bash session started (PID: {self._process.pid if self._process else 'N/A'}).") # Added None check
        except Exception as e:
            logger.error(f"DRIM AI BashTool: Failed to start local bash session: {e}")
            self._is_started = False
            raise ToolError(f"Failed to start bash session: {e}")

    def stop(self) -> None: 
        """Terminate the bash shell and its process group."""
        if not self._is_started or not self._process:
            return

        if self._process.returncode is not None:
            logger.info(f"DRIM AI BashTool: Local bash session (PID: {self._process.pid}) already exited with code {self._process.returncode}.")
            return

        logger.info(f"DRIM AI BashTool: Stopping local bash session (PID: {self._process.pid})...")
        try:
            if hasattr(os, 'killpg') and hasattr(os, 'getsid') and self._process.pid is not None:
                pgid = os.getpgid(self._process.pid)
                os.killpg(pgid, signal.SIGTERM) 
                logger.debug(f"DRIM AI BashTool: Sent SIGTERM to process group {pgid}.")
            else: 
                self._process.terminate() 
                logger.debug(f"DRIM AI BashTool: Sent SIGTERM to process {self._process.pid}.")
        except ProcessLookupError:
            logger.warning(f"DRIM AI BashTool: Process {self._process.pid if self._process else 'N/A'} not found during stop (already exited?).") # Added None check
        except Exception as e:
            logger.error(f"DRIM AI BashTool: Error during bash session stop: {e}")
        finally:
            self._is_started = False
            self._process = None

    async def run(self, command: str) -> CLIResult: 
        """Execute a command in the bash shell."""
        if not self._is_started or not self._process: 
            raise ToolError("DRIM AI BashTool: Session has not started. Call start() or restart tool.")
        
        if self._process.returncode is not None: 
            return CLIResult(
                system_message="DRIM AI BashTool: Bash session has exited and must be restarted.", 
                error=f"Bash has exited with returncode {self._process.returncode}", 
            )
        if self._has_timed_out: 
            raise ToolError(
                f"DRIM AI BashTool: Session timed out previously. Bash must be restarted. Timeout was {self._command_timeout_seconds}s." 
            )

        stdin = self._process.stdin
        stdout = self._process.stdout
        stderr = self._process.stderr

        if not stdin or not stdout or not stderr: 
            raise ToolError("DRIM AI BashTool: stdin, stdout, or stderr not available for the bash process.")

        full_command_str = f"{command.strip()}; echo '{self._sentinel_value}'$? \n"
        
        logger.debug(f"DRIM AI BashTool: Sending to bash: {full_command_str.strip()}")
        stdin.write(full_command_str.encode("utf-8"))
        await stdin.drain() 

        output_buffer = b""
        error_buffer = b""
        
        try: 
            async with asyncio.timeout(self._command_timeout_seconds): 
                while True: 
                    try:
                        stdout_chunk = await asyncio.wait_for(stdout.read(4096), timeout=self._output_read_delay_seconds)
                        if stdout_chunk: output_buffer += stdout_chunk
                    except asyncio.TimeoutError: 
                        pass 
                    
                    try:
                        stderr_chunk = await asyncio.wait_for(stderr.read(4096), timeout=self._output_read_delay_seconds)
                        if stderr_chunk: error_buffer += stderr_chunk
                    except asyncio.TimeoutError: 
                        pass

                    sentinel_bytes = self._sentinel_value.encode('utf-8')
                    if sentinel_bytes in output_buffer: 
                        raw_output_str = output_buffer.decode("utf-8", errors="replace")
                        last_sentinel_idx = raw_output_str.rfind(self._sentinel_value)
                        if last_sentinel_idx != -1:
                            # actual_output_part = raw_output_str[:last_sentinel_idx].strip() # Not directly used here for final result
                            exit_code_char_idx = last_sentinel_idx + len(self._sentinel_value)
                            if exit_code_char_idx < len(raw_output_str):
                                exit_code_str_from_output = raw_output_str[exit_code_char_idx:].splitlines()[0].strip() 
                                if not exit_code_str_from_output.isdigit(): 
                                    logger.warning(f"DRIM AI BashTool: Could not parse exit code after sentinel. Raw: '{raw_output_str[exit_code_char_idx:]}'")
                            break 
                    
                    if self._process.returncode is not None:
                        logger.warning("DRIM AI BashTool: Bash process exited while reading output.")
                        break
        
        except asyncio.TimeoutError: 
            self._has_timed_out = True 
            logger.error(f"DRIM AI BashTool: Command '{command[:50]}...' timed out after {self._command_timeout_seconds}s.")
            self.stop() 
            raise ToolError(
                f"Timeout: Bash command did not return in {self._command_timeout_seconds} seconds. Session may need restart." 
            ) from None
        
        final_output = output_buffer.decode("utf-8", errors="replace") 
        if self._sentinel_value in final_output:
            final_output = final_output.split(self._sentinel_value, 1)[0]
        
        final_error = error_buffer.decode("utf-8", errors="replace") 
        if final_error.endswith("\n"): final_error = final_error[:-1] 

        return CLIResult(output=final_output.strip(), error=final_error.strip())


class Bash(BaseTool): 
    name: str = "bash" 
    description: str = _BASH_TOOL_DESCRIPTION_DRIM_AI 
    parameters: dict = { 
        "type": "object",
        "properties": {
            "command": { 
                "type": "string",
                "description": "The bash command to execute. "
                               "Can be empty to attempt to view additional logs from an ongoing process (behavior depends on session state). "
                               "Can be 'ctrl+c' to attempt to interrupt the currently running process (experimental).",
            },
            "restart_session": { 
                "type": "boolean",
                "description": "(Optional) Set to true to stop any existing bash session and start a new one. Default: false.",
                "default": False,
            }
        },
        "required": ["command"],
    }
    _session: Optional[_BashSession] = None 

    async def execute( 
        self, command: str, restart_session: bool = False, **kwargs: Any # Type hint for kwargs is now valid
    ) -> CLIResult:
        if command is None: 
            raise ToolError("DRIM AI BashTool: 'command' parameter cannot be None.")

        if restart_session: 
            logger.info("DRIM AI BashTool: Restarting bash session as requested.")
            if self._session:
                self._session.stop() 
            self._session = _BashSession() 
            await self._session.start() 
            return CLIResult(system_message="DRIM AI BashTool: New bash session started.") 

        if self._session is None or not self._session._is_started: 
            logger.info("DRIM AI BashTool: No active bash session, starting a new one.")
            self._session = _BashSession()
            await self._session.start()
        
        if command.strip().lower() == "ctrl+c":
            if self._session and self._session._process and self._session._process.returncode is None:
                logger.info("DRIM AI BashTool: Attempting to send SIGINT (Ctrl+C) to bash process group.")
                try:
                    if hasattr(os, 'killpg') and hasattr(os, 'getsid') and self._session._process.pid is not None:
                        pgid = os.getpgid(self._session._process.pid)
                        os.killpg(pgid, signal.SIGINT)
                        return CLIResult(system_message="DRIM AI BashTool: SIGINT (Ctrl+C) sent to process group. Check subsequent output.")
                    else: 
                         self._session._process.send_signal(signal.SIGINT) 
                         return CLIResult(system_message="DRIM AI BashTool: SIGINT (Ctrl+C) sent to process. Check subsequent output.")
                except Exception as e:
                    return CLIResult(error=f"DRIM AI BashTool: Failed to send Ctrl+C: {e}")
            return CLIResult(system_message="DRIM AI BashTool: No active process in session to send Ctrl+C to.")

        if not command.strip() and self._session and self._session._is_started: 
             logger.info("DRIM AI BashTool: Empty command received, attempting to read lingering output from session.")
             return await self._session.run("") 

        return await self._session.run(command) 

    async def cleanup(self):
        """Cleans up the bash session if active."""
        logger.info("DRIM AI BashTool: Cleaning up bash tool resources...")
        if self._session:
            self._session.stop()
            self._session = None
        logger.info("DRIM AI BashTool: Cleanup complete.")

    def __del__(self):
        if self._session:
            logger.warning("DRIM AI BashTool: Bash session still active during __del__. Ensure cleanup() is called.")
            # self._session.stop() # Synchronous call in __del__ can be problematic

async def _main_test(): 
    bash_tool = Bash()
    try:
        print("--- Test 1: Simple command ---")
        result1 = await bash_tool.execute(command="echo 'Hello from DRIM AI Bash'")
        print(result1)

        print("\n--- Test 2: Restart and another command ---")
        result2 = await bash_tool.execute(command="ls -l", restart_session=True) 
        print(result2)

        print("\n--- Test 3: Command with stderr ---")
        result3 = await bash_tool.execute(command="nosuchcommand123")
        print(result3)
        
    finally:
        await bash_tool.cleanup()

if __name__ == "__main__": 
    asyncio.run(_main_test())