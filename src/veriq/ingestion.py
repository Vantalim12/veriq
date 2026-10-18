"""Bounded file readers and stable workflow normalization."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError
import yaml

from .contracts import ExportNode, Policy

MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 100
MAX_EDGES = 1000
MAX_ITEMS = 50_000


class InputError(ValueError):
    """Invalid or unsupported input structure; messages omit supplied values."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def read_bytes(path: Path, max_bytes=MAX_BYTES) -> bytes:
    if not path.is_file():
        raise InputError("input must be an existing regular file")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise InputError("input exceeds the configured byte limit")
    return raw


def pairs(items):
    result = {}
    for key, value in items:
        if not isinstance(key, str) or key in result:
            raise InputError("mapping keys must be unique strings")
        result[key] = value
    return result


def reject_constant(_value):
    raise InputError("non-finite JSON numbers are not accepted")


def checked_float(value):
    result = float(value)
    if not math.isfinite(result):
        reject_constant(value)
    return result


def check_tree(value, max_items=MAX_ITEMS, *, max_depth=MAX_DEPTH):
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > max_depth or count > max_items:
            raise InputError("input exceeds the nesting/item limit")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise InputError("mapping keys must be strings")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise InputError("only JSON-compatible scalar values are accepted; quote dates")
        elif isinstance(item, float) and not math.isfinite(item):
            reject_constant(item)


def load_json(raw: bytes, max_items=MAX_ITEMS, *, max_depth=MAX_DEPTH):
    text = raw.decode("utf-8")
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > max_depth:
                raise InputError("JSON exceeds the nesting limit")
        elif char in "]}":
            depth -= 1
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant, parse_float=checked_float)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("invalid JSON") from exc
    check_tree(value, max_items, max_depth=max_depth)
    return value


class PolicyLoader(yaml.SafeLoader):
    pass


def yaml_mapping(loader, node):
    return pairs([(loader.construct_object(key), loader.construct_object(value)) for key, value in node.value])


PolicyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, yaml_mapping)


def read_policy(path: Path) -> tuple[Policy, str]:
    return load_policy(read_bytes(path))


def load_policy(raw: bytes) -> tuple[Policy, str]:
    if len(raw) > MAX_BYTES:
        raise InputError("policy exceeds the 2 MiB input limit; split it into smaller parts")
    text = raw.decode("utf-8")
    try:
        depth = count = 0
        for event in yaml.parse(text, Loader=PolicyLoader):
            count += 1
            if count > MAX_ITEMS * 2:
                raise InputError("YAML exceeds the item limit")
            if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
                raise InputError("YAML anchors and aliases are not supported")
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
                if depth > MAX_DEPTH:
                    raise InputError("YAML exceeds the nesting limit")
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
        data = yaml.load(text, Loader=PolicyLoader)
        check_tree(data)
        policy = Policy.model_validate(data)
    except (yaml.YAMLError, ValidationError, TypeError, RecursionError) as exc:
        raise InputError("invalid policy; check schema, required approval, unique IDs, and quoted dates") from exc
    return policy, "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, order=True)
class Edge:
    source: str
    output_index: int
    target: str
    input_index: int
    channel: str = "main"
    connection_index: int = 0

    def record(self):
        return asdict(self)


@dataclass
class Workflow:
    nodes: dict[str, ExportNode]
    edges: list[Edge]
    pointers: dict[str, str]
    input_hash: str
    graph_hash: str
    settings: dict
    _outgoing: dict[str, list[Edge]] = field(init=False, repr=False)

    def __post_init__(self):
        self._outgoing = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            self._outgoing[edge.source].append(edge)

    def outgoing(self, node_id):
        return self._outgoing.get(node_id, [])


def read_workflow(path: Path) -> Workflow:
    raw = read_bytes(path)
    data = load_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise InputError("workflow must contain a nodes array")
    if not 1 <= len(data["nodes"]) <= MAX_NODES or not isinstance(data.get("connections"), dict):
        raise InputError("workflow needs 1–100 nodes and a connections object")
    if not isinstance(data.get("settings", {}), dict):
        raise InputError("workflow settings must be an object")
    try:
        node_list = [ExportNode.model_validate(item) for item in data["nodes"]]
    except ValidationError as exc:
        raise InputError("invalid node metadata or parameters") from exc
    nodes = {node.id: node for node in node_list}
    names = {node.name: node.id for node in node_list}
    if len(nodes) != len(node_list) or len(names) != len(node_list):
        raise InputError("workflow node IDs and names must be unique")
    edges = []
    for source_name, channels in data["connections"].items():
        if source_name not in names or not isinstance(channels, dict):
            raise InputError("invalid connection source")
        for channel, outputs in channels.items():
            if not isinstance(outputs, list):
                raise InputError("connection outputs must be arrays")
            for output_index, connections in enumerate(outputs):
                if not isinstance(connections, list):
                    raise InputError("each output must contain a connection array")
                for connection_index, connection in enumerate(connections):
                    if (not isinstance(connection, dict) or set(connection) != {"node", "type", "index"}
                            or not isinstance(connection["node"], str) or connection["node"] not in names
                            or connection["type"] != channel or type(connection["index"]) is not int
                            or connection["index"] < 0):
                        raise InputError("invalid or dangling connection endpoint")
                    edges.append(Edge(names[source_name], output_index, names[connection["node"]], connection["index"], channel, connection_index))
                    if len(edges) > MAX_EDGES:
                        raise InputError("workflow exceeds the 1000-edge limit")
    normalized = []
    for node in sorted(node_list, key=lambda item: item.id):
        item = node.model_dump()
        for key in ("name", "position", "notes", "notesInFlow", "color"):
            item.pop(key, None)
        normalized.append(item)
    return Workflow(nodes, sorted(edges), {node.id: f"/nodes/{i}" for i, node in enumerate(node_list)},
                    "sha256:" + hashlib.sha256(raw).hexdigest(), digest({"nodes": normalized, "edges": [edge.record() for edge in sorted(edges)], "settings": data.get("settings", {}), "canonicalization_version": 1}), data.get("settings", {}))
