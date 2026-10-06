"""Factory model and offline work demo; normal startup stays idle; --send-events explicitly transmits an NDJSON file."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from .configuration import Settings
from .sender import Sender, SenderPaused
from .run_configuration import DEFAULT_CONFIG, RunConfiguration
from .model import FactoryModel
from .work_demo import demo_work
from .dispatch_demo import demo_dispatch
from .transport_demo import demo_transport
from .scenario_demo import demo_scenarios
from .connected_demo import run_connected
from .p0_demo import run_p0

HEARTBEAT = Path(os.environ.get("SIMULATOR_HEARTBEAT_PATH", "/tmp/factory-simulator-heartbeat"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send-events", type=Path, help="Send original NDJSON file bytes to ingestion; one ACK-confirmed event at a time")
    mode.add_argument("--connected-p0-demo", action="store_true", help="Explicit registered-body P0 buffer stages, parts AMR, fault/recovery and quality")
    mode.add_argument("--connected-demo", action="store_true", help="Explicit wall-paced one-body model -> TCP -> outbox -> operations; no automatic startup production")
    mode.add_argument("--connected-three-demo", action="store_true", help="Three normally registered bodies, all PASS, using real TCP delivery")
    mode.add_argument("--check-config", action="store_true")
    mode.add_argument("--healthcheck", action="store_true")
    mode.add_argument("--inspect-model", action="store_true", help="Print a local model description without network settings")
    mode.add_argument("--demo-work", action="store_true", help="Offline three-cell work fixture, without dispatch/transport")
    mode.add_argument("--demo-dispatch", action="store_true", help="Offline buffer lock and last-slot allocation fixtures")
    mode.add_argument("--demo-transport", action="store_true", help="Offline pickup, arrival, cell entry, return and redispatch")
    mode.add_argument("--demo-scenarios", action="store_true", help="Offline cancellation, cell failure/recovery, parts AMR and v1 events")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Run configuration JSON path")
    parser.add_argument("--initial-bodies", type=int, default=0, help="Register N bodies at BODY-IN, without starting production")
    args = parser.parse_args()
    if args.healthcheck:
        try:
            age = time.time() - HEARTBEAT.stat().st_mtime
            return 0 if 0 <= age < 10 else 1
        except OSError:
            return 1
    if args.send_events:
        sender = None
        try:
            sender = Sender(Settings.from_environment(os.environ))
            count = sender.send_file(args.send_events)
            print(json.dumps({'state': 'INGESTION_CONFIRMED', 'events': count,
                              'operationsApplied': False, 'guiLive': False}))
            return 0
        except (ValueError, OSError, SenderPaused) as error:
            print(str(error), file=sys.stderr)
            return 2
        finally:
            if sender is not None:
                sender.close()
    try:
        configuration = RunConfiguration.from_path(args.config)
        if not 0 <= args.initial_bodies <= configuration.factory['maxBodies']:
            raise ValueError("--initial-bodies must be 0..maxBodies")
        if (args.connected_demo or args.connected_three_demo or args.connected_p0_demo or args.demo_work or args.demo_dispatch or args.demo_transport or args.demo_scenarios) and args.initial_bodies != 0:
            raise ValueError("Demo modes cannot be combined with --initial-bodies")
        if not (args.inspect_model or args.demo_work or args.demo_dispatch or args.demo_transport or args.demo_scenarios):
            Settings.from_environment(os.environ)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.connected_demo or args.connected_three_demo or args.connected_p0_demo:
        stopped = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda _signal, _frame: stopped.set())
        try:
            if args.connected_p0_demo:
                return run_p0(configuration, Settings.from_environment(os.environ), stopped=stopped)
            return run_connected(configuration, Settings.from_environment(os.environ), stopped=stopped,
                                 body_count=3 if args.connected_three_demo else 1,
                                 max_seconds=600 if args.connected_three_demo else 300)
        except (ValueError, OSError, SenderPaused) as error:
            print(str(error), file=sys.stderr)
            return 2
    if args.check_config:
        print("Factory and TCP target configuration valid. Cell work and transport are available in the offline model; explicit NDJSON TCP sending is available; the production loop is not automatically started.")
        return 0
    if args.demo_work or args.demo_dispatch or args.demo_transport or args.demo_scenarios:
        try:
            demo = (demo_work if args.demo_work else demo_dispatch if args.demo_dispatch
                    else demo_transport if args.demo_transport else demo_scenarios)
            description = demo(configuration)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(json.dumps(description, ensure_ascii=False, indent=2))
        return 0
    model = FactoryModel(configuration)
    for _ in range(args.initial_bodies):
        model.register_body()
    if args.inspect_model:
        print(json.dumps(model.inspect(), ensure_ascii=False, indent=2))
        return 0
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _signal, _frame: stopped.set())
    print(json.dumps({"service": "factory-simulator", "state": "MODEL_INITIALIZED",
                      "runId": model.run_id, "registeredBodyCount": len(model.bodies),
                      "factoryRunStarted": False}), flush=True)
    try:
        while not stopped.is_set():
            HEARTBEAT.touch(mode=0o600)
            stopped.wait(1)
    finally:
        HEARTBEAT.unlink(missing_ok=True)
        print(json.dumps({"service": "factory-simulator", "state": "STOPPED"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
