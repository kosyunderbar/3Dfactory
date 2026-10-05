package dev.factory.operations.domain;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import dev.factory.operations.api.ApiProblem;
import static dev.factory.operations.domain.ReadSupport.*;

/** Bounded keyset pages. Signed cursors freeze query/time/commit fence; no OFFSET drift. */
public final class HistoryQueries {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate read;
    private final Clock clock;
    private final byte[] key=new byte[32];
    public HistoryQueries(JdbcTemplate jdbc,TransactionTemplate read,Clock clock) { this.jdbc=jdbc;this.read=read;this.clock=clock;new SecureRandom().nextBytes(key); }
    public static void runId(String id) { if(id==null || !id.matches("run-[0-9]{8}-[a-z0-9]{3,32}")) throw new ApiProblem(400,"INVALID_QUERY");try { java.time.LocalDate.parse(id.substring(4,12),java.time.format.DateTimeFormatter.BASIC_ISO_DATE); } catch(RuntimeException e) { throw new ApiProblem(400,"INVALID_QUERY"); } }
    public void exists(String run) { runId(run);if(jdbc.queryForObject("SELECT count(*) FROM simulation_run WHERE run_id=?",Long.class,run)==0) throw new ApiProblem(404,"RUN_NOT_FOUND"); }
    public static void fields(Map<String,String> query,String allowed) { var keys=new HashSet<>(Arrays.asList(allowed.split(" ")));if(!keys.containsAll(query.keySet())) throw new ApiProblem(400,"INVALID_QUERY"); }
    public static Instant[] window(Map<String,String> q,Instant asOf) {
        boolean from=q.containsKey("from"),to=q.containsKey("to");if(from!=to) throw new ApiProblem(400,"INVALID_QUERY");
        try { Instant start=from?EventSyntax.timestamp(EventSyntax.JSON.valueToTree(q.get("from"))):asOf.minusMillis(300000),end=to?EventSyntax.timestamp(EventSyntax.JSON.valueToTree(q.get("to"))):asOf;
            if(!start.isBefore(end)||end.isAfter(asOf)||Duration.between(start,end).toMillis()>86400000) throw new ApiProblem(400,"INVALID_QUERY");return new Instant[]{start,end};
        } catch(ApiProblem e) { throw e; } catch(RuntimeException e) { throw new ApiProblem(400,"INVALID_QUERY"); }
    }
    public Map<String,Object> layout(String run) { return read.execute(s->{exists(run);var row=jdbc.queryForMap("SELECT source_id,config FROM simulation_run WHERE run_id=?",run);return map("schemaVersion",1,"runId",run,"sourceId",row.get("source_id"),"config",EventSyntax.JSON.readTree(row.get("config").toString()));}); }
    public Map<String,Object> qualityPage(String run,Map<String,String> q,Map<String,Object> delivery) {
        fields(q,"from to");return read.execute(s->{exists(run);Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS);var w=window(q,now);return map("schemaVersion",1,"runId",run,"viewAsOfAt",EventSyntax.time(now),"window",map("start",EventSyntax.time(w[0]),"end",EventSyntax.time(w[1])),"quality",quality(jdbc,run,w[0],w[1]),"delivery",delivery);});
    }
    public Map<String,Object> trends(String run,Map<String,String> q,Map<String,Object> delivery) {
        fields(q,"from to bucketMs");return read.execute(s->{exists(run);Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS);var w=window(q,now);int bucket=1000;
            try { if(q.containsKey("bucketMs")) bucket=Integer.parseInt(q.get("bucketMs")); } catch(RuntimeException e) { throw new ApiProblem(400,"INVALID_QUERY"); }
            if(!Set.of(1000,5000,60000).contains(bucket)) throw new ApiProblem(400,"INVALID_QUERY");
            long first=Math.floorDiv(w[0].toEpochMilli(),bucket)*bucket,last=w[1].toEpochMilli();if((last-1-first)/bucket+1>300) throw new ApiProblem(400,"INVALID_QUERY");
            // PostgreSQL groups only unique inspection facts in the requested half-open window.
            var rows=jdbc.queryForList("SELECT floor(extract(epoch FROM inspected_at)*1000/?)::bigint AS bucket,count(*) AS n,count(*) FILTER(WHERE result='PASS') AS pass,count(*) FILTER(WHERE result='FAIL') AS fail FROM inspection_result WHERE run_id=? AND inspected_at>=? AND inspected_at<? GROUP BY bucket",bucket,run,Timestamp.from(w[0]),Timestamp.from(w[1]));
            var grouped=new HashMap<Long,Map<String,Object>>();for(var r:rows) grouped.put(((Number)r.get("bucket")).longValue(),r);var buckets=new ArrayList<Map<String,Object>>();
            for(long start=first;start<last;start+=bucket) { var r=grouped.get(Math.floorDiv(start,bucket));long n=r==null?0:((Number)r.get("n")).longValue(),pass=r==null?0:((Number)r.get("pass")).longValue(),fail=r==null?0:((Number)r.get("fail")).longValue();
                buckets.add(map("start",EventSyntax.time(Instant.ofEpochMilli(Math.max(start,w[0].toEpochMilli()))),"end",EventSyntax.time(Instant.ofEpochMilli(Math.min(start+bucket,last))),"quality",map("inspectedCount",n,"passCount",pass,"failCount",fail,"failRate",n==0?null:(double)fail/n))); }
            return map("schemaVersion",1,"runId",run,"viewAsOfAt",EventSyntax.time(now),"window",map("start",EventSyntax.time(w[0]),"end",EventSyntax.time(w[1])),"bucketMs",bucket,"buckets",buckets,"delivery",delivery);
        });
    }
    public Map<String,Object> page(String collection,String run,Map<String,String> query) {
        String allowed=switch(collection) {case "runs"->"limit cursor";case "events"->"from to cellId equipmentId bodyId vehicleId eventType limit cursor";default->"from to conditionActive acknowledged severity limit cursor";}; fields(query,allowed);
        if(run!=null) exists(run);
        return read.execute(s->{
            int limit=50;try { if(query.containsKey("limit")) { if(!query.get("limit").matches("[0-9]{1,3}")) throw new IllegalArgumentException();limit=Integer.parseInt(query.get("limit")); } } catch(RuntimeException e) { throw new ApiProblem(400,"INVALID_QUERY"); }
            if(limit<1||limit>200) throw new ApiProblem(400,"INVALID_QUERY");
            JsonNode cursor=query.containsKey("cursor")?decode(query.get("cursor")):null;Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS),asOf=cursor==null?now:Instant.parse(cursor.get("asOf").stringValue());
            if(cursor!=null && !now.isBefore(Instant.parse(cursor.get("expires").stringValue()))) throw new ApiProblem(409,"CURSOR_EXPIRED");
            var filters=new TreeMap<String,String>(query);filters.remove("cursor");filters.remove("limit");
            Instant[] w=collection.equals("runs")?null:window(query,asOf);
            if(w!=null) {filters.put("from",EventSyntax.time(w[0]));filters.put("to",EventSyntax.time(w[1]));}
            validateFilters(collection,filters);
            if(cursor!=null && (!collection.equals(cursor.get("collection").stringValue()) || !Objects.equals(run,cursor.get("run").isNull()?null:cursor.get("run").stringValue()) || limit!=cursor.get("limit").intValue() || !EventSyntax.JSON.valueToTree(filters).equals(cursor.get("filters")))) throw new ApiProblem(409,"CURSOR_MISMATCH");
            String table=collection.equals("runs")?"simulation_run":collection.equals("events")?"event_projection":"alarm";
            String fenceSql="SELECT COALESCE(max(record_ordinal),0) FROM "+table+(run==null?"":" WHERE run_id=?");
            long fence=cursor==null?jdbc.queryForObject(fenceSql,Long.class,run==null?new Object[]{}:new Object[]{run}):cursor.get("fence").longValue();
            var args=new ArrayList<Object>();args.add(fence);
            String sql=collection.equals("events")?"SELECT t.*,p.source_seq,p.applied_at FROM event_projection t JOIN processed_event p USING(run_id,event_id) WHERE t.record_ordinal<=? AND t.apply_status='APPLIED'":"SELECT t.* FROM "+table+" t WHERE t.record_ordinal<=?";
            if(run!=null) {sql+=" AND t.run_id=?";args.add(run);}
            if(w!=null) {sql+=" AND t.occurred_at>=? AND t.occurred_at<?";args.add(Timestamp.from(w[0]));args.add(Timestamp.from(w[1]));}
            if(collection.equals("events")) {
                for(var pair:Map.of("cellId","cell_id","equipmentId","cell_id","bodyId","body_id","vehicleId","vehicle_id","eventType","type").entrySet()) if(filters.containsKey(pair.getKey())) {sql+=" AND t."+pair.getValue()+"=?";args.add(filters.get(pair.getKey()));}
            } else if(collection.equals("alarms")) {
                if(filters.containsKey("conditionActive")) {sql+=Boolean.parseBoolean(filters.get("conditionActive"))?" AND (t.resolved_at IS NULL OR t.resolved_at>?)":" AND t.resolved_at<=?";args.add(Timestamp.from(asOf));}
                if(filters.containsKey("acknowledged")) {sql+=Boolean.parseBoolean(filters.get("acknowledged"))?" AND t.acknowledged_at<=?":" AND (t.acknowledged_at IS NULL OR t.acknowledged_at>?)";args.add(Timestamp.from(asOf));}
                if(filters.containsKey("severity")) {sql+=" AND t.severity=?";args.add(filters.get("severity"));}
            }
            if(cursor!=null) {
                JsonNode last=cursor.get("last");Instant at=Instant.parse(last.get(0).stringValue());
                if(collection.equals("events")) {sql+=" AND (t.occurred_at,p.source_seq,t.event_id)<(?,?,?::uuid)";args.add(Timestamp.from(at));args.add(last.get(1).longValue());args.add(last.get(2).stringValue());}
                else if(collection.equals("runs")) {sql+=" AND (t.started_at,t.run_id)<(?,?)";args.add(Timestamp.from(at));args.add(last.get(1).stringValue());}
                else {sql+=" AND (t.occurred_at<? OR (t.occurred_at=? AND t.alarm_id>?::uuid))";args.add(Timestamp.from(at));args.add(Timestamp.from(at));args.add(last.get(1).stringValue());}
            }
            sql+=collection.equals("events")?" ORDER BY t.occurred_at DESC,p.source_seq DESC,t.event_id DESC":collection.equals("runs")?" ORDER BY t.started_at DESC,t.run_id DESC":" ORDER BY t.occurred_at DESC,t.alarm_id ASC";
            sql+=" LIMIT ?";args.add(limit+1);var rows=jdbc.queryForList(sql,args.toArray());
            var items=new ArrayList<Map<String,Object>>();var result=map("schemaVersion",1,"runId",run,"viewAsOfAt",EventSyntax.time(asOf),"items",items,"nextCursor",null);Map<String,Object> lastRow=null;
            for(var row:rows) {
                if(items.size()>=limit) break;
                Map<String,Object> item=collection.equals("events")?event(row):collection.equals("alarms")?alarm(row,asOf):map("runId",row.get("run_id"),"sourceId",row.get("source_id"),"startedAt",time(row.get("started_at")),"finishedAt",time(row.get("finished_at")),"processingState",row.get("processing_state"));
                items.add(item);
                if(EventSyntax.JSON.writeValueAsBytes(result).length>524288-2048) {items.removeLast();break;} lastRow=row;
            }
            if(items.isEmpty() && !rows.isEmpty()) throw new ApiProblem(503,"VIEW_NOT_READY");
            if(items.size()<rows.size()) {
                List<Object> last=collection.equals("events")?List.of(time(lastRow.get("occurred_at")),lastRow.get("source_seq"),lastRow.get("event_id").toString()):collection.equals("runs")?List.of(time(lastRow.get("started_at")),lastRow.get("run_id")):List.of(time(lastRow.get("occurred_at")),lastRow.get("alarm_id").toString());
                result.put("nextCursor",encode(map("v",1,"collection",collection,"run",run,"filters",filters,"limit",limit,"fence",fence,"last",last,"asOf",EventSyntax.time(asOf),"expires",EventSyntax.time(asOf.plusMillis(600000)))));
            }
            return result;
        });
    }
    private void validateFilters(String collection,Map<String,String> q) {
        for(var pair:Map.of("cellId","ASM-01|ASM-02|QC-01","equipmentId","ASM-01|ASM-02|QC-01","bodyId","body-[0-9]{5,10}","vehicleId","(AGV|AMR)-[0-9]{3,6}","conditionActive","true|false","acknowledged","true|false","severity","INFO|WARNING|CRITICAL").entrySet()) if(q.containsKey(pair.getKey()) && !q.get(pair.getKey()).matches(pair.getValue())) throw new ApiProblem(400,"INVALID_QUERY");
        if(q.containsKey("eventType") && !Set.of("RUN_STARTED","RUN_STATE_CHANGED","FACTORY_SNAPSHOT","BODY_REGISTERED","SLOT_RESERVED","SLOT_RELEASED","BODY_ENTERED_CELL","TELEMETRY_UPDATED","EQUIPMENT_STATE_CHANGED","OPERATION_COMPLETED","INSPECTION_COMPLETED","TRANSPORT_ASSIGNED","TRANSPORT_STARTED","TRANSPORT_COMPLETED","TRANSPORT_CANCELLED","SCENARIO_CHANGED","RUN_FINISHED").contains(q.get("eventType"))) throw new ApiProblem(400,"INVALID_QUERY");
    }
    private byte[] sign(byte[] data) {try {var mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(key,"HmacSHA256"));return mac.doFinal(data);}catch(GeneralSecurityException e){throw new IllegalStateException(e);}}
    private String encode(Map<String,Object> value) {byte[] raw=EventSyntax.JSON.writeValueAsBytes(value);String token=Base64.getUrlEncoder().withoutPadding().encodeToString(raw)+"."+Base64.getUrlEncoder().withoutPadding().encodeToString(sign(raw));if(token.getBytes(StandardCharsets.US_ASCII).length>2048) throw new ApiProblem(503,"VIEW_NOT_READY");return token;}
    private JsonNode decode(String token) {if(token.length()>2048) throw new ApiProblem(400,"INVALID_QUERY");try {String[] parts=token.split("\\.");if(parts.length!=2) throw new IllegalArgumentException();byte[] raw=Base64.getUrlDecoder().decode(parts[0]);if(!MessageDigest.isEqual(sign(raw),Base64.getUrlDecoder().decode(parts[1]))) throw new IllegalArgumentException();JsonNode n=EventSyntax.JSON.readTree(raw);if(n.get("v").intValue()!=1) throw new IllegalArgumentException();return n;}catch(RuntimeException e){throw new ApiProblem(409,"CURSOR_MISMATCH");}}
}
