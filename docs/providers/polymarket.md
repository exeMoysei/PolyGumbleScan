# Polymarket

* **Каталог и правила**: Gamma API `GET /events?tag_slug=<league>&active=true&closed=false` (пагинация
  `limit/offset`). У рынка: `outcomes` и `clobTokenIds` (JSON-строки), `gameStartTime`, `sportsMarketType`,
  `line`, `description` (правила), `acceptingOrders`, `orderMinSize`. Слаг события `nba-lal-bos-YYYY-MM-DD`
  даёт коды команд и дату — дополнительный сигнал сопоставления.
* **Стакан**: CLOB `POST /books` (батч `[{token_id}]`) / `GET /book?token_id=`. Используются **asks**;
  порядок уровней не предполагается — адаптер сортирует сам. `min_order_size`, `tick_size`.
* **Комиссия**: `fee = C · p · r · (p·(1−p))^e` по каждому заполнению, параметры рынка `fd = {r, e, to}`;
  если рынок их не сообщает — `POLYBOT_POLYMARKET_FEE_RATE/EXPONENT`. Округление вверх до 0.0001.
* **Валюта**: USDC (pUSD) — конвертация в валюту бюджета по `FX_STATIC` с резервом `FX_RESERVE_BPS`.
* **Правила (типовые спорт-рынки)**: отмена без переигровки → 50-50 (`half`), перенос → рынок ждёт
  переигровку (`carry`), «includes overtime» для NBA. Футбол: 90 минут + компенсированное время.
* **Streaming**: `wss://ws-subscriptions-clob.polymarket.com/ws/market` (`book` — снапшот, `price_change` —
  дельты). Номеров последовательности нет: после переподключения стакан невалиден до нового снапшота,
  REST-опрос остаётся страховкой. Включается `POLYBOT_POLYMARKET_WS=true`.
* **Открытые вопросы для probe**: стабильность `conditionId`, задержка `book.timestamp`, фактические
  параметры комиссии спорт-рынков, ограничения по регионам.
