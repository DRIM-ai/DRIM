from enum import Enum
from typing import Any, List, Literal, Optional, Union # [Source: 411]
from pydantic import BaseModel, Field, model_validator # Added model_validator for potential future use

class Role(str, Enum): # [Source: 411]
    """Message role options"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant" # 'model' in Gemini
    TOOL = "tool" # 'function' (response) in Gemini

ROLE_VALUES = tuple(role.value for role in Role) # [Source: 411]
ROLE_TYPE = Literal[ROLE_VALUES] # type: ignore [Source: 411]

class ToolChoice(str, Enum): # [Source: 411]
    """Tool choice options"""
    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required" # Note: Gemini's 'REQUIRED' is for a specific function. 'ANY' is closer for "some tool must be called".

TOOL_CHOICE_VALUES = tuple(choice.value for choice in ToolChoice) # [Source: 411]
TOOL_CHOICE_TYPE = Literal[TOOL_CHOICE_VALUES] # type: ignore [Source: 411]

class AgentState(str, Enum): # [Source: 412]
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

class Function(BaseModel): # [Source: 412]
    name: str
    arguments: str # Should be a JSON string

class ToolCall(BaseModel): # [Source: 412]
    """Represents a tool/function call in a message"""
    id: str # This ID is important for matching responses
    type: str = "function" # Gemini uses 'function_call' in its Part structure
    function: Function

class Message(BaseModel): # [Source: 412]
    """Represents a chat message in the conversation"""
    role: ROLE_TYPE = Field(...) # type: ignore
    content: Optional[Union[str, List[dict]]] = Field(default=None) # Allow multimodal content directly if needed
    tool_calls: Optional[List[ToolCall]] = Field(default=None)
    name: Optional[str] = Field(default=None) # For tool (function) responses, this is the function name
    tool_call_id: Optional[str] = Field(default=None) # For tool responses, to match the call
    base64_image: Optional[str] = Field(default=None) # For image data with user/assistant messages

    def __add__(self, other) -> List["Message"]: # [Source: 412]
        if isinstance(other, list):
            return [self] + other
        elif isinstance(other, Message):
            return [self, other]
        else:
            raise TypeError( # [Source: 413]
                f"unsupported operand type(s) for +: '{type(self).__name__}' and '{type(other).__name__}'"
            )

    def __radd__(self, other) -> List["Message"]: # [Source: 413]
        if isinstance(other, list):
            return other + [self]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(other).__name__}' and '{type(self).__name__}'"
            )

    def to_dict(self) -> dict: # [Source: 414]
        """Convert message to dictionary format, excluding None values for cleaner output."""
        message_data = {
            "role": self.role,
            "content": self.content,
            "tool_calls": [tc.model_dump() for tc in self.tool_calls] if self.tool_calls else None,
            "name": self.name,
            "tool_call_id": self.tool_call_id,
            "base64_image": self.base64_image,
        }
        return {k: v for k, v in message_data.items() if v is not None}


    @classmethod
    def user_message( # [Source: 414]
        cls, content: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create a user message"""
        return cls(role=Role.USER, content=content, base64_image=base64_image)

    @classmethod
    def system_message(cls, content: str) -> "Message": # [Source: 414]
        """Create a system message"""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def assistant_message( # [Source: 415]
        cls, content: Optional[str] = None, base64_image: Optional[str] = None, tool_calls: Optional[List[ToolCall]] = None
    ) -> "Message":
        """Create an assistant message"""
        return cls(role=Role.ASSISTANT, content=content, base64_image=base64_image, tool_calls=tool_calls)

    @classmethod
    def tool_message( # [Source: 415]
        cls,
        content: str, # This is the result of the tool execution
        name: str, # This is the name of the function that was called
        tool_call_id: str, # This links back to the specific ToolCall
        base64_image: Optional[str] = None, # If the tool result includes an image
    ) -> "Message":
        """Create a tool message (response from a tool)"""
        return cls(
            role=Role.TOOL,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            base64_image=base64_image,
        )

    @classmethod
    def from_tool_calls( # [Source: 416]
        cls,
        tool_calls: List[ToolCall], # Already ToolCall objects
        content: Union[str, List[str], None] = None, # Optional content alongside tool calls
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> "Message":
        """Create an assistant message that includes tool calls."""
        return cls(
            role=Role.ASSISTANT,
            content=content if content else None,
            tool_calls=tool_calls,
            base64_image=base64_image,
            **kwargs,
        )

class Memory(BaseModel): # [Source: 416]
    messages: List[Message] = Field(default_factory=list)
    max_messages: int = Field(default=100) # Max history length

    def add_message(self, message: Message) -> None: # [Source: 416]
        """Add a message to memory"""
        self.messages.append(message)
        if len(self.messages) > self.max_messages: # [Source: 416]
            self.messages = self.messages[-self.max_messages :]

    def add_messages(self, messages: List[Message]) -> None: # [Source: 417]
        """Add multiple messages to memory"""
        self.messages.extend(messages)
        if len(self.messages) > self.max_messages: # [Source: 417]
            self.messages = self.messages[-self.max_messages :]

    def clear(self) -> None: # [Source: 418]
        """Clear all messages"""
        self.messages.clear()

    def get_recent_messages(self, n: int) -> List[Message]: # [Source: 418]
        """Get n most recent messages"""
        if n <= 0:
            return []
        return self.messages[-n:]

    def to_dict_list(self) -> List[dict]: # [Source: 418]
        """Convert messages to list of dicts, useful for serialization or some LLM APIs"""
        return [msg.to_dict() for msg in self.messages]