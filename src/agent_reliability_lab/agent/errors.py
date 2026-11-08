"""Safe failure codes, with no exception text copied into persisted state."""


class ModelFailure(Exception):
    def __init__(self, code: str, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class BudgetExceeded(Exception):
    pass


class ExecutionBusy(Exception):
    pass


class ContextMismatch(Exception):
    pass


class ExecutionInterrupted(BaseException):
    """Trusted test/host interruption seam; never exposed as a model tool."""
