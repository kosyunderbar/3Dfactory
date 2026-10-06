"""Explicit, wall-paced normal production using the model and ACK-confirmed source session."""
import json
import os
from pathlib import Path
import threading
import time

from .model import FactoryModel, LocationType, CellState
from .logistics import VehicleState
from .sender import Sender, SourceSession


def artifact_root(evidence_root=None):
    configured = evidence_root or os.environ.get('CONNECTED_DEMO_ARTIFACTS')
    if configured:
        return Path(configured)
    service = Path(__file__).resolve().parent.parent
    project = service.parent.parent
    if (project / 'scripts/simulator.sh').is_file():
        return project / '.build-cache/connected-demo'
    # The container runs as an unprivileged user; /app is not writable.
    return Path('/tmp/factory-connected-demo')


class NormalDriver:
    def __init__(self, model, body_count=1):
        if body_count not in (1, 3) or body_count > model.configuration.factory['maxBodies']:
            raise ValueError('Normal demo requires capacity for 1 or 3 bodies')
        self.model = model
        self.body_count = body_count

    def initialize(self, change):
        for _ in range(self.body_count):
            change(self.model.register_body)
        change(self.model.redispatch)

    def enter_waiting(self, change):
        # Admit one waiting body per empty cell, downstream first; keep normal slot/dispatch rules.
        for cell_id in ('QC-01', 'ASM-02', 'ASM-01'):
            waiting = self.model.bodies_at(LocationType.BUFFER, 'BAY-' + cell_id)
            if waiting and self.model.cell(cell_id).state == CellState.IDLE:
                change(self.model.enter_cell, waiting[0].body_id)

    def drained(self):
        return (all(body.location.location_type == LocationType.RESULT for body in self.model.bodies)
                and not self.model.active_transports
                and all(vehicle.state == VehicleState.IDLE for vehicle in self.model.vehicles))


def run_connected(configuration, settings, *, stopped=None, evidence_root=None, max_seconds=300, body_count=1):
    stopped = stopped or threading.Event()
    model = FactoryModel(configuration, quality_results=('PASS',))
    driver = NormalDriver(model, body_count)
    evidence_root = artifact_root(evidence_root)
    evidence = evidence_root / model.run_id
    evidence.mkdir(parents=True, exist_ok=False)
    info = dict(runId=model.run_id, bodyId='body-00001', tagId='tag-00001', pid=os.getpid(),
                bodyCount=body_count, evidence=str(evidence.resolve()), state='STARTING', guiConfirmed=False)
    (evidence / 'run.json').write_text(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info), flush=True)
    # Verification-only coordination: expose the generated run before the helper checks both DBs.
    start_gate = os.environ.get('CONNECTED_DEMO_START_GATE')
    if start_gate:
        deadline = time.monotonic() + 30
        while not Path(start_gate).exists():
            if stopped.wait(.05) or time.monotonic() > deadline:
                raise ValueError('Verification start coordination timed out; no TCP write was made')
    sender = Sender(settings, error_path=evidence / 'send-errors.ndjson')
    session = SourceSession(model, sender)
    saved = 0
    confirmed = 0
    started = time.monotonic()
    last_snapshot = 0
    last_location = None

    def drain():
        nonlocal saved, confirmed
        while sender.pending:
            if stopped.is_set(): return
            original = sender.pending.head
            if original.source_seq > saved:
                with (evidence / 'originals.ndjson').open('ab') as output: output.write(original.frame)
                saved = original.source_seq
            session.send_head()
            confirmed += 1

    try:
        driver.initialize(session.change)
        session.change(model.publish_snapshot)
        drain()
        tick_seconds = configuration.factory['tickMs'] / 1000
        while not stopped.is_set():
            if time.monotonic() - started > max_seconds:
                raise ValueError('Connected demo exceeded its time budget; accepted originals remain in ingestion')
            cycle = time.monotonic()
            session.tick()
            body = model.body('body-00001')
            driver.enter_waiting(session.change)
            if driver.drained():
                session.change(model.finish_run)  # The model emits the final whole snapshot and RUN_FINISHED.
                drain()
                info.update(state='INGESTION_CONFIRMED', events=confirmed, sourceSeq=confirmed,
                            physical=model.snapshot(), operationsApplied=False, guiConfirmed=False)
                break
            if cycle - last_snapshot >= configuration.factory['snapshotIntervalMs'] / 1000:
                session.change(model.publish_snapshot)
                last_snapshot = cycle
            drain()
            location = (body.location.location_type.value, body.location.location_id, body.status.value)
            if location != last_location:
                print(json.dumps(dict(runId=model.run_id, location=location, sourceSeq=confirmed)), flush=True)
                last_location = location
            stopped.wait(max(0, tick_seconds - (time.monotonic() - cycle)))
        else:
            info.update(state='SOURCE_STOPPED', events=confirmed, physical=model.snapshot(), operationsApplied=False)
        (evidence / 'result.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({k: v for k, v in info.items() if k != 'physical'}, ensure_ascii=False), flush=True)
        return 0 if info['state'] == 'INGESTION_CONFIRMED' else 2
    except (ValueError, OSError) as error:
        info.update(state='SOURCE_FAILED', events=confirmed, physical=model.snapshot(), operationsApplied=False, error=str(error))
        (evidence / 'result.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
        raise
    finally:
        # Preserve unconfirmed originals in the local evidence file; this is not model restart recovery.
        for event in model.events:
            original = event.to_dict()
            if original['sourceSeq'] > saved:
                with (evidence / 'originals.ndjson').open('ab') as output: output.write(event.ndjson.encode('utf-8'))
                saved = original['sourceSeq']
        sender.close()
