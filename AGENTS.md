# Инструкции для агентов (Codex, Claude Code)

Продукт — PolyBot, репозиторий — exeMoysei/PolyGumbleScan. ТЗ и этапы — `docs/TODO.md`, архитектура — `docs/architecture.md`.
План спринтов и статус issues — `docs/sprinty.md`. Документация (`README.md`, `docs/**`) ведётся на польском.

## Правила

* Работать небольшими PR, по одному этапу. Сохранять чужие изменения.
* `src/polybot/domain` не импортирует SDK, Redis, Telegram, ORM и HTTP. Только стандартная библиотека.
* Деньги, цены, курсы — только `Decimal` (`polybot.domain.money.dec`), никогда `float`. Время — UTC-aware.
* Расчёт ставки — только по ask на нужный объём. Last trade/midpoint — диагностика.
* Неизвестное (лимит, правило, глубина) остаётся `unknown`; ничего не угадывать.
* Новые связки рынков подтверждает админ; одобрение привязано к версии правил и параметрам.
* Тестовые данные помечать `TEST DATA` (`tests/fixtures/**`, `_note`). Секреты не коммитить; `.env.example` — только имена.
* Новый поставщик = новый пакет в `src/polybot/adapters/<name>/` + fixtures + `docs/providers/<name>.md` (probe).

## Проверки перед коммитом

```bash
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run mypy                       # strict на весь пакет
uv run pytest -q                  # + POLYBOT_TEST_DATABASE_URL / POLYBOT_TEST_REDIS_URL для интеграции
uv run polybot demo               # офлайн-прогон конвейера
```

Изменил модели БД → `uv run alembic revision --autogenerate -m "..."` и проверь `alembic check`.
