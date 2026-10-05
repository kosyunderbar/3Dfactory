from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from factory_simulator.configuration import Settings
from factory_simulator.model import FactoryModel, Location, LocationType
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.sender import BudgetPressure, Original, PendingQueue, Sender, SenderPaused, SourceSession


class FakeSocket:
    def __init__(self, replies, sent):
        self.replies, self.sent = list(replies), sent

    def settimeout(self, timeout):
        pass

    def sendall(self, frame):
        self.sent.append(frame)

    def recv(self, size):
        return self.replies.pop(0) if self.replies else b''

    def close(self):
        pass


class SenderTests(unittest.TestCase):
    def model(self):
        return FactoryModel(RunConfiguration.from_path(), clock=lambda: datetime(2026, 10, 5, tzinfo=timezone.utc))

    def ack(self, original, **changes):
        value = dict(protocolVersion=1, kind='INGESTION_ACK', runId=original.run_id, sourceId=original.source_id,
                     eventId=original.event_id, sourceSeq=original.source_seq, eventSha256=original.sha256,
                     status='RECEIVED', code='OK', receivedAt='2026-10-05T00:00:00.000Z',
                     committedAt='2026-10-05T00:00:00.001Z', retryAfterMs=None)
        value.update(changes)
        return json.dumps(value).encode()+b'\n'

    def test_lost_broken_unrelated_ack_retries_identical_original_with_one_in_flight(self):
        model = self.model()
        model.register_body()
        queue = PendingQueue()
        queue.enqueue_batch(model.events)
        original = queue.head
        sent, waits = [], []
        good = self.ack(original, status='DUPLICATE_RECEIVED')
        responses = [[], [b'{bad}\n'], [self.ack(original, eventSha256='0'*64)], [good[:10], good[10:]]]
        with tempfile.TemporaryDirectory() as tmp:
            sender = Sender(Settings('127.0.0.1', 9090), queue,
                            connector=lambda *_args, **_kwargs: FakeSocket(responses.pop(0), sent),
                            sleep=waits.append, jitter=lambda: 0, error_path=Path(tmp)/'errors')
            self.assertIs(sender.send_head(), original)
            self.assertEqual(sent, [original.frame]*4)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue.head.source_seq, 2)
            self.assertEqual(waits, [0.5, 1, 2])
            self.assertEqual(sender.confirmed, [(1, 'DUPLICATE_RECEIVED')])

    def test_ten_attempt_pause_retry_after_and_rejection_preserve_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ('network', 'retry', 'config', 'rejected', 'unreadable'):
                queue = PendingQueue()
                queue.enqueue_batch(self.model().events)
                original = queue.head
                sent, waits, attempts = [], [], []
                def connect(*args, **kwargs):
                    attempts.append(1)
                    if mode == 'network':
                        raise OSError('Unavailable')
                    if mode in ('rejected', 'unreadable'):
                        changes = dict(status='REJECTED', code='SCHEMA_INVALID', committedAt=None)
                        if mode == 'unreadable':
                            changes.update(runId=None, sourceId=None, eventId=None, sourceSeq=None, eventSha256=None)
                    else:
                        changes = dict(status='RETRY_LATER', code='OUTBOX_FULL', committedAt=None,
                                       retryAfterMs=2000 if mode == 'retry' else 30001)
                    return FakeSocket([self.ack(original, **changes)], sent)
                sender = Sender(Settings('127.0.0.1', 9090), queue, connector=connect, sleep=waits.append,
                                jitter=lambda: 1, error_path=Path(tmp)/(mode+'.ndjson'))
                with self.assertRaises(SenderPaused):
                    sender.send_head()
                self.assertIs(queue.head, original)
                self.assertEqual(len(attempts), 10 if mode in ('network', 'retry') else 1)
                self.assertEqual(sender.state, 'PAUSED_RETRY' if mode in ('network', 'retry') else
                                 'PAUSED_CONFIG' if mode == 'config' else 'STOPPED_REJECTED')
                self.assertTrue(all(0 < delay <= 30 for delay in waits))
                if mode == 'retry':
                    self.assertEqual(waits[0], 2)
                self.assertTrue(sender.error_path.exists())
                if mode in ('network', 'retry', 'config'):
                    sender.resume()
                    self.assertEqual(sender.attempts, 0)
                    self.assertIs(queue.head, original)
                else:
                    with self.assertRaises(SenderPaused):
                        sender.resume()

    def test_atomic_count_byte_budget_tick_rollback_pause_and_safe_resume(self):
        model = self.model()
        body = model.register_body()
        pending = PendingQueue(max_events=3)
        sender = Sender(Settings('127.0.0.1', 9090), pending)
        session = SourceSession(model, sender)
        before = model.snapshot()
        session.change(model.assign_transport, body.body_id)  # Two generated events cannot fit; rollback first.
        after = model.snapshot()
        self.assertEqual(after['runState'], 'PAUSED')
        self.assertEqual(after['simElapsedMs'], before['simElapsedMs'])
        self.assertEqual(after['bodies'], before['bodies'])
        self.assertEqual(after['buffers'], before['buffers'])
        self.assertEqual(after['activeTransports'], [])
        self.assertEqual([e.to_dict()['eventType'] for e in model.events], ['RUN_STARTED', 'BODY_REGISTERED', 'RUN_STATE_CHANGED'])
        self.assertEqual(len(pending), 3)
        for _ in range(3):
            pending.acknowledge(pending.head)
        model.discard_confirmed_events(3)
        session.change(model.resume)
        self.assertEqual(model.events[0].to_dict()['sourceSeq'], 4)
        self.assertEqual(model.snapshot()['runState'], 'RUNNING')
        self.assertEqual(model.assign_transport(body.body_id).transport_id, 'transport-00001')
        original = Original.from_frame(self.model().events[0].ndjson.encode())
        bytes_queue = PendingQueue(max_bytes=len(original.frame))
        bytes_queue.enqueue_originals([original])
        with self.assertRaises(BudgetPressure):
            bytes_queue.enqueue_originals([original])
        self.assertEqual((len(bytes_queue), bytes_queue.bytes), (1, len(original.frame)))
        high = PendingQueue()
        high.enqueue_originals([original]*900)
        self.assertTrue(high.should_pause)
        self.assertFalse(high.may_resume)
        for _ in range(401):
            high.acknowledge(high.head)
        self.assertTrue(high.may_resume)
        # A real completion tick must also roll back simulated time, work, facts and physical state.
        data = RunConfiguration.from_path().to_dict()
        data['config']['equipment'][0]['workDurationMs'] = 100
        working = FactoryModel(RunConfiguration.from_dict(data), allow_initial_fixtures=True,
                               clock=lambda: datetime(2026, 10, 5, tzinfo=timezone.utc))
        working.register_fixture_body(Location(LocationType.CELL, 'ASM-01'))
        working.start_work('ASM-01')
        tick_pending = PendingQueue(max_events=len(working.events)+1)
        tick_session = SourceSession(working, Sender(Settings('127.0.0.1', 9090), tick_pending))
        work_before, time_before = working.cell('ASM-01'), working.sim_elapsed_ms
        tick_session.tick()
        self.assertEqual(working.cell('ASM-01'), work_before)
        self.assertEqual(working.sim_elapsed_ms, time_before)
        self.assertEqual(working.snapshot()['runState'], 'PAUSED')
        self.assertEqual(working.events[-1].to_dict()['eventType'], 'RUN_STATE_CHANGED')
        manual = self.model()
        manual_session = SourceSession(manual, Sender(Settings('127.0.0.1', 9090)))
        manual_session.automatic_pause = True
        manual_session.pause()
        manual_session.tick()
        self.assertEqual(manual.snapshot()['runState'], 'PAUSED')
