"""Private Appwrite blobs, ownership records and transactional storage reservations."""

import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

import httpx

from .artifacts import (ArtifactStore, KINDS, TTL_SECONDS, MAX_USER_BYTES, MAX_TOTAL_BYTES,
                        MAX_USER_FILES, MAX_TOTAL_FILES)
from .hosted_auth import https_url
from .ingestion import InputError, digest
from .reporting import (MAX_REPORT_BYTES, MAX_USER_AUDITS, MAX_TOTAL_AUDITS,
                        MAX_TOTAL_AUDIT_BYTES, json_report)


class AppwriteError(OSError):
    def __init__(self, code):
        super().__init__("Appwrite storage unavailable")
        self.code = code


def query(method, attribute=None, values=None):
    value = {"method": method}
    if attribute is not None:
        value["attribute"] = attribute
    if values is not None:
        value["values"] = values
    return json.dumps(value, separators=(",", ":"))


class AppwriteAPI:
    def __init__(self, endpoint, project, key, *, transport=None):
        https_url(endpoint)
        if not endpoint.endswith("/v1") or not key or any(c.isspace() for c in key):
            raise InputError("configure the trusted Appwrite /v1 endpoint and server API key")
        self.client = httpx.Client(base_url=endpoint + "/", timeout=15, follow_redirects=False,
            trust_env=False, transport=transport,
            headers={"X-Appwrite-Project": project, "X-Appwrite-Key": key})

    def close(self):
        self.client.close()

    def request(self, method, path, *, limit=MAX_REPORT_BYTES, binary=False, **kwargs):
        try:
            with self.client.stream(method, path.lstrip("/"), **kwargs) as response:
                if not 200 <= response.status_code < 300:
                    raise AppwriteError(response.status_code)
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > limit:
                        raise AppwriteError(502)
                if not binary and "application/json" in response.headers.get("content-type", ""):
                    return json.loads(payload) if payload else {}
                return bytes(payload)
        except (httpx.HTTPError, ValueError) as exc:
            raise AppwriteError(503) from exc


