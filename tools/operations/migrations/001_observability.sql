CREATE TABLE observability_samples (
    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    quality TEXT NOT NULL CHECK(quality IN ('OBSERVED','ESTIMATED','INSUFFICIENT_DATA')),
    scope TEXT NOT NULL,
    correlation_id TEXT,
    evidence_hash TEXT,
    CHECK((quality = 'INSUFFICIENT_DATA' AND value IS NULL) OR
          (quality != 'INSUFFICIENT_DATA' AND value IS NOT NULL))
);
CREATE INDEX idx_observability_metric_time ON observability_samples(metric,scope,observed_at);

CREATE TABLE alert_rules (
    rule_id TEXT PRIMARY KEY,
    metric TEXT NOT NULL,
    comparison TEXT NOT NULL CHECK(comparison IN ('GT','GTE','LT','LTE')),
    threshold REAL NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','CRITICAL')),
    window_seconds INTEGER NOT NULL CHECK(window_seconds > 0),
    min_samples INTEGER NOT NULL CHECK(min_samples > 0),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
);

CREATE TABLE alert_instances (
    alert_key TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL REFERENCES alert_rules(rule_id),
    scope TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    severity TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    occurrences INTEGER NOT NULL CHECK(occurrences > 0),
    evidence_hash TEXT NOT NULL,
    observed_value REAL NOT NULL,
    UNIQUE(rule_id,scope)
);

CREATE TABLE incident_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL REFERENCES alert_instances(alert_key),
    event_type TEXT NOT NULL CHECK(event_type IN ('OPENED','UPDATED','ACKNOWLEDGED','RESOLVED','REOPENED')),
    observed_at INTEGER NOT NULL,
    evidence_hash TEXT NOT NULL,
    detail TEXT NOT NULL,
    UNIQUE(alert_key,event_type,evidence_hash)
);
CREATE INDEX idx_incident_events_alert ON incident_events(alert_key,observed_at);

CREATE TABLE provider_health (
    provider_id TEXT PRIMARY KEY,
    network TEXT NOT NULL,
    genesis_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('OPEN','HALF_OPEN','CLOSED')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
    opened_until INTEGER NOT NULL DEFAULT 0,
    half_open_lease_until INTEGER NOT NULL DEFAULT 0,
    window_started_at INTEGER NOT NULL DEFAULT 0,
    requests_in_window INTEGER NOT NULL DEFAULT 0 CHECK(requests_in_window >= 0),
    last_success_at INTEGER,
    last_error_code TEXT,
    updated_at INTEGER NOT NULL
);
