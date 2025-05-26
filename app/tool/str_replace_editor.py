# [Source: 715]
"""DRIM AI File and directory manipulation tool with sandbox support."""
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, List, Literal, Optional, get_args, Union 
from pydantic import Field 

from app.config import config as app_main_config 
from app.exceptions import ToolError 
from app.tool.base import BaseTool, CLIResult, ToolResult, ToolFailure 
from app.tool.file_operators import ( 
    FileOperator,
    LocalFileOperator,
    PathLike, 
    SandboxFileOperator,
)
from app.logger import logger

Command = Literal[ 
    "view", "create", "str_replace", "insert", "undo_edit",
]
COMMAND_ARGS = get_args(Command) 

SNIPPET_LINES: int = 4
MAX_RESPONSE_LEN: int = 16000
TRUNCATED_MESSAGE: str = ( 
    "<response clipped>\n<NOTE>To save on context, only part of this file/output has been shown. "
    "If you need to see other parts, use the 'view' command with specific line ranges, "
    "or use shell commands like `grep -n` (via the Bash tool if available and appropriate) "
    "to find line numbers for what you are looking for.</NOTE>"
)

_STR_REPLACE_EDITOR_DESCRIPTION_DRIM_AI = """\
DRIM AI's custom editing tool for viewing, creating, and editing files using string replacement or line insertion.
This tool can operate on the local filesystem or within a secure sandbox, depending on DRIM AI's configuration.

Key Features & Usage:
* State Persistence: Edits are persistent. An undo history is maintained per file for the 'undo_edit' command.
* `view` command:
    - If `path` is a file: Displays content with line numbers (`cat -n` like). Supports `view_range` (a list of two integers [start, end]) for specific lines.
    - If `path` is a directory: Lists non-hidden files and directories up to 2 levels deep.
* `create` command: Creates a new file with `file_text`. Fails if `path` already exists.
* `str_replace` command:
    - `old_str` must EXACTLY match one or more consecutive lines in the original file (whitespace sensitive).
    - Fails if `old_str` is not unique in the file; include enough context in `old_str` for uniqueness.
    - `new_str` contains the lines to replace `old_str`. If `new_str` is omitted, `old_str` is deleted.
* `insert` command: Inserts `new_str` AFTER the line number specified by `insert_line`.
* `undo_edit` command: Reverts the last successful edit (`str_replace` or `insert`) made to the file at `path`.
* Output Truncation: Long outputs are truncated and marked with `<response clipped>`.
* Path Requirement: All paths must be absolute.
""" 

def _maybe_truncate( 
    content: str, truncate_after: Optional[int] = MAX_RESPONSE_LEN
) -> str:
    if not truncate_after or len(content) <= truncate_after: 
        return content
    return content[:truncate_after] + "\n" + TRUNCATED_MESSAGE 

