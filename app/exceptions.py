class ToolError(Exception): # [Source: 139]
    """Raised when a tool encounters an error."""
    def __init__(self, message: str): # [Source: 139]
        self.message = message
        super().__init__(message)

class DRIMAIFrameworkError(Exception): # Renamed from OpenManusError [Source: 139]
    """Base exception for all DRIM AI framework errors."""
    pass

class TokenLimitExceeded(DRIMAIFrameworkError): # [Source: 139]
    """Exception raised when the token limit is exceeded."""
    pass

# You can add more DRIM AI specific exceptions here as needed.
class LLMConnectionError(DRIMAIFrameworkError):
    """Raised when there's an issue connecting to the LLM service."""
    pass

class LLMResponseError(DRIMAIFrameworkError):
    """Raised when the LLM service returns an unexpected or error response."""
    pass

class ConfigurationError(DRIMAIFrameworkError):
    """Raised for configuration-related issues."""
    pass