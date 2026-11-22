"""Prometheus metrics, served at `GET /metrics` in the text format Prometheus scrapes.

- http_requests_total / http_request_duration_seconds: every request, labelled by the
  route *template* (`/api/v1/visits/{visit_id}`), never the raw path, so ids don't create
  millions of label values.
- gate_events_total: plate reads by outcome (created / duplicate / debounced) and match.
- websocket_connections: live connections right now.

Each process keeps its own counters. With several API worker processes, Prometheus must
scrape each one (or use prometheus_client's multiprocess mode); see docs/performance.md.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

registry = CollectorRegistry(auto_describe=True)

http_requests = Counter(
    "http_requests_total",
    "HTTP requests handled",
    ["method", "route", "status"],
    registry=registry,
)
http_duration = Histogram(
    "http_request_duration_seconds",
    "Time to handle a request, by route",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=registry,
)
gate_events = Counter(
    "gate_events_total",
    "Plate reads received from cameras",
    ["status", "match"],
    registry=registry,
)
websocket_connections = Gauge(
    "websocket_connections",
    "Open WebSocket connections (guard consoles and resident apps)",
    registry=registry,
)
rate_limited = Counter(
    "rate_limited_total",
    "Requests refused with 429",
    ["scope"],
    registry=registry,
)
