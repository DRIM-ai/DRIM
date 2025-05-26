import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set, AsyncGenerator, Any # [Source: 335]

import docker # type: ignore
from docker.errors import APIError, ImageNotFound # type: ignore # [Source: 335]

from app.config import SandboxSettings, config as app_main_config # [Source: 335]
from app.logger import logger # [Source: 335]
from app.sandbox.core.sandbox import DockerSandbox # [Source: 335]

class SandboxManager: # [Source: 335]
    """
    DRIM AI Docker sandbox manager.
    Manages multiple DockerSandbox instances' lifecycle including creation,
    monitoring, and cleanup. Provides concurrent access control and automatic
    cleanup mechanisms for sandbox resources for DRIM AI. [Source: 335]
    """
    def __init__( # [Source: 336]
        self,
        max_sandboxes: int = 10, # Reduced default from 100 for typical local use
        idle_timeout: int = 3600, # seconds (1 hour) [Source: 336]
        cleanup_interval: int = 300, # seconds (5 minutes) [Source: 336]
    ):
        self.max_sandboxes: int = max_sandboxes # [Source: 336]
        self.idle_timeout: int = idle_timeout # [Source: 336]
        self.cleanup_interval: int = cleanup_interval # [Source: 336]
        
        try:
            self._client = docker.from_env() # [Source: 336]
        except docker.errors.DockerException as e:
            logger.error(f"DRIM AI SandboxManager: Could not connect to Docker daemon: {e}. Sandbox functionality will be unavailable.")
            self._client = None # Indicate Docker is not available

        self._sandboxes: Dict[str, DockerSandbox] = {} # [Source: 336]
        self._last_used: Dict[str, float] = {} # [Source: 336]
        self._locks: Dict[str, asyncio.Lock] = {} # [Source: 336]
        self._global_lock = asyncio.Lock() # [Source: 336]
        self._active_operations: Set[str] = set() # [Source: 336]
        
        self._cleanup_task: Optional[asyncio.Task] = None # [Source: 336]
        self._is_shutting_down = False # [Source: 336]
        
        if self._client: # Only start cleanup if Docker client is available
            self.start_cleanup_task() # [Source: 336]
        else:
            logger.warning("DRIM AI SandboxManager: Docker client not available. Automatic cleanup task not started.")

    async def ensure_image(self, image_name: str) -> bool: # [Source: 337] Renamed `image` to `image_name`
        """Ensures Docker image is available, pulling if necessary."""
        if not self._client:
            logger.error("DRIM AI SandboxManager: Cannot ensure image, Docker client not available.")
            return False
        try:
            await asyncio.to_thread(self._client.images.get, image_name) # [Source: 338]
            logger.info(f"DRIM AI SandboxManager: Image '{image_name}' found locally.")
            return True
        except ImageNotFound: # [Source: 338]
            logger.info(f"DRIM AI SandboxManager: Image '{image_name}' not found locally. Pulling...") # [Source: 338]
            try:
                await asyncio.to_thread(self._client.images.pull, image_name) # [Source: 339]
                logger.info(f"DRIM AI SandboxManager: Successfully pulled image '{image_name}'.")
                return True
            except APIError as e: # [Source: 339]
                logger.error(f"DRIM AI SandboxManager: Failed to pull image '{image_name}' due to APIError: {e}")
                return False
            except Exception as e: # Catch other potential errors during pull (e.g., network)
                logger.error(f"DRIM AI SandboxManager: Failed to pull image '{image_name}': {e}") # [Source: 339]
                return False
        except Exception as e:
            logger.error(f"DRIM AI SandboxManager: Error checking for image '{image_name}': {e}")
            return False

    @asynccontextmanager
    async def sandbox_operation(self, sandbox_id: str) -> AsyncGenerator[DockerSandbox, None]: # [Source: 339]
        """Context manager for safe sandbox operations with locking and usage tracking."""
        if not self._client:
            raise RuntimeError("DRIM AI SandboxManager: Docker client not available. Cannot perform sandbox operation.")

        # Ensure lock exists for the sandbox_id
        async with self._global_lock: # Protect access to self._locks dictionary
            if sandbox_id not in self._locks:
                # This case should ideally not be hit if sandbox_id comes from create_sandbox
                # or if get_sandbox is called only for existing sandboxes.
                # If it can be hit, means get_sandbox might be called for an ID not yet in _locks.
                logger.warning(f"DRIM AI SandboxManager: Lock for sandbox {sandbox_id} created on-demand in sandbox_operation.")
                self._locks[sandbox_id] = asyncio.Lock()
        
        op_lock = self._locks[sandbox_id] # Get the specific lock for this sandbox_id

        async with op_lock: # [Source: 339] Acquire the specific sandbox lock
            if sandbox_id not in self._sandboxes: # [Source: 339]
                # This check is crucial after acquiring the lock
                logger.error(f"DRIM AI SandboxManager: Sandbox {sandbox_id} not found during operation.")
                raise KeyError(f"DRIM AI SandboxManager: Sandbox {sandbox_id} not found")
            
            self._active_operations.add(sandbox_id) # [Source: 339]
            try:
                self._last_used[sandbox_id] = asyncio.get_event_loop().time() # [Source: 339]
                yield self._sandboxes[sandbox_id] # [Source: 339]
            finally:
                self._active_operations.remove(sandbox_id) # [Source: 339]


    async def create_sandbox( # [Source: 339]
        self,
        sandbox_config_override: Optional[SandboxSettings] = None, # Renamed from 'config'
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> str:
        """Creates a new DRIM AI sandbox instance."""
        if not self._client:
            logger.error("DRIM AI SandboxManager: Cannot create sandbox, Docker client not available.")
            raise RuntimeError("DRIM AI SandboxManager: Docker client not available.")

        async with self._global_lock: # [Source: 341] Protect access to _sandboxes count and dict
            if len(self._sandboxes) >= self.max_sandboxes: # [Source: 341]
                logger.error(f"DRIM AI SandboxManager: Max sandboxes ({self.max_sandboxes}) reached.")
                raise RuntimeError(f"Maximum number of sandboxes ({self.max_sandboxes}) reached")

            current_sandbox_settings = sandbox_config_override or app_main_config.sandbox # [Source: 341]
            
            if not await self.ensure_image(current_sandbox_settings.image): # [Source: 341]
                raise RuntimeError(f"Failed to ensure Docker image: {current_sandbox_settings.image}")

            sandbox_id = str(uuid.uuid4()) # [Source: 341]
            # Create lock before adding to _sandboxes to prevent race condition in sandbox_operation
            self._locks[sandbox_id] = asyncio.Lock()

            try:
                # Pass the specific settings for this sandbox instance
                sandbox = DockerSandbox(config_override=current_sandbox_settings, volume_bindings=volume_bindings) # [Source: 341]
                await sandbox.create() # This is an async method
                
                self._sandboxes[sandbox_id] = sandbox # [Source: 341]
                self._last_used[sandbox_id] = asyncio.get_event_loop().time() # [Source: 341]
                logger.info(f"DRIM AI SandboxManager: Created sandbox {sandbox_id} (Image: {current_sandbox_settings.image}).")
                return sandbox_id
            except Exception as e: # [Source: 341]
                logger.exception(f"DRIM AI SandboxManager: Failed to create sandbox instance {sandbox_id}.")
                # Cleanup partial resources if sandbox object was created but create() failed
                if sandbox_id in self._sandboxes: # Should not happen if create() failed before assignment
                    await self._safe_delete_sandbox_resources(sandbox_id, self._sandboxes.get(sandbox_id))
                    self._sandboxes.pop(sandbox_id, None)
                    self._last_used.pop(sandbox_id, None)
                self._locks.pop(sandbox_id, None) # Remove lock if creation failed
                raise RuntimeError(f"Failed to create sandbox: {e}") from e # [Source: 341]

    async def get_sandbox(self, sandbox_id: str) -> DockerSandbox: # [Source: 342]
        """Gets a DRIM AI sandbox instance using the sandbox_operation context manager for safety."""
        if not self._client:
            raise RuntimeError("DRIM AI SandboxManager: Docker client not available. Cannot get sandbox.")
        # The sandbox_operation context manager handles locking and existence checks.
        async with self.sandbox_operation(sandbox_id) as sandbox: # [Source: 343]
            return sandbox # [Source: 344]

    def start_cleanup_task(self) -> None: # [Source: 344]
        """Starts the automatic background task for cleaning up idle sandboxes."""
        if self._cleanup_task and not self._cleanup_task.done():
            logger.info("DRIM AI SandboxManager: Cleanup task already running.")
            return

        async def cleanup_loop(): # [Source: 344]
            logger.info("DRIM AI SandboxManager: Cleanup loop started.")
            while not self._is_shutting_down:
                try:
                    await asyncio.sleep(self.cleanup_interval) # [Source: 344] Wait first
                    if not self._is_shutting_down: # Check again after sleep
                        await self._cleanup_idle_sandboxes()
                except asyncio.CancelledError:
                    logger.info("DRIM AI SandboxManager: Cleanup loop cancelled.")
                    break
                except Exception as e: # [Source: 344]
                    logger.error(f"DRIM AI SandboxManager: Error in cleanup loop: {e}", exc_info=True)
            logger.info("DRIM AI SandboxManager: Cleanup loop stopped.")

        self._cleanup_task = asyncio.create_task(cleanup_loop()) # [Source: 344]

    async def _cleanup_idle_sandboxes(self) -> None: # [Source: 344]
        """Internal method to identify and clean up idle sandboxes."""
        if self._is_shutting_down: return

        current_time = asyncio.get_event_loop().time()
        # Iterate over a copy of keys for safe modification
        sandboxes_to_check = list(self._sandboxes.keys())
        
        logger.debug(f"DRIM AI SandboxManager: Running idle sandbox check. Current sandboxes: {len(sandboxes_to_check)}")

        for sandbox_id in sandboxes_to_check:
            async with self._global_lock: # Protect shared dictionaries briefly
                if sandbox_id not in self._sandboxes: # Already removed
                    continue
                is_active = sandbox_id in self._active_operations # [Source: 344]
                last_used_time = self._last_used.get(sandbox_id, 0)
            
            if not is_active and (current_time - last_used_time > self.idle_timeout): # [Source: 344]
                logger.info(f"DRIM AI SandboxManager: Sandbox {sandbox_id} is idle. Cleaning up...")
                try:
                    # Use _safe_delete_sandbox to handle actual deletion
                    await self._safe_delete_sandbox(sandbox_id) # This will also acquire global_lock internally
                except Exception as e: # [Source: 344]
                    logger.error(f"DRIM AI SandboxManager: Error cleaning up idle sandbox {sandbox_id}: {e}")
            else:
                logger.debug(f"DRIM AI SandboxManager: Sandbox {sandbox_id} is active or not past idle timeout.")


    async def _safe_delete_sandbox_resources(self, sandbox_id: str, sandbox_instance: Optional[DockerSandbox]) -> None:
        """Safely calls cleanup on a sandbox instance. Does not modify manager's dicts."""
        if sandbox_instance:
            try:
                await sandbox_instance.cleanup() # Call the DockerSandbox's cleanup
            except Exception as e:
                logger.error(f"DRIM AI SandboxManager: Error during resource cleanup of sandbox {sandbox_id} instance: {e}")

    async def _safe_delete_sandbox(self, sandbox_id: str) -> None: # [Source: 347] (Modified for clarity)
        """Safely deletes a single sandbox instance and its records from the manager."""
        if not self._client: return

        logger.debug(f"DRIM AI SandboxManager: Initiating safe delete for sandbox {sandbox_id}.")
        
        # Wait for active operations to complete on this specific sandbox
        if sandbox_id in self._active_operations: # [Source: 347]
            logger.warning(f"DRIM AI SandboxManager: Sandbox {sandbox_id} has active operations, waiting for completion before deletion...") # [Source: 347]
            for _ in range(10): # Wait up to 5 seconds (10 * 0.5s) [Source: 347]
                if sandbox_id not in self._active_operations: break
                await asyncio.sleep(0.5)
            else: # Loop finished without break
                logger.error(f"DRIM AI SandboxManager: Timeout waiting for sandbox {sandbox_id} operations to complete. Proceeding with deletion attempt.") # [Source: 348]
        
        sandbox_instance_to_delete: Optional[DockerSandbox] = None
        lock_to_delete: Optional[asyncio.Lock] = None

        async with self._global_lock: # Ensure atomic removal from manager's tracking
            sandbox_instance_to_delete = self._sandboxes.pop(sandbox_id, None) # [Source: 348]
            self._last_used.pop(sandbox_id, None) # [Source: 348]
            lock_to_delete = self._locks.pop(sandbox_id, None) # [Source: 348]

        if sandbox_instance_to_delete:
            await self._safe_delete_sandbox_resources(sandbox_id, sandbox_instance_to_delete)
            logger.info(f"DRIM AI SandboxManager: Deleted sandbox {sandbox_id} from manager and cleaned resources.") # [Source: 348]
        elif lock_to_delete : # Sandbox was in locks but not _sandboxes, ensure lock is cleared
            logger.warning(f"DRIM AI SandboxManager: Sandbox {sandbox_id} was not in active sandboxes list but had a lock; lock removed.")
        else:
            logger.info(f"DRIM AI SandboxManager: Sandbox {sandbox_id} already removed or never fully added.")


    async def delete_sandbox(self, sandbox_id: str) -> None: # [Source: 349]
        """Public method to delete a specified DRIM AI sandbox."""
        if not self._client:
            logger.warning("DRIM AI SandboxManager: Docker client not available. Cannot delete sandbox.")
            return
            
        if sandbox_id not in self._sandboxes and sandbox_id not in self._locks : # More comprehensive check
            logger.info(f"DRIM AI SandboxManager: Attempted to delete non-existent or already cleaned sandbox {sandbox_id}.")
            return
        try:
            await self._safe_delete_sandbox(sandbox_id) # [Source: 349]
        except Exception as e: # [Source: 349]
            # _safe_delete_sandbox should ideally handle its own exceptions and log them.
            # This is a fallback.
            logger.error(f"DRIM AI SandboxManager: Failed to delete sandbox {sandbox_id} through public method: {e}")


    async def cleanup(self) -> None: # [Source: 345]
        """Cleans up all DRIM AI sandbox manager resources, including all active sandboxes."""
        logger.info("DRIM AI SandboxManager: Starting full manager cleanup...")
        self._is_shutting_down = True # [Source: 345]

        if self._cleanup_task and not self._cleanup_task.done(): # [Source: 345]
            self._cleanup_task.cancel() # [Source: 345]
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0) # Wait for graceful cancel [Source: 345]
            except (asyncio.CancelledError, asyncio.TimeoutError): # [Source: 346]
                logger.warning("DRIM AI SandboxManager: Cleanup task did not shut down gracefully or timed out.")
            except Exception as e:
                 logger.error(f"DRIM AI SandboxManager: Error waiting for cleanup task: {e}")
        self._cleanup_task = None

        if not self._client:
            logger.info("DRIM AI SandboxManager: Docker client was not available. No Docker resources to clean.")
            self._sandboxes.clear()
            self._last_used.clear()
            self._locks.clear()
            self._active_operations.clear()
            logger.info("DRIM AI SandboxManager: Manager records cleared (Docker was unavailable).")
            return

        # Concurrently clean up all remaining sandboxes
        # Important to get keys before modifying the dict in _safe_delete_sandbox
        sandbox_ids_to_cleanup: List[str] = []
        async with self._global_lock: # Ensure we get a consistent list of keys
            sandbox_ids_to_cleanup = list(self._sandboxes.keys()) # [Source: 346]

        cleanup_tasks = [
            self._safe_delete_sandbox(sid) for sid in sandbox_ids_to_cleanup
        ] # [Source: 346]
        
        if cleanup_tasks:
            try:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True) # Wait for all, collect results/exceptions
            except Exception as e: # gather itself might raise if one task is unhandled
                logger.error(f"DRIM AI SandboxManager: Unexpected error during asyncio.gather for sandbox cleanup: {e}")
        
        # Final clear of tracking dicts (should be empty if _safe_delete_sandbox worked)
        async with self._global_lock:
            self._sandboxes.clear() # [Source: 346]
            self._last_used.clear() # [Source: 346]
            self._locks.clear() # [Source: 346]
            self._active_operations.clear() # [Source: 346]
        
        logger.info("DRIM AI SandboxManager: Full manager cleanup completed.")

    async def __aenter__(self) -> "SandboxManager": # [Source: 349]
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: # [Source: 349]
        await self.cleanup()

    def get_stats(self) -> Dict[str, Any]: # [Source: 350]
        """Gets DRIM AI sandbox manager statistics."""
        return { # [Source: 350]
            "total_sandboxes": len(self._sandboxes),
            "active_operations": len(self._active_operations), # [Source: 351]
            "max_sandboxes": self.max_sandboxes, # [Source: 351]
            "idle_timeout_seconds": self.idle_timeout, # [Source: 351]
            "cleanup_interval_seconds": self.cleanup_interval, # [Source: 351]
            "is_shutting_down": self._is_shutting_down, # [Source: 351]
            "docker_client_available": self._client is not None,
        }