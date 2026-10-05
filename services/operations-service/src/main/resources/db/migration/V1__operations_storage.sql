-- A shared ordinal across append-only view collections, serialized until COMMIT.
-- P0 writers acquire a single run lock first; do not write multiple runs per transaction.
CREATE SEQUENCE view_record_ordinal_seq;
CREATE FUNCTION next_view_record_ordinal() RETURNS bigint
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(17010002);
    RETURN nextval('public.view_record_ordinal_seq');
END $$;

CREATE TABLE simulation_run (
    run_id text PRIMARY KEY,
    source_id text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    finished_source_seq bigint CHECK (finished_source_seq BETWEEN 1 AND 9007199254740991),
    seed bigint NOT NULL,
    config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
    processing_state text NOT NULL DEFAULT 'ACTIVE' CHECK (processing_state IN ('ACTIVE','BLOCKED')),
    blocked_reason text,
    record_ordinal bigint NOT NULL DEFAULT next_view_record_ordinal() UNIQUE,
    UNIQUE (run_id, source_id),
    CHECK ((finished_at IS NULL) = (finished_source_seq IS NULL)),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);
CREATE TABLE equipment (
    run_id text NOT NULL REFERENCES simulation_run (run_id),
    equipment_id text NOT NULL,
    cell_id text NOT NULL,
    work_duration_ms bigint NOT NULL CHECK (work_duration_ms > 0),
    x double precision NOT NULL,
    y double precision NOT NULL,
    PRIMARY KEY (run_id, equipment_id),
    UNIQUE (run_id, cell_id)
);
CREATE TABLE factory_buffer (
    run_id text NOT NULL REFERENCES simulation_run (run_id),
    buffer_id text NOT NULL,
    cell_id text NOT NULL,
    capacity integer NOT NULL CHECK (capacity BETWEEN 2 AND 4),
    slot_ids jsonb NOT NULL CHECK (jsonb_typeof(slot_ids) = 'array'),
    x double precision NOT NULL,
    y double precision NOT NULL,
    PRIMARY KEY (run_id, buffer_id),
    UNIQUE (run_id, cell_id),
    FOREIGN KEY (run_id, cell_id) REFERENCES equipment (run_id, cell_id),
    CHECK (jsonb_array_length(slot_ids) = capacity)
);
CREATE TABLE vehicle (
    run_id text NOT NULL REFERENCES simulation_run (run_id),
    vehicle_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('AGV','AMR')),
    home jsonb NOT NULL CHECK (jsonb_typeof(home) = 'object'),
    initial_position jsonb NOT NULL CHECK (jsonb_typeof(initial_position) = 'object'),
    PRIMARY KEY (run_id, vehicle_id)
);
CREATE TABLE body (
    run_id text NOT NULL REFERENCES simulation_run (run_id),
    body_id text NOT NULL,
    tag_id text NOT NULL,
    model_code text NOT NULL,
    spec_code text NOT NULL,
    created_at timestamptz NOT NULL,
    initial_location jsonb NOT NULL CHECK (jsonb_typeof(initial_location) = 'object'),
    PRIMARY KEY (run_id, body_id),
    UNIQUE (run_id, tag_id)
);

