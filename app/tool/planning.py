# tool/planning.py [Source: 627]
from typing import Dict, List, Literal, Optional, Any, get_args
from pydantic import Field 

from app.exceptions import ToolError 
from app.tool.base import BaseTool, ToolResult, CLIResult, ToolFailure 
from app.logger import logger

_PLANNING_TOOL_DESCRIPTION_DRIM_AI = """\
A DRIM AI tool for creating, managing, and tracking structured plans to solve complex tasks.
Use this tool to:
- `create`: Define a new plan with a title and list of steps.
- `update`: Modify an existing plan's title or steps.
- `list`: View all current plans and their overall progress.
- `get`: Retrieve and display the details of a specific plan (or the active plan).
- `set_active`: Designate a plan as the current one to work on.
- `mark_step`: Update the status (e.g., not_started, in_progress, completed, blocked) and add notes to a specific step in a plan.
- `delete`: Remove a plan.
This tool helps maintain an organized approach to multi-step problem-solving for DRIM AI.
""" # Adapted from [Source: 627]

PLAN_STEP_STATUSES = Literal["not_started", "in_progress", "completed", "blocked"] # [Source: 634]
COMMAND_LITERAL = Literal["create", "update", "list", "get", "set_active", "mark_step", "delete"] # [Source: 629]

