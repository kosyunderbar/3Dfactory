"""Read-only macOS process resource samples for one owned measurement folder.

%CPU is ps's process CPU percentage estimate; RSS is KiB, not total system RAM.
No process environment or command arguments are collected.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('evidence',type=Path);args=parser.parse_args()
    directory=args.evidence.resolve();root=Path(__file__).resolve().parents[1]
    if directory.parent!=root/'.build-cache/performance-verification':raise ValueError('Only owned performance folders')
    with (directory/'resources.ndjson').open('a') as output:
        while not (directory/'result.json').exists() and not (directory/'failed-probe.json').exists():
            pids=set()
            for service in ('ingestion','operations'):
                file=directory/(service+'-measurement.csv')
                if file.exists():
                    with file.open() as trace:
                        line=trace.readline().strip().split(',')
                    if len(line)==9:pids.add(int(line[-1]))
            pg=directory/'data/postmaster.pid'
            if pg.exists():pids.add(int(pg.read_text().splitlines()[0]))
            if pids:
                result=subprocess.run(['ps','-o','pid=,%cpu=,rss=','-p',','.join(map(str,sorted(pids)))],capture_output=True,text=True)
                if result.returncode not in (0,1):raise RuntimeError('Process resource read unavailable')
                rows=[]
                for line in result.stdout.splitlines():
                    pid,cpu,rss=line.split();rows.append(dict(pid=int(pid),cpuPercent=float(cpu),rssKiB=int(rss)))
                output.write(json.dumps(dict(at=time.time()*1000,processes=rows))+'\n');output.flush()
            time.sleep(5)

if __name__=='__main__':main()
