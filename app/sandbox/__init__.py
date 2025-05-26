# [Source: 310]
"""
DRIM AI Docker Sandbox Module
Provides a secure containerized execution environment with resource limits
and isolation for DRIM AI to run untrusted code or commands safely. [Source: 310]
"""
from app.sandbox.client import ( # [Source: 310]
    BaseSandboxClient,
    LocalSandboxClient,
    create_sandbox_client,
    SANDBOX_CLIENT, # Export the global client instance
)
from app.sandbox.core.exceptions import ( # [Source: 310]
    SandboxError,
    SandboxResourceError,
    SandboxTimeoutError,
)
from app.sandbox.core.manager import SandboxManager # [Source: 310]
from app.sandbox.core.sandbox import DockerSandbox # [Source: 310]

__all__ = [ # [Source: 310]
    "DockerSandbox",
    "SandboxManager",
    "BaseSandboxClient",
    "LocalSandboxClient",
    "create_sandbox_client",
    "SANDBOX_CLIENT",
    "SandboxError",
    "SandboxTimeoutError",
    "SandboxResourceError",
]

# Role in the System (Updated for DRIM AI)
# As part of the DRIM AI sandbox subsystem, this module makes key classes and instances
# available for creating and managing secure execution environments. [Source: 311] The sandbox is
# critical for DRIM AI's security, preventing potentially harmful operations while
# still allowing the agent to perform useful tasks that involve code execution. [Source: 312, 313]