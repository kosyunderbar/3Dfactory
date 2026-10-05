#!/usr/bin/env python3
"""Optional workspace-local macOS arm64 tools; no system installation or VM startup."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=['node', 'docker'])
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        raise SystemExit('This optional helper supports macOS arm64 only. Use Node 24 / Docker Compose on your platform.')
    selected = ['node'] if args.group == 'node' else ['docker', 'compose', 'buildx', 'lima']
    lock = json.loads((ROOT / 'infrastructure/local-tools.lock.json').read_text())['tools']
    tools = ROOT / '.build-cache/tools'
    downloads = tools / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    for key in selected:
        item = lock[key]
        archive = downloads / item['file']
        if not archive.exists():
            partial = archive.with_suffix(archive.suffix + '.partial')
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', item['url'],
                            '--output', str(partial)], check=True)
            partial.replace(archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item['sha256']:
            raise SystemExit(f'Checksum mismatch: {key}; remove the damaged cached archive and retry.')
        if item['extractTo'] is not None:
            target = tools / item['extractTo']
            target.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive) as contents:
                contents.extractall(target, filter='data')
        else:
            destination = tools / ('docker-compose' if key == 'compose' else 'docker-buildx')
            shutil.copy2(archive, destination)
            destination.chmod(0o755)
        print(key + ': downloaded archive matches pinned SHA-256')
    if args.group == 'docker':
        plugins = ROOT / '.build-cache/docker-config/cli-plugins'
        plugins.mkdir(parents=True, exist_ok=True)
        for name in ['docker-compose', 'docker-buildx']:
            shutil.copy2(tools / name, plugins / name)
            (plugins / name).chmod(0o755)
    print('Prepared local tools. No VM has been started.')


if __name__ == '__main__':
    main()