-- No run FK: a rejected RUN_STARTED must be retained before registration exists.
CREATE TABLE processed_event (
    run_id text NOT NULL,
    event_id uuid NOT NULL,
    source_id text NOT NULL,
    source_seq bigint NOT NULL CHECK (source_seq BETWEEN 1 AND 9007199254740991),
    raw_json_text text NOT NULL CHECK (octet_length(raw_json_text) BETWEEN 1 AND 65535),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    apply_status text NOT NULL CHECK (apply_status IN ('APPLIED','REJECTED')),
    result_code text NOT NULL,
    applied_at timestamptz,
    recorded_at timestamptz NOT NULL,
    rejection_reason text,
    PRIMARY KEY (run_id, event_id),
    UNIQUE (run_id, source_id, source_seq),
    CHECK ((apply_status = 'APPLIED') = (applied_at IS NOT NULL)),
    CHECK ((apply_status = 'REJECTED') = (rejection_reason IS NOT NULL)),
    CHECK (payload_hash = encode(sha256(convert_to(raw_json_text, 'UTF8')), 'hex'))
);
CREATE TABLE event_projection (
    record_ordinal bigint NOT NULL DEFAULT next_view_record_ordinal() PRIMARY KEY,
    run_id text NOT NULL,
    event_id uuid NOT NULL,
    type text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('INFO','WARN','ERROR')),
    apply_status text NOT NULL CHECK (apply_status IN ('APPLIED','REJECTED')),
    entity_id text,
    cell_id text,
    body_id text,
    vehicle_id text,
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    UNIQUE (run_id, event_id),
    FOREIGN KEY (run_id, event_id) REFERENCES processed_event (run_id, event_id)
);
CREATE TABLE factory_snapshot (
    run_id text PRIMARY KEY REFERENCES simulation_run (run_id),
    source_seq bigint NOT NULL CHECK (source_seq BETWEEN 1 AND 9007199254740991),
    event_id uuid NOT NULL,
    captured_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    state_json jsonb NOT NULL CHECK (jsonb_typeof(state_json) = 'object'),
    FOREIGN KEY (run_id, event_id) REFERENCES processed_event (run_id, event_id)
);
CREATE TABLE inspection_result (
    run_id text NOT NULL,
    inspection_id text NOT NULL,
    unit_id text NOT NULL,
    equipment_id text NOT NULL,
    result text NOT NULL CHECK (result IN ('PASS','FAIL')),
    defect_code text,
    inspected_at timestamptz NOT NULL,
    event_id uuid NOT NULL,
    PRIMARY KEY (run_id, inspection_id),
    UNIQUE (run_id, unit_id),
    FOREIGN KEY (run_id, unit_id) REFERENCES body (run_id, body_id),
    FOREIGN KEY (run_id, equipment_id) REFERENCES equipment (run_id, equipment_id),
    FOREIGN KEY (run_id, event_id) REFERENCES processed_event (run_id, event_id),
    CHECK ((result = 'FAIL') = (defect_code IS NOT NULL))
);
CREATE TABLE operation_history (
    run_id text NOT NULL,
    operation_id text NOT NULL,
    unit_id text NOT NULL,
    equipment_id text NOT NULL,
    entered_at timestamptz, -- unknown when introduced by the initial snapshot; never invent a start time
    completed_at timestamptz,
    duration_ms bigint CHECK (duration_ms >= 0),
    introduced_event_id uuid NOT NULL,
    completed_event_id uuid,
    PRIMARY KEY (run_id, operation_id),
    FOREIGN KEY (run_id, unit_id) REFERENCES body (run_id, body_id),
    FOREIGN KEY (run_id, equipment_id) REFERENCES equipment (run_id, equipment_id),
    FOREIGN KEY (run_id, introduced_event_id) REFERENCES processed_event (run_id, event_id),
    FOREIGN KEY (run_id, completed_event_id) REFERENCES processed_event (run_id, event_id),
    CHECK ((completed_at IS NULL) = (duration_ms IS NULL)),
    CHECK ((completed_at IS NULL) = (completed_event_id IS NULL)),
    CHECK (completed_at IS NULL OR completed_at >= entered_at)
);
CREATE TABLE transport_history (
    run_id text NOT NULL,
    transport_id text NOT NULL,
    vehicle_id text NOT NULL,
    route_id text NOT NULL,
    cargo_type text NOT NULL CHECK (cargo_type IN ('BODY','PARTS')),
    body_id text,
    parts_kit_id text,
    reservation_id text,
    slot_id text,
    source_location jsonb NOT NULL CHECK (jsonb_typeof(source_location) = 'object'),
    destination_location jsonb NOT NULL CHECK (jsonb_typeof(destination_location) = 'object'),
    status text NOT NULL CHECK (status IN ('ASSIGNED','IN_TRANSIT','COMPLETED','CANCELLED')),
    last_source_seq bigint NOT NULL CHECK (last_source_seq BETWEEN 1 AND 9007199254740991),
    assigned_at timestamptz NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    cancelled_at timestamptz,
    cancel_reason text,
    last_event_id uuid NOT NULL,
    PRIMARY KEY (run_id, transport_id),
    FOREIGN KEY (run_id, vehicle_id) REFERENCES vehicle (run_id, vehicle_id),
    FOREIGN KEY (run_id, body_id) REFERENCES body (run_id, body_id),
    FOREIGN KEY (run_id, last_event_id) REFERENCES processed_event (run_id, event_id),
    CHECK ((cargo_type = 'BODY' AND body_id IS NOT NULL AND parts_kit_id IS NULL)
        OR (cargo_type = 'PARTS' AND body_id IS NULL AND parts_kit_id IS NOT NULL AND reservation_id IS NULL AND slot_id IS NULL)),
    CHECK ((reservation_id IS NULL) = (slot_id IS NULL)),
    CHECK ((status = 'COMPLETED') = (completed_at IS NOT NULL)),
    CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL)),
    CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL)),
    CHECK (status NOT IN ('IN_TRANSIT','COMPLETED') OR started_at IS NOT NULL),
    CHECK (status <> 'CANCELLED' OR (cargo_type = 'BODY' AND started_at IS NULL)),
    CHECK (started_at IS NULL OR started_at >= assigned_at),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    CHECK (cancelled_at IS NULL OR cancelled_at >= assigned_at)
);
CREATE UNIQUE INDEX transport_active_vehicle_idx ON transport_history (run_id, vehicle_id)
    WHERE status IN ('ASSIGNED','IN_TRANSIT');
