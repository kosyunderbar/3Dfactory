"""Read S05 delivery state or explicitly resume the same paused head. Never skip or edit a report."""
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','outbox','resume'])
    parser.add_argument('run_id')
    parser.add_argument('--base-url',default=os.environ.get('INGESTION_BASE_URL','http://127.0.0.1:8081'))
    parser.add_argument('--source-seq',type=int)
    parser.add_argument('--operator')
    parser.add_argument('--reason')
    parser.add_argument('--status',choices=['PENDING','RETRY_WAIT','DELIVERED','QUARANTINED'])
    parser.add_argument('--after-seq',type=int,default=0)
    parser.add_argument('--limit',type=int,default=50)
    args=parser.parse_args()
    route={'status':'delivery-status','outbox':'outbox','resume':'delivery-resume'}[args.action]
    url=args.base_url.rstrip('/')+'/internal/v1/runs/'+urllib.parse.quote(args.run_id,safe='')+'/'+route
    body=None
    if args.action=='resume':
        if args.source_seq is None or not args.operator or not args.reason:parser.error('resume requires --source-seq, --operator and --reason')
        body=json.dumps(dict(sourceSeq=args.source_seq,operatorId=args.operator,reason=args.reason),ensure_ascii=False).encode()
    elif args.action=='outbox':
        params=dict(afterSeq=args.after_seq,limit=args.limit)
        if args.status:params['status']=args.status
        url+='?'+urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=body,headers={'Content-Type':'application/json; charset=utf-8'}),timeout=5) as response:
            print(json.dumps(json.load(response),ensure_ascii=False,indent=2))
    except urllib.error.HTTPError as error:
        print(json.dumps(json.load(error),ensure_ascii=False,indent=2))
        raise SystemExit(f'HTTP {error.code}; no cursor skip or payload edit performed')


if __name__=='__main__':
    main()
