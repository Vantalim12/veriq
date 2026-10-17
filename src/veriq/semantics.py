"""The deliberately small, version-pinned n8n model. Nothing is evaluated."""

import math
import operator
import re
import sys

from .contracts import Predicate

ADAPTER_VERSION = "n8n-v1-bounded-1"
SUPPORTED = {"n8n-nodes-base.webhook": 1, "n8n-nodes-base.noOp": 1,
             "n8n-nodes-base.if": 1, "n8n-nodes-base.wait": 1}
OPERATIONS = {"equal": "eq", "notEqual": "ne", "larger": "gt", "largerEqual": "ge", "smaller": "lt", "smallerEqual": "le"}
COMPARE = {"eq": operator.eq, "ne": operator.ne, "gt": operator.gt,
           "ge": operator.ge, "lt": operator.lt, "le": operator.le}
FIELD_REF = re.compile(r"^=\{\{\s*\$json\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}\}$")


class UnknownSemantics(ValueError):
    pass


def node_problem(node):
    if SUPPORTED.get(node.type) != node.typeVersion:
        return "node type/version is outside the compatibility list"
    if node.disabled:
        return "disabled-node routing is not modeled"
    extras = node.model_extra or {}
    if any(extras.get(key, False) is not False for key in ("continueOnFail", "alwaysOutputData", "executeOnce", "retryOnFail")):
        return "node execution/error options are not modeled"
    if extras.get("onError", "stopWorkflow") != "stopWorkflow":
        return "non-default error routing is not modeled"
    if node.type.endswith(".noOp") and node.parameters:
        return "unexpected No Operation parameters"
    if node.type.endswith(".wait"):
        params = node.parameters
        options = params.get("options", {})
        if (params.get("resume") != "webhook" or not isinstance(options, dict)
                or options.get("limitWaitTime", False) is not False
                or params.get("limitWaitTime", False) is not False):
            return "only webhook-resumed Wait without a timeout is modeled"
    return None


def read_condition(node, fields):
    problem = node_problem(node)
    if problem or node.type != "n8n-nodes-base.if":
        raise UnknownSemantics(problem or "condition rule requires an IF v1 node")
    params = node.parameters
    if set(params) - {"conditions", "combineOperation"} or params.get("combineOperation", "all") not in ("all", "any"):
        raise UnknownSemantics("unsupported IF options")
    groups = params.get("conditions")
    if not isinstance(groups, dict) or set(groups) - {"number", "string", "boolean", "dateTime"}:
        raise UnknownSemantics("missing IF conditions")
    active = [(kind, items) for kind, items in groups.items() if items != []]
    if len(active) != 1 or active[0][0] not in ("number", "string"):
        raise UnknownSemantics("only one numeric or string IF condition is supported")
    kind, items = active[0]
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise UnknownSemantics("only one IF comparison is supported")
    condition = items[0]
    if set(condition) != {"value1", "operation", "value2"}:
        raise UnknownSemantics("unsupported IF comparison shape")
    operation = OPERATIONS.get(condition["operation"]) if isinstance(condition["operation"], str) else None
    if not operation or (kind == "string" and operation not in ("eq", "ne")):
        raise UnknownSemantics("unsupported IF operation")
    left, right = condition["value1"], condition["value2"]
    pointer = f"/parameters/conditions/{kind}/0"

    def valid_literal(value):
        if kind == "string":
            return isinstance(value, str) and not value.startswith("=")
        return type(value) in (int, float) and abs(value) <= 2**53 and math.isfinite(value)

    if not valid_literal(right):
        raise UnknownSemantics("IF right operand must be a supported literal")
    match = FIELD_REF.fullmatch(left) if isinstance(left, str) else None
    if match:
        field = match.group(1)
        if fields.get(field) != kind:
            raise UnknownSemantics("IF field needs a matching declared policy type")
        return Predicate(field=field, operator=operation, value=right), None, pointer
    if not valid_literal(left):
        raise UnknownSemantics("IF left operand is not a literal or the whitelisted $json field reference")
    return None, COMPARE[operation](left, right), pointer


def satisfiable(constraints):
    """Conjunction over independent, typed, unchanged fields; finite binary64 numbers."""
    by_field = {}
    for predicate, truth in constraints:
        by_field.setdefault(predicate.field, []).append((predicate, truth))
    for terms in by_field.values():
        constants = [predicate.value for predicate, _ in terms]
        if isinstance(constants[0], str):
            other = ""
            while other in constants:
                other += "_"
            candidates = set(constants) | {other}
        else:
            candidates = {0.0, -sys.float_info.max, sys.float_info.max}
            for constant in constants:
                number = float(constant)
                candidates.update((number, math.nextafter(number, -math.inf), math.nextafter(number, math.inf)))
            candidates = {item for item in candidates if math.isfinite(item)}
        if not any(all(COMPARE[predicate.operator](value, predicate.value) == truth for predicate, truth in terms) for value in candidates):
            return False
    return True
