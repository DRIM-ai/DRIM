import asyncio
import os # [Source: 845]
import tempfile # [Source: 845]
from typing import AsyncGenerator, List # [Source: 845]
import pytest # [Source: 845]
import pytest_asyncio # [Source: 845]

# Ensure these import DRIM AI's components
from app.sandbox.core.manager import SandboxManager # [Source: 845]
from app.sandbox.core.sandbox import DockerSandbox # For type checking
from app.config import SandboxSettings # For potentially overriding config in tests
from app.logger import logger, define_log_level

define_log_level(print_level="DEBUG", logfile_level="DEBUG", name="DRIM_AI_Test_SandboxManager")

@pytest_asyncio.fixture(scope="function") # [Source: 845]
async def drim_sandbox_manager() -> AsyncGenerator[SandboxManager, None]: # Renamed
    """Creates a DRIM AI sandbox manager instance for each test function."""
    logger.info("Fixture: Setting up DRIM AI SandboxManager for test...")
    # Use short timeouts for faster idle cleanup tests
    manager = SandboxManager(max_sandboxes=2, idle_timeout=2, cleanup_interval=1) # [Source: 845] Adjusted timeouts
    try:
        if not manager._client: # If Docker client failed to init in SandboxManager
             pytest.skip("Docker client not available in SandboxManager, skipping manager tests.", allow_module_level=True)
        yield manager # [Source: 845]
    finally:
        logger.info("Fixture: Tearing down DRIM AI SandboxManager after test...")
        await manager.cleanup() # [Source: 845]

