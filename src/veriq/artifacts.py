"""Private expiring input artifacts for the single-process hosted service."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from uuid import uuid4

from .ingestion import InputError, MAX_BYTES, read_policy, read_workflow
from .sop import MAX_SOP_BYTES, read_sop

KINDS = {"workflow": (".json", MAX_BYTES, read_workflow), "policy": (".yaml", MAX_BYTES, read_policy),
         "pdf": (".pdf", MAX_SOP_BYTES, read_sop), "docx": (".docx", MAX_SOP_BYTES, read_sop)}
TTL_SECONDS = 24 * 60 * 60
MAX_USER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_USER_FILES = 100
MAX_TOTAL_FILES = 1000


class ArtifactStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.lock = threading.RLock()

    def user_dir(self, owner):
        if re.fullmatch(r"[0-9a-f]{64}", owner) is None:
            raise InputError("invalid authenticated identity")
        directory = self.root / owner
        return directory

    @contextmanager
    def temporary(self, owner, kind):
        if kind not in KINDS:
            raise InputError("artifact kind must be workflow, policy, pdf or docx")
        directory = self.user_dir(owner)
        suffix = KINDS[kind][0]
        with self.lock:
            directory.mkdir(mode=0o700, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=".upload-", suffix=suffix, dir=directory)
        os.close(descriptor)
        path = Path(name)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)
            with self.lock:
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def commit(self, owner, kind, temporary):
        KINDS[kind][2](temporary)
        with self.lock:
            self.prune()
            directory = self.user_dir(owner)
            files = [p for p in self.root.glob("*/*") if p.is_file() and not p.name.startswith(".")]
            own = [p for p in files if p.parent == directory]
            size = temporary.stat().st_size
            if (len(own) >= MAX_USER_FILES or len(files) >= MAX_TOTAL_FILES
                    or sum(p.stat().st_size for p in own) + size > MAX_USER_BYTES
                    or sum(p.stat().st_size for p in files) + size > MAX_TOTAL_BYTES):
                raise InputError("artifact storage quota reached; delete inputs or wait for expiry")
            identifier = uuid4().hex
            destination = directory / (identifier + KINDS[kind][0])
            os.replace(temporary, destination)
            return {"artifact_id": destination.name, "kind": kind, "bytes": size,
                    "expires_at": int(destination.stat().st_mtime + TTL_SECONDS)}

    def resolve(self, owner, identifier, suffixes):
        if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{32}\.(json|yaml|pdf|docx)", identifier) is None:
            raise InputError("use the opaque artifact_id returned by an authenticated upload")
        path = self.user_dir(owner) / identifier
        if (not path.is_file() or path.is_symlink() or path.suffix not in suffixes
                or time.time() - path.stat().st_mtime >= TTL_SECONDS):
            raise InputError("artifact unavailable, expired or wrong type")
        return path

    def delete(self, owner, identifier):
        with self.lock:
            self.resolve(owner, identifier, {".json", ".yaml", ".pdf", ".docx"}).unlink()

    def prune(self):
        with self.lock:
            for path in self.root.glob("*/*"):
                if path.is_file() and time.time() - path.stat().st_mtime >= (600 if path.name.startswith(".upload-") else TTL_SECONDS):
                    path.unlink(missing_ok=True)
