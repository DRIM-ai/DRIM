# [Source: 826]
"""Tests for the DRIM AI AsyncDockerizedTerminal implementation."""
import docker # type: ignore [Source: 826]
import pytest # [Source: 826]
import pytest_asyncio # [Source: 826]

from app.sandbox.core.terminal import AsyncDockerizedTerminal # [Source: 826] (DRIM AI's version)
from app.logger import logger, define_log_level

define_log_level(print_level="DEBUG", logfile_level="DEBUG", name="DRIM_AI_Test_DockerTerminal")

@pytest.fixture(scope="module") # [Source: 826]
def drim_docker_client(): # Renamed
    """Fixture providing a Docker client for DRIM AI tests."""
    logger.info("Setting up Docker client for DRIM AI terminal tests.")
    try:
        client = docker.from_env()
        client.ping() # Check if Docker daemon is responsive
        return client
    except docker.errors.DockerException as e:
        logger.error(f"DRIM AI Docker Test: Docker daemon not available or not responsive: {e}. Skipping Docker tests.")
        pytest.skip("Docker daemon not available, skipping Docker-dependent tests.", allow_module_level=True)


@pytest_asyncio.fixture(scope="module") # [Source: 826]
async def drim_docker_container(drim_docker_client: docker.DockerClient): # Renamed, depends on drim_docker_client
    """Fixture providing a test Docker container for DRIM AI."""
    container_name = "drim_ai_test_terminal_container"
    image_name = "python:3.12-slim" # Consistent with DRIM AI's Dockerfile
    logger.info(f"Setting up DRIM AI test container '{container_name}' from image '{image_name}'.")
    
    # Remove container if it exists from a previous failed run
    try:
        existing_container = drim_docker_client.containers.get(container_name)
        logger.warning(f"Found existing container '{container_name}'. Removing it.")
        existing_container.remove(force=True)
    except docker.errors.NotFound:
        pass # Container doesn't exist, good.
    except Exception as e:
        logger.error(f"Error removing pre-existing container '{container_name}': {e}")


    container = drim_docker_client.containers.run( # [Source: 826]
        image_name,
        command="tail -f /dev/null", # Keep it running [Source: 826]
        name=container_name, # [Source: 826]
        detach=True, # [Source: 826]
        # remove=True, # remove=True makes it hard to use if we need to inspect after error. Manual cleanup preferred.
    )
    logger.info(f"DRIM AI test container '{container.name}' (ID: {container.short_id}) started.")
    yield container # [Source: 826]
    
    logger.info(f"Tearing down DRIM AI test container '{container.name}'...")
    try:
        container.stop(timeout=5) # [Source: 826]
        container.remove(force=True)
        logger.info(f"DRIM AI test container '{container.name}' stopped and removed.")
    except Exception as e:
        logger.error(f"Error during DRIM AI test container cleanup: {e}")


@pytest_asyncio.fixture # No scope specified, defaults to function [Source: 827]
async def drim_terminal(drim_docker_container: docker.models.containers.Container) -> AsyncGenerator[AsyncDockerizedTerminal, None]: # Renamed
    """Fixture providing an initialized DRIM AI AsyncDockerizedTerminal instance."""
    logger.debug(f"Initializing DRIM AI AsyncDockerizedTerminal for container '{drim_docker_container.short_id}'.")
    terminal = AsyncDockerizedTerminal( # [Source: 827]
        container=drim_docker_container.id, # Pass container ID
        working_dir="/drim_tests", # Custom working dir for tests [Source: 827]
        env_vars={"DRIM_TEST_VAR": "drim_value"}, # [Source: 827]
        default_timeout=10, # Shorter timeout for tests [Source: 827]
    )
    await terminal.init() # [Source: 827]
    logger.debug("DRIM AI AsyncDockerizedTerminal initialized.")
    yield terminal
    logger.debug("Closing DRIM AI AsyncDockerizedTerminal...")
    await terminal.close() # [Source: 827]
    logger.debug("DRIM AI AsyncDockerizedTerminal closed.")

