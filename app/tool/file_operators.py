# [Source: 602]
"""
DRIM AI File operation interfaces and implementations for local and sandbox environments.
"""
import asyncio
from pathlib import Path
from typing import Optional, Protocol, Tuple, Union, runtime_checkable, Any # [Source: 602]

from app.config import SandboxSettings, config as app_main_config # [Source: 602]
from app.exceptions import ToolError # [Source: 602]
from app.sandbox.client import SANDBOX_CLIENT, BaseSandboxClient # [Source: 602] (Import BaseSandboxClient for type hinting)
from app.logger import logger

PathLike = Union[str, Path] # [Source: 602]

@runtime_checkable
class FileOperator(Protocol): # [Source: 602]
    """Interface for DRIM AI file operations in different environments."""
    async def read_file(self, path: PathLike) -> str: # [Source: 602]
        """Read content from a file."""
        ...
    async def write_file(self, path: PathLike, content: str) -> None: # [Source: 602]
        """Write content to a file."""
        ...
    async def is_directory(self, path: PathLike) -> bool: # [Source: 603]
        """Check if path points to a directory."""
        ...
    async def exists(self, path: PathLike) -> bool: # [Source: 603]
        """Check if path exists."""
        ...
    async def run_command( # [Source: 603]
        self, cmd: str, timeout: Optional[float] = 120.0 # Changed from int to float for more flexibility
    ) -> Tuple[int, str, str]: # return_code, stdout, stderr
        """Run a shell command and return (return_code, stdout, stderr)."""
        ...
    async def ensure_initialized(self) -> None:
        """Ensure any underlying resources (like a sandbox) are initialized."""
        ...


