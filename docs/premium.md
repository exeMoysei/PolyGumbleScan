# Subskrypcja premium (US12)

Autor: Mikhailo Ivanyshyn (Orlixx003), Sprint 4, issue #12.

## Cel

Klient bez opłaty może sprawdzić, jak działa bot, ale dostaje ograniczoną liczbę alertów.
Klient Premium dostaje wszystkie alerty. Płatność odbywa się w Telegramie (Telegram Stars),
więc nie potrzebujemy zewnętrznego operatora płatności ani przechowywania danych kart.

## Plany

| | Free | Premium |
|---|---|---|
| Alerty push | do `FREE_DAILY_ALERTS` (domyślnie 3) w ciągu ostatnich 24 h | bez limitu |
| `/signals` | `FREE_SIGNALS_SHOWN` kart (domyślnie 1) + informacja, ile jest ukrytych | wszystkie aktywne (do 5) |
| `/budget` | do `FREE_MAX_BUDGET` (domyślnie 250) | do `MAX_BUDGET` |

Ceny ustawia się w `POLYBOT_PREMIUM_PLANS` jako JSON „liczba dni → cena w Stars”, domyślnie
`{"30": 250, "90": 600}`. Ponowny zakup **przedłuża** aktywny okres (nie traci się dni); po wygaśnięciu
okres liczy się od chwili zakupu.

Funkcja jest **domyślnie wyłączona** (`POLYBOT_PREMIUM_ENABLED=false`): wtedy wszyscy mają pełny produkt,
a polecenia `/premium` i płatności nie są rejestrowane. Dzięki temu scalenie kodu nie zmienia działania bota,
dopóki zespół świadomie go nie włączy.

## Przepływ płatności

```
/premium ─► przycisk planu ─► faktura (XTR) ─► pre_checkout_query ─► successful_payment ─► premium_until += dni
                                                (sprawdzenie planu,       (zapis w payments,
                                                 waluty i kwoty)           raz na charge_id)
```

* `pre_checkout_query` odrzuca fakturę, jeśli plan już nie istnieje albo zmieniła się cena/waluta.
* `successful_payment` jest idempotentne: unikalny `telegram_payment_charge_id` w tabeli `payments`,
  więc ponownie dostarczona aktualizacja nie przedłuży subskrypcji drugi raz.
* Jeśli użytkownik zapłacił przed `/start`, subskrypcja jest tworzona — płatność nigdy nie przepada.
* `/paysupport` — kontakt w sprawie płatności (wymóg Telegrama dla botów z płatnościami),
  kontakt ustawia `POLYBOT_SUPPORT_CONTACT`.

## Gdzie działa limit

Limit alertów jest sprawdzany w `repo.publish_draft` — w tej samej transakcji, w której powstają wiersze
`outbox`. Liczone są wiersze `outbox` typu `signal` i `update` danego czatu z ostatnich 24 godzin
(okno kroczące). Czat Premium jest pomijany przy liczeniu. Wiadomości techniczne i administracyjne nie
wliczają się do limitu.

## Kod

| Plik | Zawartość |
|---|---|
| `src/polybot/domain/premium.py` | czyste reguły: plany, przedłużanie, limity, format payloadu faktury (tylko biblioteka standardowa) |
| `src/polybot/services/premium.py` | plany i limity z ustawień |
| `src/polybot/storage/premium.py` | zapytania: liczba alertów, płatności, `/grant`, `/revoke`, statystyki |
| `src/polybot/telegram/premium.py` | polecenia i obsługa płatności w aiogram 3 |
| `migrations/versions/20261113_0002_premium_subscription.py` | kolumna `subscriptions.premium_until`, tabela `payments` |
| `tests/unit/test_premium.py`, `tests/integration/test_premium.py` | testy |

## Polecenia admina

* `/grant <chat_id> <dni>` — przyznaje lub przedłuża Premium (np. prezent, rekompensata).
* `/revoke <chat_id>` — odbiera Premium.
* `/premium` u admina pokazuje też liczbę aktywnych Premium i płatności z 30 dni.

Każda akcja admina trafia do tabeli `admin_actions`.

## Poza zakresem

Zwroty Stars (`refundStarPayment`) wykonuje się na razie ręcznie; automatyczne powiadomienie o końcu
Premium i rabaty — w kolejnych iteracjach.
