import multiprocessing
import sys
from io import StringIO
from typing import Dict, Any 

from app.tool.base import BaseTool, ToolResult 
from app.logger import logger

class PythonExecute(BaseTool): 
    name: str = "python_execute" 
    description: str = ( 
        "Executes a given Python code string in a separate process. "
        "Captures and returns standard output (print statements). "
        "Does not capture function return values directly; use print() for outputs. "
        "Limited by a timeout."
    )
    parameters: dict = { 
        "type": "object",
        "properties": {
            "code": { 
                "type": "string",
                "description": "The Python code string to execute.", 
            },
            "timeout": { 
                 "type": "integer",
                 "description": "(Optional) Execution timeout in seconds. Default handled by tool if not provided.",
                 # "default": 10, # MODIFIED: Removed this line
            }
        },
        "required": ["code"], 
    }

    def _run_code_in_process(self, code: str, result_queue: multiprocessing.Queue, safe_globals: dict) -> None: 
        original_stdout = sys.stdout
        captured_output = StringIO() 
        sys.stdout = captured_output 
        
        process_result: Dict[str, Any] = {"output": None, "error": None}
        try:
            exec(code, safe_globals, safe_globals) 
            process_result["output"] = captured_output.getvalue()
        except Exception as e: 
            logger.warning(f"DRIM AI PythonExecute: Error during code execution in subprocess: {e}")
            process_result["error"] = str(e)
            process_result["output"] = captured_output.getvalue() 
        finally:
            sys.stdout = original_stdout 
            try:
                result_queue.put(process_result)
            except Exception as q_err: 
                logger.error(f"DRIM AI PythonExecute: Error putting result to queue: {q_err}")


    async def execute(self, code: str, timeout: int = 10) -> ToolResult: 
        logger.info(f"DRIM AI PythonExecute: Attempting to execute Python code (Timeout: {timeout}s). Code snippet: {code[:100]}...")

        if isinstance(__builtins__, dict): 
            safe_globals = {"__builtins__": __builtins__}
        else:
            safe_globals = {"__builtins__": __builtins__.__dict__.copy()} 

        result_queue = multiprocessing.Queue()

        process = multiprocessing.Process(
            target=self._run_code_in_process, args=(code, result_queue, safe_globals) 
        )
        
        process.start() 
        process.join(timeout) 

        if process.is_alive(): 
            logger.warning(f"DRIM AI PythonExecute: Process timed out after {timeout} seconds. Terminating.")
            process.terminate() 
            process.join(1) 
            if process.is_alive(): 
                logger.error("DRIM AI PythonExecute: Process could not be terminated. Attempting kill.")
                process.kill() 
                process.join(1)
            return ToolResult(error=f"Execution timed out after {timeout} seconds and was terminated.") 

        try:
            result_data = result_queue.get(timeout=1) 
            output = result_data.get("output")
            error = result_data.get("error")
            
            if error:
                logger.warning(f"DRIM AI PythonExecute: Code execution resulted in an error: {error}")
                return ToolResult(output=output if output else None, error=error)
            
            logger.info(f"DRIM AI PythonExecute: Code executed successfully. Output snippet: {str(output)[:100] if output else 'No output.'}")
            return ToolResult(output=output if output else "Code executed with no print output.")
            
        except multiprocessing.queues.Empty: # type: ignore
            logger.error("DRIM AI PythonExecute: Result queue was empty after process join. Process might have crashed or timed out before producing result.")
            return ToolResult(error="Process finished or was terminated without providing a result to the queue.")
        except Exception as e:
            logger.error(f"DRIM AI PythonExecute: Error retrieving result from queue: {e}")
            return ToolResult(error=f"Error retrieving execution result: {e}")
        finally:
            result_queue.close()
            result_queue.join_thread() 


async def _test_python_execute():
    tool = PythonExecute()
    code1 = "print('Hello from DRIM AI PythonExecute!')\na=1+1\nprint(f'Result of 1+1 is {a}')"
    result1 = await tool.execute(code=code1)
    print(f"Test 1 Output: {result1.output}, Error: {result1.error}")
    # ... (rest of test code if you want to keep it) ...

if __name__ == "__main__":
    import asyncio # Ensure asyncio is imported for the test runner
    asyncio.run(_test_python_execute())