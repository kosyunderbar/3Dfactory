"""S09 SQL/API evidence, existing-data restart, and fresh P0 demo in an owned DB.

Synthetic 100k logs are explicitly separate from immutable 100-body source replay.
Never reads/writes the user's developer Compose database.
"""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from verification_runtime import ROOT,Runtime,await_condition,free_port
sys.path.insert(0,str(ROOT/'services/factory-simulator'))
from factory_simulator.model import FactoryModel
from factory_simulator.run_configuration import RunConfiguration,DEFAULT_CONFIG
from factory_simulator.configuration import Settings
from factory_simulator.sender import Sender,SourceSession,Original
from factory_simulator.p0_demo import P0Driver

def stats(values):
    import math
    values=sorted(values)
    return dict(count=len(values),p50=values[math.ceil(len(values)*.5)-1],p95=values[math.ceil(len(values)*.95)-1],max=values[-1])

def explain(rt,name,query):
    value=json.loads(rt.sql('operations_db','EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query))
    rt.save(name+'.json',value);return value[0]['Execution Time']

def fixture_sql(run,count=100000,start=1,seed=42):
    return f"""WITH fixture AS MATERIALIZED (
        SELECT {start}+n AS g,('00000000-0000-4000-8000-'||lpad(to_hex({start}+n),12,'0'))::uuid AS id,
            (ARRAY['ASM-01','ASM-02','QC-01'])[1+(({start}+n+{seed})%3)] AS cell,
            date_trunc('milliseconds',statement_timestamp())-interval '100 seconds'+(({start}+n)%100000)*interval '1 millisecond' AS at
        FROM generate_series(0,{count-1}) AS n),
    payloads AS MATERIALIZED (SELECT *,jsonb_build_object('entityType','EQUIPMENT','entityId',cell,'measurements',jsonb_build_object('temperatureC',20+((g+{seed})%17)),'position',null) AS payload FROM fixture),
    raw AS MATERIALIZED (SELECT *,jsonb_build_object('schemaVersion',1,'eventId',id,'runId','{run}','sourceId','simulator-01','sourceSeq',g+2,'eventType','TELEMETRY_UPDATED','occurredAt',to_char(at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'),'payload',payload)::text AS raw FROM payloads),
    inserted AS (INSERT INTO processed_event(run_id,event_id,source_id,source_seq,raw_json_text,payload_hash,apply_status,result_code,applied_at,recorded_at)
        SELECT '{run}',id,'simulator-01',g+2,raw,encode(sha256(convert_to(raw,'UTF8')),'hex'),'APPLIED','OK',at,at FROM raw RETURNING event_id)
    INSERT INTO event_projection(run_id,event_id,type,severity,apply_status,entity_id,cell_id,occurred_at,received_at,payload)
        SELECT '{run}',r.id,'TELEMETRY_UPDATED','INFO','APPLIED',r.cell,r.cell,r.at,r.at,r.payload FROM raw r JOIN inserted i ON i.event_id=r.id"""

def http_samples(rt,name,run,window):
    cases=dict(equipment=f'/api/v1/runs/{run}/events?'+urllib.parse.urlencode(dict(window,cellId='ASM-01',limit=20)),
               ordered=f'/api/v1/runs/{run}/events?'+urllib.parse.urlencode(dict(window,limit=20)))
    output={}
    for case,path in cases.items():
        samples=[]
        for n in range(55):
            start=time.perf_counter_ns();view=rt.get('operations',path);elapsed=(time.perf_counter_ns()-start)/1e6
            assert len(view['items'])==20 and view['nextCursor']
            if n>=5:samples.append(elapsed)
        output[case]=dict(milliseconds=stats(samples),samplesMs=samples,request=path,
            firstPageIdentities=[dict(eventId=i['eventId'],sourceSeq=i['sourceSeq']) for i in view['items']])
    rt.save(name+'.json',output);return output

def sql_work(rt):
    model=FactoryModel(RunConfiguration.from_path(DEFAULT_CONFIG));sender=Sender(Settings('127.0.0.1',int(rt.env['INGESTION_TCP_PORT'])),error_path=rt.evidence/'sql-source-errors.ndjson');session=SourceSession(model,sender)
    session.change(model.publish_snapshot)
    while sender.pending:session.send_head()
    sender.close();run=model.run_id
    await_condition(lambda:rt.get('operations',f'/api/v1/runs/{run}/snapshot')['sourceSeq']==2)
    rt.sql('operations_db',fixture_sql(run));rt.sql('operations_db','ANALYZE event_projection; ANALYZE processed_event')
    assert rt.sql('operations_db',f"SELECT count(*) FROM event_projection WHERE run_id='{run}' AND type='TELEMETRY_UPDATED'")=='100000'
    now=datetime.now(timezone.utc);to=now.isoformat(timespec='milliseconds').replace('+00:00','Z');start=(now-timedelta(minutes=5)).isoformat(timespec='milliseconds').replace('+00:00','Z');window={'from':start,'to':to}
    fence=f"SELECT COALESCE(max(record_ordinal),0) FROM event_projection WHERE run_id='{run}'"
    ordinal=rt.sql('operations_db',fence)
    base=f"SELECT t.*,p.source_seq,p.applied_at FROM event_projection t JOIN processed_event p USING(run_id,event_id) WHERE t.record_ordinal<={ordinal} AND t.apply_status='APPLIED' AND t.run_id='{run}' AND t.occurred_at>='{start}' AND t.occurred_at<'{to}'"
    ordered=base+' ORDER BY t.occurred_at DESC,p.source_seq DESC,t.event_id DESC LIMIT 21'
    equipment=base+" AND t.cell_id='ASM-01' ORDER BY t.occurred_at DESC,p.source_seq DESC,t.event_id DESC LIMIT 21"
    first={key:explain(rt,'sql-first-observation-'+key,q) for key,q in dict(fence=fence,equipment=equipment,ordered=ordered).items()}
    before=http_samples(rt,'api-before',run,window)
    warm_before={key:explain(rt,'sql-warm-before-'+key,q) for key,q in dict(fence=fence,equipment=equipment,ordered=ordered).items()}
    # A scoped experimental index in this disposable cluster, before deciding on a repository migration.
    rt.sql('operations_db','CREATE INDEX s09_candidate_event_fence_idx ON event_projection(run_id,record_ordinal DESC)');rt.sql('operations_db','ANALYZE event_projection')
    after=http_samples(rt,'api-after',run,window)
    assert all(before[key]['firstPageIdentities']==after[key]['firstPageIdentities'] for key in before)
    warm_after={key:explain(rt,'sql-warm-after-'+key,q) for key,q in dict(fence=fence,equipment=equipment,ordered=ordered).items()}
    index_bytes=int(rt.sql('operations_db',"SELECT pg_relation_size('s09_candidate_event_fence_idx')"))
    # Identical rollback-only 1000-row fixture insert; no production facts or source throughput claims.
    write_query=fixture_sql(run,1000,100001)
    def writes(label):
        times=[]
        for n in range(4):
            text=rt.sql('operations_db','BEGIN; EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+write_query+'; ROLLBACK;')
            data=json.JSONDecoder().raw_decode(text[text.index('['):])[0];rt.save(f'sql-write-{label}-{n}.json',data)
            if n:times.append(data[0]['Execution Time'])
        return dict(milliseconds=stats(times),samplesMs=times)
    write_after=writes('after');rt.sql('operations_db','DROP INDEX s09_candidate_event_fence_idx');write_before=writes('before')
    archived=ROOT/'.build-cache/recovery-verification/05f6bac4de3e4011be194b0719399d10/run-20261005-88b0c450e944469684a17e9fb0fe76e6.ndjson'
    # A fresh 100-body scenario may be supplied; this checked immutable source was already functionally verified in S08.
    if not archived.exists():
        candidates=list((ROOT/'.build-cache/recovery-verification/05f6bac4de3e4011be194b0719399d10').rglob('originals.ndjson'))
        archived=next((p for p in candidates if json.loads(p.open().readline())['runId']=='run-20261005-88b0c450e944469684a17e9fb0fe76e6'),archived)
    if not archived.exists():raise FileNotFoundError('Verified 100-body originals unavailable; supply/archive S08 evidence first')
    with archived.open('rb') as source:quality_run=Original.from_frame(source.readline(65537)).run_id
    assert rt.sql('ingestion_db',f"SELECT count(*) FROM raw_event WHERE run_id='{quality_run}'")=='0'
    sender=Sender(Settings('127.0.0.1',int(rt.env['INGESTION_TCP_PORT'])),error_path=rt.evidence/'quality-replay-errors.ndjson')
    replayed=sender.send_file(archived);sender.close()
    await_condition(lambda:rt.get('ingestion',f'/internal/v1/runs/{quality_run}/delivery-status')['pendingCount']==0,90)
    range_json=json.loads(rt.sql('operations_db',f"SELECT json_build_object('from',to_char((min(inspected_at)-interval '1 second') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'),'to',to_char((max(inspected_at)+interval '1 second') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'),'count',count(*)) FROM inspection_result WHERE run_id='{quality_run}'"))
    assert range_json.pop('count')==100
    quality_query=f"SELECT count(*) AS n,count(*) FILTER(WHERE result='PASS') AS pass,count(*) FILTER(WHERE result='FAIL') AS fail FROM inspection_result WHERE run_id='{quality_run}' AND inspected_at>='{range_json['from']}' AND inspected_at<'{range_json['to']}'"
    explain(rt,'sql-quality-100-real-facts',quality_query)
    path=f'/api/v1/runs/{quality_run}/quality?'+urllib.parse.urlencode(range_json);samples=[]
    for n in range(55):
        at=time.perf_counter_ns();view=rt.get('operations',path);elapsed=(time.perf_counter_ns()-at)/1e6
        assert view['quality']==dict(inspectedCount=100,passCount=80,failCount=20,failRate=.2)
        if n>=5:samples.append(elapsed)
    result=dict(syntheticRun=run,syntheticLogRows=100000,sourceAdmittedEvents=2,fixtureSeed=42,fixtureMethod='Deterministic SQL generate_series; not admitted TCP production',
        firstObservationMs=first,cache='55 sequential HTTP calls, first 5 excluded. Warm results only; no OS cache flush/cold guarantee',
        warmSqlBeforeMs=warm_before,warmSqlAfterMs=warm_after,apiBefore=before,apiAfter=after,
        candidateIndex='event_projection(run_id,record_ordinal DESC)',candidateIndexBytes=index_bytes,candidateIndexRemoved=True,
        rollbackInsertBefore=write_before,rollbackInsertAfter=write_after,
        qualityRun=quality_run,qualityFacts=100,qualityReplayOriginals=replayed,qualityOriginalSha256=hashlib.sha256(archived.read_bytes()).hexdigest(),qualityApi=dict(milliseconds=stats(samples),samplesMs=samples,request=path),
        recommendedMigration=warm_before['fence']>warm_after['fence']*2 and warm_before['fence']-warm_after['fence']>1)
    rt.save('sql-result.json',result);print('SQL_COMPLETE',rt.evidence,'candidate migration',result['recommendedMigration'],flush=True)
    return result

def fingerprints(rt):
    tables={'ingestion_db':['raw_event','event_outbox','delivery_stream'],'operations_db':['processed_event','event_projection','inspection_result','body','factory_snapshot']}
    return {db:{t:rt.sql(db,f"SELECT count(*)||':'||md5(COALESCE(string_agg(row_to_json(x)::text,'' ORDER BY row_to_json(x)::text),'')) FROM {t} x") for t in ts} for db,ts in tables.items()}

def restart(rt,sql_result,browser):
    before=fingerprints(rt)
    # Existing initialization must refuse, preserving data. This is intentionally a nonzero command.
    with (rt.evidence/'existing-init-refusal.log').open('w') as file:
        code=subprocess.run([str(ROOT/'scripts/init-databases.sh')],cwd=ROOT,env=rt.env,stdout=file,stderr=subprocess.STDOUT).returncode
    assert code!=0 and 'Refusing to reset or overwrite' in (rt.evidence/'existing-init-refusal.log').read_text()
    assert fingerprints(rt)==before
    rt.stop('ingestion');rt.stop('operations');rt.stop_pg()
    rt.start_pg();rt.start_service('operations');rt.start_service('ingestion')
    after=fingerprints(rt);assert before==after
    histories={name:rt.sql(name+'_db',"SELECT string_agg(version,',' ORDER BY installed_rank) FROM flyway_schema_history WHERE success") for name in ('ingestion','operations')}
    value=dict(existingInitRefused=True,initializationPreservedAllFingerprints=True,sameDataDirectoryRestart=True,allFingerprintsEqual=True,before=before,after=after,migrations=histories)
    rt.save('restart-result.json',value);return value

def demo(rt,port,browser):
    config=json.loads(DEFAULT_CONFIG.read_text())
    for cell in config['config']['equipment']:cell['workDurationMs']=200
    for route in config['config']['routes']:route['travelDurationMs']=1000
    rt.save('demo-config.json',config)
    model=FactoryModel(RunConfiguration.from_dict(config),quality_results=('FAIL','PASS','PASS','PASS','PASS'))
    sender=Sender(Settings('127.0.0.1',int(rt.env['INGESTION_TCP_PORT'])),error_path=rt.evidence/'demo-send-errors.ndjson');session=SourceSession(model,sender);driver=P0Driver(model);run=model.run_id
    assert rt.sql('operations_db',f"SELECT count(*) FROM simulation_run WHERE run_id='{run}'")=='0'
    originals=(rt.evidence/'demo-originals.ndjson').open('wb');stages=[];snapshot_seq=0
    def drain():
        nonlocal snapshot_seq
        while sender.pending:
            original=sender.pending.head;originals.write(original.frame);originals.flush();session.send_head()
            if json.loads(original.frame)['eventType']=='FACTORY_SNAPSHOT':snapshot_seq=original.source_seq
    def report():session.change(model.publish_snapshot);drain()
    def hold(name):
        if name!='FINISHED':session.change(model.pause);report()
        current=await_condition(lambda:(v if v['sourceSeq']==snapshot_seq and (name!='FINISHED' or v['dataStatus']=='FINISHED') else None) if (v:=rt.get('operations',f'/api/v1/runs/{run}/snapshot')) else None)
        rt.save('demo-'+name+'.json',current);rt.save('phase.json',dict(phase=name,runId=run,url=f'http://127.0.0.1:{port}/?run={run}',evidence=str(rt.evidence)))
        print('DEMO',name,run,flush=True);stages.append(name)
        if browser:
            end=time.monotonic()+600
            while not (rt.evidence/('UI.'+name+'.continue')).exists():
                if time.monotonic()>end:raise TimeoutError('Demo actual browser gate timed out: '+name)
                if name!='FINISHED':report()
                time.sleep(.5)
        if name!='FINISHED':session.change(model.resume)
    try:
        driver.initialize(session.change);report();start=time.monotonic()
        while not driver.drained():
            if time.monotonic()-start>900:raise TimeoutError('Demo exceeded 900 seconds')
            stage=driver.step(session.change)
            if stage:
                hold(stage);following=driver.after(stage,session.change)
                while following:hold(following);following=driver.after(following,session.change)
            report();time.sleep(.1)
        session.change(model.finish_run);drain();originals.close()
        await_condition(lambda:rt.get('ingestion',f'/internal/v1/runs/{run}/delivery-status')['pendingCount']==0,30)
        hold('FINISHED')
        final=rt.get('operations',f'/api/v1/runs/{run}/snapshot');tag=rt.get('operations',f'/api/v1/runs/{run}/tags/tag-00001/body');quality=final['metrics']['cumulativeQuality']
        assert quality==dict(inspectedCount=5,passCount=4,failCount=1,failRate=.2) and tag['data']['locationId']=='HOLD'
        assert stages==['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED','FINISHED']
        for name in stages[:-1]:
            view=json.loads((rt.evidence/('demo-'+name+'.json')).read_text());bay=next(b for b in view['buffers'] if b['cellId']=='ASM-02')
            if name in ('FULL_RESERVED','FULL_IN_TRANSIT'):assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(2,1,0)
            if name in ('FULL_ARRIVED','CELL_DOWN'):assert (bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots'])==(3,0,0)
        source=(rt.evidence/'demo-originals.ndjson').read_bytes().splitlines()
        for database,table in [('ingestion_db','raw_event'),('operations_db','processed_event')]:
            rows=json.loads(rt.sql(database,f"SELECT json_agg(json_build_object('seq',source_seq,'raw',raw_json_text,'hash',payload_hash) ORDER BY source_seq) FROM {table} WHERE run_id='{run}'"))
            assert len(rows)==len(source)
            for n,(raw,row) in enumerate(zip(source,rows),1):assert row['seq']==n and row['raw'].encode()==raw and row['hash']==hashlib.sha256(raw).hexdigest()
        rt.save('demo-tag.json',tag)
        result=dict(runId=run,stages=stages,originals=len(source),byteExactBothDatabases=True,quality=quality,tagLocation='HOLD',browserGatesObserved=browser)
        if browser:
            proof=json.loads((rt.evidence/'browser-proof.json').read_text());assert proof['runId']==run
            assert all(name in proof['stages'] for name in stages) and all((rt.evidence/file).is_file() for file in proof['screenshots'])
            result['browserProof']=proof
        rt.save('demo-result.json',result);return result
    finally:originals.close();sender.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--browser',action='store_true');args=parser.parse_args();rt=Runtime('performance-verification')
    print('EVIDENCE',rt.evidence,flush=True)
    try:
        rt.start_pg();rt.run([ROOT/'scripts/init-databases.sh'],'initial-databases')
        for name in ('ingestion','operations'):rt.run([ROOT/'scripts/service-maven.sh',name+'-service','--offline','--batch-mode','--no-transfer-progress','-DskipTests','verify'],name+'-build')
        rt.start_service('operations');rt.start_service('ingestion');sql=sql_work(rt)
        pre_migration=fingerprints(rt);rt.save('pre-migration-fingerprints.json',pre_migration)
        rt.save('phase.json',dict(phase='SQL_REVIEW',evidence=str(rt.evidence)));print('SQL_REVIEW awaiting review.continue',flush=True)
        await_condition(lambda:(rt.evidence/'review.continue').exists(),3600)
        # Review may add a measured index migration; rebuild applies it to the same existing records.
        rt.stop('operations');rt.run([ROOT/'scripts/service-maven.sh','operations-service','--offline','--batch-mode','--no-transfer-progress','-DskipTests','verify'],'operations-final-build');rt.start_service('operations')
        assert fingerprints(rt)==pre_migration
        rt.save('migration-preservation.json',dict(allFingerprintsEqual=True,before=pre_migration,after=fingerprints(rt)))
        restarted=restart(rt,sql,args.browser)
        port=free_port();env=dict(rt.env,OPERATIONS_PROXY_TARGET=rt.url('operations'),VITE_FACTORY_MEASUREMENT='true',FACTORY_BROWSER_MEASUREMENT_FILE=str(rt.evidence/'browser.ndjson'))
        rt.spawn('console',[ROOT/'scripts/console.sh','dev','--host','127.0.0.1','--port',str(port)],env)
        await_condition(lambda:urllib.request.urlopen(f'http://127.0.0.1:{port}/readyz',timeout=2).status==200)
        exhibited=demo(rt,port,args.browser)
        rt.save('result.json',dict(suite='S09 SQL, existing-data restart, fresh demo',sql=sql,restart=restarted,demo=exhibited,ownedProcessesStopped=False,retainedDatabase=True));print('PASS: SQL, existing-data restart and fresh P0 demonstration',flush=True)
    except Exception as error:rt.save('failed-probe.json',dict(error=str(error),recordsPreserved=True));raise
    finally:rt.close()

if __name__=='__main__':main()
