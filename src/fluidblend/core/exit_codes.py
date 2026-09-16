"""Documented exit codes of the `fluidblend` CLI."""

OK = 0
FAILED = 1  # operation ran but failed in a known way (partial effects listed)
BLOCKED = 2  # missing permission, dependency or capability: controlled stop
CONFLICT = 3  # revision, lock or operation_id reused with different parameters
INVALID = 4  # invalid request or arguments (nothing was executed)
UNKNOWN_STATE = 5  # uncertain write state: `task reconcile` required
BUDGET_EXCEEDED = 6

DESCRIPTIONS = {
    OK: "success (or dry-run / idempotent replay)",
    FAILED: "known failure, partial effects listed in state/tasks/<task_id>/",
    BLOCKED: "missing permission, dependency or capability; user decision expected",
    CONFLICT: "revision conflict, lock held or operation_id reused with different parameters",
    INVALID: "invalid request or arguments; nothing was executed",
    UNKNOWN_STATE: "uncertain write state; run `fluidblend task reconcile`",
    BUDGET_EXCEEDED: "time/frame/disk budget exceeded; stopped before execution",
}
