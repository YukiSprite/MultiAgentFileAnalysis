"""Shared domain enums."""

from enum import StrEnum


class RunMode(StrEnum):
    """How the workflow is expected to run."""

    INTERACTIVE = "interactive"
    BATCH = "batch"
    DRY_RUN = "dry_run"


class WorkflowStatus(StrEnum):
    """Lifecycle status for a diagnosis workflow."""

    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FAILED = "failed"


class WorkflowStage(StrEnum):
    """Named graph stages."""

    INTAKE = "intake"
    EXPLORE = "explore"
    REASON = "reason"
    REQUEST_HUMAN_INPUT = "request_human_input"
    CRITIQUE = "critique"
    FINALIZE = "finalize"


class AgentRole(StrEnum):
    """Supported agent roles."""

    EXPLORER = "explorer"
    REASONER = "reasoner"
    CRITIC = "critic"


class AgentResultStatus(StrEnum):
    """Result states emitted by an agent step."""

    SUCCEEDED = "succeeded"
    NEEDS_MORE_CONTEXT = "needs_more_context"
    REJECTED = "rejected"
    FAILED = "failed"


class ReviewDecision(StrEnum):
    """Critic review decisions."""

    APPROVED = "approved"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class TrustLevel(StrEnum):
    """How far a supplied statement can be trusted.

    Only DOCUMENTARY material may support documented rules. USER_ASSERTED
    material describes the user's own environment: it can support a conditional
    conclusion but can never establish or override rule meaning. MODEL_DIGEST is
    model-written prose about evidence and is not evidence at all.
    """

    DOCUMENTARY = "documentary"
    USER_ASSERTED = "user_asserted"
    MODEL_DIGEST = "model_digest"


class EvidenceKind(StrEnum):
    """Evidence categories stored in shared state."""

    RULE = "rule"
    CONFIG_REFERENCE = "config_reference"
    LOG_INTERPRETATION = "log_interpretation"
    USER_RUNTIME_CONTEXT = "user_runtime_context"


class ToolName(StrEnum):
    """Virtual browsing tools available to Explorer."""

    UNKNOWN = "unknown"
    PWD = "pwd"
    CD = "cd"
    LS = "ls"
    FIND = "find"
    STAT = "stat"
    CAT = "cat"
    HEAD = "head"
    TAIL = "tail"
    GREP = "grep"
    SEARCH = "search"
    V_LS = "v_ls"
    V_CAT = "v_cat"
    V_GREP = "v_grep"
    V_SEARCH = "v_search"
    V_READ_RANGE = "v_read_range"
