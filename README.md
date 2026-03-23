# kaiano-common-utils

[![Build](https://github.com/kaianolevine/kaiano-common-utils/actions/workflows/ci.yml/badge.svg)](https://github.com/kaianolevine/kaiano-common-utils/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-auto--updated-brightgreen.svg)](https://github.com/kaianolevine/kaiano-common-utils)
[![Version](https://img.shields.io/github/v/tag/kaianolevine/kaiano-common-utils?label=version)](https://github.com/kaianolevine/kaiano-common-utils/releases)

Common utility functions shared across Kaiano’s projects.

---

## 🧑‍💻 Local Development Setup

This project uses **[Poetry](https://python-poetry.org/)** for dependency management and **pre-commit hooks** for code quality enforcement.

---

### 1️⃣ Prerequisites

Ensure you have the following installed:

| Tool | Version | Installation |
|------|----------|---------------|
| **Python** | ≥ 3.10 (tested on 3.13) | [python.org/downloads](https://www.python.org/downloads/) |
| **Poetry** | ≥ 1.8 | `pip install poetry` or follow [Poetry Install Guide](https://python-poetry.org/docs/#installation) |
| **Git** | Any recent version | [git-scm.com/downloads](https://git-scm.com/downloads) |

---

### 2️⃣ Clone the Repository

```bash
git clone git@github.com:kaianolevine/kaiano-common-utils.git
cd kaiano-common-utils
```

---

### 3️⃣ Install Dependencies

```bash
poetry install
```

This installs all runtime and development dependencies (pytest, black, flake8, mypy, etc.).  
A `.venv` will be automatically created by Poetry.

To enter that virtual environment:
```bash
poetry shell
```

---

### 4️⃣ Enable Pre-Commit Hooks

```bash
pre-commit install
```

This installs hooks that automatically run **formatting**, **linting**, and **type checks** before each commit.

You can also run them manually:
```bash
pre-commit run --all-files
```

---

### 5️⃣ Run Tests

```bash
poetry run pytest --cov=kaiano --cov-report=term-missing
```

Expected:
- Coverage ≥ 90%
- All tests passing ✅

---

### 6️⃣ Type Checking

```bash
poetry run mypy src/
```

If any third-party stub packages are missing (e.g., pytz), install them with:
```bash
poetry add -D types-pytz
```

---

### 7️⃣ Code Formatting & Linting

```bash
poetry run black .
poetry run isort .
poetry run flake8
```

---

### 8️⃣ GitHub Actions CI

Pushes and pull requests to `main` run the **CI** workflow (lint + tests).  
Merges to `main` also run **semantic-release** to version, tag, and update the changelog.

Ensure **GitHub Actions → Settings → Workflow permissions** is set to “Read and write” (needed for releases).

---

### 9️⃣ Useful Shortcuts

| Task | Command |
|------|----------|
| Run all tests | `poetry run pytest` |
| Run coverage | `poetry run pytest --cov` |
| Type check | `poetry run mypy src/` |
| Format all files | `poetry run black . && poetry run isort .` |
| Run pre-commit checks | `pre-commit run --all-files` |

---

### 🔄 10️⃣ Optional: Reset the Environment

If Poetry or dependencies become inconsistent:

```bash
rm -rf .venv
poetry lock --no-update
poetry install
```

---

## 🚀 Quickstart (One-Liner Bootstrap)

If you want to set up a clean environment in a single step (for CI or first-time contributors):

```bash
curl -sSL https://install.python-poetry.org | python3 - && export PATH="$HOME/.local/bin:$PATH" && poetry install && poetry run pre-commit install && poetry run pytest --maxfail=1 --disable-warnings -q
```

This installs Poetry (if missing), installs dependencies, enables pre-commit hooks, and runs an initial test pass.

---

## Installation

**From GitHub (recommended):**
```bash
poetry add git+https://github.com/kaianolevine/kaiano-common-utils.git@v0.0.1
```

**For local development:**
```toml
[tool.poetry.dependencies]
kaiano-common-utils = { path = "../kaiano-common-utils", develop = true }
```

## Usage

```python
import kaiano as kcu
# from kaiano.something import useful_function
```

## Internal API Client

KaianoApiClient is used by processors to call Kaiano's internal
FastAPI services (e.g. deejay-marvel-api).

Configuration via environment variables:
  KAIANO_API_BASE_URL — base URL of the target service
  KAIANO_API_OWNER_ID — owner ID (falls back to OWNER_ID)

Usage:
```python
from kaiano.api import KaianoApiClient

client = KaianoApiClient.from_env()
result = client.post("/v1/ingest", payload)
```

## Development

```bash
poetry install
pre-commit install
poetry run pytest --cov=kaiano
```

## Versioning

This repo uses semantic-release for automated versioning.
Versions are determined automatically from commit messages
on merge to main:

- feat: → minor version bump
- fix: → patch version bump
- feat!: or BREAKING CHANGE → major bump
- chore/docs/refactor/test/ci → no version bump

Never manually edit the version in pyproject.toml.
Never manually edit CHANGELOG.md.
Both are managed automatically on merge to main.

## License

MIT © 2025 Kaiano Levine