class PlanningTool(BaseTool): # [Source: 628]
    name: str = "planning_manager" 
    description: str = _PLANNING_TOOL_DESCRIPTION_DRIM_AI 
    parameters: Dict[str, Any] = { 
        "type": "object",
        "properties": {
            "command": { 
                "description": "The planning command to execute. Options: create, update, list, get, set_active, mark_step, delete.",
                "enum": get_args(COMMAND_LITERAL), 
                "type": "string",
            },
            "plan_id": { 
                "description": "Unique identifier for the plan. Required for most commands except 'list'. If omitted for 'get' or 'mark_step', uses the active plan.",
                "type": "string",
            },
            "title": { 
                "description": "Title for the plan. Required for 'create', optional for 'update'.",
                "type": "string",
            },
            "steps": { 
                "description": "List of plan steps (strings). Required for 'create', optional for 'update'.",
                "type": "array", "items": {"type": "string"},
            },
            "step_index": { 
                "description": "0-based index of the step to update. Required for 'mark_step'.",
                "type": "integer",
            },
            "step_status": { 
                "description": "Status to set for a step. Used with 'mark_step'. Options: not_started, in_progress, completed, blocked.",
                "enum": get_args(PLAN_STEP_STATUSES), 
                "type": "string",
            },
            "step_notes": { 
                "description": "Additional notes for a step. Optional for 'mark_step'.",
                "type": "string",
            },
        },
        "required": ["command"], 
        "additionalProperties": False, 
    }

    plans: Dict[str, Dict[str, Any]] = Field(default_factory=dict) 
    # MODIFIED: Renamed field to remove leading underscore
    active_plan_id_internal: Optional[str] = Field(default=None, exclude=True) 

    async def execute( 
        self,
        *, 
        command: COMMAND_LITERAL,
        plan_id: Optional[str] = None, 
        title: Optional[str] = None, 
        steps: Optional[List[str]] = None, 
        step_index: Optional[int] = None, 
        step_status: Optional[PLAN_STEP_STATUSES] = None, 
        step_notes: Optional[str] = None, 
        **kwargs: Any, 
    ) -> ToolResult: 
        logger.info(f"DRIM AI PlanningTool: Executing command '{command}' with plan_id '{plan_id}'.")
        try:
            if command == "create": 
                return self._create_plan_op(plan_id, title, steps)
            elif command == "update": 
                return self._update_plan_op(plan_id, title, steps)
            elif command == "list": 
                return self._list_plans_op()
            elif command == "get": 
                return self._get_plan_op(plan_id)
            elif command == "set_active": 
                return self._set_active_plan_op(plan_id)
            elif command == "mark_step": 
                return self._mark_step_op(plan_id, step_index, step_status, step_notes)
            elif command == "delete": 
                return self._delete_plan_op(plan_id)
            else:
                raise ToolError(f"DRIM AI: Unrecognized planning command: {command}") 
        except ToolError as te:
            logger.error(f"DRIM AI PlanningTool: Error executing command '{command}': {te.message}")
            return ToolFailure(error=te.message)
        except Exception as e:
            logger.exception(f"DRIM AI PlanningTool: Unexpected error during command '{command}'.")
            return ToolFailure(error=f"Unexpected error in PlanningTool: {str(e)}")

    def _get_effective_plan_id(self, plan_id: Optional[str], command_requires_id: bool = True) -> str:
        # MODIFIED: Use renamed field
        pid_to_use = plan_id or self.active_plan_id_internal 
        if not pid_to_use:
            if command_requires_id:
                 raise ToolError("DRIM AI: No `plan_id` provided and no plan is currently active. Please specify a `plan_id` or use 'set_active'.")
            raise ToolError("DRIM AI: No `plan_id` could be determined (none provided, none active).")

        if pid_to_use not in self.plans: 
            raise ToolError(f"DRIM AI: No plan found with ID: '{pid_to_use}'. Available plans: {list(self.plans.keys()) if self.plans else 'None'}")
        return pid_to_use 

    def _create_plan_op(self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]) -> ToolResult: 
        if not plan_id: raise ToolError("DRIM AI: `plan_id` is required for 'create' command.") 
        if plan_id in self.plans: 
            raise ToolError(f"DRIM AI: Plan with ID '{plan_id}' already exists. Use 'update' or choose a different ID.")
        if not title: raise ToolError("DRIM AI: `title` is required for 'create' command.") 
        if not steps or not isinstance(steps, list) or not all(isinstance(step, str) for step in steps): 
            raise ToolError("DRIM AI: `steps` must be a non-empty list of strings for 'create' command.")

        plan_data: Dict[str, Any] = { 
            "plan_id": plan_id, "title": title, "steps": steps,
            "step_statuses": ["not_started"] * len(steps), 
            "step_notes": [""] * len(steps), 
        }
        self.plans[plan_id] = plan_data
        # MODIFIED: Use renamed field
        self.active_plan_id_internal = plan_id 
        msg = f"DRIM AI: Plan '{title}' created successfully with ID: {plan_id}. It is now the active plan.\n\n{self._format_plan_for_display(plan_data)}"
        return ToolResult(output=msg) 

    def _update_plan_op(self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]) -> ToolResult: 
        pid = self._get_effective_plan_id(plan_id) 
        plan = self.plans[pid]

        updated = False
        if title is not None: 
            plan["title"] = title
            updated = True
        if steps is not None: 
            if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps): 
                raise ToolError("DRIM AI: If provided, `steps` must be a list of strings for 'update' command.")
            old_steps = plan["steps"]
            old_statuses = plan["step_statuses"]
            old_notes = plan["step_notes"]
            new_statuses = ["not_started"] * len(steps)
            new_notes = [""] * len(steps)
            
            for i_new, new_step_text in enumerate(steps):
                try:
                    i_old = old_steps.index(new_step_text)
                    new_statuses[i_new] = old_statuses[i_old]
                    new_notes[i_new] = old_notes[i_old]
                except ValueError: 
                    pass 

            plan["steps"] = steps
            plan["step_statuses"] = new_statuses
            plan["step_notes"] = new_notes
            updated = True
        
        if not updated:
            return ToolResult(output=f"DRIM AI: No changes provided for plan '{pid}'. Plan remains unchanged.\n\n{self._format_plan_for_display(plan)}")

        msg = f"DRIM AI: Plan '{pid}' updated successfully.\n\n{self._format_plan_for_display(plan)}"
        return ToolResult(output=msg) 

    def _list_plans_op(self) -> ToolResult: 
        if not self.plans: 
            return ToolResult(output="DRIM AI: No plans available. Use 'create' command to make one.")
        
        output_lines = ["DRIM AI: Available plans:"]
        for plan_id_key, plan_val in self.plans.items(): 
            # MODIFIED: Use renamed field
            active_marker = " (ACTIVE)" if plan_id_key == self.active_plan_id_internal else "" 
            completed_count = sum(1 for s in plan_val["step_statuses"] if s == "completed") 
            total_steps = len(plan_val["steps"]) 
            output_lines.append(f"- ID: {plan_id_key}{active_marker}, Title: \"{plan_val['title']}\" ({completed_count}/{total_steps} steps completed)")
        return ToolResult(output="\n".join(output_lines)) 

    def _get_plan_op(self, plan_id: Optional[str]) -> ToolResult: 
        requires_id_for_get = plan_id is not None 
        pid_to_get = self._get_effective_plan_id(plan_id, command_requires_id=requires_id_for_get) 
        plan = self.plans[pid_to_get]
        return ToolResult(output=self._format_plan_for_display(plan)) 

    def _set_active_plan_op(self, plan_id: Optional[str]) -> ToolResult: 
        if not plan_id: raise ToolError("DRIM AI: `plan_id` is required for 'set_active' command.") 
        if plan_id not in self.plans: raise ToolError(f"DRIM AI: No plan found with ID: '{plan_id}'.") 
        
        # MODIFIED: Use renamed field
        self.active_plan_id_internal = plan_id 
        msg = f"DRIM AI: Plan '{plan_id}' (Title: \"{self.plans[plan_id]['title']}\") is now the active plan.\n\n{self._format_plan_for_display(self.plans[plan_id])}"
        return ToolResult(output=msg) 

    def _mark_step_op(self, plan_id: Optional[str], step_idx: Optional[int], status_val: Optional[PLAN_STEP_STATUSES], notes: Optional[str]) -> ToolResult: 
        requires_id_for_mark = plan_id is not None
        pid_to_mark = self._get_effective_plan_id(plan_id, command_requires_id=requires_id_for_mark) 
        plan = self.plans[pid_to_mark]

        if step_idx is None: raise ToolError("DRIM AI: `step_index` (0-based) is required for 'mark_step'.") 
        if not (0 <= step_idx < len(plan["steps"])): 
            raise ToolError(f"DRIM AI: Invalid `step_index` {step_idx}. Must be between 0 and {len(plan['steps'])-1} for plan '{pid_to_mark}'.")

        updated = False
        if status_val: 
            plan["step_statuses"][step_idx] = status_val 
            updated = True
        if notes is not None: 
            plan["step_notes"][step_idx] = notes
            updated = True
        
        if not updated:
            return ToolResult(output=f"DRIM AI: No changes specified for step {step_idx} in plan '{pid_to_mark}'.")

        msg = f"DRIM AI: Step {step_idx} in plan '{pid_to_mark}' updated.\n\n{self._format_plan_for_display(plan)}"
        return ToolResult(output=msg) 

    def _delete_plan_op(self, plan_id: Optional[str]) -> ToolResult: 
        if not plan_id: raise ToolError("DRIM AI: `plan_id` is required for 'delete' command.") 
        if plan_id not in self.plans: raise ToolError(f"DRIM AI: No plan found with ID: '{plan_id}' to delete.") 
        
        deleted_plan_title = self.plans[plan_id]["title"]
        del self.plans[plan_id] 
        # MODIFIED: Use renamed field
        if self.active_plan_id_internal == plan_id: 
            self.active_plan_id_internal = None
        return ToolResult(output=f"DRIM AI: Plan '{deleted_plan_title}' (ID: {plan_id}) has been deleted.") 

    def _format_plan_for_display(self, plan_data: Dict[str, Any]) -> str: 
        lines = []
        lines.append(f"Plan Details for ID: {plan_data['plan_id']} (Title: \"{plan_data['title']}\")") 
        # MODIFIED: Use renamed field
        if plan_data['plan_id'] == self.active_plan_id_internal:
            lines[0] += " (ACTIVE)"
        lines.append("=" * len(lines[0]))

        total = len(plan_data["steps"]) 
        completed = sum(1 for s in plan_data["step_statuses"] if s == "completed") 
        in_prog = sum(1 for s in plan_data["step_statuses"] if s == "in_progress") 
        blocked = sum(1 for s in plan_data["step_statuses"] if s == "blocked") 
        not_started = sum(1 for s in plan_data["step_statuses"] if s == "not_started") 
        
        progress_percent = (completed / total * 100) if total > 0 else 0 
        lines.append(f"Progress: {completed}/{total} steps completed ({progress_percent:.1f}%).") 
        lines.append(f"Status Breakdown: {completed} completed, {in_prog} in progress, {blocked} blocked, {not_started} not started.") 
        lines.append("\nSteps:") 

        status_symbols = {"not_started": "[ ]", "in_progress": "[->]", "completed": "[X]", "blocked": "[!]" } 
        
        for i, (step_text, current_step_status, note_text) in enumerate(zip(plan_data["steps"], plan_data["step_statuses"], plan_data["step_notes"])): 
            symbol = status_symbols.get(current_step_status, "[?]")
            lines.append(f"{i:2d}. {symbol} {step_text}") 
            if note_text: 
                lines.append(f"    Notes: {note_text}")
        return "\n".join(lines)