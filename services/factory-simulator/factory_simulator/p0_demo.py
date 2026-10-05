"""Explicit P0 observation scenario. Normal registrations and model commands only; no DTO fabrication."""
import json
import os
from pathlib import Path
import threading
import time
from .connected_demo import artifact_root
from .model import FactoryModel, LocationType, CellState
from .logistics import VehicleState
from .sender import Sender, SourceSession

STAGES=('FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED','FINISHED')

class P0Driver:
    def __init__(self, model):
        self.model=model
        self.stage=0
        self.entry_allowed=False
    def initialize(self, change):
        capacity=self.model.buffer('BAY-ASM-02')['capacity']
        if self.model.configuration.factory['maxBodies']<capacity+2:
            raise ValueError('P0 demo requires maxBodies >= ASM-02 capacity + 2')
        for _ in range(capacity+2):change(self.model.register_body)
        decision=change(self.model.assign_parts,'ASM-01')
        if decision.approved:change(self.model.start_transport,decision.transport_id)
        change(self.model.redispatch)
    def step(self, change):
        model=self.model
        change(model.tick)
        for cell in ('QC-01','ASM-02','ASM-01'):
            if cell=='ASM-02' and not self.entry_allowed:continue
            waiting=model.bodies_at(LocationType.BUFFER,'BAY-'+cell)
            if waiting and model.cell(cell).state==CellState.IDLE:change(model.enter_cell,waiting[0].body_id)
        bay=model.buffer('BAY-ASM-02')
        incoming=next((t for t in model.active_transports if t.destination.location_id=='BAY-ASM-02'),None)
        stage=None
        if self.stage==0 and bay['waitingCount']==bay['capacity']-1 and bay['reservedInboundCount']==1 and incoming and incoming.status.value=='ASSIGNED':
            stage='FULL_RESERVED'
        elif self.stage==1 and incoming and incoming.status.value=='IN_TRANSIT':
            stage='FULL_IN_TRANSIT'
        elif self.stage==2 and bay['waitingCount']==bay['capacity'] and bay['reservedInboundCount']==0 and model.cell('ASM-01').blocked_reason=='BUFFER_FULL':
            stage='FULL_ARRIVED'
        if stage:self.stage+=1
        return stage
    def after(self, stage, change):
        if stage=='FULL_ARRIVED':
            change(self.model.fail_cell,'ASM-01');self.stage+=1;return 'CELL_DOWN'
        if stage=='CELL_DOWN':
            change(self.model.recover_cell,'ASM-01')
            waiting=self.model.bodies_at(LocationType.BUFFER,'BAY-ASM-02')
            change(self.model.enter_cell,waiting[0].body_id)
            self.entry_allowed=True;self.stage+=1;return 'SLOT_RELEASED'
        return None
    def drained(self):
        return all(b.location.location_type==LocationType.RESULT for b in self.model.bodies) and not self.model.active_transports and all(v.state==VehicleState.IDLE for v in self.model.vehicles)


def run_p0(configuration,settings,*,stopped=None,max_seconds=600):
    stopped=stopped or threading.Event()
    model=FactoryModel(configuration,quality_results=('FAIL','PASS','PASS','PASS','PASS','PASS'))
    evidence=artifact_root()/model.run_id;evidence.mkdir(parents=True,exist_ok=False)
    info=dict(runId=model.run_id,pid=os.getpid(),evidence=str(evidence.resolve()),scenario='P0',guiConfirmed=False,operationsApplied=False)
    (evidence/'run.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info),flush=True)
    gate=os.environ.get('CONNECTED_DEMO_START_GATE')
    if gate:
        end=time.monotonic()+30
        while not Path(gate).exists():
            if stopped.wait(.05) or time.monotonic()>end:raise ValueError('P0 verification start timed out; no TCP write was made')
    sender=Sender(settings,error_path=evidence/'send-errors.ndjson');session=SourceSession(model,sender);driver=P0Driver(model)
    started=time.monotonic();saved=0;last_report=0;observation_wait=0
    def drain():
        nonlocal saved
        while sender.pending and not stopped.is_set():
            original=sender.pending.head
            if original.source_seq>saved:
                with (evidence/'originals.ndjson').open('ab') as output:output.write(original.frame)
                saved=original.source_seq
            session.send_head()
    def report():session.change(model.publish_snapshot);drain()
    def stage_hold(stage):
        nonlocal observation_wait
        hold_started=time.monotonic()
        session.change(model.pause);report()
        state=dict(stage=stage,runId=model.run_id,sourceSeq=saved,physical=model.snapshot())
        (evidence/(stage+'.json')).write_text(json.dumps(state,indent=2)+'\n')
        (evidence/'phase.json').write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(dict(stage=stage,runId=model.run_id)),flush=True)
        markers=os.environ.get('P0_DEMO_MARKERS')
        deadline=time.monotonic()+(660 if markers else 4)
        while not stopped.is_set():
            if markers and (Path(markers)/(stage+'.continue')).exists():break
            if time.monotonic()>deadline:
                if markers:raise ValueError('P0 browser stage timed out: '+stage)
                break
            report();stopped.wait(.5)
        session.change(model.resume)
        observation_wait+=time.monotonic()-hold_started
    try:
        driver.initialize(session.change);report()
        while not stopped.is_set():
            if time.monotonic()-started-observation_wait>max_seconds:raise ValueError('P0 demo time budget exceeded; accepted originals remain')
            cycle=time.monotonic();stage=driver.step(session.change)
            if stage:
                stage_hold(stage)
                following=driver.after(stage,session.change)
                while following:
                    stage_hold(following);following=driver.after(following,session.change)
            if driver.drained():
                session.change(model.finish_run);drain()
                info.update(state='SOURCE_STOPPED' if sender.pending or stopped.is_set() else 'INGESTION_CONFIRMED',events=saved);break
            if cycle-last_report>=configuration.factory['snapshotIntervalMs']/1000:report();last_report=cycle
            else:drain()
            stopped.wait(max(0,configuration.factory['tickMs']/1000-(time.monotonic()-cycle)))
        else:info.update(state='SOURCE_STOPPED',events=saved)
        if driver.stage!=5 and info.get('state')=='INGESTION_CONFIRMED':raise ValueError('P0 stages were not all reached')
        info['physical']=model.snapshot();(evidence/'result.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps({k:v for k,v in info.items() if k!='physical'}),flush=True)
        return 0 if info['state']=='INGESTION_CONFIRMED' else 2
    except (ValueError,OSError) as error:
        info.update(state='SOURCE_FAILED',events=saved,error=str(error));(evidence/'result.json').write_text(json.dumps(info,indent=2)+'\n');raise
    finally:
        for event in model.events:
            if event.to_dict()['sourceSeq']>saved:
                with (evidence/'originals.ndjson').open('ab') as output:output.write(event.ndjson.encode())
                saved=event.to_dict()['sourceSeq']
        sender.close()