class AppwriteStore(ArtifactStore):
    """Local paths live for one invocation; Appwrite owns all persistent state."""
    def __init__(self, root, api, database="veriq", bucket="veriq-private"):
        super().__init__(root)
        for identifier in (database, bucket):
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,35}", identifier) is None:
                raise InputError("invalid Appwrite resource ID")
        self.api = api
        self.tables = f"/tablesdb/{database}/tables"
        self.files = f"/storage/buckets/{bucket}/files"

    def rows(self, table):
        return f"{self.tables}/{table}/rows"

    def object_id(self, owner, identifier):
        self.user_dir(owner)
        return digest([owner, identifier]).removeprefix("sha256:")[:32]

    def counters(self, owner, category):
        return [category + "-global", category + "-" + self.object_id(owner, "quota")[:24]]

    def ensure_counters(self, owner, category):
        for identifier in self.counters(owner, category):
            try:
                self.api.request("POST", self.rows("quotas"), json={"rowId": identifier,
                    "data": {"count": 0, "bytes": 0}, "permissions": []})
            except AppwriteError as exc:
                if exc.code != 409:
                    raise

    def transaction(self, operation):
        for attempt in range(3):
            tx = self.api.request("POST", "/tablesdb/transactions", json={"ttl": 60})["$id"]
            try:
                result = operation(tx)
                self.api.request("PATCH", f"/tablesdb/transactions/{tx}", json={"commit": True})
                return result
            except BaseException as exc:
                try:
                    self.api.request("PATCH", f"/tablesdb/transactions/{tx}", json={"rollback": True})
                except OSError:
                    pass
                if isinstance(exc, AppwriteError) and exc.code == 409 and attempt < 2:
                    continue
                raise

    def reserve(self, identifier, owner, kind, size, reference, replacement=None):
        category = "audit" if kind == "audit" else "artifact"
        self.ensure_counters(owner, category)
        limits = [(MAX_TOTAL_AUDITS, MAX_TOTAL_AUDIT_BYTES),
                  (MAX_USER_AUDITS, MAX_USER_AUDITS * MAX_REPORT_BYTES)] if category == "audit" else [
            (MAX_TOTAL_FILES, MAX_TOTAL_BYTES), (MAX_USER_FILES, MAX_USER_BYTES)]
        data = {"owner": owner, "category": category, "kind": kind, "bytes": size, "reference": reference,
                "expires": int(time.time()) + 600, "state": "pending"}

        def operation(tx):
            if replacement is not None:
                old = self.api.request("GET", f"{self.rows('objects')}/{replacement}", params={"transactionId": tx})
                if kind != "audit" or old["owner"] != owner or old["category"] != "audit" or old["state"] != "ready":
                    raise InputError("audit replacement unavailable; rerun verification")
            for counter, (count_limit, byte_limit) in zip(self.counters(owner, category), limits):
                # A replacement temporarily holds both blobs; its final usage must fit the normal caps.
                if replacement is not None:
                    count_limit += 1
                    byte_limit += old["bytes"]
                for column, value, maximum in (("count", 1, count_limit), ("bytes", size, byte_limit)):
                    self.api.request("PATCH", f"{self.rows('quotas')}/{counter}/{column}/increment",
                        json={"value": value, "max": maximum, "transactionId": tx})
            return self.api.request("POST", self.rows("objects"),
                json={"rowId": identifier, "data": data, "permissions": [], "transactionId": tx})
        try:
            return self.transaction(operation)
        except AppwriteError as exc:
            if exc.code == 400:
                raise InputError("storage quota reached; delete inputs or wait for expiry") from exc
            raise

    def metadata(self, identifier):
        return self.api.request("GET", f"{self.rows('objects')}/{identifier}")

    def upload_blob(self, identifier, payload, filename):
        chunk_size = 5 * 1024 * 1024
        for start in range(0, len(payload), chunk_size):
            end = min(start + chunk_size, len(payload))
            headers = {}
            if len(payload) > chunk_size:
                headers["Content-Range"] = f"bytes {start}-{end - 1}/{len(payload)}"
                if start:
                    headers["X-Appwrite-ID"] = identifier
            self.api.request("POST", self.files, data={"fileId": identifier},
                files={"file": (filename, payload[start:end], "application/octet-stream")}, headers=headers)

    def put(self, identifier, owner, kind, payload, filename, reference, replacement=None):
        self.reserve(identifier, owner, kind, len(payload), reference, replacement)
        try:
            self.upload_blob(identifier, payload, filename)
            expires = int(time.time()) + (3600 if kind == "audit" else TTL_SECONDS)

            def finish(tx):
                if replacement is not None:
                    old = self.api.request("GET", f"{self.rows('objects')}/{replacement}", params={"transactionId": tx})
                    if old["owner"] != owner or old["category"] != "audit" or old["state"] != "ready":
                        raise InputError("audit replacement unavailable; rerun verification")
                    self.api.request("PATCH", f"{self.rows('objects')}/{replacement}",
                        json={"data": {"state": "retired", "expires": 0}, "transactionId": tx})
                self.api.request("PATCH", f"{self.rows('objects')}/{identifier}",
                    json={"data": {"state": "ready", "expires": expires}, **({"transactionId": tx} if tx else {})})

            if replacement is None:
                finish(None)
            else:
                self.transaction(finish)
        except BaseException:
            # Keep failed reservations if cleanup is unavailable; the scheduled reaper releases them.
            try:
                # A lost commit response may hide a completed replacement; never delete its ready blob.
                if replacement is None or self.metadata(identifier)["state"] == "pending":
                    self.remove(identifier)
            except OSError:
                pass
            raise
        if replacement is not None:
            try:
                self.remove(replacement)
            except OSError:
                pass  # The retired row lets scheduled cleanup retry physical deletion.
        return expires

    def commit(self, owner, kind, temporary):
        payload = Path(temporary).read_bytes()
        if len(payload) > KINDS[kind][1]:
            raise InputError("input exceeds the byte limit")
        KINDS[kind][2](temporary)
        artifact = uuid4().hex + KINDS[kind][0]
        expires = self.put(self.object_id(owner, artifact), owner, kind, payload, artifact, artifact)
        return {"artifact_id": artifact, "kind": kind, "bytes": len(payload), "expires_at": expires}

    def available(self, owner, identifier, category):
        key = self.object_id(owner, identifier)
        try:
            row = self.metadata(key)
        except AppwriteError as exc:
            if exc.code == 404:
                raise InputError("input or audit unavailable") from exc
            raise
        if row["owner"] != owner or row["category"] != category or row["state"] != "ready" or row["expires"] <= time.time():
            raise InputError("input or audit unavailable or expired")
        return key, row

    def resolve(self, owner, identifier, suffixes):
        if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{32}\.(json|yaml|pdf|docx)", identifier) is None:
            raise InputError("use the opaque artifact_id returned by an authenticated upload")
        if Path(identifier).suffix not in suffixes:
            raise InputError("artifact has the wrong type")
        key, row = self.available(owner, identifier, "artifact")
        limit = KINDS[row["kind"]][1]
        payload = self.api.request("GET", f"{self.files}/{key}/download", limit=limit, binary=True)
        if len(payload) != row["bytes"]:
            raise InputError("artifact is incomplete")
        directory = self.user_dir(owner)
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / identifier
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
        return path

    def delete(self, owner, identifier):
        if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{32}\.(json|yaml|pdf|docx)", identifier) is None:
            raise InputError("invalid artifact ID")
        key, _ = self.available(owner, identifier, "artifact")
        self.remove(key)

    def remove(self, identifier):
        try:
            self.api.request("DELETE", f"{self.files}/{identifier}")
        except AppwriteError as exc:
            if exc.code != 404:
                raise

        def operation(tx):
            try:
                row = self.api.request("GET", f"{self.rows('objects')}/{identifier}", params={"transactionId": tx})
            except AppwriteError as exc:
                if exc.code == 404:
                    return
                raise
            for counter in self.counters(row["owner"], row["category"]):
                for column, value in (("count", 1), ("bytes", row["bytes"])):
                    self.api.request("PATCH", f"{self.rows('quotas')}/{counter}/{column}/decrement",
                        json={"value": value, "min": 0, "transactionId": tx})
            self.api.request("DELETE", f"{self.rows('objects')}/{identifier}", json={"transactionId": tx})
        self.transaction(operation)

    def list_objects(self, *queries):
        return self.api.request("GET", self.rows("objects"),
            params=[("queries[]", q) for q in queries])["rows"]

    def save_audit(self, owner, result):
        self.user_dir(owner)
        payload = json_report(result).encode()
        try:
            self.put(uuid4().hex, owner, "audit", payload, "audit.json", result["audit_id"])
        except InputError:
            oldest = self.list_objects(query("equal", "owner", [owner]),
                query("equal", "category", ["audit"]),
                query("equal", "state", ["ready"]), query("orderAsc", "expires"), query("limit", values=[1]))
            own = self.api.request("GET", f"{self.rows('quotas')}/{self.counters(owner, 'audit')[1]}")
            if own["count"] != MAX_USER_AUDITS or not oldest:
                raise
            self.put(uuid4().hex, owner, "audit", payload, "audit.json", result["audit_id"], oldest[0]["$id"])

    def load_audit(self, owner, audit_id):
        if not isinstance(audit_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", audit_id) is None:
            raise InputError("invalid audit ID")
        self.user_dir(owner)
        rows = self.list_objects(query("equal", "owner", [owner]), query("equal", "reference", [audit_id]),
            query("equal", "state", ["ready"]), query("greaterThan", "expires", [int(time.time())]),
            query("orderDesc", "expires"), query("limit", values=[1]))
        if not rows or rows[0]["owner"] != owner or rows[0]["category"] != "audit":
            raise InputError("audit unavailable or expired; rerun verification")
        row = rows[0]
        payload = self.api.request("GET", f"{self.files}/{row['$id']}/download", binary=True)
        if len(payload) != row["bytes"]:
            raise InputError("audit is incomplete")
        return json.loads(payload)

    def prune(self):
        removed = 0
        deadline = time.monotonic() + 80
        for _ in range(11):
            expired = self.list_objects(query("lessThanEqual", "expires", [int(time.time())]),
                query("orderAsc", "expires"), query("limit", values=[100]))
            for row in expired:
                if time.monotonic() >= deadline:
                    return removed
                self.remove(row["$id"])
                removed += 1
            if len(expired) < 100:
                break
        return removed
