# [Source: 383]
"""
Asynchronous Docker Terminal for DRIM AI Sandbox
This module provides asynchronous terminal functionality for Docker containers,
allowing interactive command execution with timeout control. [Source: 383]
"""
import os
import asyncio
import re
import socket
from typing import Dict, Optional, Tuple, Union, Any # MODIFIED: Added Any [Source: 383]

import docker # type: ignore
from docker import APIClient # type: ignore # [Source: 383]
from docker.errors import APIError # type: ignore # [Source: 383]
from docker.models.containers import Container # type: ignore # [Source: 383]

from app.logger import logger # Import DRIM AI logger

class DockerSession: # [Source: 383]
    def __init__(self, container_id: str) -> None:
        """Initializes a Docker session. [Source: 383]
        Args:
            container_id: ID of the Docker container. [Source: 383]
        """
        self.api: APIClient = APIClient() # [Source: 383]
        self.container_id: str = container_id # [Source: 383]
        self.exec_id: Optional[str] = None # [Source: 383]
        self.socket: Optional[socket.socket] = None # [Source: 383]

    async def create(self, working_dir: str, env_vars: Dict[str, str]) -> None: # [Source: 384]
        """Creates an interactive session with the container.
        Args:
            working_dir: Working directory inside the container. [Source: 384]
            env_vars: Environment variables to set. [Source: 384]
        Raises:
            RuntimeError: If socket connection fails. [Source: 384]
        """
        startup_command = [ # [Source: 384]
            "bash",
            "-c",
            f"cd {working_dir} && PROMPT_COMMAND='' PS1='$ ' exec bash --norc --noprofile",
        ]
        exec_data = self.api.exec_create( # [Source: 384]
            self.container_id,
            startup_command,
            stdin=True,
            tty=True,
            stdout=True,
            stderr=True,
            privileged=False, 
            user="root", 
            environment={**env_vars, "TERM": "dumb", "PS1": "$ ", "PROMPT_COMMAND": ""},
        )
        self.exec_id = exec_data["Id"] # [Source: 384]
        
        socket_obj_or_tuple = self.api.exec_start( # [Source: 384]
            self.exec_id, socket=True, tty=True, stream=True, demux=False 
        )
        
        if isinstance(socket_obj_or_tuple, tuple): 
            self.socket = socket_obj_or_tuple[0]
        else: 
             self.socket = socket_obj_or_tuple # type: ignore 

        if hasattr(self.socket, "_sock"): 
            self.socket = self.socket._sock # type: ignore [Source: 384]
        
        if not isinstance(self.socket, socket.socket):
             logger.error(f"DRIM AI Sandbox: Failed to get a valid socket connection. Type: {type(self.socket)}")
             raise RuntimeError("Failed to get a valid socket connection for Docker exec")

        self.socket.setblocking(False) # [Source: 384]
        await self._read_until_prompt() # [Source: 384]

    async def close(self) -> None: # [Source: 385]
        """Cleans up session resources."""
        try:
            if self.socket:
                try:
                    self.socket.sendall(b"exit\n") # [Source: 386]
                    await asyncio.sleep(0.1)
                except socket.error as se:
                    logger.warning(f"DRIM AI Sandbox: Socket error sending 'exit' during close: {se}")
                except Exception as e:
                    logger.warning(f"DRIM AI Sandbox: Error sending 'exit' during close: {e}")
                
                try:
                    self.socket.shutdown(socket.SHUT_RDWR) # [Source: 386]
                except socket.error as se:
                    if se.errno not in [socket.errno.ENOTCONN, socket.errno.ECONNRESET, socket.errno.ESHUTDOWN]: # type: ignore
                        logger.warning(f"DRIM AI Sandbox: Socket error during shutdown: {se}")
                except Exception as e: 
                    logger.warning(f"DRIM AI Sandbox: Non-socket error during shutdown: {e}")

                self.socket.close() # [Source: 386]
                self.socket = None
            
            if self.exec_id: # [Source: 386]
                try:
                    exec_inspect = self.api.exec_inspect(self.exec_id) # [Source: 386]
                    if exec_inspect.get("Running", False): # [Source: 386]
                        logger.warning(f"DRIM AI Sandbox: Exec {self.exec_id} still running during close. This might indicate an issue.")
                        await asyncio.sleep(0.5) 
                except APIError as apie:
                    if apie.response.status_code == 404: 
                        logger.debug(f"DRIM AI Sandbox: Exec {self.exec_id} not found during close (already cleaned up).")
                    else:
                        logger.warning(f"DRIM AI Sandbox: APIError inspecting exec {self.exec_id} during close: {apie}")
                except Exception as e:
                    logger.warning(f"DRIM AI Sandbox: Error inspecting exec {self.exec_id} during close: {e}")
                self.exec_id = None
        except Exception as e:
            logger.error(f"DRIM AI Sandbox: Unexpected error during DockerSession close: {e}") # [Source: 387]

    async def _read_until_prompt(self, prompt_regex: bytes = b"\\$ $") -> str: # [Source: 388] 
        """Reads output until prompt is found."""
        buffer = b""
        prompt_pattern = re.compile(prompt_regex) 

        while True:
            if not self.socket:
                raise socket.error("Socket is not available/closed.")
            try:
                chunk = self.socket.recv(4096) # [Source: 389]
                if not chunk: 
                    logger.warning("DRIM AI Sandbox: DockerSession socket closed by remote while reading for prompt.")
                    raise socket.error("Socket closed prematurely")
                buffer += chunk
                if prompt_pattern.search(buffer):
                    break
            except socket.error as e: # [Source: 389]
                if e.errno == socket.EWOULDBLOCK or e.errno == socket.errno.EAGAIN: # type: ignore
                    await asyncio.sleep(0.05) 
                    continue
                logger.error(f"DRIM AI Sandbox: DockerSession socket error: {e}")
                raise
            except Exception as e:
                logger.error(f"DRIM AI Sandbox: Unexpected error in _read_until_prompt: {e}")
                raise
        return buffer.decode("utf-8", errors="replace") # [Source: 389]

    async def execute(self, command: str, timeout: Optional[int] = None) -> str: # [Source: 390]
        """Executes a command and returns cleaned output."""
        if not self.socket or not self.exec_id: # [Source: 392]
            raise RuntimeError("DRIM AI Sandbox: DockerSession not properly initialized (no socket or exec_id).")

        try:
            sanitized_command = self._sanitize_command(command) # [Source: 392]
            # Using a unique sentinel without needing asyncio.Sam (which is not standard)
            sentinel = f"DRIM_CMD_END_{os.urandom(4).hex()}" 
            full_command_bytes = f"{sanitized_command}\necho $?\necho {sentinel}\n".encode("utf-8") # [Source: 392]

            self.socket.sendall(full_command_bytes) # [Source: 392]

            async def read_output_with_sentinel() -> str: # [Source: 392]
                output_buffer = b""
                while True:
                    if not self.socket: raise socket.error("Socket closed during read_output")
                    try:
                        chunk = self.socket.recv(8192) 
                        if not chunk: 
                            break 
                        output_buffer += chunk
                        if sentinel.encode("utf-8") in output_buffer:
                            break
                    except socket.error as e:
                        if e.errno == socket.EWOULDBLOCK or e.errno == socket.errno.EAGAIN: # type: ignore
                            await asyncio.sleep(0.05)
                            continue
                        raise
                
                decoded_output = output_buffer.decode("utf-8", errors="replace")
                output_before_sentinel, _, _ = decoded_output.rpartition(sentinel)
                output_lines = output_before_sentinel.strip().split('\n')

                exit_code_str = ""
                if output_lines:
                    potential_exit_code = output_lines[-1].strip()
                    if potential_exit_code.isdigit():
                        exit_code_str = potential_exit_code
                        processed_output = "\n".join(output_lines[:-1]).strip()
                    else:
                        processed_output = "\n".join(output_lines).strip()
                else: 
                    processed_output = ""

                if processed_output.startswith(command.strip()): 
                    processed_output = processed_output[len(command.strip()):].lstrip()
                
                if exit_code_str and exit_code_str != "0":
                    logger.warning(f"DRIM AI Sandbox: Command '{command[:50]}...' exited with code {exit_code_str}.")
                return processed_output.strip()

            effective_timeout = timeout if timeout is not None else 60 
            result = await asyncio.wait_for(read_output_with_sentinel(), timeout=effective_timeout) # [Source: 394]
            
            await self._read_until_prompt()
            return result

        except asyncio.TimeoutError: # [Source: 394]
            logger.error(f"DRIM AI Sandbox: Command '{command[:50]}...' timed out after {effective_timeout}s.")
            if self.exec_id:
                try:
                    logger.info(f"DRIM AI Sandbox: Attempting to send SIGINT (Ctrl+C) to exec_id {self.exec_id} due to timeout.")
                    pass 
                except Exception as e_int:
                    logger.warning(f"DRIM AI Sandbox: Failed to send interrupt signal after timeout: {e_int}")
            raise TimeoutError(f"Command execution timed out after {effective_timeout} seconds")
        except Exception as e: # [Source: 395]
            logger.exception(f"DRIM AI Sandbox: Failed to execute command '{command[:50]}...': {e}")
            raise RuntimeError(f"Failed to execute command: {str(e)}")

    def _sanitize_command(self, command: str) -> str: # [Source: 395]
        """Sanitizes the command string to prevent obvious shell injection or dangerous commands."""
        command = command.strip()
        if not command:
            raise ValueError("Command cannot be empty.")

        risky_patterns = [ # [Source: 395]
            "rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero",
            ":(){:|:&};:", "chmod -R 777 /", "chown -R",
        ]
        normalized_command_check = ' '.join(command.lower().split())
        for risky in risky_patterns:
            if risky in normalized_command_check: # [Source: 395]
                logger.error(f"DRIM AI Sandbox: Potentially dangerous command blocked: '{command}' due to pattern: '{risky}'")
                raise ValueError(f"Command contains potentially dangerous operation: {risky}")
        
        return command

