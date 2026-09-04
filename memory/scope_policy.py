"""Scope and tenant-isolation rules for memory reads and writes."""

from __future__ import annotations

from dataclasses import dataclass

from memory.model import Scope, ScopeType


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Backend-provided identity and operation context."""

    user_id: str | None = None
    case_id: str | None = None
    task_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("user_id", "case_id", "task_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when provided")
        if self.case_id and not self.user_id:
            raise ValueError("case_id requires user_id")
        if self.task_id and not self.case_id:
            raise ValueError("task_id requires case_id")

    def scope(self, scope_type: ScopeType) -> Scope:
        if scope_type is ScopeType.SYSTEM:
            return Scope(ScopeType.SYSTEM, "system")
        if scope_type is ScopeType.USER and self.user_id:
            return Scope(ScopeType.USER, self.user_id)
        if scope_type is ScopeType.CASE and self.case_id:
            return Scope(ScopeType.CASE, self.case_id, self.user_id)
        if scope_type is ScopeType.TASK and self.task_id:
            return Scope(ScopeType.TASK, self.task_id, self.case_id)
        raise ValueError(f"{scope_type.value} scope is not present in the access context")


def _node_set(scope_type: ScopeType, scope_id: str) -> str:
    return f"sudarshan:scope:{scope_type.value}:{scope_id}"


def accessible_node_sets(context: AccessContext) -> list[str]:
    """Return the only node sets a request is allowed to read."""

    result = [_node_set(ScopeType.SYSTEM, "system")]
    if context.user_id:
        result.append(_node_set(ScopeType.USER, context.user_id))
    if context.case_id:
        result.append(_node_set(ScopeType.CASE, context.case_id))
    if context.task_id:
        result.append(_node_set(ScopeType.TASK, context.task_id))
    return result


def node_sets_for_scope(scope: Scope) -> list[str]:
    """Tag a write with its exact scope.

    Parent scopes are included at read time. Keeping them off child writes is
    important: a user-level query must not accidentally retrieve every case
    and task owned by that user.
    """

    if scope.scope_type is ScopeType.TASK and not scope.parent_id:
        raise ValueError("task scope requires a case parent_id")
    return [_node_set(scope.scope_type, scope.scope_id)]
