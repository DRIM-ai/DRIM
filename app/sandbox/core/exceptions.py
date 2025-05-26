# [Source: 330]
"""Exception classes for the sandbox system.
This module defines custom exceptions used throughout the sandbox system to
handle various error conditions in a structured way.
"""

class SandboxError(Exception): # [Source: 330]
    """Base exception for sandbox-related errors."""
    pass

class SandboxTimeoutError(SandboxError): # [Source: 330]
    """Exception raised when a sandbox operation times out."""
    pass

class SandboxResourceError(SandboxError): # [Source: 330]
    """Exception raised for resource-related errors."""
    pass

# Role in the System (Updated for DRIM AI)
# As part of the sandbox subsystem for DRIM AI, this script defines custom exceptions
# for handling errors within the secure execution environment. [Source: 328, 331] This allows for
# structured error reporting and management when DRIM AI executes code or commands
# in the sandbox. [Source: 329, 332]