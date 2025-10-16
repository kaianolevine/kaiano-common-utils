# kaiano-common-utils

[![Build](https://github.com/kaianolevine/kaiano-common-utils/actions/workflows/test.yml/badge.svg)](https://github.com/kaianolevine/kaiano-common-utils/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/badge/coverage-auto--updated-brightgreen.svg)](https://github.com/kaianolevine/kaiano-common-utils)
[![Version](https://img.shields.io/github/v/tag/kaianolevine/kaiano-common-utils?label=version)](https://github.com/kaianolevine/kaiano-common-utils/releases)

Common utility functions shared across Kaiano’s projects.

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
import kaiano_common_utils as kcu
# from kaiano_common_utils.something import useful_function
```

## Development

```bash
poetry install
pre-commit install
poetry run pytest --cov=kaiano_common_utils
```

## Versioning

- Starts at `0.0.0`
- Auto-bumps PATCH on push to `main` (tags `vX.Y.Z`)
- Managed by Poetry + GitHub Actions

## License

MIT © 2025 Kaiano Levine
