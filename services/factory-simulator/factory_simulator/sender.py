"""S03: bounded volatile pending originals, one in-flight event and strictly correlated ACKs."""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import random
import re
import socket
import time


class BudgetPressure(ValueError):
    pass


class SenderPaused(RuntimeError):
    pass


class BadAck(ValueError):
    pass


class BadConfiguration(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _parse(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', value):
        raise BadAck('Invalid ACK time')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise BadAck('Invalid ACK time') from error


@dataclass(frozen=True)
class Original:
    frame: bytes
    run_id: str
    source_id: str
    event_id: str
    source_seq: int
    sha256: str

    @classmethod
    def from_frame(cls, frame):
        if not isinstance(frame, bytes) or not 2 <= len(frame) <= 65536 or not frame.endswith(b'\n'):
            raise ValueError('Expected one UTF-8 NDJSON frame, <=65536 bytes including LF')
        raw = frame[:-1]
        if b'\n' in raw or b'\r' in raw or raw.startswith(b'\xef\xbb\xbf'):
            raise ValueError('Invalid NDJSON frame')
        event = _parse(raw.decode('utf-8'))
        if not isinstance(event, dict):
            raise ValueError('Event must be an object')
        for field, pattern in [('runId', r'run-\d{8}-[a-z0-9]{3,32}'),
                               ('sourceId', r'simulator-\d{2,4}'),
                               ('eventId', r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')]:
            if not isinstance(event.get(field), str) or not re.fullmatch(pattern, event[field]):
                raise ValueError('Invalid event identifier: ' + field)
        datetime.strptime(event['runId'][4:12], '%Y%m%d')
        seq = event.get('sourceSeq')
        if type(seq) is not int or not 1 <= seq <= 9007199254740991:
            raise ValueError('Invalid sourceSeq')
        return cls(frame, event['runId'], event['sourceId'], event['eventId'], seq, hashlib.sha256(raw).hexdigest())


class PendingQueue:
    """Single writer, all-or-nothing batch admission. Bytes include the frame's LF conservatively."""
    def __init__(self, *, max_events=1000, max_bytes=64*1024*1024):
        self._items = deque()
        self.bytes = 0
        self.max_events, self.max_bytes = max_events, max_bytes

    def __len__(self):
        return len(self._items)

    @property
    def head(self):
        return self._items[0]

    @property
    def should_pause(self):
        return len(self) >= 900 or self.bytes >= 60*1024*1024

    @property
    def may_resume(self):
        return len(self) < 500 and self.bytes < 32*1024*1024

    def enqueue_batch(self, events):
        staged = [Original.from_frame(e.ndjson.encode('utf-8')) for e in events]
        self.enqueue_originals(staged)

    def enqueue_originals(self, staged):
        added = sum(len(e.frame) for e in staged)
        if len(self)+len(staged) > self.max_events or self.bytes+added > self.max_bytes:
            raise BudgetPressure('Pending event limit reached; transition must roll back')
        self._items.extend(staged)
        self.bytes += added

    def acknowledge(self, original):
        if self.head is not original:
            raise ValueError('Only the confirmed head can be removed')
        self._items.popleft()
        self.bytes -= len(original.frame)


class Sender:
    def __init__(self, settings, pending=None, *, connector=socket.create_connection,
                 sleep=time.sleep, jitter=random.random, error_path=Path('logs/simulator-send-errors.ndjson')):
        self.settings = settings
        self.pending = pending if pending is not None else PendingQueue()
        self.connector, self.sleep, self.jitter = connector, sleep, jitter
        self.error_path = Path(error_path)
        self.state = 'READY'
        self.attempts = 0
        self.connection = None
        self.confirmed = []  # Recent confirmation only: never an unbounded success journal.

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _error(self, original, code):
        self.error_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(self.error_path, maxBytes=10*1024*1024, backupCount=2, encoding='utf-8')
        try:
            record = {'timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                      'runId': original.run_id, 'sourceId': original.source_id,
                      'eventId': original.event_id, 'sourceSeq': original.source_seq,
                      'eventSha256': original.sha256, 'code': code, 'state': self.state,
                      'attempts': self.attempts}
            handler.emit(logging.LogRecord('sender', logging.ERROR, '', 0, json.dumps(record), (), None))
        finally:
            handler.close()

    def _read_ack(self):
        end = time.monotonic()+3
        response = bytearray()
        while True:
            remaining = end-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('ACK deadline')
            self.connection.settimeout(remaining)
            chunk = self.connection.recv(4096-len(response))
            if not chunk:
                raise ConnectionError('Connection closed before ACK')
            response.extend(chunk)
            if b'\n' in response:
                if not response.endswith(b'\n') or response.count(b'\n') != 1 or b'\r' in response:
                    raise BadAck('ACK framing')
                return _parse(response[:-1].decode('utf-8'))
            if len(response) >= 4096:
                raise BadAck('ACK too large')

    def _validate_ack(self, ack, original):
        fields = set('protocolVersion kind runId sourceId eventId sourceSeq eventSha256 status code receivedAt committedAt retryAfterMs'.split())
        if not isinstance(ack, dict) or set(ack) != fields or type(ack['protocolVersion']) is not int or ack['protocolVersion'] != 1 or ack['kind'] != 'INGESTION_ACK':
            raise BadAck('ACK envelope')
        _time(ack['receivedAt'])
        identity = (ack['runId'], ack['sourceId'], ack['eventId'], ack['sourceSeq'])
        expected = (original.run_id, original.source_id, original.event_id, original.source_seq)
        if ack['status'] == 'REJECTED' and identity == (None, None, None, None):
            if ack['committedAt'] is not None or ack['retryAfterMs'] is not None:
                raise BadAck('Unreadable rejection shape')
            if ack['code'] not in REJECTION_CODES:
                raise BadAck('Unknown rejection code')
            return 'REJECTED', ack['code'], None
        if identity != expected or type(ack['sourceSeq']) is not int or ack['eventSha256'] != original.sha256:
            raise BadAck('ACK correlation')
        status, code = ack['status'], ack['code']
        if status in ('RECEIVED', 'DUPLICATE_RECEIVED'):
            if code != 'OK' or ack['retryAfterMs'] is not None:
                raise BadAck('ACK success shape')
            _time(ack['committedAt'])
        elif status == 'REJECTED':
            if code not in REJECTION_CODES or ack['committedAt'] is not None or ack['retryAfterMs'] is not None:
                raise BadAck('ACK rejection shape')
        elif status == 'RETRY_LATER':
            delay = ack['retryAfterMs']
            if code not in RETRY_CODES or ack['committedAt'] is not None or type(delay) is not int or delay < 1:
                raise BadAck('ACK retry shape')
            if delay > 30000:
                raise BadConfiguration('retryAfterMs exceeds v1 maximum')
        else:
            raise BadAck('ACK status')
        return status, code, ack['retryAfterMs']

    def send_head(self):
        if self.state != 'READY':
            raise SenderPaused(self.state)
        if not self.pending:
            return None
        original = self.pending.head
        while self.attempts < 10:
            self.attempts += 1
            retry_after = 0
            try:
                if self.connection is None:
                    self.connection = self.connector((self.settings.ingestion_host, self.settings.ingestion_port), timeout=2)
                self.connection.settimeout(3)
                self.connection.sendall(original.frame)
                status, code, retry_after = self._validate_ack(self._read_ack(), original)
                if status in ('RECEIVED', 'DUPLICATE_RECEIVED'):
                    self.pending.acknowledge(original)
                    self.attempts = 0
                    self.confirmed[:] = [(original.source_seq, status)]
                    return original
                if status == 'REJECTED':
                    self.state = 'STOPPED_REJECTED'
                    self.close()
                    self._error(original, code)
                    raise SenderPaused(code)
            except BadConfiguration as error:
                self.state = 'PAUSED_CONFIG'
                self.close()
                self._error(original, str(error))
                raise SenderPaused(str(error)) from error
            except (OSError, ValueError, ConnectionError):
                # A broken/unrelated response has never acknowledged this original.
                retry_after = 0
            self.close()
            if self.attempts >= 10:
                break
            delay = min(500*2**(self.attempts-1),30000)
            delay = min(30000, delay*(1+0.1*self.jitter()))
            self.sleep(max(delay, retry_after or 0)/1000)
        self.state = 'PAUSED_RETRY'
        self._error(original, 'RETRY_EXHAUSTED')
        raise SenderPaused('Ten attempts exhausted; original remains pending')

    def resume(self):
        if self.state == 'STOPPED_REJECTED':
            raise SenderPaused('Rejected run needs a new run')
        self.state, self.attempts = 'READY', 0

    def drain(self):
        while self.pending:
            self.send_head()

    def send_file(self, path):
        """Stream one bounded line at a time; replay never parses/reserializes the sent original."""
        count = 0
        with Path(path).open('rb') as source:
            while frame := source.readline(65537):
                self.pending.enqueue_originals([Original.from_frame(frame)])
                self.send_head()
                count += 1
        return count


REJECTION_CODES = set('INVALID_UTF8 INVALID_JSON INVALID_FRAME FRAME_TOO_LARGE FRAME_TIMEOUT SCHEMA_INVALID UNSUPPORTED_SCHEMA ID_CONFLICT SEQUENCE_CONFLICT SOURCE_CONFLICT'.split())
RETRY_CODES = set('DB_UNAVAILABLE INGESTION_BUSY OUTBOX_FULL HISTORY_LIMIT CLOCK_AHEAD DIAGNOSTIC_UNAVAILABLE'.split())


class SourceSession:
    """Model and source share one writer. A failed admission rolls back that whole transition."""
    def __init__(self, model, sender):
        self.model, self.sender = model, sender
        self.automatic_pause = False
        self.control_event = False
        sender.pending.enqueue_batch(model.events)
        model.set_event_sink(self._admit)

    def _admit(self, events):
        # Reserve 100 events / 4 MiB for the PAUSED control event before hitting hard limits.
        originals = [Original.from_frame(e.ndjson.encode('utf-8')) for e in events]
        queue = self.sender.pending
        added = sum(len(e.frame) for e in originals)
        if not self.control_event and (len(queue)+len(originals) > 900 or queue.bytes+added > 60*1024*1024):
            raise BudgetPressure('Production transition would consume reserved pause capacity')
        queue.enqueue_originals(originals)
        # PendingQueue is all-or-nothing and this is the last action before model commit.

    def _control(self, method):
        self.control_event = True
        try:
            method()
        finally:
            self.control_event = False

    def pause(self):
        """An operator pause overrides any automatic backpressure pause."""
        self.automatic_pause = False
        self._control(self.model.pause)

    def resume(self):
        if self.sender.state != 'READY':
            raise SenderPaused('Resolve and explicitly resume the sender first')
        self.automatic_pause = False
        self._control(self.model.resume)

    def change(self, method, *args, **kwargs):
        if method == self.model.pause:
            return self.pause()
        if method == self.model.resume:
            return self.resume()
        if self.sender.state != 'READY':
            if not self.model.snapshot()['runState'] == 'PAUSED':
                self._control(self.model.pause)
            return None
        if method == self.model.publish_snapshot and self.model.snapshot()['runState'] == 'PAUSED':
            # Reporting a paused observation cannot advance or automatically resume the factory.
            if self.sender.pending.should_pause:
                return None
            try:
                return method(*args, **kwargs)
            except BudgetPressure:
                return None
        if self.automatic_pause:
            if not self.sender.pending.may_resume:
                return None
            self._control(self.model.resume)
            self.automatic_pause = False
        elif self.model.snapshot()['runState'] == 'PAUSED':
            return None  # An intentional pause never automatically resumes.
        if self.sender.pending.should_pause:
            self._control(self.model.pause)
            self.automatic_pause = True
            return None
        try:
            return method(*args, **kwargs)
        except BudgetPressure:
            self._control(self.model.pause)
            self.automatic_pause = True
            return None

    def tick(self):
        return self.change(self.model.tick)

    def send_head(self):
        try:
            confirmed = self.sender.send_head()
        except SenderPaused:
            if self.model.snapshot()['runState'] != 'FINISHED':
                self._control(self.model.pause)
            raise
        if confirmed:
            self.model.discard_confirmed_events(confirmed.source_seq)
        return confirmed
