# Polymarket

* **Katalog i zasady**: Gamma API `GET /events?tag_slug=<liga>&active=true&closed=false` (paginacja
  `limit/offset`). Rynek ma: `outcomes` i `clobTokenIds` (napisy JSON), `gameStartTime`, `sportsMarketType`,
  `line`, `description` (zasady), `acceptingOrders`, `orderMinSize`. Slug wydarzenia `nba-lal-bos-RRRR-MM-DD`
  zawiera kody drużyn i datę — dodatkowy sygnał przy dopasowaniu.
* **Arkusz zleceń**: CLOB `POST /books` (paczka `[{token_id}]`) / `GET /book?token_id=`. Używane są **aski**;
  kolejność poziomów nie jest zakładana — adapter sortuje sam. `min_order_size`, `tick_size`.
* **Prowizja**: `fee = C · p · r · (p·(1−p))^e` dla każdego wypełnienia, parametry rynku `fd = {r, e, to}`;
  jeśli rynek ich nie podaje — `POLYBOT_POLYMARKET_FEE_RATE/EXPONENT`. Zaokrąglenie w górę do 0.0001.
* **Waluta**: USDC (pUSD) — przeliczenie na walutę budżetu wg `FX_STATIC` z rezerwą `FX_RESERVE_BPS`.
* **Zasady (typowe rynki sportowe)**: odwołanie bez powtórki → 50-50 (`half`), przełożenie → rynek czeka na
  rozegranie (`carry`), „includes overtime” dla NBA. Piłka nożna: 90 minut + czas doliczony.
* **Streaming**: `wss://ws-subscriptions-clob.polymarket.com/ws/market` (`book` — zrzut, `price_change` —
  delty). Brak numerów sekwencji: po ponownym połączeniu arkusz jest nieważny do nowego zrzutu, odpytywanie
  REST pozostaje zabezpieczeniem. Włączane przez `POLYBOT_POLYMARKET_WS=true`.
* **Otwarte pytania do probe**: stabilność `conditionId`, opóźnienie `book.timestamp`, faktyczne parametry
  prowizji rynków sportowych, ograniczenia regionalne.
