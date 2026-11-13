"""Core domain enums and exceptions."""

from .errors import (
    AgentExecutionError,
    ConfigError,
    HITLError,
    MFAError,
    PageIndexError,
    VirtualFileSystemError,
    WorkflowError,
)
from .types import (
    AgentResultStatus,
    AgentRole,
    EvidenceKind,
    ReviewDecision,
    RunMode,
    ToolName,
    TrustLevel,
    WorkflowStage,
    WorkflowStatus,
)

__all__ = [
    "AgentExecutionError",
    "AgentResultStatus",
    "AgentRole",
    "ConfigError",
    "EvidenceKind",
    "HITLError",
    "MFAError",
    "PageIndexError",
    "ReviewDecision",
    "RunMode",
    "ToolName",
    "TrustLevel",
    "VirtualFileSystemError",
    "WorkflowError",
    "WorkflowStage",
    "WorkflowStatus",
]
