# Release process (for the owner)

1. **Decide the LICENSE** (owner-reserved; recommendation stands: Apache-2.0 or
   MIT). Until then, artifacts carry `LicenseRef-Proprietary-Until-Owner-Decides`
   and public redistribution is discouraged.
2. Bump `version` in `pyproject.toml` and `__version__` in
   `src/jarvis/__init__.py` (must match; a unit test enforces it), update
   `packaging/rpm/jarvis-agent.spec` + `packaging/arch/PKGBUILD`, add a
   CHANGELOG entry.
3. Commit on the working branch, then cut a tag:
   ```sh
   git tag v1.0.0 && git push origin v1.0.0
   ```
4. The `Release` workflow builds wheel + sdist + deb, smoke-tests the wheel in a
   clean venv, and opens a **draft** GitHub Release with all artifacts attached.
   Review, publish the draft when satisfied.
5. PyPI publishing is **manual and owner-only** (`twine upload dist/*` with your
   own account / trusted publisher). The agent never publishes.
6. To re-run any verification on fresh GitHub VMs on demand:
   **Actions → CI / Container eval / Packaging & install → Run workflow**
   (`workflow_dispatch` is enabled on all three).
