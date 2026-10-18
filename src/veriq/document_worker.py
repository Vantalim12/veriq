"""Bounded SOP parsing in a fresh process without runtime credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from .ingestion import InputError, read_bytes
from .sop import MAX_SOP_BYTES

PARSE_SECONDS = 15
MAX_RESULT_BYTES = 2 * 1024 * 1024


def read_sop_isolated(path):
    path = Path(path)
    if path.suffix.lower() not in {".pdf", ".docx"}:
        raise InputError("SOP must be a text-based .pdf or .docx file")
    raw = read_bytes(path, MAX_SOP_BYTES)
    with TemporaryDirectory(prefix="veriq-parser-") as directory:
        source = Path(directory) / ("input" + path.suffix.lower())
        source.write_bytes(raw)
        source.chmod(0o600)
        # -I ignores Python environment overrides; only the installed application is added.
        bootstrap = ("import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); "
                     "runpy.run_module('veriq.document_worker',run_name='__main__')")
        try:
            with (Path(directory) / "result.json").open("w+b") as output:
                result = subprocess.run([sys.executable, "-I", "-c", bootstrap,
                    str(Path(__file__).resolve().parents[1]), str(source)],
                    cwd=directory, env={"LANG": "C.UTF-8"}, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.DEVNULL, timeout=PARSE_SECONDS,
                    close_fds=True)
                if result.returncode:
                    raise InputError("SOP parser rejected the document or exceeded its resource budget")
                output.seek(0)
                payload = output.read(MAX_RESULT_BYTES + 1)
            if len(payload) > MAX_RESULT_BYTES:
                raise InputError("SOP parser output exceeds its byte limit")
            document = json.loads(payload)
            if not isinstance(document, dict) or "document_hash" not in document or "blocks" not in document:
                raise ValueError("invalid parser response")
            return document
        except subprocess.TimeoutExpired as exc:
            raise InputError("SOP parsing exceeded the time limit") from exc
        except (OSError, ValueError) as exc:
            if isinstance(exc, InputError):
                raise
            raise InputError("SOP parser unavailable or returned invalid output") from exc


def worker():
    # Fail closed on hosts without the Linux resource controls used by Appwrite/Docker.
    if sys.platform != "linux":
        raise InputError("hosted SOP parsing requires Linux resource controls")
    import ctypes
    import resource
    os.umask(0o077)
    for limit, maximum in ((resource.RLIMIT_CPU, 8), (resource.RLIMIT_AS, 512 * 1024 * 1024),
                           (resource.RLIMIT_FSIZE, MAX_RESULT_BYTES), (resource.RLIMIT_NOFILE, 32),
                           (resource.RLIMIT_CORE, 0), (resource.RLIMIT_NPROC, 0)):
        resource.setrlimit(limit, (maximum, maximum))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.prctl(4, 0, 0, 0, 0) != 0:
        raise InputError("parser privilege controls unavailable")
    # Python parsers do not need networking or process creation.
    def deny_external(event, args):
        if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn", "os.fork")):
            raise PermissionError("external operations disabled in document parser")
    sys.addaudithook(deny_external)
    from .sop import read_sop
    sys.stdout.write(json.dumps(read_sop(Path(sys.argv[1])), ensure_ascii=True))


if __name__ == "__main__":
    worker()
