import tempfile
from pathlib import Path
from typing import AsyncGenerator # [Source: 818]

import pytest # [Source: 818]
import pytest_asyncio # [Source: 818]

# Ensure these import DRIM AI's components
from app.config import SandboxSettings # [Source: 818]
from app.sandbox.client import LocalSandboxClient, create_sandbox_client # [Source: 818]
from app.logger import logger, define_log_level

# Configure logging for tests
define_log_level(print_level="DEBUG", logfile_level="DEBUG", name="DRIM_AI_Test_SandboxClient")

@pytest_asyncio.fixture(scope="function") # [Source: 818]
async def drim_local_client() -> AsyncGenerator[LocalSandboxClient, None]: # Renamed fixture
    """Creates a DRIM AI local sandbox client for testing."""
    logger.info("Setting up DRIM AI LocalSandboxClient for test...")
    client = create_sandbox_client() # This creates DRIM AI's LocalSandboxClient
    try:
        yield client
    finally:
        logger.info("Tearing down DRIM AI LocalSandboxClient after test...")
        await client.cleanup() # [Source: 818]

@pytest.fixture(scope="function") # [Source: 818]
def drim_temp_dir() -> Path: # Renamed fixture
    """Creates a temporary directory for DRIM AI sandbox testing."""
    with tempfile.TemporaryDirectory(prefix="drim_ai_test_") as tmp_dir: # [Source: 818]
        logger.debug(f"Created temporary directory for testing: {tmp_dir}")
        yield Path(tmp_dir)

@pytest.mark.asyncio
async def test_drim_sandbox_creation(drim_local_client: LocalSandboxClient): # [Source: 819] Renamed test and fixture
    """Tests DRIM AI sandbox creation with specific configuration."""
    logger.info("Test: DRIM AI sandbox creation.")
    custom_config = SandboxSettings( # [Source: 819]
        image="python:3.12-slim", # As per our Dockerfile
        work_dir="/drim_workspace", # Custom work_dir for test
        memory_limit="256m", # Reduced for test [Source: 819]
        cpu_limit=0.5, # [Source: 819]
        network_enabled=False # Explicitly test with network off
    )
    await drim_local_client.create(config_override=custom_config)
    assert drim_local_client.is_active, "Sandbox should be active after creation"
    
    result = await drim_local_client.run_command("python3 --version")
    logger.debug(f"Python version in sandbox: {result}")
    # The original PDF had "Python 3.10" [Source: 819]. Our Dockerfile uses 3.12-slim.
    assert "Python 3.12" in result or "Python 3.13" in result # Adjust based on actual slim image python version
    
    # Test if work_dir was respected (Note: DockerSandbox creates its own host mapping for work_dir)
    # To truly test custom work_dir inside container, we'd check `pwd`
    pwd_result = await drim_local_client.run_command("pwd")
    assert custom_config.work_dir in pwd_result.strip()


@pytest.mark.asyncio
async def test_drim_local_command_execution(drim_local_client: LocalSandboxClient): # [Source: 819] Renamed
    """Tests command execution in DRIM AI local sandbox."""
    logger.info("Test: DRIM AI local command execution.")
    await drim_local_client.create() # Use default DRIM AI config
    
    echo_test_string = "hello_drim_ai_sandbox"
    result = await drim_local_client.run_command(f"echo '{echo_test_string}'") # [Source: 819]
    assert result.strip() == echo_test_string # [Source: 819]
    
    with pytest.raises(Exception): # Original PDF expected Exception, likely SandboxTimeoutError [Source: 819]
        # Test command timeout
        await drim_local_client.run_command("sleep 5", timeout=1) # [Source: 819]

