# PolyBot (репозиторий PolyGumbleScan)

PolyBot собирает рынки prediction markets (Polymarket, Kalshi) и котировки букмекеров (через The Odds API),
сопоставляет **одно и то же событие** на разных площадках, и ищет комбинации ставок, где выплата после всех
затрат покрывает вложения во всех обычных исходах. Отмены, переносы, ничьи и возвраты считаются отдельными
сценариями. Результат приходит в Telegram карточкой со ставками, P&L по сценариям, возрастом цен и ссылками.

Ставки размещает пользователь. Бот не хранит средства, не торгует и не использует торговые API-ключи.

## Как это работает

```
 adapters ──► ingest ──► matching ──► admin review ──► scan ──► opportunities+outbox ──► bot
 (Polymarket,   (catalog,   (команды→ID,    (Telegram       (Decimal-   (одна транзакция,     (карточки,
  Kalshi,        котировки   события по      /pending,       решатель    дедуп по чату и       перепроверка,
  Odds API)      → Redis)    времени, рынки) версия правил)  по сценар.) ревизии)              фильтры)
```

* **domain/** — чистый расчёт: сценарии (ничья, ОТ, тотал/пуш, отмена, перенос), модели комиссий
  (Polymarket `C·p·r·(p(1-p))^e`, Kalshi `ceil(0.07·C·P·(1-P))`), проход по стакану, FX с резервом,
  точный решатель с ограниченным перебором, вердикты «сигнал / кандидат / отказ». Только `Decimal`.
* **matching/** — реестр команд NBA/NFL/NHL/MLB/EPL с алиасами всех площадок (включая стиль Kalshi
  «Los Angeles L»), кластеризация событий по паре команд и времени (точное время ±3 ч, события «только
  дата» прикрепляются к единственному матчу этого дня, даблхедеры — по номеру игры или в ручную проверку),
  канонический ключ рынка `событие|тип|период|линия`, проверка правил, сброс одобрения при изменениях.
* **adapters/** — по пакету на поставщика + общий HTTP-клиент (лимит параллелизма, backoff с jitter,
  Retry-After, маскирование ключей) и состояние стакана для WebSocket.
* **services/** — ingest, scan, recheck, replay; **storage/** — PostgreSQL (источник истины) и Redis
  (горячие котировки с монотонной записью через Lua); **telegram/** — бот aiogram 3 и outbox-воркер.

Подробнее: [docs/architecture.md](docs/architecture.md), этап 0 — [docs/stage0-audit.md](docs/stage0-audit.md),
эксплуатация — [docs/runbook.md](docs/runbook.md), статус работ — [docs/TODO.md](docs/TODO.md).

## Быстрый старт (локально, без сети и секретов)

```bash
uv sync
uv run polybot demo            # полный конвейер на TEST DATA fixtures: парсинг → сопоставление → расчёт → карточки
uv run pytest -q               # unit-тесты (интеграционные пропускаются без БД)
uv run ruff check src tests && uv run mypy
```

Интеграционные тесты (PostgreSQL + Redis, без секретов):

```bash
export POLYBOT_TEST_DATABASE_URL=postgresql+asyncpg://polybot:polybot@localhost:5432/polybot_test
export POLYBOT_TEST_REDIS_URL=redis://localhost:6379/1
uv run pytest -q
```

## Команды

| Команда | Назначение |
|---|---|
| `polybot migrate` | применить миграции Alembic |
| `polybot run-ingest` | discovery каталога, сопоставление, опрос котировок |
| `polybot run-scan` | пересчёт по изменениям котировок/правил и по TTL |
| `polybot run-bot` | Telegram-бот (long polling) + воркер уведомлений |
| `polybot probe [--samples N --interval S --out f.json]` | этап 0: доступ, объёмы, глубина/лимиты, пересечение событий |
| `polybot replay --at 2026-01-15T23:00:00+00:00` | пересчёт по историческому снимку из БД без будущих котировок |
| `polybot demo` / `polybot replay --fixtures tests/fixtures` | офлайн-прогон на fixtures |
| `polybot mappings list|approve ID|reject ID` | админ-очередь связок из консоли |
| `polybot healthcheck` | проверка БД и Redis (используется Docker) |

## Развёртывание на VPS

1. Установить Docker + Compose, склонировать репозиторий, `cp .env.example .env` и заполнить
   (`POSTGRES_PASSWORD`, `POLYBOT_TELEGRAM_BOT_TOKEN`, `POLYBOT_ADMIN_IDS`, `POLYBOT_ODDS_API_KEY`).
2. Первый прогон этапа 0 на живых данных: `docker compose run --rm ingest probe --samples 6 --interval 600 --out /tmp/probe.json`.
3. `ops/deploy.sh <sha>` — pull образа `ghcr.io/exemoysei/polygumblescan:<sha>`, миграции (лог в `var/log/`),
   запуск `ingest`, `scan`, `bot`, `backup`, проверка health. Наружу ничего не публикуется: метрики только на
   `127.0.0.1:9101-9103`, PostgreSQL и Redis — в приватной сети Compose.
4. В Telegram админ открывает `/pending` и подтверждает связки. Сигналы появляются только по подтверждённым.

Staging-проверка без живых API: `POLYBOT_FIXTURES_DIR=/app/tests/fixtures` — бот прогоняет тестовые
события с живыми часами, так можно проверить весь путь до сообщения в Telegram.

## Основные настройки (`POLYBOT_*`)

`LEAGUES` (по умолчанию `["nba"]`), `DEFAULT_BUDGET`, `MIN_PROFIT`, `MIN_ROI`, `ROUTES`
(`prediction_prediction`, `prediction_sportsbook`; `sportsbook_sportsbook` выключен), `QUOTE_TTL_S`,
`MAX_QUOTE_SKEW_S`, `FX_STATIC` + `FX_RESERVE_BPS` (USDC не приравнивается к USD без резерва),
`SPORTSBOOK_MAX_STAKE` (известные лимиты по букмекерам), `AUTO_APPROVE_STRONG_MATCHES` (выключено: в MVP
все связки подтверждает админ). Полный список — `src/polybot/settings.py`.

## Ограничения MVP

* Только прематч, 2–3 ноги, рынки «победитель», 1X2 и тотал с половинной/целой линией.
* Котировки Odds API всегда дают **кандидатов**: лимит неизвестен, свежесть подтверждает агрегатор,
  правила букмекера по умолчанию.
* Правила площадок разбираются по ключевым словам; всё нераспознанное — `unknown` и в ручную проверку.
* Наблюдение без сделок проверяет сканер, но не подтверждает реальную доходность.