CREATE UNIQUE INDEX transport_active_body_idx ON transport_history (run_id, body_id)
    WHERE status IN ('ASSIGNED','IN_TRANSIT') AND body_id IS NOT NULL;
CREATE UNIQUE INDEX operation_active_equipment_idx ON operation_history (run_id, equipment_id)
    WHERE completed_at IS NULL;

CREATE TABLE alarm (
    alarm_id uuid PRIMARY KEY,
    record_ordinal bigint NOT NULL DEFAULT next_view_record_ordinal() UNIQUE,
    run_id text NOT NULL REFERENCES simulation_run (run_id),
    target_id text NOT NULL,
    type text NOT NULL CHECK (type IN ('EQUIPMENT_DOWN','BUFFER_FULL','SOURCE_STALE','SOURCE_DISCONNECTED','PROCESSING_BLOCKED','QUALITY_WARNING')),
    severity text NOT NULL CHECK (severity IN ('INFO','WARNING','CRITICAL')),
    occurred_at timestamptz NOT NULL,
    last_observed_at timestamptz NOT NULL,
    resolved_at timestamptz,
    acknowledged_at timestamptz,
    acknowledged_by text,
    message text NOT NULL,
    CHECK ((acknowledged_at IS NULL) = (acknowledged_by IS NULL)),
    CHECK (resolved_at IS NULL OR resolved_at >= occurred_at),
    CHECK (acknowledged_at IS NULL OR acknowledged_at >= occurred_at)
);
CREATE UNIQUE INDEX alarm_active_idx ON alarm (run_id, target_id, type) WHERE resolved_at IS NULL;
CREATE TABLE alarm_note (
    note_id uuid PRIMARY KEY,
    alarm_id uuid NOT NULL REFERENCES alarm (alarm_id),
    author text NOT NULL,
    body text NOT NULL,
    created_at timestamptz NOT NULL
);
-- alarm_note is a reserved P1 schema only; no P1 endpoint is implemented.
CREATE INDEX event_time_idx ON event_projection (run_id, occurred_at DESC, event_id DESC);
CREATE INDEX event_body_time_idx ON event_projection (run_id, body_id, occurred_at DESC);
CREATE INDEX event_cell_time_idx ON event_projection (run_id, cell_id, occurred_at DESC);
CREATE INDEX event_vehicle_time_idx ON event_projection (run_id, vehicle_id, occurred_at DESC);
CREATE INDEX inspection_time_idx ON inspection_result (run_id, inspected_at);
CREATE INDEX alarm_time_idx ON alarm (run_id, occurred_at DESC);
REVOKE INSERT, UPDATE, DELETE ON flyway_schema_history FROM operations_app;
