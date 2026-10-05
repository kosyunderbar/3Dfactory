"""Owned native PostgreSQL + Java processes for destructive integration probes.

Never targets Compose or a user database. Data/logs survive both success and failure.
Secrets are private files and child environment only, never command-line arguments.
"""
from pathlib import Path
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def await_condition(check, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise TimeoutError('Integration condition timed out')


class Runtime:
    def __init__(self, namespace='recovery-verification'):
        if namespace not in ('recovery-verification','performance-verification'):
            raise ValueError('Unknown isolated verification namespace')
        self.evidence = ROOT / '.build-cache' / namespace / uuid.uuid4().hex
        self.evidence.mkdir(parents=True, mode=0o700)
        config = ROOT / '.build-cache/postgresql-toolchain.json'
        self.bin = Path(os.environ.get('FACTORY_PG_BIN', json.loads(config.read_text())['bin']))
        version = subprocess.check_output([str(self.bin/'postgres'), '--version'], text=True).strip()
        if version != 'postgres (PostgreSQL) 17.11':
            raise ValueError('This probe requires PostgreSQL 17.11')
        self.socket_dir = Path(tempfile.mkdtemp(prefix='factory-s08-pg-'))
        self.data = self.evidence/'data'
        self.env = dict(os.environ)
        credentials = {key: secrets.token_urlsafe(32) for key in (
            'INGESTION_DB_PASSWORD', 'INGESTION_MIGRATION_PASSWORD',
            'OPERATIONS_DB_PASSWORD', 'OPERATIONS_MIGRATION_PASSWORD', 'ADMIN_PASSWORD')}
        fd = os.open(self.evidence/'private-credentials.json', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump(credentials, file)
        self.env.update({k:v for k,v in credentials.items() if k != 'ADMIN_PASSWORD'})
        self.env.update(PGHOST=str(self.socket_dir), PGPORT=str(free_port()), PGUSER='factory_admin',
                        FACTORY_PSQL=str(self.bin/'psql'), FACTORY_OPERATIONS_TESTS='true', DEBUG='false')
        for name in ('INGESTION', 'OPERATIONS'):
            self.env[name+'_DB_URL'] = f"jdbc:postgresql://127.0.0.1:{self.env['PGPORT']}/{name.lower()}_db"
            self.env[name+'_DB_USERNAME'] = name.lower()+'_app'
            self.env[name+'_MIGRATION_USERNAME'] = name.lower()+'_migrator'
            self.env[name+'_HTTP_PORT'] = str(free_port())
            self.env[name+'_HTTP_ADDRESS'] = '127.0.0.1'
        self.env.update(INGESTION_TCP_ADDRESS='127.0.0.1', INGESTION_TCP_PORT=str(free_port()),
                        INGESTION_REJECTION_LOG=str(self.evidence/'rejections.ndjson'),
                        OPERATIONS_BASE_URL=self.url('operations'), INGESTION_DIAGNOSTIC_URL=self.url('ingestion'))
        self.java = Path(subprocess.check_output(['/usr/libexec/java_home','-v','21'], text=True).strip())/'bin/java' if Path('/usr/libexec/java_home').exists() else shutil.which('java')
        self.children = {}
        self.logs = []
        self.generation = {}
        self.started = False
        pwfile = self.evidence/'admin-password'
        fd = os.open(pwfile, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd,'w') as file:
            file.write(credentials['ADMIN_PASSWORD']+'\n')
        try:
            self.run([self.bin/'initdb','-D',self.data,'-U','factory_admin','--pwfile',pwfile,
                      '--encoding=UTF8','--locale=C','--auth-local=trust','--auth-host=scram-sha-256'],'initdb')
        finally:
            pwfile.unlink(missing_ok=True)
        (self.data/'pg_hba.conf').write_text('local all factory_admin trust\nlocal all all scram-sha-256\nhost all all 127.0.0.1/32 scram-sha-256\n')
        with (self.data/'postgresql.conf').open('a') as file:
            file.write(f"\nlisten_addresses='127.0.0.1'\nport={self.env['PGPORT']}\nunix_socket_directories='{self.socket_dir}'\nmax_connections=24\nshared_buffers='32MB'\n")

    def save(self, name, value):
        (self.evidence/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

    def run(self, command, name):
        with (self.evidence/(name+'.log')).open('w') as log:
            result = subprocess.run([str(x) for x in command], cwd=ROOT, env=self.env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{name} failed; see its retained log')

    def sql(self, database, query):
        return subprocess.check_output([str(self.bin/'psql'),'--no-psqlrc','-At','-v','ON_ERROR_STOP=1',
                                        '--dbname',database,'-c',query], env=self.env, text=True, stderr=subprocess.DEVNULL).strip()

    def database_access(self, name, allowed):
        if name not in ('ingestion_db','operations_db'):
            raise ValueError('Only this cluster\'s two databases are allowed')
        self.sql('postgres',f'ALTER DATABASE {name} ALLOW_CONNECTIONS {str(allowed).lower()}')
        if not allowed:
            self.sql('postgres',f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}'")

    def url(self, name):
        return 'http://127.0.0.1:'+self.env[name.upper()+'_HTTP_PORT']

    def start_pg(self):
        self.run([self.bin/'pg_ctl','-D',self.data,'-l',self.evidence/'postgres.log','-w','start'],'postgres-start')
        self.started = True

    def stop_pg(self):
        self.run([self.bin/'pg_ctl','-D',self.data,'-m','fast','-w','stop'],'postgres-stop')
        self.started = False

    def spawn(self, name, command, env=None):
        if name in self.children and self.children[name].poll() is None:
            raise ValueError('Owned child already running')
        self.generation[name] = self.generation.get(name,0)+1
        log = (self.evidence/f'{name}-{self.generation[name]}.log').open('w')
        self.logs.append(log)
        self.children[name] = subprocess.Popen([str(x) for x in command], cwd=ROOT, env=env or self.env,
                                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def start_service(self, name):
        arguments=[self.java]
        if self.env.get('FACTORY_MEASUREMENT_ENABLED')=='true':
            arguments.append('-Dfactory.measurement.file='+str(self.evidence/(name+'-measurement.csv')))
        arguments.extend(['-jar',ROOT/f'services/{name}-service/target/{name}-service-0.1.0-SNAPSHOT.jar'])
        self.spawn(name, arguments)
        await_condition(lambda: self.get(name,'/readyz'), 40)

    def stop(self, name):
        process = self.children.get(name)
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=5)

    def get(self, name, path):
        with urllib.request.urlopen(self.url(name)+path, timeout=5) as response:
            return json.load(response)

    def close(self):
        for name in reversed(list(self.children)):
            self.stop(name)
        for log in self.logs:
            log.close()
        if self.started or (self.data/'postmaster.pid').exists():
            self.stop_pg()
        self.socket_dir.rmdir()
        result = self.evidence/'result.json'
        if result.exists():
            value=json.loads(result.read_text());value['ownedProcessesStopped']=True
            self.save('result.json',value)
