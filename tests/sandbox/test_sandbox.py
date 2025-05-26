import pytest # [Source: 834]
import pytest_asyncio # [Source: 834]
import docker # type: ignore # For checking container removal

# Ensure these import DRIM AI's components
from app.sandbox.core.sandbox import DockerSandbox, SandboxSettings # [Source: 834]
from app.logger import logger, define_log_level

# Configure logging for these specific tests
define_log_level(print_level="DEBUG", logfile_level="DEBUG", name="DRIM_AI_Test_SandboxCore")

@pytest.fixture(scope="module") # [Source: 834]
def drim_sandbox_config() -> SandboxSettings: # Renamed
    """Creates DRIM AI sandbox configuration for testing."""
    logger.info("Fixture: Creating DRIM AI SandboxSettings for core sandbox tests.")
    return SandboxSettings( # [Source: 834]
        image="python:3.12-slim", # Consistent with DRIM AI Dockerfile
        work_dir="/drim_test_workspace", # Custom workspace for this test module [Source: 834]
        memory_limit="512m", # Adjusted from 1g for potentially lighter tests [Source: 834]
        cpu_limit=0.5, # [Source: 834]
        network_enabled=True, # Enable network for specific tests [Source: 834]
    )

@pytest_asyncio.fixture(scope="module") # [Source: 834]
async def drim_sandbox_instance(drim_sandbox_config: SandboxSettings) -> AsyncGenerator[DockerSandbox, None]: # Renamed
    """Creates and manages a DRIM AI test sandbox instance for the module."""
    logger.info(f"Fixture: Setting up DRIM AI DockerSandbox instance with image '{drim_sandbox_config.image}'.")
    sandbox = DockerSandbox(config_override=drim_sandbox_config) # Use config_override [Source: 834]
    await sandbox.create() # [Source: 834]
    try:
        yield sandbox # [Source: 834]
    finally:
        logger.info(f"Fixture: Tearing down DRIM AI DockerSandbox instance (ID: {sandbox.container.id if sandbox.container else 'N/A'}).")
        await sandbox.cleanup() # [Source: 834]