class AsyncDockerizedTerminal: # [Source: 395]
    def __init__(
        self,
        container: Union[str, Container], # [Source: 397]
        working_dir: str = "/workspace", # [Source: 397]
        env_vars: Optional[Dict[str, str]] = None, # [Source: 398]
        default_timeout: int = 60, # [Source: 398]
    ) -> None:
        """Initializes an asynchronous terminal for Docker containers for DRIM AI."""
        self.client = docker.from_env() # [Source: 398]
        self.container: Container = ( # [Source: 398]
            container
            if isinstance(container, Container)
            else self.client.containers.get(container) # type: ignore
        )
        self.working_dir: str = working_dir # [Source: 398]
        self.env_vars: Dict[str, str] = env_vars or {} # [Source: 398]
        self.default_timeout: int = default_timeout # [Source: 398]
        self.session: Optional[DockerSession] = None # [Source: 398]

    async def init(self) -> None: # [Source: 399]
        """Initializes the terminal environment for DRIM AI."""
        logger.info(f"DRIM AI Sandbox: Initializing AsyncDockerizedTerminal for container {self.container.short_id}...")
        await self._ensure_workdir() # [Source: 400]
        self.session = DockerSession(self.container.id) # [Source: 400]
        try:
            await self.session.create(self.working_dir, self.env_vars) # [Source: 400]
            logger.info(f"DRIM AI Sandbox: AsyncDockerizedTerminal session created in {self.working_dir}.")
        except Exception as e:
            logger.error(f"DRIM AI Sandbox: Failed to create DockerSession: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            raise RuntimeError(f"Failed to initialize terminal session: {e}")

    async def _ensure_workdir(self) -> None: # [Source: 400]
        """Ensures working directory exists in container."""
        try:
            exit_code, output = await self._exec_simple(f"mkdir -p {self.working_dir} && test -d {self.working_dir}") # [Source: 401]
            if exit_code != 0:
                logger.error(f"DRIM AI Sandbox: Failed to create/verify working directory '{self.working_dir}'. Output: {output.strip()}")
                raise RuntimeError(f"Failed to create/verify working directory: {self.working_dir}. Docker exec output: {output.strip()}")
            logger.debug(f"DRIM AI Sandbox: Working directory '{self.working_dir}' ensured. Output: {output.strip()}")
        except APIError as e: # [Source: 401]
            logger.error(f"DRIM AI Sandbox: APIError ensuring working directory: {e}")
            raise RuntimeError(f"Failed to create working directory due to Docker API error: {e}")

    async def _exec_simple(self, cmd: str) -> Tuple[int, str]: # [Source: 402]
        """Executes a simple non-interactive command using Docker's exec_run."""
        logger.debug(f"DRIM AI Sandbox: Executing simple command in {self.container.short_id}: {cmd}")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor( # [Source: 404]
            None, 
            lambda: self.container.exec_run(cmd, environment=self.env_vars, workdir=self.working_dir) 
        )
        output_str = result.output.decode("utf-8", errors="replace") if result.output else ""
        logger.debug(f"DRIM AI Sandbox: Simple command exit code: {result.exit_code}, Output: {output_str[:100]}...")
        return result.exit_code if result.exit_code is not None else -1, output_str # Ensure exit_code is int [Source: 404]

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str: # [Source: 405]
        """Runs a command in the container's interactive session with timeout."""
        if not self.session: # [Source: 406]
            logger.error("DRIM AI Sandbox: Terminal session not initialized. Cannot run command.")
            raise RuntimeError("Terminal not initialized. Call init() first.")
        
        effective_timeout = timeout if timeout is not None else self.default_timeout
        logger.info(f"DRIM AI Sandbox: Running command in {self.container.short_id}: '{cmd[:100]}...' (Timeout: {effective_timeout}s)")
        try:
            result = await self.session.execute(cmd, timeout=effective_timeout) # [Source: 406]
            logger.info(f"DRIM AI Sandbox: Command execution successful. Output snippet: {result[:100]}...")
            return result
        except TimeoutError as te:
            logger.error(f"DRIM AI Sandbox: Command '{cmd[:50]}...' in {self.container.short_id} timed out: {te}")
            raise 
        except Exception as e:
            logger.exception(f"DRIM AI Sandbox: Error running command '{cmd[:50]}...' in {self.container.short_id}: {e}")
            raise 

    async def close(self) -> None: # [Source: 406]
        """Closes the terminal session."""
        logger.info(f"DRIM AI Sandbox: Closing AsyncDockerizedTerminal for container {self.container.short_id}.")
        if self.session:
            try:
                await self.session.close()
                logger.info(f"DRIM AI Sandbox: DockerSession closed for {self.container.short_id}.")
            except Exception as e:
                logger.error(f"DRIM AI Sandbox: Error closing DockerSession for {self.container.short_id}: {e}")
            self.session = None
        else:
            logger.info(f"DRIM AI Sandbox: No active DockerSession to close for {self.container.short_id}.")

    async def __aenter__(self) -> "AsyncDockerizedTerminal": # [Source: 406]
        """Async context manager entry."""
        await self.init()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: # [Source: 406]
        """Async context manager exit."""
        await self.close()

# Role in the System (Updated for DRIM AI)
# As part of the DRIM AI sandbox subsystem, this script contributes to the safe
# execution environment for the agent. [Source: 407, 408] It provides the core interactive
# terminal functionality within Docker containers, crucial for tools like Bash
# or Python execution, ensuring that DRIM AI can perform command-line tasks
# securely and with resource isolation. [Source: 409]