class LocalFileOperator(FileOperator): # [Source: 603]
    """DRIM AI File operations implementation for the local filesystem."""
    encoding: str = "utf-8" # [Source: 603]

    async def ensure_initialized(self) -> None:
        # Local operations don't need special initialization beyond OS being up.
        logger.debug("DRIM AI LocalFileOperator: Initialized (no specific setup needed).")
        pass

    async def read_file(self, path: PathLike) -> str: # [Source: 603]
        """Read content from a local file."""
        abs_path = Path(path).resolve()
        logger.debug(f"DRIM AI LocalFileOperator: Reading local file: {abs_path}")
        try:
            with open(abs_path, "r", encoding=self.encoding) as f:
                return await asyncio.to_thread(f.read) # Make it async friendly
        except FileNotFoundError:
            logger.warning(f"DRIM AI LocalFileOperator: File not found: {abs_path}")
            raise ToolError(f"File not found: {path}") from None
        except Exception as e: # [Source: 603]
            logger.error(f"DRIM AI LocalFileOperator: Failed to read local file {abs_path}: {e}")
            raise ToolError(f"Failed to read {path}: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None: # [Source: 603]
        """Write content to a local file."""
        abs_path = Path(path).resolve()
        logger.debug(f"DRIM AI LocalFileOperator: Writing to local file: {abs_path}")
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True) # Ensure parent directory exists
            with open(abs_path, "w", encoding=self.encoding) as f:
                await asyncio.to_thread(f.write, content) # Make it async friendly # [Source: 604]
        except Exception as e: # [Source: 604]
            logger.error(f"DRIM AI LocalFileOperator: Failed to write to local file {abs_path}: {e}")
            raise ToolError(f"Failed to write to {path}: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool: # [Source: 604]
        """Check if local path points to a directory."""
        return await asyncio.to_thread(Path(path).resolve().is_dir)

    async def exists(self, path: PathLike) -> bool: # [Source: 604]
        """Check if local path exists."""
        return await asyncio.to_thread(Path(path).resolve().exists)

    async def run_command( # [Source: 604]
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """Run a shell command locally for DRIM AI."""
        logger.info(f"DRIM AI LocalFileOperator: Running local command: '{cmd[:100]}...' (Timeout: {timeout}s)")
        try:
            process = await asyncio.create_subprocess_shell( # [Source: 605]
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout) # [Source: 605]
            
            return_code = process.returncode if process.returncode is not None else -1 # Default to -1 if None
            stdout_str = stdout_bytes.decode(self.encoding, errors="replace") # [Source: 605]
            stderr_str = stderr_bytes.decode(self.encoding, errors="replace") # [Source: 605]
            
            logger.debug(f"DRIM AI LocalFileOperator: Command '{cmd[:50]}' exited with {return_code}. Stdout: {stdout_str[:100]}... Stderr: {stderr_str[:100]}...")
            return return_code, stdout_str, stderr_str

        except asyncio.TimeoutError as exc: # [Source: 605]
            logger.warning(f"DRIM AI LocalFileOperator: Command '{cmd[:50]}' timed out after {timeout} seconds.")
            if process and process.returncode is None: # Check if process is defined and running
                try:
                    process.kill() # [Source: 605]
                    await process.wait() # Ensure process is reaped
                except ProcessLookupError:
                    pass # Process already exited
                except Exception as kill_exc:
                    logger.error(f"DRIM AI LocalFileOperator: Error killing timed-out process: {kill_exc}")
            raise ToolError(f"Command '{cmd}' timed out after {timeout} seconds") from exc
        except Exception as e:
            logger.error(f"DRIM AI LocalFileOperator: Error running local command '{cmd[:50]}...': {e}")
            raise ToolError(f"Error executing local command '{cmd}': {str(e)}")


class SandboxFileOperator(FileOperator): # [Source: 605]
    """DRIM AI File operations implementation for the sandbox environment."""
    def __init__(self, sandbox_client: Optional[BaseSandboxClient] = None): # [Source: 605]
        self.sandbox_client: BaseSandboxClient = sandbox_client or SANDBOX_CLIENT # Use provided or global
        self._initialized = False

    async def ensure_initialized(self) -> None:
        """Ensure sandbox is initialized via the client."""
        if not self._initialized or not self.sandbox_client.is_active:
            logger.info("DRIM AI SandboxFileOperator: Sandbox not initialized or inactive. Initializing...")
            # Use the global config for sandbox settings if not overridden by a specific client instance
            # This assumes SANDBOX_CLIENT.create() uses app_main_config.sandbox by default
            await self.sandbox_client.create(config_override=app_main_config.sandbox) # [Source: 605]
            self._initialized = True
            logger.info("DRIM AI SandboxFileOperator: Sandbox initialized/ensured active.")


    async def read_file(self, path: PathLike) -> str: # [Source: 605]
        """Read content from a file in DRIM AI sandbox."""
        await self.ensure_initialized() # [Source: 605]
        logger.debug(f"DRIM AI SandboxFileOperator: Reading sandbox file: {path}")
        try:
            return await self.sandbox_client.read_file(str(path)) # [Source: 606]
        except Exception as e: # [Source: 606]
            logger.error(f"DRIM AI SandboxFileOperator: Failed to read sandbox file {path}: {e}")
            raise ToolError(f"Failed to read {path} in sandbox: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None: # [Source: 607]
        """Write content to a file in DRIM AI sandbox."""
        await self.ensure_initialized() # [Source: 607]
        logger.debug(f"DRIM AI SandboxFileOperator: Writing to sandbox file: {path}")
        try:
            await self.sandbox_client.write_file(str(path), content) # [Source: 607]
        except Exception as e: # [Source: 607]
            logger.error(f"DRIM AI SandboxFileOperator: Failed to write to sandbox file {path}: {e}")
            raise ToolError(f"Failed to write to {path} in sandbox: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool: # [Source: 607]
        """Check if path points to a directory in DRIM AI sandbox."""
        await self.ensure_initialized() # [Source: 607]
        # This relies on run_command returning simple 'true' or 'false' string.
        # Ensure the sandbox's run_command handles simple echo like this correctly.
        # The DockerSandbox.run_command returns the stdout.
        try:
            result = await self.sandbox_client.run_command(
                f"test -d \"{str(path)}\" && echo true || echo false" # Added quotes for paths with spaces
            ) # [Source: 607]
            return result.strip().lower() == "true"
        except Exception as e:
            logger.error(f"DRIM AI SandboxFileOperator: Error checking if '{path}' is directory: {e}")
            return False # Default to false on error

    async def exists(self, path: PathLike) -> bool: # [Source: 607]
        """Check if path exists in DRIM AI sandbox."""
        await self.ensure_initialized() # [Source: 607]
        try:
            result = await self.sandbox_client.run_command(
                f"test -e \"{str(path)}\" && echo true || echo false" # Added quotes
            ) # [Source: 607]
            return result.strip().lower() == "true"
        except Exception as e:
            logger.error(f"DRIM AI SandboxFileOperator: Error checking if '{path}' exists: {e}")
            return False # Default to false on error


    async def run_command( # [Source: 608]
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """Run a command in DRIM AI sandbox environment."""
        await self.ensure_initialized() # [Source: 608]
        logger.info(f"DRIM AI SandboxFileOperator: Running sandbox command: '{cmd[:100]}...' (Timeout: {timeout}s)")
        try:
            # The SANDBOX_CLIENT.run_command only returns stdout string.
            # It does not provide exit code or stderr directly from its current signature.
            # This is a limitation of the original BaseSandboxClient interface.
            # For a more complete run_command, SANDBOX_CLIENT.run_command would need to be enhanced
            # or DockerSandbox.terminal.run_command used more directly (which is not ideal here).
            
            # Assuming timeout is an int for SANDBOX_CLIENT as per original PDF for client.run_command
            effective_timeout_int = int(timeout) if timeout is not None else None
            
            # We need a way to get exit code and stderr.
            # A common pattern for sandbox is to wrap the command to capture these.
            # E.g., `( (your_command_here) && echo "DRIM_EXIT_CODE:$?" ) || echo "DRIM_EXIT_CODE:$?"`
            # This is complex to parse robustly.
            # For now, we'll work with the existing SANDBOX_CLIENT.run_command signature.
            # This means exit code will be assumed 0 on success (no exception), 1 on error, and stderr won't be captured.
            
            stdout_str = await self.sandbox_client.run_command(cmd, timeout=effective_timeout_int) # [Source: 608]
            logger.debug(f"DRIM AI SandboxFileOperator: Command '{cmd[:50]}' sandbox stdout: {stdout_str[:100]}...")
            return 0, stdout_str, "" # Assume 0 exit code, no stderr captured by current client [Source: 608]
        except ToolError as te: # If sandbox_client.run_command raises ToolError (e.g. timeout from sandbox)
            logger.error(f"DRIM AI SandboxFileOperator: ToolError running sandbox command '{cmd[:50]}...': {te.message}")
            return 1, "", te.message # Use ToolError message as stderr
        except Exception as exc: # [Source: 608]
            logger.error(f"DRIM AI SandboxFileOperator: Error running sandbox command '{cmd[:50]}...': {exc}")
            return 1, "", f"Error executing command in sandbox: {str(exc)}" # [Source: 608]

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem for DRIM AI, this script defines the FileOperator
# interface and its concrete implementations for local and sandboxed environments. [Source: 600, 609]
# This abstraction allows DRIM AI tools that perform file operations (like StrReplaceEditor)
# to function seamlessly whether operating on the local filesystem or within a
# secure sandbox, based on DRIM AI's configuration. [Source: 601, 610, 611]