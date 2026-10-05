"""Real PostgreSQL 17.11 verification in an isolated retained cluster: foundations, S03 ingestion or S04 operations."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import secrets
import socket
import subprocess
import tempfile
import uuid
import argparse
import time
import urllib.request
import signal
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["foundations", "ingestion", "operations", "delivery", "stream"], default="foundations")
    args=parser.parse_args()
    configured=ROOT/'.build-cache/postgresql-toolchain.json'
    default_binary=json.loads(configured.read_text())['bin'] if configured.exists() else '/tmp/factory-pg-17.11/bin'
    binary = Path(os.environ.get('FACTORY_PG_BIN', default_binary))
    for executable in ['initdb', 'pg_ctl', 'psql', 'postgres']:
        if not (binary / executable).is_file():
            raise SystemExit('Set FACTORY_PG_BIN to PostgreSQL 17.11 bin; no global install or Docker is performed.')
    version = subprocess.check_output([str(binary/'postgres'), '--version'], text=True).strip()
    if version != 'postgres (PostgreSQL) 17.11':
        raise SystemExit('Expected PostgreSQL 17.11; found '+version)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence=ROOT/'.build-cache/database-verification'/(stamp+'-'+uuid.uuid4().hex[:8])
    evidence.mkdir(parents=True, mode=0o700)
    socket_dir=Path(tempfile.mkdtemp(prefix='factory-pg-socket-'))
    data=evidence/'data'
    credentials={key:secrets.token_urlsafe(32) for key in ['INGESTION_DB_PASSWORD','INGESTION_MIGRATION_PASSWORD','OPERATIONS_DB_PASSWORD','OPERATIONS_MIGRATION_PASSWORD','ADMIN_PASSWORD']}
    fd=os.open(evidence/'private-credentials.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: json.dump(credentials,f)
    pwfile=evidence/'admin-password'
    fd=os.open(pwfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(credentials['ADMIN_PASSWORD']+'\n')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    env=dict(os.environ)
    env.update({key:value for key,value in credentials.items() if key!='ADMIN_PASSWORD'})
    env.update(PGHOST=str(socket_dir),PGPORT=str(port),PGUSER='factory_admin',FACTORY_PSQL=str(binary/'psql'),FACTORY_DATABASE_TESTS='true',FACTORY_INGESTION_TESTS='true',FACTORY_OPERATIONS_TESTS='true',FACTORY_DELIVERY_TESTS='true',FACTORY_STREAM_TESTS='true',DEBUG='false')
    for short in ['ingestion','operations']:
        upper=short.upper()
        env[upper+'_DB_URL']=f'jdbc:postgresql://127.0.0.1:{port}/{short}_db'
        env[upper+'_DB_USERNAME']=short+'_app'
        env[upper+'_MIGRATION_USERNAME']=short+'_migrator'
    def run(args,name):
        with (evidence/(name+'.log')).open('w') as log:
            result=subprocess.run([str(x) for x in args],env=env,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        if result.returncode:
            raise RuntimeError(f'{name} failed (exit {result.returncode}); inspect {evidence/(name+".log")}')
    run([binary/'initdb','-D',data,'-U','factory_admin','--pwfile',pwfile,'--encoding=UTF8','--locale=C','--auth-local=trust','--auth-host=scram-sha-256'],'initdb')
    pwfile.unlink()
    (data/'pg_hba.conf').write_text('local all factory_admin trust\nlocal all all scram-sha-256\nhost all all 127.0.0.1/32 scram-sha-256\nhost all all ::1/128 reject\n')
    socket_path=str(socket_dir).replace("'","''")
    with (data/'postgresql.conf').open('a') as f:
        f.write(f"\nlisten_addresses='127.0.0.1'\nport={port}\nunix_socket_directories='{socket_path}'\nmax_connections=20\nshared_buffers='32MB'\npassword_encryption='scram-sha-256'\n")
    operations_process=None
    operations_log=None
    started=False
    try:
        run([binary/'pg_ctl','-D',data,'-l',evidence/'postgres.log','-w','start'],'start');started=True
        run([ROOT/'scripts/init-databases.sh'],'initialize-databases')
        if args.suite == 'delivery':
            run([ROOT/'scripts/service-maven.sh','operations-service','--offline','--batch-mode','--no-transfer-progress','-DskipTests','package'],'operations-package')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));operations_port=probe.getsockname()[1]
            if env.get('JAVA_HOME'):
                java=Path(env['JAVA_HOME'])/'bin/java'
            elif Path('/usr/libexec/java_home').exists():
                java=Path(subprocess.check_output(['/usr/libexec/java_home','-v','21'],text=True).strip())/'bin/java'
            else:
                java=shutil.which('java')
            env['OPERATIONS_HTTP_PORT']=str(operations_port)
            env['OPERATIONS_HTTP_ADDRESS']='127.0.0.1'
            env['INGESTION_DIAGNOSTIC_URL']='http://127.0.0.1:1'
            env['FACTORY_OPERATIONS_TEST_URL']=f'http://127.0.0.1:{operations_port}'
            operations_log=(evidence/'real-operations.log').open('w')
            operations_process=subprocess.Popen([str(java),'-jar',str(ROOT/'services/operations-service/target/operations-service-0.1.0-SNAPSHOT.jar')],env=env,stdout=operations_log,stderr=subprocess.STDOUT,cwd=ROOT,start_new_session=True)
            deadline=time.monotonic()+30
            while True:
                if operations_process.poll() is not None:raise RuntimeError('Isolated operations process exited; inspect real-operations.log')
                try:
                    with urllib.request.urlopen(env['FACTORY_OPERATIONS_TEST_URL']+'/readyz',timeout=1) as response:
                        if response.status==200:break
                except Exception:pass
                if time.monotonic()>=deadline:raise RuntimeError('Isolated operations readiness timeout')
                time.sleep(.1)
            run([ROOT/'scripts/service-maven.sh','ingestion-service','--offline','--batch-mode','--no-transfer-progress',
                 '-Dtest=DeliveryWireTests,DeliveryIntegrationTests,EventStoreTests,IngestionApplicationTests','verify'],'delivery-s05')
            (evidence/'result.json').write_text(json.dumps({'postgresql':version,'suite':'S05',
                'wireTests':1,'realDeliveryTests':3,'affectedAdmissionTcpRegression':3,'bootstrapRegression':1,
                'realOperationsPort':operations_port,'port':port,'stoppedOnExit':False},indent=2)+'\n')
            print('PASS: S05 real TCP/HTTP/two DBs, lost response/result rollback/restart/ops DB outage/order/limits/resume; evidence:',evidence.relative_to(ROOT),flush=True)
            return
        if args.suite == 'stream':
            run([ROOT/'scripts/service-maven.sh','operations-service','--offline','--batch-mode','--no-transfer-progress',
                 '-Dtest=SnapshotChannelTests,StreamIntegrationTests,OperationsApplicationTests','verify'],'stream-s06')
            (evidence/'result.json').write_text(json.dumps({'postgresql':version,'suite':'S06',
                'boundedChannelTests':1,'realDatabaseHttpStreamTests':1,'bootstrapRegression':1,'port':port,'stoppedOnExit':False},indent=2)+'\n')
            print('PASS: S06 bounded non-blocking channel + actual DB/HTTP SSE/reconnect/20-limit/cleanup + bootstrap; evidence:',evidence.relative_to(ROOT),flush=True)
            return
        if args.suite == 'operations':
            run([ROOT/'scripts/service-maven.sh','operations-service','--offline','--batch-mode','--no-transfer-progress',
                 '-Dtest=ObservationTests,OperationsIntegrationTests,OperationsApplicationTests','verify'],'operations-s04')
            (evidence/'result.json').write_text(json.dumps({'postgresql':version,'suite':'S04',
                'observationTests':2,'realDatabaseHttpTests':4,'bootstrapRegression':1,'port':port,'stoppedOnExit':False},indent=2)+'\n')
            print('PASS: S04 real apply/rollback/projection/SQL/alarm/HTTP + freshness; evidence:',evidence.relative_to(ROOT),flush=True)
            return
        if args.suite == 'ingestion':
            run([ROOT/'scripts/service-maven.sh','ingestion-service','--offline','--batch-mode','--no-transfer-progress',
                 '-Dtest=ReceiverUnitTests,EventStoreTests,IngestionApplicationTests','verify'],'ingestion-s03')
            (evidence/'result.json').write_text(json.dumps({'postgresql':version,'suite':'S03',
                'unitTests':3,'realDatabaseTcpTests':3,'bootstrapRegression':1,'port':port,'stoppedOnExit':False},indent=2)+'\n')
            print('PASS: S03 framing/schema/queue + real commit/duplicate/caps/rollback/ACK loss; evidence:',evidence.relative_to(ROOT),flush=True)
            return
        for service in ['ingestion-service','operations-service']:
            run([ROOT/'scripts/service-maven.sh',service,'--offline','--batch-mode','--no-transfer-progress','-Dtest=DatabaseMigrationTests','verify'],service)
            print('PASS:',service,'real Flyway migration, own DB write, repeat migration preserves row, cross DB/DDL denied',flush=True)
        # Same init must refuse existing objects rather than drop/recreate them.
        with (evidence/'repeat-init.log').open('w') as log:
            repeat=subprocess.run([str(ROOT/'scripts/init-databases.sh')],env=env,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        if repeat.returncode==0 or 'Refusing to reset or overwrite' not in (evidence/'repeat-init.log').read_text():
            raise RuntimeError('Repeat database provisioning did not refuse existing state')
        for short,expected in [('ingestion',4),('operations',13)]:
            query="SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name<>'flyway_schema_history'"
            output=subprocess.check_output([str(binary/'psql'),'--no-psqlrc','-At','--dbname',short+'_db','-c',query],env=env,text=True).strip()
            if int(output)!=expected:raise RuntimeError('Unexpected '+short+' table count: '+output)
        (evidence/'result.json').write_text(json.dumps({'postgresql':version,'databaseScenariosPassed':2,'tables':{'ingestion':4,'operations':13},'repeatProvisioning':'REFUSED_WITHOUT_RESET','port':port,'stoppedOnExit':False},indent=2)+'\n')
        print('PASS: 17 owned tables; repeat provisioning refused without resetting. Evidence:',evidence.relative_to(ROOT),flush=True)
    finally:
        if operations_process is not None:
            if operations_process.poll() is None:
                os.killpg(operations_process.pid,signal.SIGTERM)
                try:operations_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(operations_process.pid,signal.SIGKILL);operations_process.wait(timeout=5)
            if operations_log:operations_log.close()
            print('Stopped only the isolated S05 operations process.',flush=True)
        if started or (data/'postmaster.pid').exists():
            run([binary/'pg_ctl','-D',data,'-m','fast','-w','stop'],'stop')
            result_file=evidence/'result.json'
            if result_file.exists():
                result=json.loads(result_file.read_text());result['stoppedOnExit']=True
                result_file.write_text(json.dumps(result,indent=2)+'\n')
            print('Stopped only this verification cluster; its data and logs remain.',flush=True)
        socket_dir.rmdir()


if __name__=='__main__':
    main()
