# Runbook (VPS)

## Wdrożenie i wycofanie
* `ops/deploy.sh <sha>` — obraz dokładnie z danego commita, migracje logowane do `var/log/migrations-*.log`.
* Wycofanie: `ops/deploy.sh <poprzedni sha>` (ostatnio wdrożony — `var/deployed.env`). Migracje są pisane jako
  wstecznie zgodne; `alembic downgrade` tylko ręcznie i po wykonaniu kopii zapasowej.
* GitHub Actions: `ci` (lint, mypy, testy z PostgreSQL/Redis, obraz `ghcr.io/...:<sha>`), `deploy` — ręcznie,
  sekrety `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_APP_DIR` w środowisku `production`.

## Kopie zapasowe
* Usługa `backup`: `pg_dump -Fc` co 6 godzin do `./backups`, przechowywanie `BACKUP_KEEP_DAYS` (14 dni),
  kontrola archiwum przez `pg_restore --list`.
* **Test odtworzenia** (raz w tygodniu i po każdej zmianie schematu):
  `docker compose exec backup sh /restore_test.sh` — odtwarza ostatni zrzut do tymczasowej bazy, wypisuje
  liczbę wierszy i wersję migracji, usuwa bazę.
* Katalog `./backups` należy kopiować poza VPS (rclone/S3) — po stronie hosta.

## Restart i odtwarzanie stanu
* Wszystkie usługi mają `restart: unless-stopped`, healthcheck to `polybot healthcheck` (baza + Redis).
* Redis nie jest trwały: po restarcie kursy wracają przy następnym odpytaniu platform; sygnały zamknięte
  z powodu braku danych są reaktywowane bez ponownej wysyłki.
* Outbox przeżywa restart bota: niedokończone dzierżawy wygasają po `OUTBOX_LEASE_S`.
* Utrata połączenia z Redisem lub bazą nie zatrzymuje pętli `ingest` i `scan` — błąd jest logowany i liczony.

## Monitoring
Metryki Prometheus na `127.0.0.1:9101` (ingest), `:9102` (scan), `:9103` (bot); przykład — `ops/prometheus.yml`,
alerty — `ops/alerts.yml`. Powiadomienia techniczne trafiają do `POLYBOT_TECH_CHAT_ID` (albo do adminów).

Metryki pilotażu:

| Co | Metryka / źródło |
|---|---|
| wspólne wydarzenia | `polybot_shared_events`, `/stats` |
| zatwierdzone powiązania | `polybot_mappings{status}`, `/stats` |
| wiek kursów | `polybot_quote_age_seconds{provider}` |
| opóźnienie aktualizacja → sygnał | `polybot_signal_latency_seconds` |
| odsetek kandydatów, którzy przetrwali ponowne sprawdzenie | `polybot_rechecks_total{result}` |
| czas życia okazji | `opportunities.created_at … closed_at` |
| odrzucenia wg przyczyn | `polybot_rejections_total{reason}`, tabela `scan_rejections` |
| błędy i limity API | `polybot_feed_errors_total`, `polybot_api_quota_remaining` |
| duplikaty powiadomień | log `telegram delivery uncertain`, `polybot_outbox_total{status}` |

## Incydenty
* **Źródło niedostępne** — pozostałe działają; kursy tego źródła wygasają po TTL i wypadają z obliczeń.
* **Limit The Odds API** — zwiększyć `QUOTE_INTERVAL_S.oddsapi`, zawęzić `ODDS_API_BOOKMAKERS`/`REGIONS`.
* **Podejrzany sygnał** — `/pause` (skaner dalej liczy, wysyłka stoi), sprawdzić powiązanie, `/resume`.
* **Nowa nazwa drużyny nie została dopasowana** — `unresolved` w logach discovery →
  `/alias <liga> "<nazwa>" <team_id>`.