# No temp_file fixture used in original PDF for manager tests, so omitting unless needed. [Source: 846]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_manager_create_sandbox(drim_sandbox_manager: SandboxManager): # [Source: 846] Renamed
    """Tests DRIM AI sandbox creation via the manager."""
    logger.info("Test: DRIM AI manager - create sandbox.")
    sandbox_id = await drim_sandbox_manager.create_sandbox() # [Source: 846]
    assert sandbox_id in drim_sandbox_manager._sandboxes # [Source: 846]
    assert sandbox_id in drim_sandbox_manager._last_used # [Source: 846]

    # Verify sandbox functionality briefly
    sandbox_instance = await drim_sandbox_manager.get_sandbox(sandbox_id) # [Source: 846]
    assert isinstance(sandbox_instance, DockerSandbox)
    result = await sandbox_instance.run_command("echo 'drim_test_manager_create'") # [Source: 846]
    assert result.strip() == "drim_test_manager_create" # [Source: 846]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_manager_max_sandboxes_limit(drim_sandbox_manager: SandboxManager): # [Source: 846] Renamed
    """Tests DRIM AI manager's maximum sandbox limit enforcement."""
    logger.info("Test: DRIM AI manager - max sandboxes limit.")
    created_sandbox_ids: List[str] = [] # [Source: 847]
    try:
        for i in range(drim_sandbox_manager.max_sandboxes): # [Source: 847]
            sandbox_id = await drim_sandbox_manager.create_sandbox()
            created_sandbox_ids.append(sandbox_id)
        
        assert len(drim_sandbox_manager._sandboxes) == drim_sandbox_manager.max_sandboxes # [Source: 847]

        with pytest.raises(RuntimeError) as exc_info: # [Source: 847]
            await drim_sandbox_manager.create_sandbox() # Attempt to create one more
        
        expected_message = f"Maximum number of sandboxes ({drim_sandbox_manager.max_sandboxes}) reached" # [Source: 847]
        assert str(exc_info.value) == expected_message # [Source: 847]
    
    finally: # Ensure cleanup of created sandboxes even if test fails [Source: 848]
        logger.debug(f"Cleaning up {len(created_sandbox_ids)} sandboxes from max_sandboxes_limit test.")
        for sid in created_sandbox_ids:
            try:
                await drim_sandbox_manager.delete_sandbox(sid) # [Source: 848]
            except Exception as e:
                logger.error(f"Error cleaning up sandbox {sid} in test: {e}") # [Source: 848]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_manager_get_nonexistent_sandbox(drim_sandbox_manager: SandboxManager): # [Source: 848] Renamed
    """Tests retrieving a non-existent sandbox from DRIM AI manager."""
    logger.info("Test: DRIM AI manager - get non-existent sandbox.")
    non_existent_id = "drim-nonexistent-id-123"
    with pytest.raises(KeyError, match=f"DRIM AI SandboxManager: Sandbox {non_existent_id} not found"): # [Source: 848] Updated match
        await drim_sandbox_manager.get_sandbox(non_existent_id) # [Source: 848]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_manager_sandbox_deletion(drim_sandbox_manager: SandboxManager): # [Source: 848] Renamed from cleanup
    """Tests DRIM AI manager's sandbox deletion functionality."""
    logger.info("Test: DRIM AI manager - sandbox deletion.")
    sandbox_id = await drim_sandbox_manager.create_sandbox()
    assert sandbox_id in drim_sandbox_manager._sandboxes # [Source: 848]
    
    await drim_sandbox_manager.delete_sandbox(sandbox_id) # [Source: 848]
    assert sandbox_id not in drim_sandbox_manager._sandboxes # [Source: 848]
    assert sandbox_id not in drim_sandbox_manager._last_used # [Source: 848]
    assert sandbox_id not in drim_sandbox_manager._locks # Check locks also cleared

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_manager_idle_sandbox_cleanup(drim_sandbox_manager: SandboxManager): # [Source: 848] Renamed
    """Tests DRIM AI manager's automatic cleanup of idle sandboxes."""
    logger.info("Test: DRIM AI manager - idle sandbox cleanup.")
    # Manager fixture already has short idle_timeout (2s) and cleanup_interval (1s)
    
    sandbox_id = await drim_sandbox_manager.create_sandbox()
    assert sandbox_id in drim_sandbox_manager._sandboxes # [Source: 848]
    
    logger.debug(f"Waiting for idle timeout ({drim_sandbox_manager.idle_timeout + drim_sandbox_manager.cleanup_interval + 1}s approx)...")
    await asyncio.sleep(drim_sandbox_manager.idle_timeout + drim_sandbox_manager.cleanup_interval + 1) # Wait longer than idle + cleanup check
        
    # _cleanup_idle_sandboxes is called by the background task.
    # To test deterministically, we can call it directly OR rely on the task having run.
    # For more deterministic test: await drim_sandbox_manager._cleanup_idle_sandboxes()
    # For this test, we'll rely on the background task having run due to the sleep.
    
    assert sandbox_id not in drim_sandbox_manager._sandboxes, "Idle sandbox should have been cleaned up by background task." # [Source: 849]
    assert sandbox_id not in drim_sandbox_manager._locks

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_manager_full_cleanup(drim_sandbox_manager: SandboxManager): # [Source: 849] Renamed
    """Tests DRIM AI manager's full cleanup functionality."""
    logger.info("Test: DRIM AI manager - full cleanup.")
    sandbox_ids: List[str] = [] # [Source: 850]
    for _ in range(drim_sandbox_manager.max_sandboxes): # Create some sandboxes [Source: 850]
        sid = await drim_sandbox_manager.create_sandbox()
        sandbox_ids.append(sid) # [Source: 850]
    
    assert len(drim_sandbox_manager._sandboxes) == drim_sandbox_manager.max_sandboxes
    
    await drim_sandbox_manager.cleanup() # Call full manager cleanup [Source: 850]
    
    # Verify all tracking dicts are empty
    assert not drim_sandbox_manager._sandboxes, "All sandboxes should be removed after manager cleanup." # [Source: 850]
    assert not drim_sandbox_manager._last_used, "Last used tracking should be empty." # [Source: 850]
    assert not drim_sandbox_manager._locks, "Locks should be cleared."
    assert not drim_sandbox_manager._active_operations, "Active operations should be empty."


if __name__ == "__main__":
    logger.info("Running DRIM AI Sandbox Manager tests directly. Ensure Docker is running.")
    pytest.main(["-v", "-s", "--asyncio-mode=auto", __file__])