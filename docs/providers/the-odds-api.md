# The Odds API (v4)

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
