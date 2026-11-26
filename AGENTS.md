# Instructions for agents (Codex, Claude Code)

The product is PolyBot, the repository is exeMoysei/PolyGumbleScan. Specification stages: `docs/TODO.md`,
architecture: `docs/architecture.md`, sprint plan and issue status: `docs/sprinty.md`.

Languages: code, comments, commit messages and every bot message are in English. Documentation (`README.md`,
`docs/**`) is in Polish. Do not use Russian or Ukrainian anywhere in the repository.

## Rules

* Work in small PRs, one stage at a time. Preserve other people's changes.
* `src/polybot/domain` does not import SDKs, Redis, Telegram, the ORM or HTTP clients. Standard library only.
* Money, prices and FX rates are `Decimal` only (`polybot.domain.money.dec`), never `float`. Time is UTC-aware.
* Bet sizing uses the ask side for the required volume only. Last trade and midpoint are diagnostics.
* Anything unknown (limit, rule, depth) stays `unknown`; never guess.
* New market mappings are approved by an admin; an approval is tied to the rules version and parameters.
* Mark test data as `TEST DATA` (`tests/fixtures/**`, `_note`). Never commit secrets; `.env.example` holds names only.
* A new provider = a new package in `src/polybot/adapters/<name>/` + fixtures + `docs/providers/<name>.md` (probe).

## Checks before committing

```bash
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run mypy                       # strict on the whole package
uv run pytest -q                  # + POLYBOT_TEST_DATABASE_URL / POLYBOT_TEST_REDIS_URL for integration tests
uv run polybot demo               # offline run of the pipeline
```

Changed the database models → `uv run alembic revision --autogenerate -m "..."` and verify with `alembic check`.
