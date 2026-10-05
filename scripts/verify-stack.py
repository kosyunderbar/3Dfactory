#!/usr/bin/env python3
"""One real Compose lifecycle check. Preserves volumes and deletes only its own probes."""
import argparse
from datetime import datetime, timezone
import json
import os
import shutil
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / 'scripts/dev-stack.sh'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep-running', action='store_true')
    args = parser.parse_args()
    run_id = 'stack-probe-' + uuid.uuid4().hex
    results = {}
    evidence = ROOT / '.build-cache/stack-verification' / run_id
    evidence.mkdir(parents=True)
    env_values = {}
    for line in (ROOT / '.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            env_values[key] = value
    ports = {'ingestion-service': int(os.environ.get('INGESTION_HTTP_PORT', env_values.get('INGESTION_HTTP_PORT', '8081'))),
             'operations-service': int(os.environ.get('OPERATIONS_HTTP_PORT', env_values.get('OPERATIONS_HTTP_PORT', '8082'))),
             'factory-console': int(os.environ.get('CONSOLE_HTTP_PORT', env_values.get('CONSOLE_HTTP_PORT', '5173')))}

    local_docker = ROOT / '.build-cache/tools/docker/docker'
    if not shutil.which('docker') and local_docker.exists():
        os.environ['PATH'] = str(local_docker.parent) + os.pathsep + os.environ['PATH']
        os.environ['DOCKER_CONFIG'] = str(ROOT / '.build-cache/docker-config')
        if 'DOCKER_HOST' not in os.environ:
            os.environ['DOCKER_HOST'] = 'unix:///private/tmp/factory-lima-s01/factory/sock/docker.sock'

    with (evidence / 'commands.log').open('w') as log:
        def compose(*arguments, input_text=None, capture=False):
            result = subprocess.run([str(STACK), 'compose', *arguments], cwd=ROOT,
                                    text=True, input=input_text, stdout=subprocess.PIPE if capture else log,
                                    stderr=log, check=True)
            return result.stdout if capture else None

        def sql(database, statement):
            return compose('exec', '-T', 'postgres', 'psql', '--no-psqlrc', '-U', 'postgres',
                           '-d', database, '-v', 'ON_ERROR_STOP=1', '-At',
                           input_text=statement, capture=True).strip()

        def status(service, endpoint):
            try:
                with urlopen(f'http://127.0.0.1:{ports[service]}/{endpoint}', timeout=5) as response:
                    return response.status
            except HTTPError as error:
                return error.code
            except (URLError, TimeoutError):
                return None

        def expect(service, endpoint, expected, wait=45):
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                actual = status(service, endpoint)
                if actual == expected:
                    return
                time.sleep(1)
            raise AssertionError(f'{service}/{endpoint}: expected {expected}, received {actual}')

        def check(name, condition=True):
            if not condition:
                raise AssertionError(name)
            results[name] = 'PASS'
            print(name + ': PASS', flush=True)

        try:
            # Required interpolation must fail without exposing the rendered config.
            empty_env = evidence / 'empty.env'
            empty_env.touch()
            clean_environment = {key: value for key, value in os.environ.items() if key not in env_values}
            if shutil.which('docker'):
                command = ['docker', 'compose']
            else:
                command = [str(ROOT / '.build-cache/tools/docker-compose')]
            failure = subprocess.run([*command, '--env-file', str(empty_env), '-f', str(ROOT / 'compose.yaml'),
                                      'config', '--quiet'], env=clean_environment, stdout=log, stderr=log)
            check('missing-required-settings-rejected', failure.returncode != 0)
            compose('up', '--wait', '--wait-timeout', '180')
            for service in ('ingestion-service', 'operations-service'):
                expect(service, 'readyz', 200)
                expect(service, 'livez', 200)
            expect('factory-console', 'healthz', 200)
            expect('factory-console', 'readyz', 200)
            statuses = [
                json.loads(line) for line in compose('ps', '--format', 'json', capture=True).splitlines() if line.strip()]
            check('five-processes-healthy', len(statuses) == 5 and all(row.get('Health') == 'healthy' for row in statuses))
            sql('ingestion_db', f"INSERT INTO delivery_stream(run_id,source_id) VALUES ('{run_id}','stack-probe');")
            sql('operations_db', f"INSERT INTO simulation_run(run_id,source_id,started_at,seed,config) VALUES ('{run_id}','stack-probe',now(),1,'{{}}');")
            compose('stop', 'ingestion-service')
            expect('operations-service', 'readyz', 200)
            expect('factory-console', 'readyz', 200)
            survivors = [json.loads(line) for line in compose('ps', '--format', 'json', capture=True).splitlines() if line.strip()]
            check('ingestion-stop-isolated', len(survivors) == 4 and all(row['State'] == 'running' for row in survivors))
            compose('up', '-d', '--wait', 'ingestion-service')
            compose('stop', 'postgres')
            for service in ('ingestion-service', 'operations-service'):
                expect(service, 'readyz', 503)
                expect(service, 'livez', 200)
            check('database-loss-is-not-process-death')
            compose('down', '--timeout', '10')
            compose('up', '-d', '--wait', '--wait-timeout', '180')
            for database, table in [('ingestion_db', 'delivery_stream'), ('operations_db', 'simulation_run')]:
                check(database + '-record-survives-down-up', sql(database, f"SELECT count(*) FROM {table} WHERE run_id='{run_id}';") == '1')
                check(database + '-migration-history-preserved', sql(database, "SELECT count(*) FROM flyway_schema_history WHERE version='1' AND success;") == '1')
            check('all-services-recovered')
            results['status'] = 'PASS'
        except Exception:
            results['status'] = 'FAIL'
            raise
        finally:
            # Restart before cleaning only these uniquely named rows; never DROP/volume-delete.
            try:
                compose('up', '-d', '--wait', '--wait-timeout', '180', 'postgres')
                for database, table in [('ingestion_db', 'delivery_stream'), ('operations_db', 'simulation_run')]:
                    sql(database, f"DELETE FROM {table} WHERE run_id='{run_id}';")
            finally:
                if not args.keep_running:
                    compose('down', '--timeout', '10')
                results['keptRunning'] = args.keep_running
                results['checkedAt'] = datetime.now(timezone.utc).isoformat()
                (evidence / 'result.json').write_text(json.dumps(results, indent=2) + '\n')
                print('Evidence: ' + str(evidence.relative_to(ROOT)), flush=True)


if __name__ == '__main__':
    main()
