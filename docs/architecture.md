# Architektura PolyBot

Modularny monolit: jeden pakiet i jeden obraz, trzy procesy (`run-ingest`, `run-scan`, `run-bot`) skalowane
niezależnie. PostgreSQL jest źródłem prawdy; Redis przechowuje tylko bieżące kursy (odtwarzane ze zrzutów
platform) oraz strumień zmian dla skanera.

## Przepływ danych

1. **Discovery** (`services/ingest.py`, co `DISCOVERY_INTERVAL_S`): każdy adapter zwraca `ProviderEvent`
   i `ProviderMarket` z rozpoznanymi zasadami (`RuleSet`). Awaria jednego źródła nie zatrzymuje pozostałych.
2. **Dopasowanie wydarzeń** (`matching/events.py`):
   * nazwa → stabilne ID drużyny (`TeamRegistry`): dokładny alias → kod platformy → „zawiera dokładnie jeden
     alias” → porównanie rozmyte (rapidfuzz, próg 88 i odstęp 6 od drugiego kandydata). Dopasowanie rozmyte
     nigdy nie jest uznawane za pewne i zawsze trafia do weryfikacji. Niejednoznaczne aliasy (np. „Los Angeles”
     w NBA) są automatycznie usuwane ze słownika;
   * grupowanie po `(liga, nieuporządkowana para drużyn)`, potem po czasie startu: dokładne czasy w oknie 3 h,
     najbliższy klaster, najwyżej jedno wydarzenie danej platformy w klastrze;
   * wydarzenia „tylko data” (Kalshi) są dołączane do jedynego meczu tego lokalnego dnia ligi; przy
     doubleheaderze — po numerze gry, w przeciwnym razie osobny klaster `ambiguous_doubleheader`;
   * role gospodarz/gość ustalane głosowaniem platform, konflikt → `role_conflict`;
   * pewność (`confidence`) spada za rozmyte nazwy, rozbieżność czasu i konflikt ról.
3. **Dopasowanie rynków** (`matching/markets.py`): klucz `wydarzenie|typ|okres[|linia]`. Wyniki zamieniane są
   na kanoniczne `Selection` (w których zwykłych scenariuszach wygrywają, gdzie jest zwrot, gdzie wynik zależy
   od zasad platformy). „Nie” na kontrakcie binarnym = wszystkie scenariusze poza „tak”. Brakujące zasady
   (`unknown`) i zasady domyślne → `needs_review`.
4. **Ręczna weryfikacja**: `/pending` w Telegramie albo `polybot mappings`. Akceptacja zapisuje wersję zasad
   i parametry (drużyny, czas, typ, okres, linia). Każda zmiana → `invalidated`, aktywne sygnały dla klucza
   są zamykane.
5. **Kursy**: tylko dla zatwierdzonych rynków. Zapis do Redisa jest monotoniczny (Lua): starszy lub powtórzony
   kurs jest odrzucany. Każdy zapis to zdarzenie w `pb:changes`. Historia — w `quote_snapshots`
   (ograniczony czas przechowywania).
6. **Skan** (`services/scan.py` → `services/scanner.py`): przeliczenie kluczy, dla których przyszły zmiany
   (z debounce), pełne przeliczenie co 30 s (TTL). Filtry: status, TTL per źródło, różnica czasu między nogami,
   kurs walut, start wydarzenia. Kombinacje 2–3 nóg pokrywające wszystkie zwykłe scenariusze bez nakładania się,
   na różnych platformach; trasa musi być włączona.
7. **Publikacja**: przed zapisem sprawdzane jest, czy kursy wejściowe się nie zmieniły. Okazja i wpisy outbox
   zapisywane są w jednej transakcji; deduplikacja po `(czat, fingerprint, rewizja)`; nowa rewizja tylko przy
   istotnej zmianie (werdykt, rozmiary, ceny, zysk w krokach 0.5). Identyczny sygnał zamknięty z powodu braku
   danych (restart, awaria źródła) jest reaktywowany bez ponownego powiadomienia.
8. **Powiadomienia** (`telegram/notifier.py`): pobranie z dzierżawą (`FOR UPDATE SKIP LOCKED`), backoff,
   rezygnacja po wygaśnięciu sygnału; przy niepewnej odpowiedzi Telegrama — ponowienie z wpisem w logu
   (możliwy duplikat).

## Matematyka

* Wstępna selekcja dla podziału liniowego: `S = Σ 1/dᵢ` po najlepszych cenach z prowizją — to dolna granica
  kosztu, więc `S ≥ 1` pewnie odrzuca. `S < 1` to tylko kandydat dla solvera.
* Decyzja zapada na scenariuszach: `pnl[s] = Σ cashflow(noga, s) − Σ koszt_całkowity(noga)`, gdzie koszt to
  przejście po poziomach arkusza + prowizja wg modelu platformy + kurs walut z rezerwą na niekorzyść
  użytkownika; wypłata bukmachera zaokrąglana w dół do centa; przy zwrocie wraca tylko nominał, prowizje nie.
* Solver: kotwicą jest noga z najmniejszą liczbą dopuszczalnych rozmiarów; dla pozostałych sprawdzane są
  sąsiednie dopuszczalne rozmiary wokół punktu równej wypłaty oraz granice. Przeszukiwanie jest ograniczone
  (`solver_limit`). Wybór: maksimum najmniejszego zysku w zwykłych scenariuszach, przy remisie mniejszy wkład.
  Plany bez straty w opisanych wyjątkach dają „zwykły” sygnał; najlepszy plan bez tego ograniczenia — osobnego
  „kandydata”.
* Przełożenie: jeśli obie pozycje „czekają na rozegranie”, scenariusz równa się najgorszemu zwykłemu; jeśli
  jedna strona jest anulowana, pozostała pozycja w najgorszym razie przegrywa.
* Werdykt: sygnał tylko wtedy, gdy minimum przekracza progi kwotowy i procentowy, limity są znane, świeżość
  potwierdza sama platforma i nie ma straty w wyjątkach. W przeciwnym razie — kandydat z listą powodów.

## Model danych (PostgreSQL)

`providers`, `canonical_events`, `provider_events`, `rule_sets`, `markets`, `outcomes`, `market_mappings`,
`quote_snapshots`, `opportunities`, `scan_rejections`, `subscriptions`, `outbox`, `hidden_opportunities`,
`system_flags`, `team_aliases`, `admin_actions`. Zewnętrzne ID są unikalne w obrębie dostawcy, kwoty i ceny to
`NUMERIC`, daty w UTC. Schemat tworzy migracja `migrations/versions/*_0001_initial_schema.py`.
