-- Additive upgrade: preserve every V1 original, outbox status and stream cursor.
ALTER TABLE event_outbox
    ADD COLUMN total_attempt_count bigint NOT NULL DEFAULT 0 CHECK (total_attempt_count >= 0),
    ADD COLUMN last_attempt_at timestamptz;
UPDATE event_outbox SET total_attempt_count=attempt_count;

CREATE TABLE delivery_action (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id text NOT NULL,
    source_id text NOT NULL,
    source_seq bigint NOT NULL CHECK (source_seq BETWEEN 1 AND 9007199254740991),
    action text NOT NULL CHECK (action = 'RESUME'),
    previous_state text NOT NULL CHECK (previous_state IN ('PAUSED_RETRY','PAUSED_DEPENDENCY','PAUSED_CONFIG')),
    operator_id text NOT NULL CHECK (operator_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    reason text NOT NULL CHECK (octet_length(reason) BETWEEN 1 AND 1024),
    recorded_at timestamptz NOT NULL,
    FOREIGN KEY (run_id,source_id) REFERENCES delivery_stream(run_id,source_id)
);
CREATE INDEX delivery_action_run_idx ON delivery_action(run_id,id);
