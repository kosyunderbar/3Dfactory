package dev.factory.operations.domain;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.context.SmartLifecycle;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.*;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import tools.jackson.databind.JsonNode;
import static dev.factory.operations.domain.ReadSupport.*;

/** One immutable bundle per run every <=500ms; detail queries reuse its epoch/revision. REST and SSE share this bundle. */
public final class ViewPublisher implements SmartLifecycle {
    private record Cached(Map<String,Object> view,String operationsState,long generated,long used) {}
    private record Built(Map<String,Object> view,String operationsState) {}
    public record CurrentStatus(Map<String,Object> view,String operationsState) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate read,write;
    private final Clock clock;
    private final DeliveryDiagnostics diagnostics;
    private final Map<String,Long> baseline=new HashMap<>();
    private final Map<String,Cached> bundles=new LinkedHashMap<>();
    private final Map<String,Long> revisions=new HashMap<>();
    private String epoch=UUID.randomUUID().toString();
    private volatile boolean running;
    public ViewPublisher(JdbcTemplate jdbc,PlatformTransactionManager manager,Clock clock,DeliveryDiagnostics diagnostics) {
        this.jdbc=jdbc;this.clock=clock;this.diagnostics=diagnostics;write=new TransactionTemplate(manager);read=new TransactionTemplate(manager);
        read.setReadOnly(true);read.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }
    @Override public synchronized void start() {
        if(running) return;
        for(var row:jdbc.queryForList("SELECT run_id,source_seq FROM factory_snapshot")) baseline.put(row.get("run_id").toString(),((Number)row.get("source_seq")).longValue());
        running=true;
    }
    @Override public void stop() { running=false; }
    @Override public boolean isRunning() { return running; }
    public synchronized Map<String,Object> current(String run) {
        long now=System.nanoTime(); Cached old=bundles.get(run);
        if(old==null || now-old.generated()>=500_000_000L) refresh(run,now);
        Cached selected=bundles.get(run); bundles.put(run,new Cached(selected.view(),selected.operationsState(),selected.generated(),now));
        return selected.view();
    }
    public synchronized CurrentStatus currentStatus(String run) {var view=current(run);return new CurrentStatus(view,bundles.get(run).operationsState());}
    @Scheduled(fixedDelay=500) public synchronized void refreshSelected() {
        if(!running) return; long now=System.nanoTime();
        for(String run:new ArrayList<>(bundles.keySet())) {
            if(now-bundles.get(run).used()>600_000_000_000L) { bundles.remove(run); diagnostics.forget(run); }
            else if(now-bundles.get(run).generated()>=500_000_000L) try { refresh(run,now); }
            catch(RuntimeException failure) { bundles.remove(run); } // A failed DB read must produce VIEW_NOT_READY/DB_UNAVAILABLE, not fake LIVE.
        }
    }
    private void refresh(String run,long monotonic) {
        if(!running) throw new dev.factory.operations.api.ApiProblem(503,"VIEW_NOT_READY");
        var meta=jdbc.queryForList("SELECT source_id,processing_state,finished_source_seq FROM simulation_run WHERE run_id=?",run);
        if(meta.isEmpty()) throw new dev.factory.operations.api.ApiProblem(404,"RUN_NOT_FOUND");
        String source=meta.getFirst().get("source_id").toString(); Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS); var delivery=diagnostics.get(run,source,now);
        // Observational alarms are a separate short write transaction, followed by one consistent read.
        write.execute(status->{
            jdbc.queryForList("SELECT pg_advisory_xact_lock(hashtextextended(?,7304001))",run);
            var state=jdbc.queryForMap("SELECT processing_state,finished_source_seq FROM simulation_run WHERE run_id=?",run);
            var snaps=jdbc.queryForList("SELECT source_seq,captured_at FROM factory_snapshot WHERE run_id=?",run);
            boolean observed=!snaps.isEmpty() && ((Number)snaps.getFirst().get("source_seq")).longValue()>baseline.getOrDefault(run,0L);
            Long finalSeq=state.get("finished_source_seq")==null?null:((Number)state.get("finished_source_seq")).longValue();
            boolean finished=Observation.finished(finalSeq,delivery); Instant captured=snaps.isEmpty()?null:((Timestamp)snaps.getFirst().get("captured_at")).toInstant();
            new AlarmService(jdbc,clock).observation(run,source,state.get("processing_state").toString(),finished,observed,Observation.freshness(now,captured,finished),delivery,now); return null;
        });
        Built built=read.execute(status->build(run,source,delivery,clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS)));
        Map<String,Object> view=built.view();
        Cached old=bundles.get(run); long revision=revisions.getOrDefault(run,0L)+1;
        if(revision>9007199254740991L) { epoch=UUID.randomUUID().toString();bundles.clear();revisions.clear();revision=1; }
        revisions.put(run,revision);
        view.put("serverEpoch",epoch);view.put("revision",revision);Instant published=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS);Instant asOf=Instant.parse((String)view.get("viewAsOfAt"));
        view.put("publishedAt",EventSyntax.time(published.isBefore(asOf)?asOf:published));
        if(EventSyntax.JSON.writeValueAsBytes(view).length>524288) throw new dev.factory.operations.api.ApiProblem(503,"VIEW_NOT_READY");
        if(old==null && bundles.size()>=32) { String evict=bundles.entrySet().stream().min(Comparator.comparingLong(e->e.getValue().used())).orElseThrow().getKey();bundles.remove(evict);diagnostics.forget(evict); }
        bundles.put(run,new Cached(Collections.unmodifiableMap(view),built.operationsState(),monotonic,old==null?monotonic:old.used()));
    }
    private Built build(String run,String source,Map<String,Object> delivery,Instant now) {
        var meta=jdbc.queryForMap("SELECT processing_state,finished_source_seq FROM simulation_run WHERE run_id=?",run);
        var snapshots=jdbc.queryForList("SELECT source_seq,captured_at,state_json FROM factory_snapshot WHERE run_id=?",run);
        JsonNode snapshot=snapshots.isEmpty()?null:EventSyntax.JSON.readTree(snapshots.getFirst().get("state_json").toString());
        Long seq=snapshot==null?null:((Number)snapshots.getFirst().get("source_seq")).longValue(),finalSeq=meta.get("finished_source_seq")==null?null:((Number)meta.get("finished_source_seq")).longValue();
        Instant captured=snapshot==null?null:((Timestamp)snapshots.getFirst().get("captured_at")).toInstant();boolean observed=seq!=null && seq>baseline.getOrDefault(run,0L),finished=Observation.finished(finalSeq,delivery);
        var freshness=Observation.freshness(now,captured,finished); String runState=snapshot==null?null:ModelRules.text(snapshot,"runState");
        var alarms=jdbc.queryForList("SELECT * FROM alarm WHERE run_id=? ORDER BY (resolved_at IS NULL) DESC,occurred_at DESC,alarm_id ASC LIMIT 100",run).stream().map(r->alarm(r,now)).toList();
        var recent=jdbc.queryForList("SELECT e.*,p.source_seq,p.applied_at FROM event_projection e JOIN processed_event p USING(run_id,event_id) WHERE e.run_id=? AND e.apply_status='APPLIED' ORDER BY e.occurred_at DESC,p.source_seq DESC,e.event_id DESC LIMIT 50",run).stream().map(ReadSupport::event).toList();
        var summary=jdbc.queryForMap("SELECT count(*) FILTER(WHERE resolved_at IS NULL) AS active,count(*) FILTER(WHERE resolved_at IS NULL AND acknowledged_at IS NULL) AS unack FROM alarm WHERE run_id=?",run);
        var metrics=map("currentBodyCount",snapshot==null?null:snapshot.get("bodies").size(),"runningCellCount",countCells(snapshot,"RUNNING"),"blockedCellCount",countCells(snapshot,"BLOCKED"),"downCellCount",countCells(snapshot,"DOWN"),"cumulativeQuality",quality(jdbc,run,null,null),"windowQuality",quality(jdbc,run,now.minusMillis(300000),now),"alarmSummary",map("activeCount",summary.get("active"),"unacknowledgedActiveCount",summary.get("unack")));
        var view=map("schemaVersion",1,"runId",run,"sourceId",source,"serverEpoch",null,"revision",null,"publishedAt",null,"viewAsOfAt",EventSyntax.time(now),"snapshotCapturedAt",captured==null?null:EventSyntax.time(captured),"sourceSeq",seq,"runState",runState,"simElapsedMs",snapshot==null?null:snapshot.get("simElapsedMs").longValue(),"observedAfterEpoch",observed,"dataStatus",Observation.status(meta.get("processing_state").toString(),finished,snapshot!=null,observed,runState,freshness,delivery,now),"freshness",freshness,"delivery",Collections.unmodifiableMap(delivery),"qualityWindow",map("start",EventSyntax.time(now.minusMillis(300000)),"end",EventSyntax.time(now)),"metrics",metrics,"alarms",alarms,"recentEvents",recent);
        for(String field:List.of("equipment","buffers","bodies","vehicles","activeTransports")) view.put(field,snapshot==null?List.of():snapshot.get(field));return new Built(view,meta.get("processing_state").toString());
    }
    private Long countCells(JsonNode snapshot,String state) { if(snapshot==null) return null;long count=0;for(var e:snapshot.get("equipment")) if(state.equals(ModelRules.text(e,"state"))) count++;return count; }
}
