from abc import ABC, abstractmethod
from typing import Dict, Optional, Protocol, Any # [Source: 316]

from app.config import SandboxSettings, config as app_main_config # [Source: 316]
from app.sandbox.core.sandbox import DockerSandbox # [Source: 316]
from app.logger import logger

# Protocol for sandbox file operations, as defined in the PDF [Source: 316]
class SandboxFileOperations(Protocol): # [Source: 316]
    """Protocol for DRIM AI sandbox file operations."""
    async def copy_from(self, container_path: str, local_path: str) -> None: # [Source: 316]
        """Copies file from container to local."""
        ...
    async def copy_to(self, local_path: str, container_path: str) -> None: # [Source: 316]
        """Copies file from local to container."""
        ...
    async def read_file(self, path: str) -> str: # [Source: 317]
        """Reads file content from container."""
        ... # [Source: 318]
    async def write_file(self, path: str, content: str) -> None: # [Source: 318]
        """Writes content to file in container."""
        ... # [Source: 320]

class BaseSandboxClient(ABC): # [Source: 320]
    """Base DRIM AI sandbox client interface."""
    @abstractmethod
    async def create( # [Source: 320]
        self,
        config_override: Optional[SandboxSettings] = None, # Renamed from 'config'
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """Creates or ensures the sandbox is created."""
        pass
    @abstractmethod
    async def run_command(self, command: str, timeout: Optional[int] = None) -> str: # [Source: 320]
        """Executes command in the sandbox."""
        pass
    @abstractmethod
    async def copy_from(self, container_path: str, local_path: str) -> None: # [Source: 320]
        """Copies file from the sandbox container."""
        pass
    @abstractmethod
    async def copy_to(self, local_path: str, container_path: str) -> None: # [Source: 320]
        """Copies file to the sandbox container."""
        pass
    @abstractmethod
    async def read_file(self, path: str) -> str: # [Source: 320]
        """Reads file from the sandbox."""
        pass
    @abstractmethod
    async def write_file(self, path: str, content: str) -> None: # [Source: 321]
        """Writes file to the sandbox."""
        pass
    @abstractmethod
    async def cleanup(self) -> None: # [Source: 321]
        """Cleans up sandbox resources associated with this client."""
        pass

    @property
    @abstractmethod
    def is_active(self) -> bool:
        """Returns True if the sandbox is currently created and active, False otherwise."""
        pass


class LocalSandboxClient(BaseSandboxClient): # [Source: 321]
    """
    Local DRIM AI sandbox client implementation.
    Manages a single DockerSandbox instance.
    """
    def __init__(self): # [Source: 321]
        self._sandbox: Optional[DockerSandbox] = None # Renamed from self.sandbox for clarity [Source: 321]
        self._is_active: bool = False

    @property
    def is_active(self) -> bool:
        return self._is_active and self._sandbox is not None

    async def create( # [Source: 321]
        self,
        config_override: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Creates a sandbox instance if one is not already active.
        If called again on an active client, it will ensure the existing sandbox is active,
        but it will not recreate it unless previously cleaned up.
        To use new settings, cleanup() must be called first.
        """
        if self._is_active and self._sandbox:
            logger.info("DRIM AI LocalSandboxClient: Sandbox already active. Skipping creation.")
            return

        # Clean up any previous remnants if it was not properly cleaned.
        if self._sandbox:
            await self.cleanup()

        current_sandbox_settings = config_override or app_main_config.sandbox
        logger.info(f"DRIM AI LocalSandboxClient: Creating new DockerSandbox with image '{current_sandbox_settings.image}'.")
        try:
            self._sandbox = DockerSandbox(config_override=current_sandbox_settings, volume_bindings=volume_bindings) # [Source: 321]
            await self._sandbox.create() # [Source: 321]
            self._is_active = True
            logger.info("DRIM AI LocalSandboxClient: DockerSandbox created successfully.")
        except Exception as e:
            logger.error(f"DRIM AI LocalSandboxClient: Failed to create DockerSandbox: {e}")
            self._sandbox = None # Ensure sandbox is None on failure
            self._is_active = False
            raise # Re-raise the exception

    async def _ensure_sandbox_active(self):
        """Internal helper to ensure the sandbox is created and active before operations."""
        if not self._is_active or not self._sandbox:
            logger.warning("DRIM AI LocalSandboxClient: Sandbox not active. Attempting to create with default settings.")
            # This implicit creation might hide issues if create() was expected to be called explicitly.
            # However, some tools might call operations directly assuming SANDBOX_CLIENT is ready.
            await self.create() # Create with default global config
            if not self._is_active or not self._sandbox: # Check again after create attempt
                 raise RuntimeError("DRIM AI LocalSandboxClient: Sandbox is not initialized or creation failed.")


    async def run_command(self, command: str, timeout: Optional[int] = None) -> str: # [Source: 321]
        await self._ensure_sandbox_active()
        if not self._sandbox: # Should be caught by _ensure_sandbox_active, but as a safeguard
             raise RuntimeError("DRIM AI LocalSandboxClient: Sandbox unavailable for run_command.")
        logger.debug(f"DRIM AI LocalSandboxClient: Running command: '{command[:50]}...'")
        return await self._sandbox.run_command(command, timeout) # [Source: 322]

    async def copy_from(self, container_path: str, local_path: str) -> None: # [Source: 322]
        await self._ensure_sandbox_active()
        if not self._sandbox: raise RuntimeError("DRIM AI LocalSandboxClient: Sandbox unavailable for copy_from.")
        logger.debug(f"DRIM AI LocalSandboxClient: Copying from container '{container_path}' to local '{local_path}'.")
        await self._sandbox.copy_from(container_path, local_path) # [Source: 323]

    async def copy_to(self, local_path: str, container_path: str) -> None: # [Source: 323]
        await self._ensure_sandbox_active()
        if not self._sandbox: raise RuntimeError("DRIM AI LocalSandboxClient: Sandbox unavailable for copy_to.")
        logger.debug(f"DRIM AI LocalSandboxClient: Copying from local '{local_path}' to container '{container_path}'.")
        await self._sandbox.copy_to(local_path, container_path) # [Source: 323]

    async def read_file(self, path: str) -> str: # [Source: 323]
        await self._ensure_sandbox_active()
        if not self._sandbox: raise RuntimeError("DRIM AI LocalSandboxClient: Sandbox unavailable for read_file.") # [Source: 324]
        logger.debug(f"DRIM AI LocalSandboxClient: Reading file from container: '{path}'.")
        return await self._sandbox.read_file(path) # [Source: 324]

    async def write_file(self, path: str, content: str) -> None: # [Source: 324]
        await self._ensure_sandbox_active()
        if not self._sandbox: raise RuntimeError("DRIM AI LocalSandboxClient: Sandbox unavailable for write_file.") # [Source: 326]
        logger.debug(f"DRIM AI LocalSandboxClient: Writing file to container: '{path}'.")
        await self._sandbox.write_file(path, content) # [Source: 326]

    async def cleanup(self) -> None: # [Source: 326]
        """Cleans up the sandbox resources managed by this client instance."""
        logger.info("DRIM AI LocalSandboxClient: Initiating cleanup.")
        if self._sandbox:
            try:
                await self._sandbox.cleanup()
                logger.info("DRIM AI LocalSandboxClient: DockerSandbox cleanup successful.")
            except Exception as e:
                logger.error(f"DRIM AI LocalSandboxClient: Error during DockerSandbox cleanup: {e}")
            finally:
                self._sandbox = None
        self._is_active = False
        logger.info("DRIM AI LocalSandboxClient: Cleanup complete, client is now inactive.")

def create_sandbox_client() -> LocalSandboxClient: # [Source: 327]
    """Creates a DRIM AI sandbox client instance."""
    logger.info("DRIM AI: Creating a new LocalSandboxClient instance.")
    return LocalSandboxClient() # [Source: 327]

# Global sandbox client instance for ease of use by agents/tools
# This implies a shared sandbox instance if not managed carefully by calling code.
# Tools or agents should call SANDBOX_CLIENT.create() explicitly if they need to ensure
# it's set up with specific configurations or to re-initialize it.
SANDBOX_CLIENT: BaseSandboxClient = create_sandbox_client() # [Source: 327]

# Role in the System (Updated for DRIM AI)
# As part of the DRIM AI sandbox subsystem, this script provides a client interface
# for interacting with the sandboxed execution environment. [Source: 314] It allows DRIM AI
# components to create, manage, and utilize sandboxes for safe operation and
# isolation of potentially risky operations like code execution. [Source: 315]