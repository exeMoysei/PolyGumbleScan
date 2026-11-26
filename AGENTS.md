# Instructions for agents (Codex, Claude Code)

The product is PolyBot, the repository is exeMoysei/PolyGumbleScan. Specification stages: `docs/TODO.md`,
architecture: `docs/architecture.md`, sprint plan and issue status: `docs/sprinty.md`, who owns which module:
`docs/podzial-pracy.md`.

Languages: code, comments, commit messages and every bot message are in English. Documentation (`README.md`,
`docs/**`) is in Polish. Do not use Russian or Ukrainian anywhere in the repository.

## Rules

* Work in small PRs, one stage at a time. Preserve other people's changes.
* Layers: `data/` (venue APIs, database, cache) → `logic/` (pure business rules) ← `bot/` (Telegram); `services/`
  connects them. `logic/` imports no SDKs, Redis, Telegram, ORM or HTTP clients (enforced by `tests/unit/test_layers.py`).
* Money, prices and FX rates are `Decimal` only (`polybot.logic.money.dec`), never `float`. Time is UTC-aware.
* Bet sizing uses the ask side for the required volume only. Last trade and midpoint are diagnostics.
* Anything unknown (limit, rule, depth) stays `unknown`; never guess.
* New market mappings are approved by an admin; an approval is tied to the rules version and parameters.
* Mark test data as `TEST DATA` (`tests/fixtures/**`, `_note`). Never commit secrets; `.env.example` holds names only.
* A new provider = a new module `src/polybot/data/<name>.py` + fixtures `tests/fixtures/<name>_*.json` + a section in
  `docs/zrodla-danych.md` (probe). Keep the layout flat: no new sub-packages.

## Checks before committing

```bash
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run mypy                       # strict on the whole package
uv run pytest -q                  # + POLYBOT_TEST_DATABASE_URL / POLYBOT_TEST_REDIS_URL for integration tests
uv run polybot demo               # offline run of the pipeline
```

Changed the database models → `uv run alembic revision --autogenerate -m "..."` and verify with `alembic check`.
