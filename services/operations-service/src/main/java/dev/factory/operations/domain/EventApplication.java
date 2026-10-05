package dev.factory.operations.domain;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import java.util.concurrent.Semaphore;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import static dev.factory.operations.domain.ModelRules.*;
import static dev.factory.operations.domain.RuleViolation.*;

/** Run-serialized transactions. Permanent rejection is recorded only after business rollback. */
public final class EventApplication {
    public record Result(int protocolVersion,String kind,String runId,String sourceId,String eventId,Long sourceSeq,
        String eventSha256,String status,String code,String appliedAt,String recordedAt,Integer retryAfterMs) {}
    public record Reply(int http,Result body) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final Semaphore admission=new Semaphore(4);
    private final Clock clock;
    private final Runnable beforeCommit;
    public EventApplication(JdbcTemplate jdbc,TransactionTemplate tx,Clock clock) { this(jdbc,tx,clock,()->{}); }
    EventApplication(JdbcTemplate jdbc,TransactionTemplate tx,Clock clock,Runnable beforeCommit) { this.jdbc=jdbc;this.tx=tx;this.clock=clock;this.beforeCommit=beforeCommit; }
    public Reply apply(EventSyntax.Event event,Instant received) {
        long start=dev.factory.operations.measurement.Measurements.start();
        Reply reply=applyInternal(event,received);
        var id=event.identity();
        dev.factory.operations.measurement.Measurements.record("operations-transaction",id.runId(),id.eventId(),id.sourceSeq(),reply.body().status(),start);
        return reply;
    }
    private Reply applyInternal(EventSyntax.Event event,Instant received) {
        if(!admission.tryAcquire()) return response(event,429,"RETRY_LATER","OPERATIONS_BUSY",null,null);
        try {
            try { return tx.execute(status -> applyTransaction(event,received)); }
            catch(RuleViolation violation) {
                if(violation.retry) return response(event,409,"RETRY_LATER",violation.code,null,null);
                // A separate transaction retains rejection after rolling back all business effects.
                return tx.execute(status -> recordRejection(event,received,violation.code));
            }
        } catch(RuntimeException unavailable) { return response(event,503,"RETRY_LATER","DB_UNAVAILABLE",null,null); }
        finally { admission.release(); }
    }
    public Reply rejectInvalid(EventSyntax.Event event,Instant received) {
        try { return tx.execute(status -> recordRejection(event,received,"INVALID_EVENT")); }
        catch(RuntimeException unavailable) { return response(event,503,"RETRY_LATER","DB_UNAVAILABLE",null,null); }
    }
    private void lock(String run) { jdbc.queryForList("SELECT pg_advisory_xact_lock(hashtextextended(?, 7304001))",run); }
    private Reply previous(EventSyntax.Event e) {
        var id=e.identity();
        var rows=jdbc.queryForList("SELECT * FROM processed_event WHERE run_id=? AND (event_id=?::uuid OR (source_id=? AND source_seq=?))",id.runId(),id.eventId(),id.sourceId(),id.sourceSeq());
        for(var old:rows) {
            boolean sameId=old.get("event_id").toString().equals(id.eventId());
            Instant recorded=((Timestamp)old.get("recorded_at")).toInstant();
            if(sameId && old.get("source_id").equals(id.sourceId()) && ((Number)old.get("source_seq")).longValue()==id.sourceSeq()
                    && old.get("raw_json_text").equals(e.raw()) && old.get("payload_hash").equals(e.hash())) {
                boolean applied=old.get("apply_status").equals("APPLIED");
                return response(e,applied?200:422,applied?"DUPLICATE_APPLIED":"REJECTED",(String)old.get("result_code"),
                    applied?((Timestamp)old.get("applied_at")).toInstant():null,recorded);
            }
            if(sameId) return response(e,409,"REJECTED","ID_CONFLICT",null,recorded);
        }
        if(!rows.isEmpty()) return response(e,409,"REJECTED","SEQUENCE_CONFLICT",null,((Timestamp)rows.getFirst().get("recorded_at")).toInstant());
        var source=jdbc.queryForList("SELECT source_id,recorded_at FROM processed_event WHERE run_id=? ORDER BY recorded_at LIMIT 1",id.runId());
        if(!source.isEmpty() && !source.getFirst().get("source_id").equals(id.sourceId()))
            return response(e,409,"REJECTED","SOURCE_CONFLICT",null,((Timestamp)source.getFirst().get("recorded_at")).toInstant());
        return null;
    }
    private Reply applyTransaction(EventSyntax.Event e,Instant received) {
        String run=e.identity().runId(); lock(run); Reply prior=previous(e); if(prior!=null) return prior;
        if(jdbc.queryForObject("SELECT count(*) FROM processed_event WHERE run_id=? AND apply_status='REJECTED'",Long.class,run)>0)
            throw new RuleViolation("RUN_BLOCKED",true);
        var runs=jdbc.queryForList("SELECT * FROM simulation_run WHERE run_id=?",run);
        if(!runs.isEmpty() && runs.getFirst().get("processing_state").equals("BLOCKED")) throw new RuleViolation("RUN_BLOCKED",true);
        String kind=text(e.json(),"eventType"); JsonNode p=e.json().get("payload");
        if(runs.isEmpty() && !kind.equals("RUN_STARTED")) throw new RuleViolation("RUN_NOT_READY",true);
        JsonNode config=runs.isEmpty()?null:EventSyntax.JSON.readTree(runs.getFirst().get("config").toString());
        Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS); insertProcessed(e,"APPLIED","OK",now,null);
        String code=switch(kind) {
            case "RUN_STARTED" -> { registerRun(e,p,runs); yield "OK"; }
            case "BODY_REGISTERED" -> registerBody(e,p,config);
            case "FACTORY_SNAPSHOT" -> projectSnapshot(e,p,config,received);
            case "BODY_ENTERED_CELL" -> introduceOperation(e,p,config);
            case "OPERATION_COMPLETED" -> completeOperation(e,p,config);
            case "INSPECTION_COMPLETED" -> inspection(e,p,config);
            case "TRANSPORT_ASSIGNED","TRANSPORT_STARTED","TRANSPORT_COMPLETED","TRANSPORT_CANCELLED" -> transportFact(e,p,config);
            case "RUN_FINISHED" -> { model(p.get("uniqueEventCount").longValue()==e.identity().sourceSeq());
                if(runs.getFirst().get("finished_at")!=null) conflict(((Timestamp)runs.getFirst().get("finished_at")).toInstant().equals(e.occurredAt()) && ((Number)runs.getFirst().get("finished_source_seq")).longValue()==e.identity().sourceSeq());
                model(!e.occurredAt().isBefore(((Timestamp)runs.getFirst().get("started_at")).toInstant()));
                jdbc.update("UPDATE simulation_run SET finished_at=?,finished_source_seq=? WHERE run_id=?",Timestamp.from(e.occurredAt()),e.identity().sourceSeq(),run); yield "OK"; }
            default -> { validateReferences(e,p,config); yield "OK"; }
        };
        jdbc.update("UPDATE processed_event SET result_code=? WHERE run_id=? AND event_id=?::uuid",code,run,e.identity().eventId());
        projectEvent(e,received,"APPLIED"); beforeCommit.run();
        return response(e,200,"APPLIED",code,now,now);
    }
    private Reply recordRejection(EventSyntax.Event e,Instant received,String code) {
        String run=e.identity().runId(); lock(run); Reply prior=previous(e); if(prior!=null) return prior;
        Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS); insertProcessed(e,"REJECTED",code,now,code); projectEvent(e,received,"REJECTED");
        jdbc.update("UPDATE simulation_run SET processing_state='BLOCKED',blocked_reason=? WHERE run_id=?",code,run);
        return response(e,422,"REJECTED",code,null,now);
    }
    private void insertProcessed(EventSyntax.Event e,String status,String code,Instant now,String reason) {
        var id=e.identity(); jdbc.update("INSERT INTO processed_event(run_id,event_id,source_id,source_seq,raw_json_text,payload_hash,apply_status,result_code,applied_at,recorded_at,rejection_reason) VALUES (?,?::uuid,?,?,?,?,?,?,?,?,?)",
            id.runId(),id.eventId(),id.sourceId(),id.sourceSeq(),e.raw(),e.hash(),status,code,status.equals("APPLIED")?Timestamp.from(now):null,Timestamp.from(now),reason);
    }
    private void registerRun(EventSyntax.Event e,JsonNode p,List<Map<String,Object>> existing) {
        conflict(existing.isEmpty()); model(e.identity().sourceSeq()==1); ModelRules.configuration(p.get("config"));
        String run=e.identity().runId(); JsonNode config=p.get("config");
        model(run.substring(4,12).equals(e.occurredAt().atOffset(ZoneOffset.UTC).format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd"))));
        jdbc.update("INSERT INTO simulation_run(run_id,source_id,started_at,seed,config) VALUES (?,?,?,?,?::jsonb)",run,e.identity().sourceId(),Timestamp.from(e.occurredAt()),p.get("seed").longValue(),config.toString());
        for(var equipment:config.get("equipment")) {
            var pos=coordinate(config,"CELL",text(equipment,"cellId"));
            jdbc.update("INSERT INTO equipment(run_id,equipment_id,cell_id,work_duration_ms,x,y) VALUES (?,?,?,?,?,?)",run,text(equipment,"equipmentId"),text(equipment,"cellId"),equipment.get("workDurationMs").longValue(),pos.get("x").doubleValue(),pos.get("y").doubleValue());
        }
        for(var bay:config.get("buffers")) {
            var pos=coordinate(config,"BUFFER",text(bay,"bufferId"));
            jdbc.update("INSERT INTO factory_buffer(run_id,buffer_id,cell_id,capacity,slot_ids,x,y) VALUES (?,?,?,?,?::jsonb,?,?)",run,text(bay,"bufferId"),text(bay,"cellId"),bay.get("capacity").intValue(),bay.get("slotIds").toString(),pos.get("x").doubleValue(),pos.get("y").doubleValue());
        }
        for(var vehicle:config.get("vehicles")) jdbc.update("INSERT INTO vehicle(run_id,vehicle_id,kind,home,initial_position) VALUES (?,?,?,?::jsonb,?::jsonb)",run,text(vehicle,"vehicleId"),text(vehicle,"kind"),vehicle.get("home").toString(),vehicle.get("initialPosition").toString());
    }
    private JsonNode coordinate(JsonNode config,String kind,String id) { for(var l:config.get("locations")) if(kind.equals(text(l,"locationType")) && id.equals(text(l,"locationId"))) return l; throw new RuleViolation("MODEL_INVALID",false); }
    private String registerBody(EventSyntax.Event e,JsonNode p,JsonNode config) {
        String run=e.identity().runId(),body=text(p,"bodyId");
        model(EventSyntax.timestamp(p.get("createdAt")).equals(e.occurredAt()));
        var old=jdbc.queryForList("SELECT * FROM body WHERE run_id=? AND (body_id=? OR tag_id=?)",run,body,text(p,"tagId"));
        if(!old.isEmpty()) {
            var row=old.getFirst(); conflict(row.get("body_id").equals(body) && row.get("tag_id").equals(text(p,"tagId")) && row.get("model_code").equals(text(p,"modelCode")) && row.get("spec_code").equals(text(p,"specCode")) && ((Timestamp)row.get("created_at")).toInstant().equals(e.occurredAt()) && EventSyntax.JSON.readTree(row.get("initial_location").toString()).equals(p.get("initialLocation")));
            return "FACT_ALREADY_RECORDED";
        }
        model(jdbc.queryForObject("SELECT count(*) FROM body WHERE run_id=?",Long.class,run)<config.get("maxBodies").intValue());
        model(Set.of("INPUT","CELL","BUFFER").contains(text(p.get("initialLocation"),"locationType")));
        coordinate(config,text(p.get("initialLocation"),"locationType"),text(p.get("initialLocation"),"locationId"));
        jdbc.update("INSERT INTO body(run_id,body_id,tag_id,model_code,spec_code,created_at,initial_location) VALUES (?,?,?,?,?,?,?::jsonb)",run,body,text(p,"tagId"),text(p,"modelCode"),text(p,"specCode"),Timestamp.from(e.occurredAt()),p.get("initialLocation").toString()); return "OK";
    }
    private void bodyRef(String run,String id) { if(id!=null) reference(jdbc.queryForObject("SELECT count(*) FROM body WHERE run_id=? AND body_id=?",Long.class,run,id)==1); }
    private void cellRef(JsonNode config,String id) { if(id!=null) reference(index(config.get("equipment"),"cellId").containsKey(id)); }
    private void baySlot(JsonNode config,JsonNode p) {
        JsonNode bay=index(config.get("buffers"),"bufferId").get(text(p,"bufferId")); reference(bay!=null); model(contains(bay.get("slotIds"),text(p,"slotId")));
        if(p.has("cellId")) model(Objects.equals(text(bay,"cellId"),text(p,"cellId")));
    }
    private String introduceOperation(EventSyntax.Event e,JsonNode p,JsonNode config) {
        String run=e.identity().runId(); bodyRef(run,text(p,"bodyId")); cellRef(config,text(p,"cellId")); baySlot(config,p);
        var old=jdbc.queryForList("SELECT unit_id,equipment_id FROM operation_history WHERE run_id=? AND operation_id=?",run,text(p,"operationId"));
        if(!old.isEmpty()) { conflict(old.getFirst().get("unit_id").equals(text(p,"bodyId")) && old.getFirst().get("equipment_id").equals(text(p,"cellId")));
            var original=jdbc.queryForList("SELECT payload::text,occurred_at FROM event_projection WHERE run_id=? AND type='BODY_ENTERED_CELL' AND payload->>'operationId'=? AND apply_status='APPLIED' ORDER BY record_ordinal LIMIT 1",run,text(p,"operationId"));
            conflict(!original.isEmpty() && EventSyntax.JSON.readTree(original.getFirst().get("payload").toString()).equals(p) && ((Timestamp)original.getFirst().get("occurred_at")).toInstant().equals(e.occurredAt())); return "FACT_ALREADY_RECORDED"; }
        model(jdbc.queryForObject("SELECT count(*) FROM operation_history WHERE run_id=? AND equipment_id=? AND completed_at IS NULL",Long.class,run,text(p,"cellId"))==0);
        jdbc.update("INSERT INTO operation_history(run_id,operation_id,unit_id,equipment_id,entered_at,introduced_event_id) VALUES (?,?,?,?,?,?::uuid)",run,text(p,"operationId"),text(p,"bodyId"),text(p,"cellId"),Timestamp.from(e.occurredAt()),e.identity().eventId()); return "OK";
    }
    private String completeOperation(EventSyntax.Event e,JsonNode p,JsonNode config) {
        String run=e.identity().runId(); bodyRef(run,text(p,"unitId")); cellRef(config,text(p,"cellId")); model(Objects.equals(text(p,"cellId"),text(p,"equipmentId")));
        var rows=jdbc.queryForList("SELECT * FROM operation_history WHERE run_id=? AND operation_id=?",run,text(p,"operationId")); reference(!rows.isEmpty()); var row=rows.getFirst();
        conflict(row.get("unit_id").equals(text(p,"unitId")) && row.get("equipment_id").equals(text(p,"equipmentId")));
        if(row.get("completed_at")!=null) { conflict(((Timestamp)row.get("completed_at")).toInstant().equals(e.occurredAt()) && ((Number)row.get("duration_ms")).longValue()==p.get("durationMs").longValue()); return "FACT_ALREADY_RECORDED"; }
        if(row.get("entered_at")!=null) model(!e.occurredAt().isBefore(((Timestamp)row.get("entered_at")).toInstant()));
        jdbc.update("UPDATE operation_history SET completed_at=?,duration_ms=?,completed_event_id=?::uuid WHERE run_id=? AND operation_id=?",Timestamp.from(e.occurredAt()),p.get("durationMs").longValue(),e.identity().eventId(),run,text(p,"operationId")); return "OK";
    }
    private String inspection(EventSyntax.Event e,JsonNode p,JsonNode config) {
        String run=e.identity().runId(); bodyRef(run,text(p,"unitId")); cellRef(config,text(p,"equipmentId")); model("QC-01".equals(text(p,"equipmentId")) && Objects.equals(text(p,"defectCode"),text(p,"result").equals("FAIL")?"SIM_DEFECT_01":null));
        var prior=jdbc.queryForList("SELECT * FROM inspection_result WHERE run_id=? AND (inspection_id=? OR unit_id=?)",run,text(p,"inspectionId"),text(p,"unitId"));
        if(!prior.isEmpty()) {
            var row=prior.getFirst(); conflict(row.get("inspection_id").equals(text(p,"inspectionId")) && row.get("unit_id").equals(text(p,"unitId")) && row.get("equipment_id").equals(text(p,"equipmentId")) && row.get("result").equals(text(p,"result")) && Objects.equals(row.get("defect_code"),text(p,"defectCode")) && ((Timestamp)row.get("inspected_at")).toInstant().equals(e.occurredAt())); return "FACT_ALREADY_RECORDED";
        }
        // Late inspection facts require body/config registration, not a newer current-state snapshot.
        jdbc.update("INSERT INTO inspection_result(run_id,inspection_id,unit_id,equipment_id,result,defect_code,inspected_at,event_id) VALUES (?,?,?,?,?,?,?,?::uuid)",run,text(p,"inspectionId"),text(p,"unitId"),text(p,"equipmentId"),text(p,"result"),text(p,"defectCode"),Timestamp.from(e.occurredAt()),e.identity().eventId()); return "OK";
    }
    private String transportFact(EventSyntax.Event e,JsonNode p,JsonNode config) {
        String run=e.identity().runId(),tid=text(p,"transportId"),kind=text(e.json(),"eventType"); bodyRef(run,text(p,"bodyId")); ModelRules.transport(p,config);
        var transition=Map.of("TRANSPORT_ASSIGNED","ASSIGNED","TRANSPORT_STARTED","IN_TRANSIT","TRANSPORT_COMPLETED","COMPLETED","TRANSPORT_CANCELLED","CANCELLED");
        var field=Map.of("ASSIGNED","assignedAt","IN_TRANSIT","startedAt","COMPLETED","completedAt","CANCELLED","cancelledAt");
        model(transition.get(kind).equals(text(p,"status")) && EventSyntax.timestamp(p.get(field.get(text(p,"status")))).equals(e.occurredAt()));
        var facts=jdbc.queryForList("SELECT payload::text,occurred_at FROM event_projection WHERE run_id=? AND type=? AND apply_status='APPLIED' AND payload->>'transportId'=? ORDER BY record_ordinal LIMIT 1",run,kind,tid);
        if(!facts.isEmpty()) { var old=facts.getFirst(); conflict(EventSyntax.JSON.readTree(old.get("payload").toString()).equals(p) && ((Timestamp)old.get("occurred_at")).toInstant().equals(e.occurredAt())); return "FACT_ALREADY_RECORDED"; }
        var trips=jdbc.queryForList("SELECT * FROM transport_history WHERE run_id=? AND transport_id=?",run,tid);
        if(trips.isEmpty()) {
            reference(kind.equals("TRANSPORT_ASSIGNED"));
            model(jdbc.queryForObject("SELECT count(*) FROM transport_history WHERE run_id=? AND status IN ('ASSIGNED','IN_TRANSIT') AND (vehicle_id=? OR body_id=?)",Long.class,run,text(p,"vehicleId"),text(p,"bodyId"))==0);
            if(text(p,"reservationId")!=null) {
                var slots=jdbc.queryForList("SELECT payload::text FROM event_projection WHERE run_id=? AND type='SLOT_RESERVED' AND apply_status='APPLIED' AND payload->>'transportId'=?",run,tid);
                reference(!slots.isEmpty());
                for(var slot:slots) {
                    JsonNode reserved=EventSyntax.JSON.readTree(slot.get("payload").toString());
                    for(String key:List.of("reservationId","slotId","bodyId","vehicleId")) conflict(Objects.equals(text(reserved,key),text(p,key)));
                    conflict(Objects.equals(text(reserved,"bufferId"),text(p.get("destination"),"locationId")));
                }
            }
            if(text(p,"reservationId")!=null) conflict(jdbc.queryForObject("SELECT count(*) FROM transport_history WHERE run_id=? AND reservation_id=?",Long.class,run,text(p,"reservationId"))==0);
            jdbc.update("INSERT INTO transport_history(run_id,transport_id,vehicle_id,route_id,cargo_type,body_id,parts_kit_id,reservation_id,slot_id,source_location,destination_location,status,last_source_seq,assigned_at,last_event_id) VALUES (?,?,?,?,?,?,?,?,?,?::jsonb,?::jsonb,'ASSIGNED',?,?,?::uuid)",run,tid,text(p,"vehicleId"),text(p,"routeId"),text(p,"cargoType"),text(p,"bodyId"),text(p,"partsKitId"),text(p,"reservationId"),text(p,"slotId"),p.get("source").toString(),p.get("destination").toString(),e.identity().sourceSeq(),Timestamp.from(EventSyntax.timestamp(p.get("assignedAt"))),e.identity().eventId());
        } else {
            var old=trips.getFirst();
            for(var pair:Map.of("vehicleId","vehicle_id","routeId","route_id","cargoType","cargo_type","bodyId","body_id","partsKitId","parts_kit_id","reservationId","reservation_id","slotId","slot_id").entrySet()) conflict(Objects.equals(text(p,pair.getKey()),old.get(pair.getValue())));
            conflict(EventSyntax.JSON.readTree(old.get("source_location").toString()).equals(p.get("source")) && EventSyntax.JSON.readTree(old.get("destination_location").toString()).equals(p.get("destination")) && ((Timestamp)old.get("assigned_at")).toInstant().equals(EventSyntax.timestamp(p.get("assignedAt"))));
            String status=text(p,"status"),previous=(String)old.get("status");
            model(status.equals("IN_TRANSIT")?previous.equals("ASSIGNED"):status.equals("COMPLETED")?previous.equals("IN_TRANSIT"):status.equals("CANCELLED")?previous.equals("ASSIGNED"):false);
            if(old.get("started_at")!=null) conflict(((Timestamp)old.get("started_at")).toInstant().equals(EventSyntax.timestamp(p.get("startedAt"))));
            jdbc.update("UPDATE transport_history SET status=?,last_source_seq=?,started_at=?,completed_at=?,cancelled_at=?,cancel_reason=?,last_event_id=?::uuid WHERE run_id=? AND transport_id=?",status,e.identity().sourceSeq(),timeOrNull(p,"startedAt"),timeOrNull(p,"completedAt"),timeOrNull(p,"cancelledAt"),text(p,"cancelReason"),e.identity().eventId(),run,tid);
        }
        return "OK";
    }
    private Timestamp timeOrNull(JsonNode p,String key) { return text(p,key)==null?null:Timestamp.from(EventSyntax.timestamp(p.get(key))); }
    private String projectSnapshot(EventSyntax.Event e,JsonNode p,JsonNode config,Instant received) {
        model(EventSyntax.timestamp(p.get("capturedAt")).equals(e.occurredAt())); String run=e.identity().runId();
        var registrations=new HashMap<String,JsonNode>();
        for(var row:jdbc.queryForList("SELECT DISTINCT ON (b.body_id) b.body_id,b.tag_id,b.model_code,b.spec_code,b.initial_location FROM body b JOIN event_projection ep ON ep.run_id=b.run_id AND ep.type='BODY_REGISTERED' AND ep.payload->>'bodyId'=b.body_id JOIN processed_event pe ON pe.run_id=ep.run_id AND pe.event_id=ep.event_id WHERE b.run_id=? AND pe.source_seq<=? ORDER BY b.body_id,pe.source_seq",run,e.identity().sourceSeq())) {
            var n=EventSyntax.JSON.createObjectNode(); n.put("tagId",row.get("tag_id").toString());n.put("modelCode",row.get("model_code").toString());n.put("specCode",row.get("spec_code").toString());n.set("initialLocation",EventSyntax.JSON.readTree(row.get("initial_location").toString()));registrations.put(row.get("body_id").toString(),n);
        }
        ModelRules.snapshot(p,config,registrations);
        for(var cell:p.get("equipment")) if(text(cell,"operationId")!=null) {
            String op=text(cell,"operationId"); var rows=jdbc.queryForList("SELECT * FROM operation_history WHERE run_id=? AND operation_id=?",run,op);
            if(rows.isEmpty()) {
                var registered=registrations.get(text(cell,"bodyId"));
                reference(place(registered.get("initialLocation")).equals("CELL:"+text(cell,"cellId")));
                jdbc.update("INSERT INTO operation_history(run_id,operation_id,unit_id,equipment_id,introduced_event_id) VALUES (?,?,?,?,?::uuid)",run,op,text(cell,"bodyId"),text(cell,"cellId"),e.identity().eventId());
            } else conflict(rows.getFirst().get("unit_id").equals(text(cell,"bodyId")) && rows.getFirst().get("equipment_id").equals(text(cell,"cellId")));
        }
        for(var trip:p.get("activeTransports")) {
            var rows=jdbc.queryForList("SELECT * FROM transport_history WHERE run_id=? AND transport_id=?",run,text(trip,"transportId"));reference(!rows.isEmpty()); var row=rows.getFirst();
            for(var pair:Map.of("vehicleId","vehicle_id","routeId","route_id","cargoType","cargo_type","bodyId","body_id","partsKitId","parts_kit_id","reservationId","reservation_id","slotId","slot_id").entrySet()) model(Objects.equals(text(trip,pair.getKey()),row.get(pair.getValue())));
            model(EventSyntax.JSON.readTree(row.get("source_location").toString()).equals(trip.get("source")) && EventSyntax.JSON.readTree(row.get("destination_location").toString()).equals(trip.get("destination")));
            if(((Number)row.get("last_source_seq")).longValue()<=e.identity().sourceSeq()) {
                var latest=jdbc.queryForMap("SELECT payload::text FROM event_projection WHERE run_id=? AND event_id=?::uuid",run,row.get("last_event_id").toString());
                model(EventSyntax.JSON.readTree(latest.get("payload").toString()).equals(trip));
            }
        }
        var old=jdbc.queryForList("SELECT source_seq,state_json::text FROM factory_snapshot WHERE run_id=?",run);
        if(!old.isEmpty() && ((Number)old.getFirst().get("source_seq")).longValue()>=e.identity().sourceSeq()) return "STALE_SNAPSHOT_RECORDED";
        if(!old.isEmpty()) {
            var prior=EventSyntax.JSON.readTree(old.getFirst().get("state_json").toString());
            model(p.get("simElapsedMs").longValue()>=prior.get("simElapsedMs").longValue());
            model(!text(prior,"runState").equals("FINISHED") || text(p,"runState").equals("FINISHED"));
            var previousBodies=index(prior.get("bodies"),"bodyId");
            for(var body:p.get("bodies")) {
                var before=previousBodies.get(text(body,"bodyId"));if(before==null) continue;
                model(body.get("completedCellIds").size()>=before.get("completedCellIds").size());
                if(!text(before,"inspectionResult").equals("NOT_INSPECTED")) model(Objects.equals(text(before,"inspectionResult"),text(body,"inspectionResult")) && Objects.equals(text(before,"inspectedAt"),text(body,"inspectedAt")));
            }
        }
        jdbc.update("INSERT INTO factory_snapshot(run_id,source_seq,event_id,captured_at,received_at,state_json) VALUES (?,?,?::uuid,?,?,?::jsonb) ON CONFLICT(run_id) DO UPDATE SET source_seq=EXCLUDED.source_seq,event_id=EXCLUDED.event_id,captured_at=EXCLUDED.captured_at,received_at=EXCLUDED.received_at,state_json=EXCLUDED.state_json",run,e.identity().sourceSeq(),e.identity().eventId(),Timestamp.from(e.occurredAt()),Timestamp.from(received),p.toString());
        new AlarmService(jdbc,clock).physical(run,p,clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS));
        return "OK";
    }
    private void validateReferences(EventSyntax.Event e,JsonNode p,JsonNode config) {
        String run=e.identity().runId(),kind=text(e.json(),"eventType"); bodyRef(run,text(p,"bodyId"));
        cellRef(config,text(p,"cellId"));cellRef(config,text(p,"equipmentId"));
        if(p.has("cellId") && p.has("equipmentId")) model(Objects.equals(text(p,"cellId"),text(p,"equipmentId")));
        if(p.has("bufferId")) baySlot(config,p);
        if(text(p,"vehicleId")!=null) reference(index(config.get("vehicles"),"vehicleId").containsKey(text(p,"vehicleId")));
        if(kind.equals("SLOT_RESERVED")) model(text(p,"vehicleId").startsWith("AGV-"));
        if(kind.equals("SLOT_RELEASED")) {
            model((text(p,"reservationId")==null)==(text(p,"transportId")==null));
            if(text(p,"transportId")!=null) reference(jdbc.queryForObject("SELECT count(*) FROM transport_history WHERE run_id=? AND transport_id=? AND reservation_id=? AND slot_id=? AND body_id=?",Long.class,run,text(p,"transportId"),text(p,"reservationId"),text(p,"slotId"),text(p,"bodyId"))==1);
        }
        if(kind.equals("TELEMETRY_UPDATED")) { if(text(p,"entityType").equals("EQUIPMENT")) cellRef(config,text(p,"entityId")); else reference(index(config.get("vehicles"),"vehicleId").containsKey(text(p,"entityId"))); }
        if(kind.equals("SCENARIO_CHANGED")) {
            String action=text(p,"action"),target=text(p,"targetId");
            if(action.startsWith("CELL_")) cellRef(config,target);
            else if(action.equals("QUALITY_PATTERN")) model(target.equals(run));
            else reference(jdbc.queryForObject("SELECT count(*) FROM transport_history WHERE run_id=? AND transport_id=?",Long.class,run,target)==1);
        }
        if(kind.equals("RUN_STATE_CHANGED")) model(!Objects.equals(text(p,"previousState"),text(p,"state")));
        if(kind.equals("EQUIPMENT_STATE_CHANGED")) model(!Objects.equals(text(p,"previousState"),text(p,"state")));
    }
    private void projectEvent(EventSyntax.Event e,Instant received,String status) {
        JsonNode p=e.json().get("payload"); String kind=text(e.json(),"eventType");
        if(status.equals("REJECTED")) {
            jdbc.update("INSERT INTO event_projection(run_id,event_id,type,severity,apply_status,occurred_at,received_at,payload) VALUES (?,?::uuid,?,'ERROR','REJECTED',?,?,?::jsonb)",e.identity().runId(),e.identity().eventId(),kind,Timestamp.from(e.occurredAt()),Timestamp.from(received),p.toString()); return;
        }
        String cell=text(p,"cellId"),body=p.has("bodyId")?text(p,"bodyId"):text(p,"unitId"),vehicle=text(p,"vehicleId");
        if(cell==null) cell=text(p,"equipmentId"); if(cell==null && text(p,"bufferId")!=null) cell=text(p,"bufferId").substring(4);
        if(cell==null && p.has("destination")) cell=cellAt(p.get("destination")); if(cell==null && p.has("source")) cell=cellAt(p.get("source"));
        if(cell==null && kind.equals("BODY_REGISTERED")) cell=cellAt(p.get("initialLocation"));
        String entity=p.has("entityId")?text(p,"entityId"):body!=null?body:vehicle!=null?vehicle:cell;
        jdbc.update("INSERT INTO event_projection(run_id,event_id,type,severity,apply_status,entity_id,cell_id,body_id,vehicle_id,occurred_at,received_at,payload) VALUES (?,?::uuid,?,?,?,?,?,?,?,?,?,?::jsonb)",e.identity().runId(),e.identity().eventId(),kind,status.equals("REJECTED")?"ERROR":"INFO",status,entity,cell,body,vehicle,Timestamp.from(e.occurredAt()),Timestamp.from(received),p.toString());
    }
    private String cellAt(JsonNode location) { String type=text(location,"locationType"); return type.equals("CELL")?text(location,"locationId"):type.equals("BUFFER")?text(location,"locationId").substring(4):null; }
    public static Reply response(EventSyntax.Event e,int http,String status,String code,Instant applied,Instant recorded) {
        var id=e==null?null:e.identity(); return new Reply(http,new Result(1,"APPLICATION_RESULT",id==null?null:id.runId(),id==null?null:id.sourceId(),id==null?null:id.eventId(),id==null?null:id.sourceSeq(),e==null?null:e.hash(),status,code,applied==null?null:EventSyntax.time(applied),recorded==null?null:EventSyntax.time(recorded),status.equals("RETRY_LATER")?500:null));
    }
}