@pytest.mark.asyncio
async def test_drim_local_file_operations(drim_local_client: LocalSandboxClient, drim_temp_dir: Path): # [Source: 819] Renamed
    """Tests file operations in DRIM AI local sandbox."""
    logger.info("Test: DRIM AI local file operations.")
    default_sandbox_config = SandboxSettings() # Get default work_dir for path construction
    sandbox_work_dir = default_sandbox_config.work_dir

    await drim_local_client.create()
    
    test_content = "Hello, DRIM AI World from Sandbox!" # [Source: 820]
    container_test_file = f"{sandbox_work_dir}/drim_test.txt" # Path inside container
    
    await drim_local_client.write_file(container_test_file, test_content) # [Source: 820]
    content_read = await drim_local_client.read_file(container_test_file) # [Source: 820]
    assert content_read.strip() == test_content # [Source: 820]

    # Test copying file TO container
    host_src_file = drim_temp_dir / "drim_src.txt" # [Source: 820]
    host_src_content = "Copy to DRIM AI container"
    host_src_file.write_text(host_src_content)
    container_copied_file = f"{sandbox_work_dir}/drim_copied_to.txt"
    await drim_local_client.copy_to(str(host_src_file), container_copied_file) # [Source: 820]
    content_copied_to = await drim_local_client.read_file(container_copied_file) # [Source: 820]
    assert content_copied_to.strip() == host_src_content # [Source: 820]

    # Test copying file FROM container
    host_dst_file = drim_temp_dir / "drim_dst.txt" # [Source: 821]
    await drim_local_client.copy_from(container_test_file, str(host_dst_file)) # [Source: 821]
    assert host_dst_file.read_text().strip() == test_content # [Source: 821]

@pytest.mark.asyncio
async def test_drim_local_volume_binding(drim_local_client: LocalSandboxClient, drim_temp_dir: Path): # [Source: 821] Renamed
    """Tests volume binding in DRIM AI local sandbox (custom bindings)."""
    logger.info("Test: DRIM AI local volume binding.")
    host_bind_path_str = str(drim_temp_dir / "custom_bind_data") # [Source: 821]
    host_bind_path = Path(host_bind_path_str)
    host_bind_path.mkdir(parents=True, exist_ok=True)
    
    container_bind_target = "/drim_data_mount"
    volume_bindings = {host_bind_path_str: container_bind_target} # [Source: 821]
    
    await drim_local_client.create(volume_bindings=volume_bindings) # [Source: 821]
    
    host_test_file_in_bind = host_bind_path / "drim_volume_test.txt" # [Source: 821]
    volume_test_content = "DRIM AI Volume Test Content"
    host_test_file_in_bind.write_text(volume_test_content) # [Source: 821]
    
    # Read the file from within the container via the mount point
    content_from_container = await drim_local_client.read_file(f"{container_bind_target}/drim_volume_test.txt") # [Source: 821]
    assert volume_test_content in content_from_container # [Source: 821]

@pytest.mark.asyncio
async def test_drim_local_error_handling(drim_local_client: LocalSandboxClient): # [Source: 821] Renamed
    """Tests error handling in DRIM AI local sandbox client."""
    logger.info("Test: DRIM AI local error handling.")
    await drim_local_client.create()
    
    non_existent_file_container = "/drim_workspace/nonexistent_drim_file.txt"
    non_existent_file_host = "local_drim_nonexistent.txt"

    with pytest.raises(Exception) as exc_info_read: # [Source: 821]
        await drim_local_client.read_file(non_existent_file_container)
    logger.debug(f"Read non-existent file error: {exc_info_read.value}")
    assert "not found" in str(exc_info_read.value).lower() # [Source: 821]

    with pytest.raises(Exception) as exc_info_copy: # [Source: 821]
        await drim_local_client.copy_from(non_existent_file_container, non_existent_file_host)
    logger.debug(f"Copy non-existent file error: {exc_info_copy.value}")
    assert "not found" in str(exc_info_copy.value).lower() # [Source: 821]

if __name__ == "__main__": # [Source: 821]
    # This allows running the tests directly with `python tests/sandbox/test_client.py`
    # For full test suite, use `pytest`.
    pytest.main(["-v", "-s", __file__]) # Added -s for stdout visibility during direct run