@pytest.mark.docker_required # Assuming this custom marker is registered in pytest.ini
@pytest.mark.asyncio
async def test_drim_sandbox_working_directory(drim_sandbox_instance: DockerSandbox): # [Source: 835] Renamed
    """Tests DRIM AI sandbox working directory configuration."""
    logger.info("Test: DRIM AI sandbox working directory.")
    assert drim_sandbox_instance.terminal is not None, "Terminal should be initialized."
    result = await drim_sandbox_instance.terminal.run_command("pwd") # [Source: 835]
    assert drim_sandbox_instance.config.work_dir in result.strip() # [Source: 835] (e.g., /drim_test_workspace)

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_file_operations(drim_sandbox_instance: DockerSandbox): # [Source: 835] Renamed
    """Tests DRIM AI sandbox file read/write operations."""
    logger.info("Test: DRIM AI sandbox file operations.")
    test_content = "Hello from DRIM AI sandbox file operations!" # [Source: 836]
    test_file_path = Path(drim_sandbox_instance.config.work_dir) / "drim_file_ops_test.txt" # [Source: 836]
    
    await drim_sandbox_instance.write_file(str(test_file_path), test_content) # [Source: 836]
    content_read = await drim_sandbox_instance.read_file(str(test_file_path)) # [Source: 836]
    assert content_read.strip() == test_content # [Source: 836]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_python_execution(drim_sandbox_instance: DockerSandbox): # [Source: 836] Renamed
    """Tests Python code execution in DRIM AI sandbox."""
    logger.info("Test: DRIM AI sandbox Python execution.")
    assert drim_sandbox_instance.terminal is not None, "Terminal should be initialized."
    
    file_content = "Hello from DRIM AI file for Python script!"
    script_content = f"""
print("Hello from DRIM AI Python script!")
try:
    with open('{drim_sandbox_instance.config.work_dir}/drim_py_test_file.txt', 'r') as f:
        print(f.read().strip())
except FileNotFoundError:
    print("DRIM_FILE_NOT_FOUND_ERROR")
""" # [Source: 836] (Adapted for clarity)
    
    await drim_sandbox_instance.write_file(f"{drim_sandbox_instance.config.work_dir}/drim_py_test_file.txt", file_content) # [Source: 836]
    await drim_sandbox_instance.write_file(f"{drim_sandbox_instance.config.work_dir}/drim_test_script.py", script_content) # [Source: 836]
    
    result = await drim_sandbox_instance.terminal.run_command(f"python3 {drim_sandbox_instance.config.work_dir}/drim_test_script.py") # [Source: 837]
    logger.debug(f"Python execution result: {result}")
    assert "Hello from DRIM AI Python script!" in result # [Source: 837]
    assert file_content in result # [Source: 837]
    assert "DRIM_FILE_NOT_FOUND_ERROR" not in result

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_file_persistence(drim_sandbox_instance: DockerSandbox): # [Source: 837] Renamed
    """Tests file persistence within the DRIM AI sandbox session."""
    logger.info("Test: DRIM AI sandbox file persistence.")
    files_to_test = { # [Source: 838]
        "drim_file1.txt": "DRIM Content 1",
        "drim_file2.txt": "DRIM Content 2",
        "drim_nested_dir/drim_file3.txt": "DRIM Content 3", # [Source: 838]
    }
    base_path = Path(drim_sandbox_instance.config.work_dir)

    for rel_path_str, content in files_to_test.items(): # [Source: 838]
        full_path_in_container = base_path / rel_path_str
        # Ensure parent directory for nested files exists using a sandbox command
        if rel_path_str.count("/") > 0: # Simple check for nested path
            parent_dir_in_container = full_path_in_container.parent
            assert drim_sandbox_instance.terminal is not None
            await drim_sandbox_instance.terminal.run_command(f"mkdir -p {parent_dir_in_container}")

        await drim_sandbox_instance.write_file(str(full_path_in_container), content) # [Source: 838]

    for rel_path_str, expected_content in files_to_test.items(): # [Source: 838]
        full_path_in_container = base_path / rel_path_str
        content_read = await drim_sandbox_instance.read_file(str(full_path_in_container)) # [Source: 838]
        assert content_read.strip() == expected_content # [Source: 838]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_python_environment(drim_sandbox_instance: DockerSandbox): # [Source: 838] Renamed
    """Tests DRIM AI sandbox Python environment configuration."""
    logger.info("Test: DRIM AI sandbox Python environment.")
    assert drim_sandbox_instance.terminal is not None
    
    # Test Python version
    result_version = await drim_sandbox_instance.terminal.run_command("python3 --version") # [Source: 838]
    logger.debug(f"Python version from sandbox: {result_version}")
    # Original PDF asserted "Python 3.10" [Source: 838]. Our image is python:3.12-slim.
    assert "Python 3.12" in result_version or "Python 3.13" in result_version 

    # Test basic module imports
    python_code_env_test = """
import sys, os, json # [Source: 838]
print("DRIM AI Python environment is working!")
""" # [Source: 838]
    script_path_in_container = f"{drim_sandbox_instance.config.work_dir}/drim_env_test.py"
    await drim_sandbox_instance.write_file(script_path_in_container, python_code_env_test) # [Source: 839]
    result_script = await drim_sandbox_instance.terminal.run_command(f"python3 {script_path_in_container}") # [Source: 839]
    assert "DRIM AI Python environment is working!" in result_script # [Source: 839]

