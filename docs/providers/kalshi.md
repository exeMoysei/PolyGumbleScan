# Kalshi

* **Каталог**: `GET /trade-api/v2/events?series_ticker=KXNBAGAME&status=open&with_nested_markets=true`
  (курсорная пагинация). Тикер события `KXNBAGAME-26JAN15LALBOS` содержит дату (ET) и коды; заголовок
  `Los Angeles L at Boston` даёт роли (гость `at` хозяин). Время начала в тикере обычно отсутствует →
  событие «только дата», привязка к матчу этого дня (см. architecture.md).
* **Рынки**: бинарный контракт на каждую команду (и `Tie` в футболе). `YES` = победа команды, `NO` =
  все остальные исходы.
* **Стакан**: `GET /markets/{ticker}/orderbook` — **только bids**. Новый формат
  `orderbook_fp.{yes_dollars,no_dollars}: [["0.4500","120.00"], ...]` (строки, возможны дробные контракты),
  старый — `orderbook.{yes,no}` в центах. Ask YES = 1 − bid NO с тем же объёмом; порядок уровней не
  предполагается.
* **Комиссия**: `ceil_to_cent(0.07 · C · P · (1−P))` по каждому заполнению (`POLYBOT_KALSHI_FEE_RATE`).
* **Валюта**: USD.
* **Правила**: `rules_primary` + `rules_secondary`, разбор ключевыми словами; всё нераспознанное —
  `unknown` → ручная проверка. Асимметричное «resolves No» поддержано (`no_wins`).
* **Streaming**: WebSocket требует подписанных API-ключей; в MVP не используется (REST-опрос).
