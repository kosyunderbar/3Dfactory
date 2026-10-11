"""Manual maintenance exercise. All model writes stay on the simulation thread."""
from datetime import datetime, timezone
import json
from queue import Empty, Queue
import sys
import threading

from .model import CellState


class ManualMaintenance:
    def __init__(self, model, change, publish=lambda state: None):
        self.model, self.change, self.publish = model, change, publish
        self.fault = None
        self.triggered = False
        self.commands = Queue(maxsize=32)
        self.last_command = None

    @property
    def active(self):
        return self.fault is not None and self.fault['stage'] != 'RESOLVED'

    def state(self):
        # JSON round trip isolates public state from subsequent history changes.
        return json.loads(json.dumps(dict(runId=self.model.run_id, mode='MANUAL',
                                         faults=[self.fault] if self.fault else [],
                                         lastCommand=self.last_command)))

    def record(self, stage, message, actor):
        self.fault['stage'] = stage
        self.fault['history'].append(dict(stage=stage, message=message, actor=actor,
            simElapsedMs=self.model.sim_elapsed_ms,
            at=datetime.now(timezone.utc).isoformat()))

    def command(self, command):
        if (not isinstance(command, dict) or set(command) != {'requestId', 'runId', 'faultId', 'action'}
                or not isinstance(command['requestId'], str) or len(command['requestId']) > 64):
            return
        request_id = command['requestId']
        # Retries of an acknowledged command must not repeat a transition.
        if self.last_command and self.last_command['requestId'] == request_id:
            self.publish(self.state())
            return
        message = None
        if command['runId'] != self.model.run_id or not self.fault or command['faultId'] != self.fault['faultId']:
            message = '현재 실행의 장애가 아닙니다.'
        elif command['action'] == 'inspect' and self.fault['stage'] == 'DETECTED':
            self.record('INSPECTING', '사용자가 현장 점검을 시작했습니다. 조치 완료 확인을 기다립니다.', 'USER')
        elif command['action'] == 'repair' and self.fault['stage'] == 'INSPECTING':
            self.fault['verifyUntilMs'] = self.model.sim_elapsed_ms + 2000
            self.record('VERIFYING', '사용자가 센서 재정렬·원점 복귀 완료를 확인했습니다. 재가동 전 동작을 확인합니다.', 'USER')
        else:
            message = '이미 처리됐거나 현재 단계에서 사용할 수 없는 조작입니다.'
        self.last_command = dict(requestId=request_id, ok=message is None, message=message)
        self.publish(self.state())

    def step(self):
        while True:
            try:
                self.command(self.commands.get_nowait())
            except Empty:
                break
        cell = self.model.cell('ASM-01')
        if not self.triggered and cell.state == CellState.RUNNING:
            operation = next(op for op in self.model.operations if op.operation_id == cell.operation_id)
            if operation.elapsed_ms >= 1000:
                self.change(self.model.fail_cell, 'ASM-01')
                self.triggered = True
                self.fault = dict(faultId='fault-00001', cellId='ASM-01', bodyId=operation.body_id,
                    operationId=operation.operation_id, code='CLAMP_POSITION_MISMATCH',
                    cause='체결 장치 위치 센서 불일치',
                    explanation='체결 장치의 목표 위치와 센서 신호가 일치하지 않아 조립을 정지했습니다.',
                    action='위치 센서 재정렬 및 체결 장치 원점 복귀',
                    occurredMs=self.model.sim_elapsed_ms, elapsedWorkMs=operation.elapsed_ms,
                    requiredWorkMs=operation.required_ms, resolvedMs=None, history=[])
                self.record('DETECTED', '위치 센서 불일치 감지. 해당 설비를 정지하고 작업 진행량을 보존했습니다.', 'SCENARIO')
                self.change(self.model.publish_snapshot)
                self.publish(self.state())
        if self.fault and self.fault['stage'] == 'VERIFYING' and self.model.sim_elapsed_ms >= self.fault['verifyUntilMs']:
            self.change(self.model.recover_cell, self.fault['cellId'])
            self.fault['resolvedMs'] = self.model.sim_elapsed_ms
            self.record('RESOLVED', '동작 확인 완료. 정지 시점의 남은 조립 작업을 재개했습니다.', 'SIMULATOR')
            self.change(self.model.publish_snapshot)
            self.publish(self.state())

    def read_stdin(self):
        def read():
            for line in sys.stdin:
                if len(line) > 512:
                    continue
                try:
                    self.commands.put(json.loads(line))
                except (ValueError, TypeError):
                    continue
        threading.Thread(target=read, daemon=True, name='maintenance-commands').start()
