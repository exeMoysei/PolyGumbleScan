# Źródła danych

Przed podłączeniem każdego źródła wykonywany jest probe (`polybot probe`): dostęp, limity, częstotliwość
aktualizacji, prawa do używania i przekazywania danych, zasady rozliczania, stabilność identyfikatorów,
kompletność limitów oraz część wspólna z działającymi źródłami. Platformy bez pasującej linii na zewnętrzne
wydarzenie nie wchodzą do obliczeń.

| Dostawca | Moduł | Stan | Na żywo (26.11.2026) |
|---|---|---|---|
| Polymarket (Gamma, CLOB) | `data/polymarket.py` | gotowy (REST + opcjonalny WebSocket) | ✅ działa, bez klucza |
| Polymarket Data API v2 | `data/polymarket_users.py` | gotowy | ✅ działa, bez klucza |
| Kalshi | `data/kalshi.py` | gotowy (REST, paczki arkuszy) | ✅ działa, bez klucza |
| The Odds API | `data/odds_api.py` | gotowy (REST) | ⏳ potrzebny klucz |
| Kasyna | `data/casino.py` | szkielet | ⏳ decyzja o źródle |

Blokada „403” występowała tylko w środowisku deweloperskim (ograniczona sieć), nie zależy od kraju. Polymarket
ogranicza w niektórych krajach handel, a nie odczyt danych — botowi wystarcza odczyt.

## Polymarket

* **Katalog i zasady**: Gamma API `GET /events?tag_slug=<liga>&active=true&closed=false` (paginacja
  `limit/offset`). Rynek ma: `outcomes` i `clobTokenIds` (napisy JSON), `gameStartTime`, `sportsMarketType`,
  `line`, `description` (zasady), `acceptingOrders`, `orderMinSize`. Slug wydarzenia `nba-lal-bos-RRRR-MM-DD`
  zawiera kody drużyn i datę — dodatkowy sygnał przy dopasowaniu.
* **Arkusz zleceń**: CLOB `POST /books` (paczka `[{token_id}]`) / `GET /book?token_id=`. Używane są **aski**;
  kolejność poziomów nie jest zakładana — adapter sortuje sam. `min_order_size`, `tick_size`.
* **Prowizja**: `fee = C · p · r · (p·(1−p))^e` dla każdego wypełnienia. Parametry z rynku Gamma:
  `feesEnabled` + `feeSchedule = {rate, exponent, takerOnly}` (26.11.2026: 0.05 sport, 0.01 ekonomia/krypto);
  starszy format CLOB `fd = {r, e}`; gdy brak — `POLYBOT_POLYMARKET_FEE_RATE/EXPONENT`. Zaokrąglenie w górę do 0.0001.
* **Świeżość**: `timestamp` w odpowiedzi `/books` to czas ostatniej zmiany arkusza (na spokojnych rynkach sprzed
  kilku minut), więc świeżość kursu liczy się od chwili pobrania.
* **Waluta**: USDC (pUSD) — przeliczenie na walutę budżetu wg `FX_STATIC` z rezerwą `FX_RESERVE_BPS`.
* **Zasady (rynki sportowe, 26.11.2026)**: „if the game is canceled, does not start by <data>, or is abandoned …
  resolve 50-50” → odwołanie i przełożenie po terminie = 50-50 (`half`); dogrywka wliczona w NBA. Piłka nożna:
  90 minut + czas doliczony. Wydarzenia poboczne („… - Total Corners”, „… - More Markets”) są pomijane.
* **Streaming**: `wss://ws-subscriptions-clob.polymarket.com/ws/market` (`book` — zrzut, `price_change` —
  delty). Brak numerów sekwencji: po ponownym połączeniu arkusz jest nieważny do nowego zrzutu, odpytywanie
  REST pozostaje zabezpieczeniem. Włączane przez `POLYBOT_POLYMARKET_WS=true`.


### Polymarket Data API v2 (portfele, ranking)

Publiczne, bez klucza: `https://data-api.polymarket.com/v2`. Wersja v1 i `lb-api.polymarket.com` zostały wyłączone
(HTTP 410, sprawdzone 26.11.2026). Klient: `src/polybot/data/polymarket_users.py`.

| Endpoint | Parametry (sprawdzone na żywo) | Do czego |
|---|---|---|
| `/v2/trades` | `limit` ≤ 1000, `user`, `filter_type=CASH` + `filter_amount` | duże zakłady (US6), transakcje obserwowanych portfeli (US7) |
| `/v2/activity` | `user` (wymagany), `limit` | historia portfela — czy jest „nowy” |
| `/v2/positions` | `user` lub `condition` | pozycje portfela (profil, US35) |
| `/v2/leaderboard` | `time_period` day/week/month/all, `sort_by` PNL/VOLUME, `category`, `limit` | ranking (US9) |

