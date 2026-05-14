"""Project-level exception boundaries."""


class MFAError(Exception):
    """Base exception for MultiAgentFileAnalysis."""


class ConfigError(MFAError):
    """Raised when application configuration is invalid."""


class PageIndexError(MFAError):
    """Raised when the static page index cannot be loaded or resolved."""


class VirtualFileSystemError(MFAError):
    """Raised by the controlled virtual file-system layer."""


class AgentExecutionError(MFAError):
    """Raised when an agent step cannot produce a valid result."""


class WorkflowError(MFAError):
    """Raised by graph orchestration and state transitions."""


class HITLError(MFAError):
    """Raised by human-in-the-loop suspension or resume handling."""
