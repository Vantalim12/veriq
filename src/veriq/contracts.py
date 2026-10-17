"""Validated policy contracts; no executable rule expressions."""

from datetime import date
import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
FieldName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$", max_length=128)]
Operator = Literal["eq", "ne", "gt", "ge", "lt", "le"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Predicate(Contract):
    field: FieldName
    operator: Operator
    value: int | float | str

    @model_validator(mode="after")
    def literal(self):
        if isinstance(self.value, (int, float)):
            if abs(self.value) > 2**53 or not math.isfinite(self.value):
                raise ValueError("numeric literals must be finite and within the safe-number range")
        elif self.operator not in ("eq", "ne"):
            raise ValueError("strings support only eq and ne")
        return self


class Approval(Contract):
    reviewer: Annotated[str, Field(min_length=1, max_length=256)]
    reviewed_on: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]

    @model_validator(mode="after")
    def review_date(self):
        date.fromisoformat(self.reviewed_on)
        if not self.reviewer.strip():
            raise ValueError("reviewer must not be blank")
        return self


class Scope(Contract):
    source_node_id: Identifier
    target_node_id: Identifier


class Rule(Contract):
    id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=512)]
    type: Literal["must_pass_through", "forbid_path", "require_condition"]
    severity: Literal["low", "medium", "high", "critical"]
    approved: Approval
    applicable: bool = True
    not_applicable_reason: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    scope: Scope | None = None
    gate_node_id: Identifier | None = None
    node_id: Identifier | None = None
    condition: Predicate | None = None
    when: Predicate | None = None
    source: dict[str, Any] | None = None

    @model_validator(mode="after")
    def rule_shape(self):
        if not self.applicable:
            if not self.not_applicable_reason or not self.not_applicable_reason.strip():
                raise ValueError("an explicit applicability exclusion needs a reviewed reason")
            return self
        if self.not_applicable_reason is not None:
            raise ValueError("an applicable rule cannot have an exclusion reason")
        if self.type == "require_condition":
            if self.node_id is None or self.condition is None:
                raise ValueError("require_condition needs node_id and condition")
            if self.scope is not None or self.gate_node_id is not None or self.when is not None:
                raise ValueError("require_condition does not accept path scope, gate, or when")
        else:
            if self.scope is None:
                raise ValueError("path rules need source/target scope")
            if self.node_id is not None or self.condition is not None:
                raise ValueError("path rules do not accept node_id or condition")
            if self.scope.source_node_id == self.scope.target_node_id:
                raise ValueError("path source and target must differ")
            if self.type == "must_pass_through" and self.gate_node_id is None:
                raise ValueError("must_pass_through needs a reviewed gate_node_id")
            if self.gate_node_id in (self.scope.source_node_id, self.scope.target_node_id):
                raise ValueError("gate must be distinct from source and target")
        return self


class Policy(Contract):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    policy_id: Identifier
    policy_version: Annotated[int, Field(ge=1)]
    fields: dict[FieldName, Literal["number", "string"]] = Field(default_factory=dict)
    source_document: dict[str, Any] | None = None
    rules: Annotated[list[Rule], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def policy_integrity(self):
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("rule IDs must be unique")
        for rule in self.rules:
            for predicate in (rule.when, rule.condition):
                if predicate is not None:
                    kind = "string" if isinstance(predicate.value, str) else "number"
                    if self.fields.get(predicate.field) != kind:
                        raise ValueError("predicate field must have a matching declared type")
        return self


class ExportNode(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=256)]
    type: Annotated[str, Field(min_length=1, max_length=256)]
    typeVersion: int | float
    parameters: dict[str, Any]
    disabled: bool = False

    @model_validator(mode="after")
    def metadata(self):
        if self.typeVersion <= 0 or (isinstance(self.typeVersion, float) and not math.isfinite(self.typeVersion)):
            raise ValueError("invalid node version")
        if re.search(r"[\x00-\x1f\x7f]", self.name):
            raise ValueError("node names cannot contain control characters")
        return self
