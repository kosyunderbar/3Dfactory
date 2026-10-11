"""Explicit, wall-paced normal production using the model and ACK-confirmed source session."""
import json
import os
from pathlib import Path
import threading
import time

from .model import FactoryModel, LocationType, CellState
from .logistics import VehicleState
from . import lane_traffic
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
        if body_count not in (1, 3, 5) or body_count > model.configuration.factory['maxBodies']:
            raise ValueError('Production demo requires capacity for 1, 3 or 5 bodies')
        self.model = model
        self.body_count = body_count

    def initialize(self, change):
        for _ in range(self.body_count):
            change(self.model.register_body)
        change(self.model.redispatch)

    def enter_waiting(self, change):
        if self.model.direct_delivery:
            return  # The dispatcher schedules physical Bay -> CELL transports.
        # Admit one waiting body per empty cell, downstream first; keep normal slot/dispatch rules.
        for cell_id in ('QC-01', 'ASM-02', 'ASM-01'):
            waiting = self.model.bodies_at(LocationType.BUFFER, 'BAY-' + cell_id)
            if waiting and self.model.cell(cell_id).state == CellState.IDLE:
                change(self.model.enter_cell, waiting[0].body_id)

    def drained(self):
        return (all(body.location.location_type == LocationType.RESULT for body in self.model.bodies)
                and not self.model.active_transports
                and all(vehicle.state == VehicleState.IDLE for vehicle in self.model.vehicles)
                and lane_traffic.final_return_complete(self.model))


def run_connected(configuration, settings, *, stopped=None, evidence_root=None, max_seconds=300, body_count=1, manual_maintenance=False):
    stopped = stopped or threading.Event()
    if configuration.factory.get('traffic',{}).get('policyVersion') == 4:
        from .parts_supply import supply_configuration
        configuration = supply_configuration(configuration)
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
    maintenance = None
    if manual_maintenance:
        from .maintenance import ManualMaintenance
        def publish_maintenance(state):
            temp = evidence / 'maintenance.tmp'
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
            temp.replace(evidence / 'maintenance.json')
            print(json.dumps(dict(type='maintenance', maintenance=state), ensure_ascii=False), flush=True)
        maintenance = ManualMaintenance(model, session.change, publish_maintenance)
        maintenance.read_stdin()
        publish_maintenance(maintenance.state())
    saved = 0
    confirmed = 0
    started = time.monotonic()
    last_snapshot = 0
    last_location = None
    maintenance_wait_seconds = 0

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
            if time.monotonic() - started - maintenance_wait_seconds > max_seconds:
                raise ValueError('Connected demo exceeded its time budget; accepted originals remain in ingestion')
            cycle = time.monotonic()
            session.tick()
            if maintenance:
                maintenance.step()
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
            # Waiting for a human is not a production timeout. The factory clock
            # keeps running, including other healthy cells and vehicle movements.
            if maintenance and maintenance.active:
                maintenance_wait_seconds += time.monotonic() - cycle
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
