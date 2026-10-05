package dev.factory.ingestion.delivery;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.*;
import org.springframework.transaction.support.TransactionTemplate;
import dev.factory.ingestion.receiver.Protocol;
import static dev.factory.ingestion.delivery.DeliveryWire.Action.*;

/** Durable head selection/reservation/result. Every HTTP call occurs after these transactions return. */
public final class DeliveryStore {
    public record Head(Protocol.Identity identity,String raw,String hash,Instant received,int attempts,long totalAttempts) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate write,read;
    private final Clock clock;
    private final Runnable afterDeliveredWrite;
    private String lastRun="";
    public DeliveryStore(JdbcTemplate jdbc,PlatformTransactionManager manager,Clock clock){this(jdbc,manager,clock,()->{});}
    DeliveryStore(JdbcTemplate jdbc,PlatformTransactionManager manager,Clock clock,Runnable afterDeliveredWrite){
        this.jdbc=jdbc;this.clock=clock;this.afterDeliveredWrite=afterDeliveredWrite;write=new TransactionTemplate(manager);write.setTimeout(3);
        read=new TransactionTemplate(manager);read.setReadOnly(true);read.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);read.setTimeout(3);
    }
    public Head reserveNext(){
        Instant now=now();
        return write.execute(tx->{
            var candidates=jdbc.queryForList("SELECT s.run_id FROM delivery_stream s WHERE s.state IN ('ACTIVE','RETRY_WAIT','GAP_WAIT','PAUSED_GAP') AND EXISTS (SELECT 1 FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE r.run_id=s.run_id AND r.source_seq>=s.next_source_seq AND o.delivery_status<>'DELIVERED') ORDER BY CASE WHEN s.run_id>? THEN 0 ELSE 1 END,s.run_id LIMIT 1",String.class,lastRun);
            if(candidates.isEmpty()) return null;String run=candidates.getFirst();lastRun=run;
            var stream=lock(run);if(!Set.of("ACTIVE","RETRY_WAIT","GAP_WAIT","PAUSED_GAP").contains(stream.get("state"))) return null;
            long next=((Number)stream.get("next_source_seq")).longValue();
            var heads=jdbc.queryForList("SELECT r.*,o.attempt_count,o.total_attempt_count,o.next_attempt_at,o.dependency_wait_started_at,o.delivery_status FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE r.run_id=? AND r.source_seq=?",run,next);
            if(heads.isEmpty()){
                Instant began=instant(stream.get("gap_started_at"));if(began==null) began=now;
                String state=Duration.between(began,now).toMillis()>=30000?"PAUSED_GAP":"GAP_WAIT";
                if(!state.equals(stream.get("state"))) jdbc.update("UPDATE delivery_stream SET state=?,blocked_seq=?,blocked_reason='SEQUENCE_GAP',gap_started_at=? WHERE run_id=?",state,next,Timestamp.from(began),run);
                return null;
            }
            var row=heads.getFirst();String status=row.get("delivery_status").toString();
            if(status.equals("DELIVERED") || status.equals("QUARANTINED")){pause(run,next,"PAUSED_CONFIG","CURSOR_CONFLICT");return null;}
            if(stream.get("gap_started_at")!=null) jdbc.update("UPDATE delivery_stream SET state='ACTIVE',gap_started_at=NULL,blocked_seq=NULL,blocked_reason=NULL WHERE run_id=?",run);
            int attempts=((Number)row.get("attempt_count")).intValue();long total=((Number)row.get("total_attempt_count")).longValue();
            Instant dependent=instant(row.get("dependency_wait_started_at"));
            if(dependent!=null && Duration.between(dependent,now).toMillis()>=30000){pause(run,next,"PAUSED_DEPENDENCY","DEPENDENCY_TIMEOUT");return null;}
            if(attempts>=20){pause(run,next,"PAUSED_RETRY","ATTEMPT_LIMIT");return null;}
            Instant due=instant(row.get("next_attempt_at"));if(due!=null && now.isBefore(due)) return null;
            String event=row.get("event_id").toString();
            // Reserve before sending. A crash retains the attempt and this conservative retry deadline.
            jdbc.update("UPDATE event_outbox SET delivery_status='RETRY_WAIT',attempt_count=attempt_count+1,total_attempt_count=total_attempt_count+1,last_attempt_at=?,next_attempt_at=? WHERE run_id=? AND event_id=?::uuid",Timestamp.from(now),Timestamp.from(now.plusMillis(5000)),run,event);
            jdbc.update("UPDATE delivery_stream SET state='RETRY_WAIT',gap_started_at=NULL,blocked_seq=NULL,blocked_reason=NULL,diagnostic_retry_count=diagnostic_retry_count+? WHERE run_id=?",total>0?1:0,run);
            return new Head(new Protocol.Identity(run,row.get("source_id").toString(),event,next),row.get("raw_json_text").toString(),row.get("payload_hash").toString(),instant(row.get("received_at")),attempts+1,total+1);
        });
    }
    public void complete(Head head,DeliveryWire.Decision result,double jitter){
        Instant now=now();write.execute(tx->{
            var id=head.identity();var streams=jdbc.queryForList("SELECT * FROM delivery_stream WHERE run_id=? FOR UPDATE",id.runId());if(streams.isEmpty()) return null;var stream=streams.getFirst();
            var rows=jdbc.queryForList("SELECT total_attempt_count,delivery_status,dependency_wait_started_at FROM event_outbox WHERE run_id=? AND event_id=?::uuid",id.runId(),id.eventId());
            if(rows.isEmpty() || !stream.get("state").equals("RETRY_WAIT") || ((Number)stream.get("next_source_seq")).longValue()!=id.sourceSeq() || ((Number)rows.getFirst().get("total_attempt_count")).longValue()!=head.totalAttempts()) return null;
            String prior=rows.getFirst().get("delivery_status").toString();if(Set.of("DELIVERED","QUARANTINED").contains(prior)) return null;
            String response=result.response()==null?null:Protocol.JSON.writeValueAsString(result.response());
            if(result.action()==DELIVERED){
                jdbc.update("UPDATE event_outbox SET delivery_status='DELIVERED',delivered_at=?,next_attempt_at=NULL,dependency_wait_started_at=NULL,last_error=NULL,last_response=?::jsonb WHERE run_id=? AND event_id=?::uuid",Timestamp.from(now),response,id.runId(),id.eventId());
                afterDeliveredWrite.run(); // Real DB constraint failure here proves cursor and success both roll back.
                jdbc.update("UPDATE delivery_stream SET next_source_seq=next_source_seq+1,state='ACTIVE',blocked_seq=NULL,blocked_reason=NULL,gap_started_at=NULL WHERE run_id=?",id.runId());return null;
            }
            if(result.action()==QUARANTINED){
                jdbc.update("UPDATE event_outbox SET delivery_status='QUARANTINED',quarantined_at=?,next_attempt_at=NULL,last_error=?,last_response=?::jsonb WHERE run_id=? AND event_id=?::uuid",Timestamp.from(now),result.code(),response,id.runId(),id.eventId());
                jdbc.update("UPDATE delivery_stream SET state='BLOCKED',blocked_seq=?,blocked_reason=?,diagnostic_rejected_count=diagnostic_rejected_count+1 WHERE run_id=?",id.sourceSeq(),result.code(),id.runId());return null;
            }
            Instant dependency=instant(rows.getFirst().get("dependency_wait_started_at"));if(result.action()==DEPENDENCY && dependency==null) dependency=now;
            String state=result.action()==CONFIG?"PAUSED_CONFIG":result.action()==BLOCKED?"BLOCKED":dependency!=null && Duration.between(dependency,now).toMillis()>=30000?"PAUSED_DEPENDENCY":head.attempts()>=20?"PAUSED_RETRY":"RETRY_WAIT";
            String code=state.equals("PAUSED_DEPENDENCY")?"DEPENDENCY_TIMEOUT":state.equals("PAUSED_RETRY")?"ATTEMPT_LIMIT":result.code();
            Instant due=state.equals("RETRY_WAIT")?now.plusMillis(DeliveryWire.delay(head.attempts(),result.delayMs(),jitter)):null;
            jdbc.update("UPDATE event_outbox SET last_error=?,last_response=?::jsonb,next_attempt_at=?,dependency_wait_started_at=? WHERE run_id=? AND event_id=?::uuid",result.code(),response,stamp(due),stamp(dependency),id.runId(),id.eventId());
            jdbc.update("UPDATE delivery_stream SET state=?,blocked_seq=?,blocked_reason=? WHERE run_id=?",state,state.equals("RETRY_WAIT")?null:id.sourceSeq(),state.equals("RETRY_WAIT")?null:code,id.runId());return null;
        });
    }
    private void pause(String run,long seq,String state,String code){jdbc.update("UPDATE delivery_stream SET state=?,blocked_seq=?,blocked_reason=? WHERE run_id=?",state,seq,code,run);}
    private Map<String,Object> lock(String run){return jdbc.queryForMap("SELECT * FROM delivery_stream WHERE run_id=? FOR UPDATE",run);}
    public Map<String,Object> diagnostic(String run,SourceConnections connections){
        return read.execute(tx->{
            var streams=jdbc.queryForList("SELECT * FROM delivery_stream WHERE run_id=?",run);if(streams.isEmpty()) throw new DeliveryProblem(404,"RUN_NOT_FOUND");var s=streams.getFirst();
            var stats=jdbc.queryForMap("SELECT count(*) AS n,COALESCE(sum(octet_length(r.raw_json_text)),0) AS bytes,min(r.received_at) AS oldest FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE o.run_id=? AND o.delivery_status<>'DELIVERED'",run);
            Long maximum=jdbc.queryForObject("SELECT max(source_seq) FROM raw_event WHERE run_id=?",Long.class,run);
            var received=jdbc.queryForList("SELECT received_at FROM raw_event WHERE run_id=? ORDER BY id DESC LIMIT 1",run);
            return map("protocolVersion",1,"runId",run,"sourceId",s.get("source_id"),"sampledAt",Protocol.time(now()),"sourceConnected",connections.connected(run),"lastReceivedAt",received.isEmpty()?null:time(received.getFirst().get("received_at")),"lastAcceptedSeq",maximum,"nextSourceSeq",s.get("next_source_seq"),"streamState",s.get("state"),"blockedSeq",s.get("blocked_seq"),"blockedCode",s.get("blocked_reason"),"pendingCount",stats.get("n"),"pendingBytes",stats.get("bytes"),"oldestPendingReceivedAt",time(stats.get("oldest")),"retryCount",s.get("diagnostic_retry_count"),"rejectedCount",s.get("diagnostic_rejected_count"));
        });
    }
    public Map<String,Object> outbox(String run,long after,int limit,String status){
        return read.execute(tx->{
            if(jdbc.queryForObject("SELECT count(*) FROM delivery_stream WHERE run_id=?",Long.class,run)==0) throw new DeliveryProblem(404,"RUN_NOT_FOUND");
            String sql="SELECT r.source_seq,r.event_id,r.payload_hash,r.received_at,o.* FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE r.run_id=? AND r.source_seq>?";
            var args=new ArrayList<Object>(List.of(run,after));if(status!=null){sql+=" AND o.delivery_status=?";args.add(status);}args.add(limit+1);
            var rows=jdbc.queryForList(sql+" ORDER BY r.source_seq LIMIT ?",args.toArray());var items=new ArrayList<Map<String,Object>>();var response=map("protocolVersion",1,"runId",run,"sampledAt",Protocol.time(now()),"items",items,"nextAfterSeq",null);
            for(var r:rows){if(items.size()>=limit) break;var item=map("eventId",r.get("event_id").toString(),"sourceSeq",r.get("source_seq"),"eventSha256",r.get("payload_hash"),"receivedAt",time(r.get("received_at")),"deliveryStatus",r.get("delivery_status"),"attemptCount",r.get("attempt_count"),"totalAttemptCount",r.get("total_attempt_count"),"lastAttemptAt",time(r.get("last_attempt_at")),"nextAttemptAt",time(r.get("next_attempt_at")),"dependencyWaitStartedAt",time(r.get("dependency_wait_started_at")),"lastError",r.get("last_error"),"lastResponse",r.get("last_response")==null?null:Protocol.JSON.readTree(r.get("last_response").toString()),"deliveredAt",time(r.get("delivered_at")),"quarantinedAt",time(r.get("quarantined_at")));
                items.add(item);if(Protocol.JSON.writeValueAsBytes(response).length>524000){items.removeLast();break;}
            }
            if(items.size()<rows.size()) response.put("nextAfterSeq",items.getLast().get("sourceSeq"));return response;
        });
    }
    public Map<String,Object> resume(String run,long expected,String operator,String reason){
        return write.execute(tx->{
            var rows=jdbc.queryForList("SELECT * FROM delivery_stream WHERE run_id=? FOR UPDATE",run);if(rows.isEmpty()) throw new DeliveryProblem(404,"RUN_NOT_FOUND");var s=rows.getFirst();
            if(((Number)s.get("next_source_seq")).longValue()!=expected) throw new DeliveryProblem(409,"CURSOR_MISMATCH");
            String previous=s.get("state").toString();if(!Set.of("PAUSED_RETRY","PAUSED_DEPENDENCY","PAUSED_CONFIG").contains(previous)) throw new DeliveryProblem(409,"RESUME_NOT_ALLOWED");
            var head=jdbc.queryForList("SELECT o.delivery_status FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE r.run_id=? AND r.source_seq=?",run,expected);
            if(head.isEmpty() || !Set.of("PENDING","RETRY_WAIT").contains(head.getFirst().get("delivery_status"))) throw new DeliveryProblem(409,"RESUME_NOT_ALLOWED");
            Instant now=now();jdbc.update("UPDATE event_outbox o SET attempt_count=0,next_attempt_at=NULL,dependency_wait_started_at=NULL FROM raw_event r WHERE o.run_id=r.run_id AND o.event_id=r.event_id AND r.run_id=? AND r.source_seq=?",run,expected);
            jdbc.update("UPDATE delivery_stream SET state='ACTIVE',blocked_seq=NULL,blocked_reason=NULL,gap_started_at=NULL WHERE run_id=?",run);
            jdbc.update("INSERT INTO delivery_action(run_id,source_id,source_seq,action,previous_state,operator_id,reason,recorded_at) VALUES (?,?,?,'RESUME',?,?,?,?)",run,s.get("source_id"),expected,previous,operator,reason,Timestamp.from(now));
            return map("protocolVersion",1,"runId",run,"sourceSeq",expected,"state","ACTIVE","resumedAt",Protocol.time(now),"operatorId",operator,"reason",reason);
        });
    }
    private Instant now(){return clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS);}
    static Instant instant(Object value){return value==null?null:((Timestamp)value).toInstant();}
    private static Timestamp stamp(Instant value){return value==null?null:Timestamp.from(value);}
    private static String time(Object value){return value==null?null:Protocol.time(instant(value));}
    public static Map<String,Object> map(Object... pairs){var m=new LinkedHashMap<String,Object>();for(int i=0;i<pairs.length;i+=2)m.put(pairs[i].toString(),pairs[i+1]);return m;}
}
