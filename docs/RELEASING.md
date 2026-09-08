# Publishing the Python SDK

The distribution is `wukong-easy-sdk`; the repository is
`WuKongIM/WuKongEasySDK-Python`. This Python project publishes to PyPI.

## One-time setup

In GitHub, create the `pypi` environment and allow deployment only from tags
matching `v*`. In the maintainer's PyPI account, add a pending Trusted Publisher:

| Field | Value |
| --- | --- |
| PyPI project | `wukong-easy-sdk` |
| Owner | `WuKongIM` |
| Repository | `WuKongEasySDK-Python` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

The first successful publication creates the PyPI project and converts the
pending publisher to a normal publisher. No long-lived PyPI token is required.
See [PyPI's setup instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Release

1. Update `pyproject.toml`, `uv.lock`, and the exact version section in
   `CHANGELOG.md`; document installation for that version in both READMEs.
2. Run the CI checks and real product/JS interoperability harness in
   [VALIDATION.md](VALIDATION.md). Merge the tested commit into `main`.
3. Create an annotated tag such as `v0.1.0` at that exact commit and push it.
   `publish.yml` verifies the tag, version, changelog and main ancestry, runs
   tests, builds wheel/sdist, checks metadata, and tests the installed wheel.
   A separate job publishes those same artifacts with PyPI OIDC and attestations.
4. Wait for a successful publish job. Compare both artifact SHA-256 values with
   `https://pypi.org/pypi/wukong-easy-sdk/0.1.0/json` (substitute the target version).
   In a new environment, install the exact version from `https://pypi.org/simple`
   and repeat the protocol tests and real product/JS harness using that interpreter.
5. Create a GitHub Release for the existing tag, using the exact changelog section
   and attaching the workflow's distributions. Record the run, hashes and
   installed-package validation. Update the public docs only after this succeeds.

If a job fails before upload, fix the cause and rerun the same tag only when its
source remains correct. Never move a published tag or replace a PyPI version.
After a partial upload, inspect PyPI file hashes and recover only the missing
artifact from the original workflow; do not rebuild or blindly skip duplicates.
