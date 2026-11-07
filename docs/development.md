# Local development and checks

Everything runs from `/home/paul/projects/groceries/serverless_grocery`. Do not copy `.env`, database exports or auth credentials into tracked files.

## Python environments

The requested environment `/home/paul/projects/pi-data-science/.venv` is Python 3.14.4 and has no pip. Its installed packages were not changed. Test dependencies are isolated in `.tools/python` and accessed through `PYTHONPATH`.

A second **project-local virtual environment** at `.tools/lambda-venv` uses Python 3.13, matching the Lambda runtime. Both interpreters passed the backend tests. SAM tooling has separate dependencies in `.tools/sam-cli` to avoid version conflicts with tests.

Recreate with `uv` (already available on this machine):

```bash
cd /home/paul/projects/groceries/serverless_grocery
export UV_CACHE_DIR="$PWD/.tools/uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python-runtimes"
# --no-bin avoids installing interpreter shims outside this project.
uv python install --no-bin 3.13
uv venv --python 3.13 .tools/lambda-venv
uv pip install --python .tools/lambda-venv/bin/python -r requirements-dev.lock
uv pip install --python .tools/lambda-venv/bin/python --target .tools/sam-cli -r requirements-sam.lock
uv pip install --python /home/paul/projects/pi-data-science/.venv/bin/python \
  --target .tools/python -r requirements-dev.lock
```

Local CLI SDK dependencies include CRT because the `serverless-grocery` profile uses `aws login`. Lambda itself uses its execution role and does not need CRT/login profiles. Backend runtime dependencies are hashed/pinned in `backend/requirements.lock`; dev/SAM tooling are separately locked. Frontend has `package-lock.json`.

## Checks (no deployment)

```bash
export AWS_DEFAULT_REGION=us-east-1 AWS_EC2_METADATA_DISABLED=true
.tools/lambda-venv/bin/python -m pytest -q

# Also test using your requested environment without modifying it:
PYTHONPATH="$PWD/.tools/python" \
  /home/paul/projects/pi-data-science/.venv/bin/python -m pytest -q

# Private input validation only; writes reports locally, never contacts AWS:
.tools/lambda-venv/bin/python scripts/migrate.py

npm ci --cache .tools/npm-cache
npm run build
npm test
PLAYWRIGHT_BROWSERS_PATH="$PWD/.tools/browsers" npx playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/.tools/browsers" npm run test:browser

bash scripts/sam.sh validate --lint
bash scripts/sam.sh build
```

Moto tests emulate AWS entirely in-process. If private exports are absent in a fresh clone, private-dataset tests skip; public tests still run. Browser tests use a local static server and mocked API/Cognito responses; those mocks are test code, not a deployed auth bypass.

`npm run build` creates `dist/`, bundling the maintained OIDC client into a hashed JavaScript file. No CDN scripts or runtime npm dependencies are required. Without `APP_CONFIG_FILE`, the built page displays a deployment-configuration notice, not a misleading working login.

For a configured build after deployment, set `APP_CONFIG_FILE` to the public JSON generated from stack outputs, then build. Configuration contains only public identifiers/URLs. Serve locally with your venv's `python -m http.server --directory dist`; live Cognito login is intentionally restricted to the deployed CloudFront origin, not localhost. Use browser mocks for local acceptance tests.

## Private migration inputs

`migration/private/` and all reports/normalized records are gitignored. Six full CSV filenames are explicit in `scripts/migrate.py`. The schema metadata CSV is reference material, not an executable SQL script. No source CSV is modified by validation/import.

Generated files:

- `validation-report.json`: counts, fingerprint, warnings/errors
- `normalized.jsonl`: all source rows mapped deterministically to DynamoDB
- `rehearsal-report.json`: full-dataset mocked import/reconciliation results (from pytest)

The importer defaults to local validation. `--apply` is a separate explicit AWS operation with additional confirmation/account checks; do not run it until approved.
