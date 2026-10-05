-- Original report storage belongs exclusively to ingestion_db.
CREATE TABLE delivery_stream (
    run_id text PRIMARY KEY,
    source_id text NOT NULL,
    next_source_seq bigint NOT NULL DEFAULT 1 CHECK (next_source_seq BETWEEN 1 AND 9007199254740991),
    state text NOT NULL DEFAULT 'ACTIVE' CHECK (state IN ('ACTIVE','RETRY_WAIT','GAP_WAIT','PAUSED_RETRY','PAUSED_GAP','PAUSED_DEPENDENCY','PAUSED_CONFIG','BLOCKED')),
    blocked_seq bigint CHECK (blocked_seq BETWEEN 1 AND 9007199254740991),
    blocked_reason text,
    gap_started_at timestamptz,
    diagnostic_rejected_count bigint NOT NULL DEFAULT 0 CHECK (diagnostic_rejected_count >= 0),
    diagnostic_retry_count bigint NOT NULL DEFAULT 0 CHECK (diagnostic_retry_count >= 0),
    UNIQUE (run_id, source_id),
    CHECK ((blocked_seq IS NULL) = (blocked_reason IS NULL))
);

CREATE TABLE raw_event (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id text NOT NULL,
    event_id uuid NOT NULL,
    source_id text NOT NULL,
    source_seq bigint NOT NULL CHECK (source_seq BETWEEN 1 AND 9007199254740991),
    schema_version integer NOT NULL CHECK (schema_version = 1),
    type text NOT NULL CHECK (type IN ('RUN_STARTED','RUN_STATE_CHANGED','FACTORY_SNAPSHOT','BODY_REGISTERED','SLOT_RESERVED','SLOT_RELEASED','BODY_ENTERED_CELL','TELEMETRY_UPDATED','EQUIPMENT_STATE_CHANGED','OPERATION_COMPLETED','INSPECTION_COMPLETED','TRANSPORT_ASSIGNED','TRANSPORT_STARTED','TRANSPORT_COMPLETED','TRANSPORT_CANCELLED','SCENARIO_CHANGED','RUN_FINISHED')),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    raw_json_text text NOT NULL CHECK (octet_length(raw_json_text) BETWEEN 1 AND 65535),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (run_id, event_id),
    UNIQUE (run_id, source_id, source_seq),
    FOREIGN KEY (run_id, source_id) REFERENCES delivery_stream (run_id, source_id),
    CHECK (payload_hash = encode(sha256(convert_to(raw_json_text, 'UTF8')), 'hex'))
);

CREATE TABLE event_outbox (
    run_id text NOT NULL,
    event_id uuid NOT NULL,
    delivery_status text NOT NULL DEFAULT 'PENDING' CHECK (delivery_status IN ('PENDING','RETRY_WAIT','DELIVERED','QUARANTINED')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 20),
    next_attempt_at timestamptz,
    dependency_wait_started_at timestamptz,
    last_error text,
    last_response jsonb,
    delivered_at timestamptz,
    quarantined_at timestamptz,
    PRIMARY KEY (run_id, event_id),
    FOREIGN KEY (run_id, event_id) REFERENCES raw_event (run_id, event_id),
    CHECK ((delivery_status = 'DELIVERED') = (delivered_at IS NOT NULL)),
    CHECK ((delivery_status = 'QUARANTINED') = (quarantined_at IS NOT NULL))
);
CREATE INDEX outbox_pending_idx ON event_outbox (next_attempt_at, run_id)
    WHERE delivery_status IN ('PENDING','RETRY_WAIT');
CREATE INDEX raw_event_received_idx ON raw_event (received_at);

-- App code may inspect versions but must not rewrite migration history.
REVOKE INSERT, UPDATE, DELETE ON flyway_schema_history FROM ingestion_app;
