package dev.factory.operations.domain;

import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;
import static dev.factory.operations.domain.ReadSupport.map;

@EnabledIfEnvironmentVariable(named="FACTORY_OPERATIONS_TESTS",matches="true")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="factory.ingestion-diagnostic-url=http://127.0.0.1:1")
@Import(OperationsIntegrationTests.FixedTime.class)
class OperationsIntegrationTests {
    static final Instant NOW=Instant.parse("2026-10-05T09:00:00.000Z");
    static class MutableClock extends Clock {
        AtomicReference<Instant> now=new AtomicReference<>(NOW);
        @Override public ZoneId getZone() {return ZoneOffset.UTC;}
        @Override public Clock withZone(ZoneId zone) {return this;}
        @Override public Instant instant() {return now.get();}
    }
    @TestConfiguration static class FixedTime {@Bean @Primary MutableClock clock() {return new MutableClock();}}
    @Autowired EventApplication application;
    @Autowired JdbcTemplate jdbc;
    @Autowired TransactionTemplate tx;
    @Autowired MutableClock clock;
    @Autowired ViewPublisher views;
    @Autowired HistoryQueries history;
    @Autowired AlarmService alarms;
    @Autowired WebServerApplicationContext context;
    List<String> runs=new ArrayList<>();
    @BeforeEach void resetClock(){clock.now.set(NOW);}
    String run(){String run="run-20261005-"+UUID.randomUUID().toString().replace("-","");runs.add(run);return run;}
    List<ObjectNode> scenario(String run) throws Exception {
        return Files.readAllLines(Path.of("src/test/resources/factory-scenario.ndjson")).stream().map(line->{var n=(ObjectNode)EventSyntax.JSON.readTree(line);String original=n.get("runId").stringValue();n.put("runId",run);n.put("eventId",UUID.randomUUID().toString());String raw=n.toString().replace(original,run);return (ObjectNode)EventSyntax.JSON.readTree(raw);}).toList();
    }
    EventSyntax.Event event(ObjectNode n){return EventSyntax.parse(n.toString().getBytes(StandardCharsets.UTF_8));}
    EventApplication.Reply apply(ObjectNode n){return application.apply(event(n),NOW);}
    ObjectNode newEvent(String run,long seq,String type,Map<String,Object> payload,Instant at){return (ObjectNode)EventSyntax.JSON.valueToTree(map("schemaVersion",1,"eventId",UUID.randomUUID().toString(),"runId",run,"sourceId","simulator-01","sourceSeq",seq,"eventType",type,"occurredAt",EventSyntax.time(at),"payload",payload));}
    ObjectNode changed(ObjectNode original,long seq){var n=(ObjectNode)original.deepCopy();n.put("eventId",UUID.randomUUID().toString());n.put("sourceSeq",seq);return n;}
    long count(String table,String run){return jdbc.queryForObject("SELECT count(*) FROM "+table+" WHERE run_id=?",Long.class,run);}
    void assertApplied(EventApplication.Reply r){assertThat(r.http()).withFailMessage("%s",r.body()).isEqualTo(200);}
    void started(String run) throws Exception {assertApplied(apply(scenario(run).getFirst()));}
    ObjectNode body(String run,long seq,int number,Instant at){String suffix=String.format("%05d",number);return newEvent(run,seq,"BODY_REGISTERED",map("bodyId","body-"+suffix,"tagId","tag-"+suffix,"modelCode","DEMO-EV-A","specCode","STANDARD","createdAt",EventSyntax.time(at),"initialLocation",map("locationType","INPUT","locationId","BODY-IN")),at);}
    @AfterEach void cleanup(){for(String run:runs){for(String table:List.of("factory_snapshot","inspection_result","operation_history","transport_history","alarm","event_projection","processed_event","body","factory_buffer","equipment","vehicle","simulation_run")) jdbc.update("DELETE FROM "+table+" WHERE run_id=?",run);}}

