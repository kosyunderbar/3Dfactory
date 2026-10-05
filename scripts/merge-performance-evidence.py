"""Combine completed trials from preserved native runs, never hide failed/provisional trials.

Creates an analysis-only folder with explicit parent provenance. No DB operations.
"""
import argparse
import csv
import json
from pathlib import Path
import shutil
import uuid
from verification_runtime import ROOT

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('parents',type=Path,nargs='+');args=parser.parse_args()
    base=ROOT/'.build-cache/performance-verification';destination=base/uuid.uuid4().hex;destination.mkdir(mode=0o700)
    chosen={};provenance=[];parents=[]
    expected={'normal-'+str(n) for n in (1,2,3)}|{'stress-'+str(rate)+'-'+str(n) for rate in (100,300,500) for n in (1,2,3)}
    for supplied in args.parents:
        parent=supplied.resolve()
        if parent.parent!=base or (parent/'data/postmaster.pid').exists():raise ValueError('Expected a stopped owned native measurement folder')
        path=parent/'result.json' if (parent/'result.json').exists() else parent/'partial-result.json'
        result=json.loads(path.read_text())
        if not result['ownedProcessesStopped']:raise ValueError('Parent processes not confirmed stopped')
        if result['completedTrials']!=len(result['trials']):raise ValueError('Parent count mismatch')
        runs=set()
        for trial in result['trials']:
            name=trial['name']
            if name not in expected or name in chosen:raise ValueError('Unknown or duplicate completed trial')
            if not trial['byteExactBothDatabases'] or not trial['ownRowsCleaned']:raise ValueError('Incomplete original reconciliation')
            chosen[name]=trial;runs.add(trial['runId']);shutil.copytree(parent/name,destination/name)
            trial['sourceEvidence']=str(parent.relative_to(ROOT));trial['sourceResultFile']=path.name
        provenance.append(dict(evidence=str(parent.relative_to(ROOT)),completedTrials=len(result['trials']),sourceResultFile=path.name,
            entireParentSucceeded=not (parent/'failed-probe.json').exists(),failedProbeFile=str((parent/'failed-probe.json').relative_to(ROOT)) if (parent/'failed-probe.json').exists() else None))
        parents.append((parent,runs))
    if set(chosen)!=expected:raise ValueError('Need exactly three completed trials at each of four rates')
    if len({r['runId'] for r in chosen.values()})!=12:raise ValueError('Duplicate run identifiers')
    for service in ('ingestion','operations'):
        with (destination/(service+'-measurement.csv')).open('w',newline='') as output:
            writer=csv.writer(output)
            for parent,runs in parents:
                with (parent/(service+'-measurement.csv')).open() as file:
                    for row in csv.reader(file):
                        if len(row)!=9:raise ValueError('Incomplete or limited parent trace; cannot publish as complete')
                        if row[1] in runs:writer.writerow(row)
    for name in ('browser.ndjson','resources.ndjson'):
        with (destination/name).open('w') as output:
            for parent,_ in parents:
                source=parent/name
                if source.exists():output.write(source.read_text())
    shutil.copyfile(parents[0][0]/'environment.json',destination/'environment.json')
    result=dict(suite='S09 measured native pipeline',completedTrials=12,requestedTrials=12,
        trials=[chosen[name] for name in ['normal-'+str(n) for n in (1,2,3)]+['stress-'+str(rate)+'-'+str(n) for rate in (100,300,500) for n in (1,2,3)]],
        byteExactBothDatabases=True,ownedProcessesStopped=True,retainedDatabase=True,analysisOnlyFolder=True,
        sourceEvidence=provenance,retainedDatabasePaths=[str((parent/'data').relative_to(ROOT)) for parent,_ in parents],
        conditions='Same host/config/seed, 5s warmup and empty live trial tables; continuation used a new owned JVM/PG after setup-tool correction. Not identical physical caches or JVM uptime')
    (destination/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('CANONICAL_EVIDENCE',destination)
    print('Merged exactly 12 completed byte-exact trials; failed/provisional trials remain only in parent evidence')

if __name__=='__main__':main()
