# Runbook (VPS)

## Деплой и откат
* `ops/deploy.sh <sha>` — образ строго по SHA коммита, миграции логируются в `var/log/migrations-*.log`.
* Откат: `ops/deploy.sh <предыдущий sha>` (последний развёрнутый — `var/deployed.env`). Миграции пишутся
  обратно совместимыми; `alembic downgrade` — только вручную после бэкапа.
* GitHub Actions: `ci` (lint, mypy, тесты с PostgreSQL/Redis, образ `ghcr.io/...:<sha>`), `deploy` — вручную,
  секреты `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_APP_DIR` в environment `production`.

## Резервные копии
* Сервис `backup`: `pg_dump -Fc` каждые 6 часов в `./backups`, хранение `BACKUP_KEEP_DAYS` (14), проверка
  архива `pg_restore --list`.
* **Тест восстановления** (раз в неделю и после изменения схемы):
  `docker compose exec backup sh /restore_test.sh` — восстанавливает последний дамп во временную БД,
  печатает число строк и версию миграции, удаляет БД.
* Копировать `./backups` за пределы VPS (rclone/S3) — на стороне хоста.

## Рестарт и восстановление
* Все сервисы `restart: unless-stopped`, healthcheck `polybot healthcheck` (БД + Redis).
* Redis не персистентный: после рестарта котировки восстанавливаются следующим опросом площадок;
  сигналы, закрытые из-за пропажи данных, реактивируются без повторной рассылки.
* Outbox переживает рестарт бота: незавершённые lease истекают через `OUTBOX_LEASE_S`.

## Мониторинг
Метрики Prometheus на `127.0.0.1:9101` (ingest), `:9102` (scan), `:9103` (bot); пример — `ops/prometheus.yml`,
алерты — `ops/alerts.yml`. Технические уведомления — в `POLYBOT_TECH_CHAT_ID` (или админам).

Метрики пилота:
| Что | Метрика / источник |
|---|---|
| общих событий | `polybot_shared_events`, `/stats` |
| подтверждённых связок | `polybot_mappings{status}`, `/stats` |
| возраст котировок | `polybot_quote_age_seconds{provider}` |
| задержка обновление → сигнал | `polybot_signal_latency_seconds` |
| доля кандидатов, переживших перепроверку | `polybot_rechecks_total{result}` |
| длительность возможностей | `opportunities.created_at … closed_at` |
| отклонения по причинам | `polybot_rejections_total{reason}`, таблица `scan_rejections` |
| ошибки и квоты API | `polybot_feed_errors_total`, `polybot_api_quota_remaining` |
| дубли уведомлений | лог `telegram delivery uncertain`, `polybot_outbox_total{status}` |

## Инциденты
* **Фид недоступен** — остальные работают; котировки фида истекают по TTL и выпадают из расчёта.
* **Квота Odds API** — увеличить `QUOTE_INTERVAL_S.oddsapi`, сузить `ODDS_API_BOOKMAKERS`/`REGIONS`.
* **Подозрительный сигнал** — `/pause` (сканер продолжает считать, рассылка стоп), разобрать связку,
  `/resume`.
* **Новое имя команды не сопоставилось** — `unresolved` в логах discovery → `/alias <league> "<имя>" <team_id>`.
