class WorkflowError(ValueError):
    """Base error for invalid workflow documents."""


class WorkflowLoadError(WorkflowError):
    """Raised when a workflow file cannot be decoded or has an invalid root."""


class WorkflowValidationError(WorkflowError):
    """Raised by callers that require a valid workflow before execution."""
