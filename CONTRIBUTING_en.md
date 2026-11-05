# Contributing Guide

[中文](CONTRIBUTING.md) **·** [English]

Thank you for your interest in Bitongue! This guide explains how to set up a development environment, the project conventions, and the full workflow for submitting contributions.

## Contents

[AI assistance policy](#ai-assistance-policy) **·** [Development environment](#development-environment) **·** [Code conventions](#code-conventions) **·** [Contribution workflow](#contribution-workflow) **·** [Commit conventions](#commit-conventions) **·** [Testing requirements](#testing-requirements) **·** [Release process](#release-process-maintainers) **·** [Documentation](#documentation) **·** [Code of conduct](#code-of-conduct)

## AI assistance policy

**AI-assisted code contributions are accepted in this project.** Please note:

- You (the submitter) must **carefully review** every line of code you submit, whether written by yourself or with AI assistance;
- AI-assisted code carries **the same responsibility** as hand-written code — correctness, security, and license compliance are the submitter's responsibility;
- Submitting means you fully understand and endorse the change; "the AI wrote it" is not an excuse for defects.

## Development environment

This project uses [uv](https://docs.astral.sh/uv/) for dependency management, requires Python ≥ 3.12, and drives day-to-day commands through GNU Make (the Makefile is cross-platform).

```bash
git clone git@github.com:Ahsen17/bitongue.git
cd bitongue
make install    # create the virtual environment and install dependencies
make check      # lint + type checks + all tests
```

Common commands:

| Command | Purpose |
|-|-|
| `make sync` | Sync dependencies |
| `make fix` | ruff auto-fix and formatting |
| `make lint` | pre-commit + mypy (strict) |
| `make pyright` | pyright type checking |
| `make test` | Unit tests |
| `make test-integration` | Integration tests |
| `make coverage` | Coverage report (`fail_under = 80`) |
| `make docs-build` | Build the bilingual documentation site |
| `make changelog` | Regenerate CHANGELOG.md with git-cliff |

## Code conventions

- Every data structure inherits from `bitongue.base.BaseStruct` (a msgspec `Struct` wrapper); do not use dataclasses or pydantic;
- Asynchronous code uses anyio primitives only (`create_memory_object_stream`, `fail_after`, etc.); never import asyncio directly;
- Generics use PEP 695 syntax (`class Flowing[T: Event]`);
- Subpackage files have fixed roles: `schemas.py` (data structures), `protocols.py` (interface Protocols), `exceptions.py` (exceptions, all inheriting `BitongueError`); each `__init__.py` re-exports with an explicit `__all__`;
- Code style is enforced by ruff: line length 90, Google-style docstring convention, rule groups in `pyproject.toml` under `[tool.ruff.lint]`;
- Type checking runs both mypy strict and pyright; both must pass.

## Contribution workflow

This project uses the **fork & pull** model — please do not push branches directly to the main repository:

1. Claim or raise an issue in [Issues](https://github.com/Ahsen17/bitongue/issues);
2. Fork `Ahsen17/bitongue` on GitHub, clone your fork, and create a feature branch from `main`, e.g. `feat/flowing-metrics`, `fix/expiry-drift`, `docs/quickstart`;
3. Develop with tests added (see [Testing requirements](#testing-requirements)); for user-visible changes, update the READMEs (Chinese / English) and both documentation sites (`docs/` Chinese, `docs/en/` English) in sync;
4. Make sure local `make check` passes;
5. Push the branch to your fork and open a pull request against `main` of `Ahsen17/bitongue`;
6. In the PR description, explain what changed, why, and how to verify it. CI (`pytest.yml`) must be fully green.

## Commit conventions

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/en/):

```
<type>(<scope>?): <description>

<body?>

<footer?>
```

Common types: `feat`, `fix`, `refactor`, `doc`, `perf`, `style`, `test`, `build`, `chore`, `revert`. The commit-msg hook enforces the format.

CHANGELOG.md is generated automatically from commit history by [git-cliff](https://git-cliff.org) (`make changelog`) and **must not be edited by hand**.

## Testing requirements

- The test tree mirrors the source layout: `src/bitongue/flow/flowing.py` → `tests/flow/test_flowing.py`;
- One test file tests exactly one module;
- Global fixtures live in `tests/conftest.py`; subpackage fixtures live in the `conftest.py` of their test subtree;
- Test cases are organized in `class TestXX` groups;
- pytest runs in asyncio auto mode, so tests are plain `async def` functions;
- External dependency strategy: unit tests use fakexx packages (e.g. fakeredis); dependencies without a fakexx package use async mocks; integration tests (`test_integration/`, marker `integration`) use real services;
- Integration tests reach qdrant through the environment: `BITONGUE_TEST_QDRANT_URL` (full URL) or `BITONGUE_TEST_QDRANT_HOST` / `BITONGUE_TEST_QDRANT_PORT` (default `localhost:6333`); when the service is unreachable the tests skip automatically instead of failing;
- New features must come with tests; coverage must stay at or above 80%.

## Release process (maintainers)

Versions follow [SemVer 2.0.0](https://semver.org/); tags always carry the `v` prefix:

- **Stable releases**: `x.y.z`, e.g. `v1.2.0`;
- **Pre-releases (beta)**: `x.y.z-beta.N`, e.g. `v1.2.0-beta.1`; `N` starts at 1 and increments within the same `x.y.z` series.

Release sequence:

1. Update `version` in pyproject, commit `chore(release): prepare for vX.Y.Z`, and merge into `main` (git-cliff skips this commit so it stays out of the CHANGELOG);
2. Tag on main and push: `git tag vX.Y.Z && git push origin vX.Y.Z`;
3. `release.yml` automatically creates a **draft** release with the version's notes (generated by git-cliff) and the sdist/wheel artifacts;
4. Run `make changelog` locally to regenerate CHANGELOG.md (it must run after the tag exists so the new section appears), and merge it with a `doc: update changelog for vX.Y.Z` commit;
5. Adjust the draft on the GitHub Releases page (mark as pre-release or stable) and publish.

## Documentation

- Build the docs site with `make docs-build`; preview locally with live reload via `make docs-serve` (watches both `src/` and `docs/`);
- The documentation is a bilingual Sphinx site: `docs/` is the Simplified Chinese main site and `docs/en/` is the English mirror; page file names correspond one-to-one (the theme's language switcher depends on this mapping);
- When changing any user-visible behavior, update the READMEs (Chinese / English) and the relevant docs pages in sync.

## Code of conduct

Stay respectful and professional. Critique ideas, not people; questions from newcomers are always welcome.

## License

By submitting a contribution, you agree to license your work under [AGPL-3.0](LICENSE).
