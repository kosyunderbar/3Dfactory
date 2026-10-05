"""Read saved S09 evidence, correlate internal/browser spans, and export non-secret summaries."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import shutil

from verification_runtime import ROOT,Runtime

def load_script():
    spec=importlib.util.spec_from_file_location('s09_measurement',ROOT/'scripts/measure-performance.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('evidence',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    directory=args.evidence.resolve()
    if directory.parent!=ROOT/'.build-cache/performance-verification':raise ValueError('Only owned performance evidence')
    result=json.loads((directory/'result.json').read_text())
    if result['suite']!='S09 measured native pipeline' or result['completedTrials']!=12 or not result['ownedProcessesStopped']:raise ValueError('Expected completed, stopped 12-trial pipeline evidence')
    runtime=Runtime.__new__(Runtime);runtime.evidence=directory
    measurement=load_script();measurement.summarize(runtime,result['trials'])
    resources=[json.loads(line) for line in (directory/'resources.ndjson').read_text().splitlines()] if (directory/'resources.ndjson').exists() else []
    pids={}
    for service in ('ingestion','operations'):
        with (directory/(service+'-measurement.csv')).open() as file:pids[service]=int(file.readline().strip().split(',')[-1])
    for trial in result['trials']:
        trial['targetReached']=trial['actualUniqueRate']>=trial['targetEventsPerSecond']
        trial['nominalRateFraction']=trial['actualUniqueRate']/trial['targetEventsPerSecond']
        trial['targetCriteria']='Actual unique rate >= nominal target; proximity is not exact offered-load verification'
        samples=[row for row in resources if trial['activeStartWallMs']<=row['at']<=trial['activeEndWallMs']]
        trial_pids={service:set(trial['internalTracePids']['ingestion-transaction' if service=='ingestion' else 'operations-transaction']) for service in pids}
        trial['resources']={service:dict(samples=sum(any(p['pid'] in ids for p in row['processes']) for row in samples),
            cpuPercent=measurement.distribution([p['cpuPercent'] for row in samples for p in row['processes'] if p['pid'] in ids]),
            rssMiB=measurement.distribution([p['rssKiB']/1024 for row in samples for p in row['processes'] if p['pid'] in ids])) for service,ids in trial_pids.items()}
        trial['resources']['coverageSeconds']=(samples[-1]['at']-samples[0]['at'])/1000 if len(samples)>1 else 0
        trial['resources']['scope']='ps CPU estimate and Java main-process RSS, 5s samples; excludes browser, simulator, PG backends and total system usage'
    runtime.save('result.json',result)
    args.output.mkdir(parents=True,exist_ok=True)
    runtime.save('summary.json',result)
    for name in ('summary.json','environment.json'):shutil.copyfile(directory/name,args.output/name)
    header=['case','target_events_s','seconds','unique_commits','unique_commits_s','originals','frame_max_bytes','ack_p95_ms','queue_p95_ms','ingestion_tx_p95_ms','delivery_http_p95_ms','operations_tx_p95_ms','observed_sse_p95_ms','foreground_dom_p95_ms','foreground_fps','foreground_render_samples','sampled_delivery_pending_max','unacknowledged_final','delivery_pending_final','target_reached']
    with (args.output/'pipeline.csv').open('w',newline='') as file:
        writer=csv.writer(file);writer.writerow(header)
        for trial in result['trials']:
            phases=trial['internalPhasesMs'];browser=trial['browser']
            writer.writerow([trial['name'],trial['targetEventsPerSecond'],trial['actualSeconds'],trial['activeUniqueEvents'],trial['actualUniqueRate'],trial['originals'],trial['frameBytes']['max'],trial['ackRoundTripMs']['p95'],*[phases[phase]['p95'] for phase in ('ingestion-queue','ingestion-transaction','delivery-http','operations-transaction')],trial['receiveToObservedSseMs']['p95'],browser['receiveToFrameMs']['p95'],browser['foregroundObservedFps'],browser['foregroundRenderSamples'],trial['maxSampledDeliveryPending'],trial['unacknowledged'],trial['deliveryPending'],trial['targetReached']])
    print('Exported 12 reconciled trials and correlated phases; no credentials or DB files copied')

if __name__=='__main__':main()
