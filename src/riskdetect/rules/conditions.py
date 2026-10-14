"""The small, safe language rules are written in.

A condition is either a comparison on one feature, or ``all`` / ``any`` of other
conditions. Rules cannot run code, so a bad rules file can never harm the system.

A comparison on a missing (unknown) value is always false: "we can't tell" must
never count as evidence against someone.
"""

import operator
from collections.abc import Callable, Mapping
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

Op = Literal[">", ">=", "<", "<=", "==", "!="]
_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Comparison(_Model):
    feature: str = Field(min_length=1)
    op: Op
    value: float

    def evaluate(self, values: Mapping[str, Any]) -> bool:
        actual = values.get(self.feature)
        if actual is None:
            return False
        return _OPERATORS[self.op](float(actual), self.value)

    def features(self) -> set[str]:
        return {self.feature}


class Group(_Model):
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Group":
        if (self.all is None) == (self.any is None):
            raise ValueError("a group needs exactly one of 'all' or 'any'")
        if not (self.all or self.any):
            raise ValueError("a group cannot be empty")
        return self

    def evaluate(self, values: Mapping[str, Any]) -> bool:
        if self.all is not None:
            return all(c.evaluate(values) for c in self.all)
        assert self.any is not None
        return any(c.evaluate(values) for c in self.any)

    def features(self) -> set[str]:
        parts = self.all if self.all is not None else self.any or []
        return set().union(*(c.features() for c in parts))


Condition = Union[Comparison, Group]  # noqa: UP007 (pydantic needs the forward-ref union)
Group.model_rebuild()
