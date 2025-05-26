import asyncio
import io
import os
import tarfile
import tempfile
import uuid
from pathlib import Path # Using pathlib for path manipulations
from typing import Dict, Optional, Any, Union # MODIFIED: Added Union [Source: 356]

import docker # type: ignore
from docker.errors import NotFound, APIError # type: ignore # [Source: 356]
from docker.models.containers import Container # type: ignore # [Source: 356]

from app.config import SandboxSettings, config as app_main_config # [Source: 356]
from app.sandbox.core.exceptions import SandboxTimeoutError, SandboxError # [Source: 356]
from app.sandbox.core.terminal import AsyncDockerizedTerminal # [Source: 356]
from app.logger import logger

class DockerSandbox: # [Source: 356]
    """
    DRIM AI Docker sandbox environment.
    Provides a containerized execution environment with resource limits,
    file operations, and command execution capabilities for DRIM AI. [Source: 356]
    """
    def __init__( # [Source: 357]
        self,
        config_override: Optional[SandboxSettings] = None, 
        volume_bindings: Optional[Dict[str, str]] = None,
    ):
        self.config: SandboxSettings = config_override or app_main_config.sandbox # [Source: 357]
        self.volume_bindings: Dict[Path, Dict[str,str]] = self._prepare_runtime_volume_bindings(volume_bindings or {}) # [Source: 357]
        self.client = docker.from_env() # [Source: 357]
        self.container: Optional[Container] = None # [Source: 357]
        self.terminal: Optional[AsyncDockerizedTerminal] = None # [Source: 357]
        self._host_work_dir_path: Optional[Path] = None 

    def _prepare_runtime_volume_bindings(self, additional_bindings: Dict[str, str]) -> Dict[Path, Dict[str,str]]:
        runtime_bindings: Dict[Path, Dict[str,str]] = {}
        for host_path_str, container_path_str in additional_bindings.items(): # [Source: 360]
            host_path = Path(host_path_str).resolve() 
            if not host_path.exists():
                logger.warning(f"DRIM AI Sandbox: Host path for custom volume binding does not exist: {host_path}. Binding might fail.")
            runtime_bindings[host_path] = {"bind": container_path_str, "mode": "rw"}
        return runtime_bindings

    async def create(self) -> "DockerSandbox": # [Source: 357]
        """Creates and starts the DRIM AI sandbox container."""
        logger.info(f"DRIM AI Sandbox: Creating container with image '{self.config.image}'...")
        try:
            self._host_work_dir_path = self._ensure_host_dir(self.config.work_dir) # [Source: 361]
            
            current_bindings_for_api = {
                str(host_path): details for host_path, details in self.volume_bindings.items()
            }
            current_bindings_for_api[str(self._host_work_dir_path)] = {
                "bind": self.config.work_dir, "mode": "rw"
            }

            host_config = self.client.api.create_host_config( # [Source: 357]
                mem_limit=self.config.memory_limit, # [Source: 357]
                cpu_period=100000,
                cpu_quota=int(100000 * self.config.cpu_limit), # [Source: 357]
                network_mode="none" if not self.config.network_enabled else "bridge", # [Source: 358]
                binds=current_bindings_for_api, # [Source: 358]
            )
            
            container_name = f"drim_ai_sandbox_{uuid.uuid4().hex[:8]}" # [Source: 358]
            
            loop = asyncio.get_event_loop()
            container_info = await loop.run_in_executor(None, lambda: self.client.api.create_container( # [Source: 358]
                image=self.config.image,
                command=["tail", "-f", "/dev/null"], # [Source: 358]
                hostname="drim-sandbox", # [Source: 359]
                working_dir=self.config.work_dir, # [Source: 359]
                host_config=host_config, # [Source: 359]
                name=container_name, # [Source: 359]
                tty=True, # [Source: 359]
                detach=True, # [Source: 359]
            ))
            self.container = self.client.containers.get(container_info["Id"]) # [Source: 359]
            await loop.run_in_executor(None, self.container.start) # [Source: 359]

            self.terminal = AsyncDockerizedTerminal( # [Source: 359]
                self.container.id, 
                self.config.work_dir,
                env_vars={"PYTHONUNBUFFERED": "1"} # [Source: 359]
            )
            await self.terminal.init() # [Source: 359]
            logger.info(f"DRIM AI Sandbox: Container '{container_name}' (ID: {self.container.short_id if self.container else 'N/A'}) created and terminal initialized.") # Added None check
            return self
        except APIError as apie:
            logger.error(f"DRIM AI Sandbox: Docker APIError during creation: {apie}")
            await self.cleanup() # [Source: 359]
            raise SandboxError(f"Failed to create sandbox due to Docker API error: {apie}") from apie
        except Exception as e:
            logger.exception("DRIM AI Sandbox: Unexpected error during sandbox creation.")
            await self.cleanup() # [Source: 359]
            raise SandboxError(f"Failed to create sandbox: {e}") from e # [Source: 359]

    @staticmethod
    def _ensure_host_dir(container_target_path: str) -> Path: # [Source: 361]
        base_name = Path(container_target_path).name
        if not base_name: base_name = "sandbox_workdir" 
        host_path_str = tempfile.mkdtemp(prefix=f"drim_ai_{base_name}_", suffix=f"_{os.urandom(4).hex()}") # [Source: 361]
        host_path = Path(host_path_str)
        logger.debug(f"DRIM AI Sandbox: Ensured host directory for work_dir mapping: {host_path}")
        return host_path

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str: # [Source: 361]
        if not self.terminal: # [Source: 361]
            raise SandboxError("DRIM AI Sandbox not initialized or already cleaned up. Cannot run command.")
        try:
            effective_timeout = timeout if timeout is not None else self.config.timeout # [Source: 362]
            return await self.terminal.run_command(cmd, timeout=effective_timeout)
        except asyncio.TimeoutError: # Catch asyncio.TimeoutError, not just built-in TimeoutError [Source: 362]
            raise SandboxTimeoutError( # [Source: 362]
                f"Command '{cmd[:50]}...' execution timed out after {effective_timeout} seconds in DRIM AI Sandbox."
            )
        except Exception as e:
            logger.error(f"DRIM AI Sandbox: Error running command '{cmd[:50]}...': {e}")
            raise SandboxError(f"Failed to run command in sandbox: {e}") from e

    def _resolve_container_path(self, path_in: Union[str, Path]) -> str: # [Source: 365] 
        path = Path(path_in)
        if ".." in path.parts: # [Source: 365]
            raise ValueError(f"Path contains potentially unsafe '..' patterns: {path_in}")
        
        if path.is_absolute(): # [Source: 365]
            return str(path)
        else:
            return str(Path(self.config.work_dir) / path) # [Source: 365]

    async def read_file(self, path: Union[str, Path]) -> str: # [Source: 363]
        if not self.container: # [Source: 363]
            raise SandboxError("DRIM AI Sandbox not initialized. Cannot read file.")
        
        resolved_path_str = self._resolve_container_path(path)
        logger.debug(f"DRIM AI Sandbox: Reading file from container: {resolved_path_str}")
        try:
            loop = asyncio.get_event_loop()
            tar_stream_bytes, _ = await loop.run_in_executor(None, lambda: self.container.get_archive(resolved_path_str)) # type: ignore [Source: 363]
            
            content = await self._read_from_tar_stream(io.BytesIO(tar_stream_bytes)) # [Source: 363]
            return content.decode("utf-8", errors="replace") # [Source: 363]
        except NotFound: # [Source: 363]
            logger.warning(f"DRIM AI Sandbox: File not found in container: {resolved_path_str}")
            raise FileNotFoundError(f"File not found in sandbox: {path}") from None
        except Exception as e: # [Source: 363]
            logger.exception(f"DRIM AI Sandbox: Failed to read file '{resolved_path_str}' from container.")
            raise SandboxError(f"Failed to read file '{path}' from sandbox: {e}") from e

    async def write_file(self, path: Union[str, Path], content: str) -> None: # [Source: 364]
        if not self.container: # [Source: 364]
            raise SandboxError("DRIM AI Sandbox not initialized. Cannot write file.")

        resolved_path_str = self._resolve_container_path(path)
        target_filename = Path(resolved_path_str).name
        container_parent_dir = str(Path(resolved_path_str).parent)

        logger.debug(f"DRIM AI Sandbox: Writing file to container: {resolved_path_str}")
        try:
            if container_parent_dir and container_parent_dir != ".": # [Source: 365]
                mkdir_cmd = f"mkdir -p '{container_parent_dir}'"
                loop = asyncio.get_event_loop()
                exit_code, out = await loop.run_in_executor(None, lambda: self.container.exec_run(mkdir_cmd)) # type: ignore
                if exit_code != 0:
                    raise SandboxError(f"Failed to create parent directory {container_parent_dir} in sandbox. Output: {out.decode(errors='replace')}")

            tar_stream = await self._create_tar_stream_for_put_archive(target_filename, content.encode("utf-8")) # [Source: 365]
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.container.put_archive(container_parent_dir or "/", tar_stream)) # type: ignore [Source: 365]
            logger.info(f"DRIM AI Sandbox: Successfully wrote file to {resolved_path_str}")
        except Exception as e: # [Source: 365]
            logger.exception(f"DRIM AI Sandbox: Failed to write file '{resolved_path_str}' to container.")
            raise SandboxError(f"Failed to write file '{path}' to sandbox: {e}") from e

    async def copy_from(self, container_src_path: Union[str, Path], host_dst_path: Union[str, Path]) -> None: # [Source: 366]
        if not self.container:
            raise SandboxError("DRIM AI Sandbox not initialized for copy_from.")
        
        resolved_container_path = self._resolve_container_path(container_src_path)
        host_destination_path = Path(host_dst_path)
        logger.debug(f"DRIM AI Sandbox: Copying from container '{resolved_container_path}' to host '{host_destination_path}'")

        try:
            loop = asyncio.get_event_loop()
            tar_stream_bytes, stat_info = await loop.run_in_executor(None, lambda: self.container.get_archive(resolved_container_path)) # type: ignore [Source: 369]
            
            # Ensure host destination directory exists
            is_dir_archive = stat_info and stat_info.get('type') == 2 # In Docker SDK, type 2 often means directory
            if is_dir_archive:
                host_destination_path.mkdir(parents=True, exist_ok=True)
            else: 
                host_destination_path.parent.mkdir(parents=True, exist_ok=True) # [Source: 369]

            with tarfile.open(fileobj=io.BytesIO(tar_stream_bytes)) as tar: # [Source: 369]
                members_to_extract = []
                for member in tar.getmembers(): # [Source: 369]
                    if member.isabs() or ".." in member.name:
                        logger.warning(f"DRIM AI Sandbox: Skipped potentially unsafe tar member during copy_from: {member.name}")
                        continue
                    members_to_extract.append(member)
                
                if not members_to_extract:
                     raise FileNotFoundError(f"No valid members found in archive from container path: {resolved_container_path}") # [Source: 369]
                
                # Extract all valid members to the host_destination_path
                # If the archive contains a single top-level directory matching the last component of resolved_container_path
                # and host_destination_path is meant to BE that directory, this works.
                # If resolved_container_path was a file, members_to_extract[0].name would be its basename.
                # If host_destination_path is a directory, it extracts into it.
                # If host_destination_path is a file path, tar.extractall might behave unexpectedly if archive has multiple files/dirs.
                # For simplicity, assuming basic file/dir copy for now.
                await loop.run_in_executor(None, lambda: tar.extractall(path=str(host_destination_path.parent if not is_dir_archive and host_destination_path.name == members_to_extract[0].name else host_destination_path), members=members_to_extract)) # [Source: 369] (Adjusted path for single file extraction)
                
            logger.info(f"DRIM AI Sandbox: Successfully copied from container '{resolved_container_path}' to '{host_destination_path}'")

        except NotFound: # [Source: 371]
            raise FileNotFoundError(f"Source path '{container_src_path}' not found in sandbox.") from None
        except Exception as e: # [Source: 371]
            logger.exception(f"DRIM AI Sandbox: Failed to copy from container path '{resolved_container_path}'.")
            raise SandboxError(f"Failed to copy from sandbox path '{container_src_path}': {e}") from e

    async def copy_to(self, host_src_path: Union[str, Path], container_dst_path: Union[str, Path]) -> None: # [Source: 372]
        if not self.container:
            raise SandboxError("DRIM AI Sandbox not initialized for copy_to.")

        host_source_path = Path(host_src_path).resolve()
        resolved_container_path_target_dir = str(Path(self._resolve_container_path(container_dst_path)).parent) # Target dir for put_archive
        
        logger.debug(f"DRIM AI Sandbox: Copying from host '{host_source_path}' to container targeting directory '{resolved_container_path_target_dir}' (intended full path: {self._resolve_container_path(container_dst_path)})")

        if not host_source_path.exists(): # [Source: 373]
            raise FileNotFoundError(f"Host source path '{host_src_path}' not found.")

        try:
            # Ensure parent directory in container exists for the destination path
            # The _resolve_container_path will be used for the tar arcname, put_archive needs dir
            if resolved_container_path_target_dir and resolved_container_path_target_dir != ".": # [Source: 373]
                mkdir_cmd = f"mkdir -p '{resolved_container_path_target_dir}'"
                loop = asyncio.get_event_loop()
                exit_code, out = await loop.run_in_executor(None, lambda: self.container.exec_run(mkdir_cmd)) # type: ignore
                if exit_code != 0:
                    raise SandboxError(f"Failed to create parent directory {resolved_container_path_target_dir} in sandbox. Output: {out.decode(errors='replace')}")

            tar_data_stream = io.BytesIO() # [Source: 373]
            with tarfile.open(fileobj=tar_data_stream, mode="w") as tar: # [Source: 373]
                # arcname should be the name of the file/dir as it should appear in container_dst_path's parent
                arcname_in_tar = Path(self._resolve_container_path(container_dst_path)).name
                tar.add(str(host_source_path), arcname=arcname_in_tar) # [Source: 373, 374]
            tar_data_stream.seek(0)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.container.put_archive(resolved_container_path_target_dir or "/", tar_data_stream.read())) # type: ignore [Source: 374]
            
            logger.info(f"DRIM AI Sandbox: Successfully copied from host '{host_source_path}' to container path related to '{container_dst_path}'")

        except FileNotFoundError: # [Source: 374]
            raise
        except Exception as e: # [Source: 374]
            logger.exception(f"DRIM AI Sandbox: Failed to copy to container path '{container_dst_path}'.")
            raise SandboxError(f"Failed to copy to sandbox path '{container_dst_path}': {e}") from e

    @staticmethod
    async def _create_tar_stream_for_put_archive(name_in_tar: str, content_bytes: bytes) -> io.BytesIO: # [Source: 375] 
        tar_stream = io.BytesIO() # [Source: 375]
        with tarfile.open(fileobj=tar_stream, mode="w") as tar: # [Source: 375]
            tarinfo = tarfile.TarInfo(name=name_in_tar) # [Source: 375]
            tarinfo.size = len(content_bytes) # [Source: 375]
            tar.addfile(tarinfo, io.BytesIO(content_bytes)) # [Source: 375]
        tar_stream.seek(0) # [Source: 375]
        return tar_stream

    @staticmethod
    async def _read_from_tar_stream(tar_data_stream: io.BytesIO) -> bytes: # [Source: 376] 
        with tarfile.open(fileobj=tar_data_stream, mode="r") as tar: # [Source: 376]
            member = tar.next() # [Source: 376]
            if not member: # [Source: 376]
                raise SandboxError("Empty tar archive received from container or member is None.")
            if member.isdir(): 
                logger.warning("DRIM AI Sandbox: _read_from_tar_stream expected a file, got a directory entry. Trying next.")
                member = tar.next() 
                if not member or member.isdir():
                     raise SandboxError(f"Tar archive from container does not contain a readable file at root. First entry: {member.name if member else 'None'}")

            file_content_obj = tar.extractfile(member) # [Source: 376]
            if not file_content_obj: # [Source: 376]
                raise SandboxError(f"Failed to extract file content for member '{member.name}' from tar stream.")
            return file_content_obj.read() # [Source: 376]

    async def cleanup(self) -> None: # [Source: 376]
        """Cleans up DRIM AI sandbox resources."""
        logger.info(f"DRIM AI Sandbox: Starting cleanup for container ID: {self.container.id if self.container else 'N/A'}")
        errors = []
        if self.terminal: # [Source: 376]
            try:
                await self.terminal.close() # [Source: 376]
            except Exception as e:
                err_msg = f"DRIM AI Sandbox: Terminal cleanup error: {e}"
                logger.error(err_msg)
                errors.append(err_msg) # [Source: 376]
            finally:
                self.terminal = None
        
        if self.container: # [Source: 376]
            container_id_for_log = self.container.id
            try:
                loop = asyncio.get_event_loop()
                logger.info(f"DRIM AI Sandbox: Stopping container {container_id_for_log}...")
                await loop.run_in_executor(None, lambda: self.container.stop(timeout=5)) # type: ignore [Source: 377]
            except APIError as apie: 
                err_msg = f"DRIM AI Sandbox: APIError stopping container {container_id_for_log}: {apie}"
                logger.error(err_msg)
                errors.append(err_msg)
            except Exception as e: 
                err_msg = f"DRIM AI Sandbox: General error stopping container {container_id_for_log}: {e}"
                logger.warning(err_msg) 
                errors.append(err_msg) # [Source: 377]
            
            try:
                logger.info(f"DRIM AI Sandbox: Removing container {container_id_for_log}...")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: self.container.remove(force=True)) # type: ignore # [Source: 378]
            except APIError as apie:
                err_msg = f"DRIM AI Sandbox: APIError removing container {container_id_for_log}: {apie}"
                logger.error(err_msg)
                errors.append(err_msg)
            except Exception as e:
                err_msg = f"DRIM AI Sandbox: General error removing container {container_id_for_log}: {e}"
                logger.error(err_msg)
                errors.append(err_msg) # [Source: 378]
            finally:
                self.container = None
        
        if self._host_work_dir_path and self._host_work_dir_path.exists():
            try:
                import shutil
                shutil.rmtree(self._host_work_dir_path)
                logger.info(f"DRIM AI Sandbox: Removed host work directory: {self._host_work_dir_path}")
            except Exception as e:
                err_msg = f"DRIM AI Sandbox: Error removing host work directory '{self._host_work_dir_path}': {e}"
                logger.error(err_msg)
                errors.append(err_msg)
            finally:
                self._host_work_dir_path = None
                
        if errors: # [Source: 378]
            logger.warning(f"DRIM AI Sandbox: Encountered errors during cleanup: {'; '.join(errors)}")
        else:
            logger.info("DRIM AI Sandbox: Cleanup complete.")

    async def __aenter__(self) -> "DockerSandbox": # [Source: 378]
        """Async context manager entry for DRIM AI Sandbox."""
        return await self.create()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: # [Source: 378]
        """Async context manager exit for DRIM AI Sandbox."""
        await self.cleanup()

# Role in the System (Updated for DRIM AI)
# As part of the DRIM AI sandbox subsystem, this script provides the core Docker-based
# sandboxing functionality. [Source: 379] It allows DRIM AI to execute commands and manage files
# in an isolated and resource-controlled environment, which is critical for security
# and stability when handling potentially untrusted code or operations. [Source: 380]