@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_network_access(drim_sandbox_instance: DockerSandbox): # [Source: 839] Renamed
    """Tests DRIM AI sandbox network access if enabled."""
    logger.info("Test: DRIM AI sandbox network access.")
    if not drim_sandbox_instance.config.network_enabled: # [Source: 839]
        logger.info("Network access is disabled in sandbox config, skipping network test.")
        pytest.skip("Network access is disabled in sandbox configuration.") # [Source: 839]
    
    assert drim_sandbox_instance.terminal is not None
    # Test network connectivity (e.g., ping google.com or curl example.com)
    # apt update and apt install curl can be slow and flaky in tests.
    # A simpler check might be `ping` if available or trying a simple Python http request.
    # For reliability, ensure curl is in the base image if this test is critical.
    # Assuming 'curl' might not be in python:slim, let's try python http.client for less deps.
    py_network_test_code = f"""
import http.client, socket
try:
    conn = http.client.HTTPSConnection("www.example.com", timeout=5)
    conn.request("GET", "/")
    response = conn.getresponse()
    print(f"STATUS: {{response.status}}")
    conn.close()
except socket.gaierror:
    print("DNS_ERROR")
except Exception as e:
    print(f"HTTP_ERROR: {{type(e).__name__}}")
"""
    script_path = f"{drim_sandbox_instance.config.work_dir}/drim_net_test.py"
    await drim_sandbox_instance.write_file(script_path, py_network_test_code)
    result = await drim_sandbox_instance.terminal.run_command(f"python3 {script_path}")
    logger.debug(f"Network test result from sandbox: {result}")
    assert "STATUS: 200" in result # Check for successful HTTP GET [Source: 839] (Original used curl)
    assert "DNS_ERROR" not in result
    assert "HTTP_ERROR" not in result


@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_cleanup_verification(drim_sandbox_config: SandboxSettings): # [Source: 840] Renamed
    """Tests DRIM AI sandbox cleanup process by checking container removal."""
    logger.info("Test: DRIM AI sandbox cleanup verification.")
    sandbox_to_cleanup = DockerSandbox(config_override=drim_sandbox_config) # [Source: 840]
    await sandbox_to_cleanup.create() # [Source: 840]
    assert sandbox_to_cleanup.container is not None, "Container should exist after creation."
    container_id_to_check = sandbox_to_cleanup.container.id # [Source: 840]

    await sandbox_to_cleanup.cleanup() # [Source: 840]
    assert sandbox_to_cleanup.container is None, "Container object should be None after cleanup."
    assert sandbox_to_cleanup.terminal is None, "Terminal object should be None after cleanup."

    # Verify container has been removed from Docker daemon
    docker_client = docker.from_env() # [Source: 840]
    try:
        docker_client.containers.get(container_id_to_check)
        pytest.fail(f"DRIM AI Sandbox container {container_id_to_check} was found after cleanup, but should have been removed.")
    except docker.errors.NotFound:
        logger.info(f"DRIM AI Sandbox container {container_id_to_check} correctly not found after cleanup.")
        pass # Expected: container is not found [Source: 840]
    except Exception as e:
        pytest.fail(f"DRIM AI Sandbox: Error checking for container {container_id_to_check} after cleanup: {e}")


@pytest.mark.docker_required
@pytest.mark.asyncio
async def test_drim_sandbox_error_handling_invalid_config(): # [Source: 840] Renamed
    """Tests DRIM AI sandbox error handling with invalid configuration (e.g., non-existent image)."""
    logger.info("Test: DRIM AI sandbox error handling with invalid config.")
    invalid_image_name = f"nonexistent-drim-ai-image:{uuid.uuid4().hex}"
    invalid_config = SandboxSettings(image=invalid_image_name, work_dir="/invalid_drim_work") # [Source: 840]
    sandbox_invalid = DockerSandbox(config_override=invalid_config)
    
    with pytest.raises(Exception) as exc_info: # Expecting SandboxError or underlying Docker error [Source: 840]
        await sandbox_invalid.create()
    logger.debug(f"Error creating sandbox with invalid config: {exc_info.value}")
    # Check for specific error related to image not found or creation failure
    assert "image" in str(exc_info.value).lower() or "failed to create" in str(exc_info.value).lower()


if __name__ == "__main__":
    logger.info("Running DRIM AI Sandbox Core tests directly. Ensure Docker is running.")
    pytest.main(["-v", "-s", "--asyncio-mode=auto", __file__]) # Added --asyncio-mode for direct run