class StrReplaceEditor(BaseTool): 
    name: str = "str_replace_editor" 
    description: str = _STR_REPLACE_EDITOR_DESCRIPTION_DRIM_AI 
    parameters: dict = { 
        "type": "object",
        "properties": {
            "command": { 
                "description": f"The command to run. Allowed options are: {', '.join(COMMAND_ARGS)}.", 
                "enum": list(COMMAND_ARGS), 
                "type": "string",
            },
            "path": { 
                "description": "Absolute path to the file or directory.", 
                "type": "string",
            },
            "file_text": { 
                "description": "Required for `create` command: the content of the file to be created.", 
                "type": "string",
            },
            "old_str": { 
                "description": "Required for `str_replace` command: the exact string/lines in `path` to replace.", 
                "type": "string",
            },
            "new_str": { 
                "description": "For `str_replace`: the new string/lines to replace old_str (if omitted, old_str is deleted). Required for `insert`: the string/lines to insert.", 
                "type": "string",
            },
            "insert_line": { 
                "description": "Required for `insert` command: the 1-based line number AFTER which `new_str` will be inserted. Use 0 to insert at the beginning.", 
                "type": "integer",
            },
            "view_range": { 
                "description": "Optional for `view` command (file only): A list of two integers [start_line, end_line] (1-based). " 
                             "e.g., [1, 10] shows lines 1-10. [11, -1] shows from line 11 to end. " 
                             "If omitted, full file is shown (potentially truncated).",
                "type": "array", 
                "items": {"type": "integer"},
                # MODIFIED: Removed minItems and maxItems
            },
        },
        "required": ["command", "path"], 
    }
    
    file_edit_history: DefaultDict[Path, List[str]] = Field(default_factory=lambda: defaultdict(list), exclude=True) 
    _file_operator: FileOperator 

    def __init__(self, **data: Any):
        super().__init__(**data)
        if app_main_config.sandbox.use_sandbox: 
            self._file_operator = SandboxFileOperator()
            logger.info("DRIM AI StrReplaceEditor: Using SandboxFileOperator.")
        else:
            self._file_operator = LocalFileOperator() 
            logger.info("DRIM AI StrReplaceEditor: Using LocalFileOperator.")

    async def _initialize_operator_if_needed(self):
        if hasattr(self._file_operator, 'ensure_initialized'):
            await self._file_operator.ensure_initialized()

    async def execute( 
        self,
        *, 
        command: Command, # Changed to Command type
        path: str,
        file_text: Optional[str] = None, 
        view_range: Optional[List[int]] = None, 
        old_str: Optional[str] = None, 
        new_str: Optional[str] = None, 
        insert_line: Optional[int] = None, 
        **kwargs: Any, 
    ) -> str: 
        logger.info(f"DRIM AI StrReplaceEditor: Executing command '{command}' on path '{path}'.")
        await self._initialize_operator_if_needed()
        
        resolved_path = Path(path) 
        await self._validate_path(command, resolved_path) 

        result: ToolResult 
        try:
            if command == "view": 
                result = await self._view_operation(resolved_path, view_range) 
            elif command == "create": 
                if file_text is None: 
                    raise ToolError("Parameter `file_text` is required for command 'create'.")
                await self._file_operator.write_file(resolved_path, file_text) 
                self.file_edit_history[resolved_path].append(file_text) 
                result = ToolResult(output=f"DRIM AI: File created successfully at: {path}") 
            elif command == "str_replace": 
                if old_str is None: 
                    raise ToolError("Parameter `old_str` is required for command 'str_replace'.")
                result = await self._str_replace_operation(resolved_path, old_str, new_str) 
            elif command == "insert": 
                if insert_line is None: 
                    raise ToolError("Parameter `insert_line` is required for command 'insert'.")
                if new_str is None: 
                    raise ToolError("Parameter `new_str` is required for command 'insert'.")
                result = await self._insert_operation(resolved_path, insert_line, new_str) 
            elif command == "undo_edit": 
                result = await self._undo_edit_operation(resolved_path) 
            else:
                # This check is technically redundant if COMMAND_LITERAL is enforced by Pydantic
                # for the 'command' parameter during tool call parsing by the agent.
                # However, it's a good safeguard within the tool's direct execute method.
                valid_commands_list = list(get_args(COMMAND_LITERAL)) # Get args from the Literal type
                if command not in valid_commands_list:
                    raise ToolError(f"DRIM AI: Unrecognized command '{command}'. Allowed: {', '.join(valid_commands_list)}")
                # If Pydantic did its job, this 'else' branch might not even be reachable with an invalid command string.
                # For safety, assume an unknown command if it somehow gets here.
                result = ToolFailure(error=f"DRIM AI: Unhandled planning command: {command}")


        except ToolError as te:
            logger.error(f"DRIM AI StrReplaceEditor: Error executing command '{command}': {te.message}")
            return str(ToolFailure(error=te.message)) 
        except Exception as e:
            logger.exception(f"DRIM AI StrReplaceEditor: Unexpected error during command '{command}'.")
            return str(ToolFailure(error=f"Unexpected error: {str(e)}"))
            
        return str(result) 

    async def _validate_path(self, command: str, path_obj: Path) -> None: 
        if not path_obj.is_absolute(): 
            raise ToolError(f"DRIM AI: The path '{path_obj}' must be an absolute path.")

        if command != "create": 
            if not await self._file_operator.exists(path_obj): 
                raise ToolError(f"DRIM AI: The path '{path_obj}' does not exist. Please provide a valid path.") 
        
        is_dir = await self._file_operator.is_directory(path_obj) 
        if is_dir and command not in ["view"]: 
            raise ToolError(f"DRIM AI: The path '{path_obj}' is a directory. Command '{command}' can only be used on files (except 'view').")
        
        if command == "create": 
            if await self._file_operator.exists(path_obj): 
                raise ToolError(f"DRIM AI: File or directory already exists at '{path_obj}'. Cannot use 'create' to overwrite.")

    async def _view_operation(self, path: Path, view_range: Optional[List[int]] = None) -> CLIResult: 
        is_dir = await self._file_operator.is_directory(path) 
        if is_dir: 
            if view_range: 
                raise ToolError("DRIM AI: The `view_range` parameter is not allowed when `path` points to a directory.")
            return await self._view_directory_contents(path) 
        else: 
            return await self._view_file_contents(path, view_range) 

    async def _view_directory_contents(self, path: Path) -> CLIResult: 
        find_cmd = f"find \"{str(path)}\" -maxdepth 2 -not -path '*/\\.*'" 
        logger.debug(f"DRIM AI StrReplaceEditor: Viewing directory with command: {find_cmd}")
        try:
            return_code, stdout, stderr = await self._file_operator.run_command(find_cmd, timeout=30.0)
            if return_code == 0:
                output_str = ( 
                    f"DRIM AI: Directory listing for '{path}' (up to 2 levels deep, excluding hidden items):\n{stdout.strip()}"
                )
                return CLIResult(output=_maybe_truncate(output_str))
            else:
                err_msg = f"DRIM AI: Error listing directory '{path}'. Exit code: {return_code}. Stderr: {stderr.strip()}"
                logger.warning(err_msg)
                return CLIResult(error=err_msg, output=stdout.strip() if stdout else None)
        except Exception as e:
            logger.error(f"DRIM AI StrReplaceEditor: Exception viewing directory '{path}': {e}")
            return CLIResult(error=f"Failed to view directory '{path}': {str(e)}")

    async def _view_file_contents(self, path: Path, view_range: Optional[List[int]] = None) -> CLIResult: 
        file_content = await self._file_operator.read_file(path) 
        file_lines = file_content.splitlines() 
        n_lines_file = len(file_lines)
        
        start_line_idx = 0 
        end_line_idx = n_lines_file 

        if view_range: 
            if len(view_range) != 2 or not all(isinstance(i, int) for i in view_range): 
                raise ToolError("DRIM AI: Invalid `view_range`. Must be a list of two integers [start_line, end_line].")

            req_start_line, req_end_line = view_range[0], view_range[1] 

            if not (1 <= req_start_line <= n_lines_file) and n_lines_file > 0 : # Allow req_start_line = 1 even if n_lines_file is 0 for empty file
                 if n_lines_file == 0 and req_start_line == 1: # Special case for viewing empty file from line 1
                    pass
                 else:
                    raise ToolError(f"DRIM AI: Invalid `start_line` {req_start_line}. Must be between 1 and {n_lines_file}.")
            
            start_line_idx = req_start_line - 1 if n_lines_file > 0 else 0


            if req_end_line == -1: 
                end_line_idx = n_lines_file
            elif req_end_line < req_start_line and not (req_start_line ==1 and req_end_line == 0 and n_lines_file == 0): # Allow [1,0] for empty file
                raise ToolError(f"DRIM AI: Invalid `end_line` {req_end_line}. Must be >= `start_line` {req_start_line} (or -1 for end of file).")
            elif req_end_line > n_lines_file: 
                 raise ToolError(f"DRIM AI: Invalid `end_line` {req_end_line}. Exceeds total lines {n_lines_file}.")
            else:
                end_line_idx = req_end_line if req_end_line >= 0 else 0 # Ensure end_line_idx is not negative
        
        content_to_display_lines = file_lines[start_line_idx:end_line_idx]
        content_to_display = "\n".join(content_to_display_lines)
        
        display_init_line = start_line_idx + 1 
        return CLIResult(output=self._make_cli_output(content_to_display, str(path), init_line=display_init_line)) 

    async def _str_replace_operation(self, path: Path, old_str: str, new_str: Optional[str]) -> ToolResult: 
        file_content = await self._file_operator.read_file(path) 
        file_content_expanded = file_content.expandtabs() 
        old_str_expanded = old_str.expandtabs() 
        new_str_expanded = new_str.expandtabs() if new_str is not None else "" 

        occurrences = file_content_expanded.count(old_str_expanded) 
        if occurrences == 0: 
            raise ToolError(f"DRIM AI: No replacement performed. Target string (old_str) was not found verbatim in '{path}'. Ensure exact match including whitespace and case.")
        elif occurrences > 1: 
            lines_with_occurrence = [
                idx + 1 for idx, line in enumerate(file_content_expanded.splitlines()) if old_str_expanded in line
            ] 
            raise ToolError( 
                f"DRIM AI: No replacement performed. Target string (old_str) found multiple times in '{path}' "
                f"(e.g., on lines: {lines_with_occurrence[:5]}{'...' if len(lines_with_occurrence)>5 else ''}). "
                "Please provide more context in `old_str` to make it unique."
            )

        new_file_content = file_content_expanded.replace(old_str_expanded, new_str_expanded) 
        
        await self._file_operator.write_file(path, new_file_content) 
        self.file_edit_history[path].append(file_content) 

        replacement_char_offset = file_content_expanded.find(old_str_expanded)
        replacement_line_num = file_content_expanded[:replacement_char_offset].count('\n') + 1
        
        new_file_lines = new_file_content.splitlines()
        snippet_start_line_idx = max(0, replacement_line_num - 1 - SNIPPET_LINES)
        snippet_end_line_idx = min(len(new_file_lines), replacement_line_num -1 + new_str_expanded.count('\n') + SNIPPET_LINES +1)
        
        snippet_lines = new_file_lines[snippet_start_line_idx : snippet_end_line_idx]
        snippet = "\n".join(snippet_lines)
        
        success_msg = ( 
            f"DRIM AI: File '{path}' has been edited successfully (string replaced).\n"
            f"{self._make_cli_output(snippet, f'a snippet of {path}', init_line=snippet_start_line_idx + 1)}\n" 
            "Review the changes carefully, especially whitespace and indentation. Edit again if necessary." 
        )
        return ToolResult(output=success_msg) 

    async def _insert_operation(self, path: Path, insert_line: int, new_str: str) -> ToolResult: 
        file_content = await self._file_operator.read_file(path) 
        file_content_expanded = file_content.expandtabs() 
        new_str_expanded = new_str.expandtabs() 
        
        file_lines = file_content_expanded.splitlines()
        n_lines_file = len(file_lines)

        if not (0 <= insert_line <= n_lines_file): 
            raise ToolError(
                f"DRIM AI: Invalid `insert_line` {insert_line}. Must be between 0 (for beginning) and {n_lines_file} (for end)."
            )
        
        new_str_lines = new_str_expanded.splitlines()
        
        if insert_line == 0: 
            updated_file_lines = new_str_lines + file_lines
        elif insert_line == n_lines_file: 
            updated_file_lines = file_lines + new_str_lines
        else: 
            updated_file_lines = file_lines[:insert_line] + new_str_lines + file_lines[insert_line:]
            
        new_file_content = "\n".join(updated_file_lines)
        await self._file_operator.write_file(path, new_file_content) 
        self.file_edit_history[path].append(file_content) 

        snippet_actual_insert_line_idx = insert_line 
        snippet_start_idx = max(0, snippet_actual_insert_line_idx - SNIPPET_LINES)
        snippet_end_idx = min(len(updated_file_lines), snippet_actual_insert_line_idx + len(new_str_lines) + SNIPPET_LINES)
        
        snippet_display_lines = updated_file_lines[snippet_start_idx:snippet_end_idx]
        snippet_content = "\n".join(snippet_display_lines)
        
        success_msg = ( 
            f"DRIM AI: Text inserted into '{path}' after line {insert_line} (0-indexed if 0, else 1-indexed line number).\n"
            f"{self._make_cli_output(snippet_content, f'a snippet of {path}', init_line=snippet_start_idx + 1)}\n" 
            "Review the changes carefully, especially indentation. Edit again if necessary." 
        )
        return ToolResult(output=success_msg) 

    async def _undo_edit_operation(self, path: Path) -> ToolResult: 
        if not self.file_edit_history.get(path): 
            raise ToolError(f"DRIM AI: No edit history found for '{path}'. Cannot undo.")
        
        last_known_good_content = self.file_edit_history[path].pop() 
        await self._file_operator.write_file(path, last_known_good_content) 
        
        restored_view_msg = self._make_cli_output(last_known_good_content, str(path))
        return ToolResult(output=f"DRIM AI: Last edit to '{path}' undone successfully.\n{restored_view_msg}") 

    def _make_cli_output( 
        self, file_content_str: str, file_descriptor: str, init_line: int = 1, expand_tabs_ignored: bool = True
    ) -> str:
        truncated_content = _maybe_truncate(file_content_str) 
        
        lines = truncated_content.splitlines()
        numbered_lines = [
            f"{i + init_line:6d}\t{line}" for i, line in enumerate(lines) 
        ]
        formatted_content = "\n".join(numbered_lines)
        
        return ( 
            f"Content of {file_descriptor} (starting line {init_line}):\n"
            f"{formatted_content}" 
        )