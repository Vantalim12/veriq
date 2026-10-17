# Publishing checks

The repository ignores generated graphs, reports, build archives, local `.aws/`, `.codex/` and `.ssh/` directories, private `.pem`/`.key` files and `.env` configuration. Placeholder `.env.example` files remain publishable. Ignore rules do not remove files already committed; inspect the files selected for the first commit and later changes with `git status --short` and `git diff --cached`.

All Actions references use full commit hashes from the official v7.0.0 releases. [GitHub recommends immutable workflow dependencies](https://docs.github.com/en/actions/reference/security/secure-use). Update hashes only after reviewing the corresponding upstream release.

## Dedicated scans

The [security workflow](../.github/workflows/security.yml) runs on pushes, pull requests and manual dispatch. It uses read-only repository permissions and does not require deployment credentials.

- [Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1) scans all fetched Git history, including deleted secrets. Its Linux x64 archive is checked against the SHA-256 digest in the [official release assets](https://github.com/gitleaks/gitleaks/releases/expanded_assets/v8.30.1). Output redacts detected secret values; findings are not uploaded as public artifacts.
- [pip-audit 2.10.1](https://github.com/pypa/pip-audit/releases/tag/v2.10.1) audits every pinned package in `constraints.txt`, covering the current core, optional runtime and test dependencies. Keep that inventory complete when adding dependencies. The scanner is installed in a separate environment. `--no-deps --disable-pip` prevents installing or executing project code during dependency collection; `--strict` rejects incomplete collection.

Both jobs fail on scanner/download errors and findings. No secret or vulnerability exclusions are configured. A successful scan covers known patterns and advisories at scan time; it does not establish that all credentials or vulnerabilities have been found. These jobs must be configured as required checks in repository settings before they can block merging.

With Gitleaks installed and local commits created, scan before pushing:

```bash
gitleaks git --redact --log-opts="--all" .
```

This scans committed history. Review uncommitted and untracked files before staging them; an empty repository history is not a successful scan of those files.

Run the dependency scan without changing project dependencies:

```bash
python3 -m venv /tmp/veriq-pip-audit
/tmp/veriq-pip-audit/bin/python -m pip install pip-audit==2.10.1
/tmp/veriq-pip-audit/bin/python -m pip_audit --strict --no-deps --disable-pip -r constraints.txt
```

## Current evidence

On 2026-10-17, local scanner installation/download attempts failed because this execution environment could not resolve GitHub or PyPI. Neither dedicated scanner completed locally, and the security workflow has not run on GitHub. Ignore-rule and workflow syntax/pin checks can be performed offline; they are not substitutes for the scans. Obtain passing dedicated scan results before treating publication checks as complete.
