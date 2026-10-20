"""Build a source allowlist for Appwrite; never archive the entire working tree."""

import argparse
from pathlib import Path
import tarfile

from veriq.ingestion import InputError


def package(root, destination):
    root, destination = Path(root), Path(destination)
    members = [root / name for name in ("README.md", "pyproject.toml", "constraints.txt", "requirements.txt",
        "deployment/appwrite/main.py", "deployment/appwrite/cleanup.py")]
    members += sorted((root / "src/veriq").glob("*.py"))
    members += [root / "src/veriq/web" / name for name in (
        "upload.html", "upload.css", "upload.js", "sign-in.html", "sign-in.js", "favicon.png")]
    if destination.exists() or destination.resolve() in {p.resolve() for p in members}:
        raise InputError("function archive must be a new path separate from source files")
    if any(p.is_symlink() or not p.is_file() for p in members):
        raise InputError("function sources must be regular files")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        try:
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for path in members:
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(root).as_posix())
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with path.open("rb") as source:
                        archive.addfile(info, source)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    destination.chmod(0o600)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/veriq-appwrite.tar.gz"))
    args = parser.parse_args()
    print(package(Path(__file__).resolve().parents[2], args.output))
