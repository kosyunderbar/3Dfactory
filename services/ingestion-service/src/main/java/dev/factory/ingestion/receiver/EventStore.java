package dev.factory.ingestion.receiver;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/** One admission worker. Checks and the three inserts run in a single database transaction. */
public final class EventStore {
    public record Limits(long pendingCount,long pendingBytes,long runCount,long runBytes,long totalCount,long totalBytes) {
        public static final Limits V1=new Limits(5000,134217728,50000,536870912,250000,1073741824);
    }
    private record Existing(String event,String source,long seq,String raw,String hash,Instant received) {}
    private record Outcome(String status,String code,Instant received) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final Limits limits;
    private final Runnable afterRawInsert;
    public EventStore(JdbcTemplate jdbc,TransactionTemplate transaction) { this(jdbc,transaction,Limits.V1,()->{}); }
    EventStore(JdbcTemplate jdbc,TransactionTemplate transaction,Limits limits,Runnable afterRawInsert) {
        this.jdbc=jdbc; this.transaction=transaction; this.limits=limits; this.afterRawInsert=afterRawInsert;
    }
    public synchronized Protocol.Ack receive(Protocol.Event event,Instant received) {
        long start=dev.factory.ingestion.measurement.Measurements.start();
        Protocol.Ack reply=receiveInternal(event,received);
        var id=event.identity();
        dev.factory.ingestion.measurement.Measurements.record("ingestion-transaction",id.runId(),id.eventId(),id.sourceSeq(),reply.status(),start);
        return reply;
    }
    private Protocol.Ack receiveInternal(Protocol.Event event,Instant received) {
        Outcome result;
        try { result=transaction.execute(status -> accept(event,received)); }
        catch(RuntimeException unavailable) {
            // Includes a failed/ambiguous commit: never infer success from an INSERT returning.
            return Protocol.Ack.of(event.identity(),event.hash(),"RETRY_LATER","DB_UNAVAILABLE",received);
        }
        // TransactionTemplate has returned AFTER commit. Duplicate queries have also committed.
        return Protocol.Ack.of(event.identity(),event.hash(),result.status(),result.code(),result.received());
    }
    /** Unknown-run errors remain in the bounded rejection log; never create a valid stream for bad input. */
    public boolean recordRejected(Protocol.Ack ack) {
        if(ack.runId()==null) return true;
        try {transaction.execute(status->{jdbc.update("UPDATE delivery_stream SET diagnostic_rejected_count=diagnostic_rejected_count+1 WHERE run_id=?",ack.runId());return null;});return true;}
        catch(RuntimeException unavailable){return false;}
    }
    private Outcome accept(Protocol.Event e,Instant received) {
        var id=e.identity();
        // Also serialize admissions if a second caller is accidentally introduced in this P0 process.
        jdbc.execute("SELECT pg_advisory_xact_lock(7303001)");
        var sources=jdbc.queryForList("SELECT source_id FROM delivery_stream WHERE run_id=?",String.class,id.runId());
        if(!sources.isEmpty() && !sources.getFirst().equals(id.sourceId())) return rejected("SOURCE_CONFLICT",received);
        List<Existing> byId=find("run_id=? AND event_id=?::uuid",id.runId(),id.eventId());
        List<Existing> bySeq=find("run_id=? AND source_id=? AND source_seq=?",id.runId(),id.sourceId(),id.sourceSeq());
        if(!byId.isEmpty()) {
            Existing old=byId.getFirst();
            if(old.source().equals(id.sourceId()) && old.seq()==id.sourceSeq() && !bySeq.isEmpty()
                    && bySeq.getFirst().event().equals(id.eventId()) && old.hash().equals(e.hash()) && old.raw().equals(e.raw()))
                return new Outcome("DUPLICATE_RECEIVED","OK",old.received());
            return rejected("ID_CONFLICT",received);
        }
        if(!bySeq.isEmpty()) return rejected("SEQUENCE_CONFLICT",received);
        if(e.occurredAt().isAfter(received.plusMillis(5000))) return retry("CLOCK_AHEAD",received);
        long size=e.raw().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
        var pending=jdbc.queryForMap("SELECT count(*) AS n,COALESCE(sum(octet_length(r.raw_json_text)),0) AS bytes FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE o.delivery_status<>'DELIVERED'");
        if(over(pending,size,limits.pendingCount(),limits.pendingBytes())) return retry("OUTBOX_FULL",received);
        var perRun=jdbc.queryForMap("SELECT count(*) AS n,COALESCE(sum(octet_length(raw_json_text)),0) AS bytes FROM raw_event WHERE run_id=?",id.runId());
        var total=jdbc.queryForMap("SELECT count(*) AS n,COALESCE(sum(octet_length(raw_json_text)),0) AS bytes FROM raw_event");
        if(over(perRun,size,limits.runCount(),limits.runBytes()) || over(total,size,limits.totalCount(),limits.totalBytes()))
            return retry("HISTORY_LIMIT",received);
        jdbc.update("INSERT INTO delivery_stream(run_id,source_id) VALUES (?,?) ON CONFLICT(run_id) DO NOTHING",id.runId(),id.sourceId());
        jdbc.update("INSERT INTO raw_event(run_id,event_id,source_id,source_seq,schema_version,type,occurred_at,received_at,raw_json_text,payload,payload_hash) VALUES (?,?::uuid,?,?,1,?,?,?,?,?::jsonb,?)",
            id.runId(),id.eventId(),id.sourceId(),id.sourceSeq(),e.json().get("eventType").stringValue(),
            Timestamp.from(e.occurredAt()),Timestamp.from(received),e.raw(),e.json().get("payload").toString(),e.hash());
        afterRawInsert.run(); // Test seam: real PostgreSQL rollback between the two required writes.
        jdbc.update("INSERT INTO event_outbox(run_id,event_id) VALUES (?,?::uuid)",id.runId(),id.eventId());
        return new Outcome("RECEIVED","OK",received);
    }
    private boolean over(java.util.Map<String,Object> stats,long bytes,long countCap,long byteCap) {
        return ((Number)stats.get("n")).longValue()+1>countCap || ((Number)stats.get("bytes")).longValue()+bytes>byteCap;
    }
    private List<Existing> find(String where,Object... args) {
        return jdbc.query("SELECT event_id::text,source_id,source_seq,raw_json_text,payload_hash,received_at FROM raw_event WHERE "+where,
            (rs,n)->new Existing(rs.getString(1),rs.getString(2),rs.getLong(3),rs.getString(4),rs.getString(5),rs.getTimestamp(6).toInstant()),args);
    }
    private Outcome rejected(String code,Instant received) { return new Outcome("REJECTED",code,received); }
    private Outcome retry(String code,Instant received) { return new Outcome("RETRY_LATER",code,received); }
}
