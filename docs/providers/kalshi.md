# Kalshi

* **Katalog**: `GET /trade-api/v2/events?series_ticker=KXNBAGAME&status=open&with_nested_markets=true`
  (paginacja kursorem). Ticker wydarzenia `KXNBAGAME-26JAN15LALBOS` zawiera datę (czas ET) i kody; tytuł
  `Los Angeles L at Boston` podaje role (gość `at` gospodarz). Godziny startu w tickerze zwykle nie ma →
  wydarzenie „tylko data”, dołączane do meczu tego dnia (zob. architecture.md).
* **Rynki**: kontrakt binarny na każdą drużynę (oraz `Tie` w piłce nożnej). `YES` = zwycięstwo drużyny,
  `NO` = wszystkie pozostałe wyniki.
* **Arkusz zleceń**: `GET /markets/{ticker}/orderbook` — **same bidy**. Nowy format
  `orderbook_fp.{yes_dollars,no_dollars}: [["0.4500","120.00"], ...]` (napisy, możliwe ułamkowe kontrakty),
  stary — `orderbook.{yes,no}` w centach. Ask YES = 1 − bid NO z tym samym wolumenem; kolejność poziomów nie
  jest zakładana.
* **Prowizja**: `ceil_do_centa(0.07 · C · P · (1−P))` dla każdego wypełnienia (`POLYBOT_KALSHI_FEE_RATE`).
* **Waluta**: USD.
* **Zasady**: `rules_primary` + `rules_secondary`, rozpoznawane po słowach kluczowych; wszystko nierozpoznane —
  `unknown` → ręczna weryfikacja. Asymetryczne „resolves No” jest obsługiwane (`no_wins`).
* **Streaming**: WebSocket wymaga podpisanych kluczy API; w MVP nieużywany (odpytywanie REST).