    @Test void completeScenarioIdempotencyFactsLateSnapshotAndRunIsolation() throws Exception {
        String run=run();var events=scenario(run);var early=events.stream().filter(e->e.get("eventType").stringValue().equals("FACTORY_SNAPSHOT")).findFirst().orElseThrow();
        for(var n:events) if(n!=early && !n.get("eventType").stringValue().equals("RUN_FINISHED")) assertApplied(apply(n));
        assertThat(count("processed_event",run)).isEqualTo(events.size()-2);assertThat(count("inspection_result",run)).isEqualTo(1);assertThat(count("operation_history",run)).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT state_json->>'runState' FROM factory_snapshot WHERE run_id=?",String.class,run)).isEqualTo("FINISHED");
        var inspection=events.stream().filter(e->e.get("eventType").stringValue().equals("INSPECTION_COMPLETED")).findFirst().orElseThrow();
        var duplicate=apply(inspection);assertThat(duplicate.body().status()).isEqualTo("DUPLICATE_APPLIED");assertThat(duplicate.body().appliedAt()).isEqualTo(EventSyntax.time(NOW));
        assertThat(apply(changed(inspection,1000)).body().code()).isEqualTo("FACT_ALREADY_RECORDED");assertThat(count("inspection_result",run)).isEqualTo(1);
        var operation=events.stream().filter(e->e.get("eventType").stringValue().equals("OPERATION_COMPLETED")).findFirst().orElseThrow();assertThat(apply(changed(operation,1001)).body().code()).isEqualTo("FACT_ALREADY_RECORDED");
        var assigned=events.stream().filter(e->e.get("eventType").stringValue().equals("TRANSPORT_ASSIGNED")).findFirst().orElseThrow();assertThat(apply(changed(assigned,1002)).body().code()).isEqualTo("FACT_ALREADY_RECORDED");
        long finalSeq=events.getLast().get("sourceSeq").longValue()-1;
        // Deliver the original unused low sequence after the final snapshot; do not fabricate newer stale state.
        assertThat(apply(early).body().code()).isEqualTo("STALE_SNAPSHOT_RECORDED");
        assertThat(jdbc.queryForObject("SELECT source_seq FROM factory_snapshot WHERE run_id=?",Long.class,run)).isEqualTo(finalSeq);
        String other=run();started(other);assertThat(count("inspection_result",other)).isZero();
        var map=history.layout(other);assertThat(map.get("runId")).isEqualTo(other);
        assertThat(application.apply(event((ObjectNode)inspection.deepCopy()),NOW).body().status()).isEqualTo("DUPLICATE_APPLIED");
    }
    @Test void rejectedOwnershipTagConflictMissingReferencesAndActualRollback() throws Exception {
        String run=run();var fixture=scenario(run);assertApplied(apply(fixture.getFirst()));
        var unknownBody=newEvent(run,500,"INSPECTION_COMPLETED",map("inspectionId","inspection-00500","unitId","body-00500","equipmentId","QC-01","result","PASS","defectCode",null),NOW);
        assertThat(apply(unknownBody).body().code()).isEqualTo("REFERENCE_NOT_READY");assertThat(count("processed_event",run)).isEqualTo(1);
        var firstBody=fixture.get(1);var broken=new EventApplication(jdbc,tx,clock,()->jdbc.update("INSERT INTO body(run_id,body_id,tag_id,model_code,spec_code,created_at,initial_location) VALUES (?, 'body-99999', 'tag-99999', 'X', 'X', now(), '[]'::jsonb)",run));
        var failure=broken.apply(event(firstBody),NOW);assertThat(failure.http()).isEqualTo(503);assertThat(count("body",run)).isZero();assertThat(count("processed_event",run)).isEqualTo(1);assertThat(count("event_projection",run)).isEqualTo(1);
        assertApplied(apply(firstBody));var wrongTag=body(run,501,2,NOW);((ObjectNode)wrongTag.get("payload")).put("tagId",firstBody.get("payload").get("tagId").stringValue());
        var rejection=apply(wrongTag);assertThat(rejection.http()).isEqualTo(422);assertThat(rejection.body().recordedAt()).isNotNull();assertThat(count("body",run)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT processing_state FROM simulation_run WHERE run_id=?",String.class,run)).isEqualTo("BLOCKED");assertThat(apply(firstBody).body().status()).isEqualTo("DUPLICATE_APPLIED");
        assertThat(apply(body(run,502,3,NOW)).body().code()).isEqualTo("RUN_BLOCKED");
        String badRun=run();var badFixture=scenario(badRun);for(var n:badFixture){if(n.get("eventType").stringValue().equals("FACTORY_SNAPSHOT")) {var slot=(ObjectNode)n.get("payload").get("buffers").get(0).get("slots").get(0);slot.put("bodyId","body-99999");slot.put("status","OCCUPIED");assertThat(apply(n).body().code()).isEqualTo("MODEL_INVALID");break;}assertApplied(apply(n));}
        assertThat(count("factory_snapshot",badRun)).isZero();
        String invalidStart=run();var start=scenario(invalidStart).getFirst();((ObjectNode)start.get("payload").get("config").get("equipment").get(0)).put("equipmentId","ASM-02");assertThat(apply(start).http()).isEqualTo(422);assertThat(count("simulation_run",invalidStart)).isZero();assertThat(count("processed_event",invalidStart)).isEqualTo(1);
    }
    @Test void quality100Fail20HalfOpenWindowLateFactAndFencedPagination() throws Exception {
        String run=run();started(run);clock.now.set(NOW.plusSeconds(300));
        ObjectNode lateInspection=null;
        for(int i=1;i<=100;i++) {assertApplied(apply(body(run,1+i,i,NOW)));String suffix=String.format("%05d",i);Instant inspected=NOW.plusSeconds(i);
            var fact=newEvent(run,101+i,"INSPECTION_COMPLETED",map("inspectionId","inspection-"+suffix,"unitId","body-"+suffix,"equipmentId","QC-01","result",i<=20?"FAIL":"PASS","defectCode",i<=20?"SIM_DEFECT_01":null),inspected);
            if(i==85) lateInspection=fact;else assertApplied(apply(fact));}
        var filters=map("eventType","INSPECTION_COMPLETED","limit","10");var query=new HashMap<String,String>();filters.forEach((k,v)->query.put(k,v.toString()));var first=history.page("events",run,query);String cursor=(String)first.get("nextCursor");assertThat(cursor).isNotNull();
        query.put("cursor",cursor);var second=history.page("events",run,query);assertThat(second.get("viewAsOfAt")).isEqualTo(first.get("viewAsOfAt"));
        assertThat(count("inspection_result",run)).isEqualTo(99);
        // This original late fact falls inside page two: without the commit fence it would shift that page.
        assertApplied(apply(lateInspection));assertThat(count("inspection_result",run)).isEqualTo(100);
        var after=history.page("events",run,query);assertThat(after.get("items")).isEqualTo(second.get("items"));
        query.put("limit","11");org.junit.jupiter.api.Assertions.assertThrows(dev.factory.operations.api.ApiProblem.class,()->history.page("events",run,query));query.put("limit","10");query.put("cursor",cursor+"x");org.junit.jupiter.api.Assertions.assertThrows(dev.factory.operations.api.ApiProblem.class,()->history.page("events",run,query));
        var quality=history.qualityPage(run,Map.of(),Observation.unavailable(run,"simulator-01"));var q=(Map<?,?>)quality.get("quality");assertThat(q.get("inspectedCount")).isEqualTo(100L);assertThat(q.get("failCount")).isEqualTo(20L);assertThat(q.get("failRate")).isEqualTo(0.2);
        var boundary=history.qualityPage(run,Map.of("from",EventSyntax.time(NOW.plusSeconds(1)),"to",EventSyntax.time(NOW.plusSeconds(2))),Observation.unavailable(run,"simulator-01"));assertThat(((Map<?,?>)boundary.get("quality")).get("inspectedCount")).isEqualTo(1L);
        var empty=history.qualityPage(run,Map.of("from",EventSyntax.time(NOW.plusSeconds(200)),"to",EventSyntax.time(NOW.plusSeconds(201))),Observation.unavailable(run,"simulator-01"));assertThat(((Map<?,?>)empty.get("quality")).get("failRate")).isNull();
        var trends=history.trends(run,Map.of("bucketMs","5000"),Observation.unavailable(run,"simulator-01"));assertThat((List<?>)trends.get("buckets")).hasSize(60);
    }
    @Test void realHttpDetailsUnknownDiagnosticsAlarmsConfirmRecoverAndInputBounds() throws Exception {
        String run=run();var frames=scenario(run);var client=HttpClient.newHttpClient();String base="http://127.0.0.1:"+context.getWebServer().getPort();String alarmId=null;boolean checked=false;
        for(var n:frames) {
            var event=event(n);var delivery=map("protocolVersion",1,"rawEvent",event.raw(),"eventSha256",event.hash(),"receivedAt",EventSyntax.time(NOW));
            var response=client.send(HttpRequest.newBuilder(URI.create(base+"/internal/v1/events/apply")).header("Content-Type","application/json; charset=utf-8").POST(HttpRequest.BodyPublishers.ofString(EventSyntax.JSON.writeValueAsString(delivery))).build(),HttpResponse.BodyHandlers.ofString());
            assertThat(response.statusCode()).withFailMessage("%s",response.body()).isEqualTo(200);assertThat(EventSyntax.JSON.readTree(response.body()).get("status").stringValue()).isEqualTo("APPLIED");
            if(n.get("eventType").stringValue().equals("BODY_REGISTERED")) {var detail=client.send(HttpRequest.newBuilder(URI.create(base+"/api/v1/runs/"+run+"/tags/tag-00001/body")).GET().build(),HttpResponse.BodyHandlers.ofString());assertThat(detail.statusCode()).isEqualTo(200);assertThat(EventSyntax.JSON.readTree(detail.body()).get("data").isNull()).isTrue();}
            if(n.get("eventType").stringValue().equals("FACTORY_SNAPSHOT") && !checked) {
                var rows=jdbc.queryForList("SELECT alarm_id FROM alarm WHERE run_id=? AND type='EQUIPMENT_DOWN' AND resolved_at IS NULL",run);
                if(!rows.isEmpty()) {alarmId=rows.getFirst().get("alarm_id").toString();for(String operator:List.of("operator_01","operator_02")) {
                    var ack=client.send(HttpRequest.newBuilder(URI.create(base+"/api/v1/alarms/"+alarmId+"/acknowledge")).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString("{\"operatorId\":\""+operator+"\"}")).build(),HttpResponse.BodyHandlers.ofString());
                    assertThat(ack.statusCode()).isEqualTo(200);var acknowledged=EventSyntax.JSON.readTree(ack.body()).get("alarm");assertThat(acknowledged.get("conditionActive").booleanValue()).isTrue();assertThat(acknowledged.get("acknowledgedBy").stringValue()).isEqualTo("operator_01");
                }checked=true;}
            }
        }
        assertThat(checked).isTrue();assertThat(jdbc.queryForObject("SELECT resolved_at IS NOT NULL FROM alarm WHERE alarm_id=?::uuid",Boolean.class,alarmId)).isTrue();
        Thread.sleep(520);var response=client.send(HttpRequest.newBuilder(URI.create(base+"/api/v1/runs/"+run+"/snapshot")).GET().build(),HttpResponse.BodyHandlers.ofString());var view=EventSyntax.JSON.readTree(response.body());assertThat(view.get("dataStatus").stringValue()).isEqualTo("UNKNOWN");assertThat(view.get("delivery").get("diagnosticState").stringValue()).isEqualTo("UNAVAILABLE");assertThat(view.get("observedAfterEpoch").booleanValue()).isTrue();
        var detail=client.send(HttpRequest.newBuilder(URI.create(base+"/api/v1/runs/"+run+"/bodies/body-00001")).GET().build(),HttpResponse.BodyHandlers.ofString());var d=EventSyntax.JSON.readTree(detail.body());assertThat(d.get("revision").longValue()).isGreaterThanOrEqualTo(view.get("revision").longValue());assertThat(d.get("data").get("locationId").stringValue()).isEqualTo("HOLD");
        // A controlled HTTP diagnostic sample verifies the S04 consumer, not a real S05 provider.
        var sampleServer=com.sun.net.httpserver.HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        sampleServer.createContext("/",exchange->{
            byte[] bytes=EventSyntax.JSON.writeValueAsBytes(map("protocolVersion",1,"runId",run,"sourceId","simulator-01","sampledAt",EventSyntax.time(NOW),"sourceConnected",false,"lastReceivedAt",EventSyntax.time(NOW),"lastAcceptedSeq",60,"nextSourceSeq",61,"streamState","ACTIVE","blockedSeq",null,"blockedCode",null,"pendingCount",0,"pendingBytes",0,"oldestPendingReceivedAt",null,"retryCount",0,"rejectedCount",0));
            exchange.getResponseHeaders().set("Content-Type","application/json; charset=utf-8");exchange.sendResponseHeaders(200,bytes.length);try(var stream=exchange.getResponseBody()){stream.write(bytes);}
        });sampleServer.start();
        try {
            var consumer=new DeliveryDiagnostics("http://127.0.0.1:"+sampleServer.getAddress().getPort());
            var confirmed=consumer.get(run,"simulator-01",NOW);assertThat(confirmed.get("diagnosticState")).isEqualTo("AVAILABLE");assertThat(Observation.finished(60L,confirmed)).isTrue();
            assertThat(consumer.get(run,"simulator-01",NOW.minusMillis(5001)).get("diagnosticState")).isEqualTo("UNAVAILABLE");
        } finally {sampleServer.stop(0);}
        var restore=new ViewPublisher(jdbc,context.getBean(org.springframework.transaction.PlatformTransactionManager.class),clock,new DeliveryDiagnostics("http://127.0.0.1:1"));restore.start();try {assertThat(restore.current(run).get("dataStatus")).isEqualTo("RESTORING");}finally{restore.stop();}
        var original=event(frames.getFirst());
        var invalidDate=EventSyntax.JSON.writeValueAsString(map("protocolVersion",1,"rawEvent",original.raw(),"eventSha256",original.hash(),"receivedAt","2026-99-05T09:00:00.000Z"));
        var oversizedVersion=EventSyntax.JSON.writeValueAsString(map("protocolVersion",new java.math.BigInteger("18446744073709551617"),"rawEvent",original.raw(),"eventSha256",original.hash(),"receivedAt",EventSyntax.time(NOW)));
        for(var pair:List.of(new String[]{"application/*","{}","415"},new String[]{"application/json",invalidDate,"400"},new String[]{"application/json",oversizedVersion,"400"},new String[]{"text/plain","{}","415"},new String[]{"application/json","x".repeat(524289),"413"},new String[]{"application/json","{\"protocolVersion\":1,\"protocolVersion\":1}","400"})) {
            var bad=client.send(HttpRequest.newBuilder(URI.create(base+"/internal/v1/events/apply")).header("Content-Type",pair[0]).POST(HttpRequest.BodyPublishers.ofString(pair[1])).build(),HttpResponse.BodyHandlers.ofString());assertThat(bad.statusCode()).withFailMessage("%s",bad.body()).isEqualTo(Integer.parseInt(pair[2]));
        }
    }
}