Odpowiedź: `{"data": [...], "pagination": {"has_more", "next_cursor"}}`, najnowsze najpierw.

### Polymarket: suma YES < 1 (US3)

Wydarzenia `negRisk: true` mają wyniki wzajemnie wykluczające się i wyczerpujące: dokładnie jedno YES płaci 1 USDC.
Pomijane są wydarzenia `negRiskAugmented: true` (lista wyników może się wydłużyć) i wydarzenia, w których któryś
wynik już rozstrzygnięto na YES. Prowizja: `feeSchedule.rate` rynku (np. 0.01 ekonomia, 0.05 sport).
26.11.2026: 93 takie wydarzenia, jedno z realnym zyskiem (+0.57 USDC na 93 USDC).

## Kalshi

* **Katalog**: `GET /trade-api/v2/events?series_ticker=KXNBAGAME&status=open&with_nested_markets=true`
  (paginacja kursorem). Ticker wydarzenia `KXNBAGAME-26JAN15LALBOS` zawiera datę (czas ET) i kody; tytuł
  `Los Angeles L at Boston` podaje role (gość `at` gospodarz). Godziny startu w tickerze zwykle nie ma →
  wydarzenie „tylko data”, dołączane do meczu tego dnia (zob. architecture.md).
* **Rynki**: kontrakt binarny na każdą drużynę (oraz `Tie` w piłce nożnej). `YES` = zwycięstwo drużyny,
  `NO` = wszystkie pozostałe wyniki.
* **Arkusz zleceń**: paczkami `GET /markets/orderbooks?tickers=A&tickers=B` (po 20; każdy arkusz ma pole `ticker`),
  a gdy paczka zawiedzie — `GET /markets/{ticker}/orderbook`. **Same bidy**. Nowy format
  `orderbook_fp.{yes_dollars,no_dollars}: [["0.4500","120.00"], ...]` (napisy, możliwe ułamkowe kontrakty),
  stary — `orderbook.{yes,no}` w centach. Ask YES = 1 − bid NO z tym samym wolumenem; kolejność poziomów nie
  jest zakładana.
* **Prowizja**: `ceil_do_centa(0.07 · C · P · (1−P))` dla każdego wypełnienia (`POLYBOT_KALSHI_FEE_RATE`).
* **Waluta**: USD.
* **Zasady**: `rules_primary` + `rules_secondary`, rozpoznawane po słowach kluczowych; wszystko nierozpoznane —
  `unknown` → ręczna weryfikacja. Asymetryczne „resolves No” jest obsługiwane (`no_wins`). Od listopada 2026
  Kalshi przy odwołaniu lub przełożeniu o ponad 48 h rozlicza po „fair price” — wartość nieznana z góry, więc
  zostaje `unknown`, a kombinacja z Kalshi jest najwyżej „kandydatem”, dopóki admin nie oceni ryzyka.
* **Streaming**: WebSocket wymaga podpisanych kluczy API; w MVP nieużywany (odpytywanie REST).

## The Odds API (v4)

* `GET /v4/sports/{sport}/odds?regions=<r>&markets=h2h,totals&oddsFormat=decimal&dateFormat=iso&includeLinks=true`.
  Jedno zapytanie zwraca wydarzenia, bukmacherów i ceny. Limit: koszt = rynki × regiony; nagłówki
  `x-requests-remaining/used/last` trafiają do metryki `polybot_api_quota_remaining`.
* **Platforma** = marka bukmachera + region: `oddsapi:<bookmaker_key>:<region>`; źródłem danych jest `oddsapi`.
  Każdy region jest pobierany osobnym zapytaniem, żeby etykieta była dokładna.
* Przy kursie zapisywane są `bookmaker`, `last_update` (rynku lub bukmachera) i region. Świeżość potwierdza
  **tylko agregator**, limit jest **unknown** → takie kombinacje to zawsze „kandydaci”.
* `h2h` z wynikiem `Draw` → 1X2 (czas regulaminowy); bez remisu → zwycięzca z dogrywką. `totals` — wg `point`.
* Zasady bukmachera są **domyślne** (odwołanie/przełożenie → void, remis w dwudrogowym rynku NFL → push),
  oznaczone `assumed` i wymagają potwierdzenia przez admina. Znane limity podaje się w
  `POLYBOT_SPORTSBOOK_MAX_STAKE`.
* Odpytywanie co `QUOTE_INTERVAL_S.oddsapi` (domyślnie 300 s) i tylko wtedy, gdy istnieją zatwierdzone
  powiązania — żeby nie zużywać limitu.

## Kasyna

Brak oficjalnego publicznego API zakładów w dużych kasynach. Opcje i rekomendacja: [podzial-pracy.md](podzial-pracy.md#kasyna-us10--decyzja-do-podjęcia).
