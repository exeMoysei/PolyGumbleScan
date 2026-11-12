from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

QUOTES = Counter("polybot_quotes_total", "Quotes accepted into the cache", ["provider"])
QUOTES_DROPPED = Counter("polybot_quotes_dropped_total", "Late/duplicate quotes dropped", ["provider"])
QUOTE_AGE = Histogram(
    "polybot_quote_age_seconds", "Quote age at ingest", ["provider"], buckets=(1, 2, 5, 10, 30, 60, 120, 300, 600, 1800)
)
FEED_ERRORS = Counter("polybot_feed_errors_total", "Adapter failures", ["provider", "stage"])
API_QUOTA = Gauge("polybot_api_quota_remaining", "Remaining API quota", ["provider"])
EVENTS_SHARED = Gauge("polybot_shared_events", "Events listed by 2+ providers")
MAPPINGS = Gauge("polybot_mappings", "Market mappings by status", ["status"])
SCAN_SECONDS = Histogram("polybot_scan_seconds", "Scan duration")
OPPORTUNITIES = Counter("polybot_opportunities_total", "Published revisions", ["verdict", "route"])
REJECTIONS = Counter("polybot_rejections_total", "Rejected combinations", ["reason"])
SIGNAL_LATENCY = Histogram(
    "polybot_signal_latency_seconds", "Quote source time -> publish", buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300)
)
OUTBOX = Counter("polybot_outbox_total", "Notification outcomes", ["status"])
RECHECKS = Counter("polybot_rechecks_total", "Recheck outcomes", ["result"])


def serve(port: int) -> None:
    start_http_server(port)