@pytest.mark.docker_required # Custom marker for Docker tests
class TestDrimAsyncDockerizedTerminal: # [Source: 827] Renamed
    """Test cases for DRIM AI's AsyncDockerizedTerminal."""

    @pytest.mark.asyncio
    async def test_drim_basic_command_execution(self, drim_terminal: AsyncDockerizedTerminal): # [Source: 827] Renamed
        """Test basic command execution functionality in DRIM AI terminal."""
        logger.info("Test: DRIM AI terminal basic command execution.")
        test_phrase = "Hello DRIM AI Terminal"
        result = await drim_terminal.run_command(f"echo '{test_phrase}'") # [Source: 827]
        assert test_phrase in result # [Source: 827]

    @pytest.mark.asyncio
    async def test_drim_environment_variables(self, drim_terminal: AsyncDockerizedTerminal): # [Source: 827] Renamed
        """Test environment variable setting and access in DRIM AI terminal."""
        logger.info("Test: DRIM AI terminal environment variables.")
        result = await drim_terminal.run_command("echo $DRIM_TEST_VAR") # [Source: 827]
        assert "drim_value" in result # [Source: 827]

    @pytest.mark.asyncio
    async def test_drim_working_directory(self, drim_terminal: AsyncDockerizedTerminal): # [Source: 827] Renamed
        """Test working directory setup in DRIM AI terminal."""
        logger.info("Test: DRIM AI terminal working directory.")
        result = await drim_terminal.run_command("pwd") # [Source: 827]
        assert "/drim_tests" == result.strip() # Based on fixture setup [Source: 827]

    @pytest.mark.asyncio
    async def test_drim_command_timeout(self, drim_docker_container: docker.models.containers.Container): # [Source: 828] Renamed
        """Test command timeout functionality in DRIM AI terminal."""
        logger.info("Test: DRIM AI terminal command timeout.")
        # Create a new terminal with a very short timeout for this specific test
        short_timeout_terminal = AsyncDockerizedTerminal(drim_docker_container.id, default_timeout=1) # [Source: 828]
        await short_timeout_terminal.init()
        try:
            with pytest.raises(TimeoutError): # [Source: 828] (asyncio.TimeoutError or custom SandboxTimeoutError)
                await short_timeout_terminal.run_command("sleep 3") # [Source: 828]
        finally:
            await short_timeout_terminal.close() # [Source: 828]

    @pytest.mark.asyncio
    async def test_drim_multiple_commands(self, drim_terminal: AsyncDockerizedTerminal): # [Source: 829] Renamed
        """Test execution of multiple commands in sequence in DRIM AI terminal."""
        logger.info("Test: DRIM AI terminal multiple commands.")
        cmd1_out = await drim_terminal.run_command("echo 'DRIM First Command'") # [Source: 829]
        cmd2_out = await drim_terminal.run_command("echo 'DRIM Second Command'") # [Source: 829]
        assert "DRIM First Command" in cmd1_out # [Source: 829]
        assert "DRIM Second Command" in cmd2_out # [Source: 829]

    @pytest.mark.asyncio
    async def test_drim_session_cleanup_idempotency(self, drim_docker_container: docker.models.containers.Container): # [Source: 829] Renamed test for clarity
        """Test proper cleanup of DRIM AI terminal resources and idempotency of close."""
        logger.info("Test: DRIM AI terminal session cleanup.")
        terminal_to_cleanup = AsyncDockerizedTerminal(drim_docker_container.id) # [Source: 829]
        await terminal_to_cleanup.init() # [Source: 829]
        assert terminal_to_cleanup.session is not None, "Session should be active after init" # [Source: 829]
        
        await terminal_to_cleanup.close() # [Source: 829]
        assert terminal_to_cleanup.session is None, "Session should be None after first close" # Check if session is set to None

        # Test calling close again (should not error)
        try:
            await terminal_to_cleanup.close()
            logger.info("DRIM AI terminal second close call handled gracefully.")
        except Exception as e:
            pytest.fail(f"DRIM AI terminal second close call raised an exception: {e}")


# Pytest configuration for asyncio mode, if not globally set in pytest.ini or conftest.py
# The PDF [Source: 829] shows this at the end of the file.
# It's often better in conftest.py, but can be here.
# def pytest_configure(config):
# """Configure pytest-asyncio."""
# config.addinivalue_line("asyncio_mode", "strict") # [Source: 829]
# config.addinivalue_line("asyncio_default_fixture_loop_scope", "function") # [Source: 829]
# This might cause issues if there's a global conftest.py.
# For standalone run, it's fine.

if __name__ == "__main__": # [Source: 829]
    # Requires Docker to be running.
    # Use `pytest -m docker_required` to run only these tests if marker is registered.
    logger.info("Running DRIM AI Docker Terminal tests directly. Ensure Docker is running.")
    pytest.main(["-v", "-s", __file__]) # [Source: 829] Added -s