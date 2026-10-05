package dev.factory.ingestion.delivery;

import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.*;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import tools.jackson.databind.node.ObjectNode;
import dev.factory.ingestion.receiver.*;
import static dev.factory.ingestion.delivery.DeliveryStore.map;
import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named="FACTORY_DELIVERY_TESTS",matches="true")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={"factory.delivery.enabled=false","factory.tcp.port=0","management.endpoint.health.group.readiness.include=readinessState,db,tcp"})
@Import(DeliveryIntegrationTests.FixedTime.class)
class DeliveryIntegrationTests {
    static final Instant NOW=Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MILLIS);
    static class MutableClock extends Clock {
        AtomicReference<Instant> value=new AtomicReference<>(NOW);
        @Override public ZoneId getZone(){return ZoneOffset.UTC;}
        @Override public Clock withZone(ZoneId zone){return this;}
        @Override public Instant instant(){return value.get();}
    }
    @TestConfiguration static class FixedTime {@Bean @Primary MutableClock clock(){return new MutableClock();}}
    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager manager;
    @Autowired MutableClock clock;
    @Autowired EventStore admission;
    @Autowired DeliveryStore store;
    @Autowired SourceConnections connections;
    @Autowired TcpReceiver receiver;
    @Autowired WebServerApplicationContext context;
    final List<String> runs=new ArrayList<>();
    final HttpClient http=HttpClient.newHttpClient();
    JdbcTemplate operations;
    String target;
    @BeforeEach void setup(){clock.value.set(NOW);target=System.getenv("FACTORY_OPERATIONS_TEST_URL");operations=new JdbcTemplate(new DriverManagerDataSource(System.getenv("OPERATIONS_DB_URL"),System.getenv("OPERATIONS_DB_USERNAME"),System.getenv("OPERATIONS_DB_PASSWORD")));}
    String run(){String run="run-"+NOW.atOffset(ZoneOffset.UTC).toLocalDate().format(java.time.format.DateTimeFormatter.BASIC_ISO_DATE)+"-"+UUID.randomUUID().toString().replace("-","");runs.add(run);return run;}
    List<ObjectNode> frames(String run) throws IOException {
        return Files.readAllLines(Path.of("src/test/resources/factory-scenario.ndjson")).stream().map(line->{String old=Protocol.JSON.readTree(line).get("runId").stringValue();var n=(ObjectNode)Protocol.JSON.readTree(line.replace(old,run).replace("2026-10-05T09:00:00.000Z",Protocol.time(NOW)));n.put("eventId",UUID.randomUUID().toString());return n;}).toList();
    }
    Protocol.Event event(ObjectNode n){return Protocol.parse(n.toString().getBytes(StandardCharsets.UTF_8));}
    void admit(ObjectNode n){assertThat(admission.receive(event(n),NOW).status()).isEqualTo("RECEIVED");}
    DeliveryWorker worker(DeliveryStore store,String url){return new DeliveryWorker(store,new OperationsClient(url),()->0);}
    long count(JdbcTemplate db,String table,String run){return db.queryForObject("SELECT count(*) FROM "+table+" WHERE run_id=?",Long.class,run);}
    Map<String,Object> stream(String run){return jdbc.queryForMap("SELECT * FROM delivery_stream WHERE run_id=?",run);}
    Map<String,Object> head(String run){return jdbc.queryForMap("SELECT o.* FROM event_outbox o JOIN raw_event r USING(run_id,event_id) WHERE r.run_id=? ORDER BY r.source_seq LIMIT 1",run);}
    void await(BooleanSupplier condition,int millis) throws Exception {long end=System.nanoTime()+millis*1_000_000L;while(!condition.getAsBoolean() && System.nanoTime()<end) Thread.sleep(10);assertThat(condition.getAsBoolean()).isTrue();}
    String base(){return "http://127.0.0.1:"+context.getWebServer().getPort();}
    Map<String,Object> json(String path) throws Exception {var response=http.send(HttpRequest.newBuilder(URI.create(base()+path)).GET().build(),HttpResponse.BodyHandlers.ofString());assertThat(response.statusCode()).withFailMessage("%s",response.body()).isEqualTo(200);return Protocol.JSON.readValue(response.body(),Map.class);}
    @AfterEach void cleanup(){
        for(String run:runs){for(String table:List.of("delivery_action","event_outbox","raw_event","delivery_stream"))jdbc.update("DELETE FROM "+table+" WHERE run_id=?",run);
            for(String table:List.of("factory_snapshot","inspection_result","operation_history","transport_history","alarm","event_projection","processed_event","body","factory_buffer","equipment","vehicle","simulation_run"))operations.update("DELETE FROM "+table+" WHERE run_id=?",run);}
    }
    @Test void actualTcpAutomaticHttpCommitDiagnosticAndUnchangedOriginals() throws Exception {
        String run=run();var frames=frames(run);var worker=worker(store,target);worker.start();
        try(Socket socket=new Socket("127.0.0.1",receiver.boundPort())){
            socket.setSoTimeout(5000);var reader=new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8));
            for(var n:frames){socket.getOutputStream().write((n+"\n").getBytes(StandardCharsets.UTF_8));var ack=Protocol.JSON.readTree(reader.readLine());assertThat(ack.get("status").stringValue()).isEqualTo("RECEIVED");}
            await(()->((Number)stream(run).get("next_source_seq")).longValue()==61,10000);
            assertThat(count(operations,"processed_event",run)).isEqualTo(60);assertThat(count(operations,"inspection_result",run)).isEqualTo(1);
            var diag=json("/internal/v1/runs/"+run+"/delivery-status");assertThat(diag).hasSize(16);assertThat(diag.get("sourceConnected")).isEqualTo(true);assertThat(((Number)diag.get("pendingCount")).longValue()).isZero();assertThat(((Number)diag.get("nextSourceSeq")).longValue()).isEqualTo(61);
            var rows=jdbc.queryForList("SELECT r.raw_json_text,r.payload_hash,r.source_seq,o.delivery_status,o.last_response::text FROM raw_event r JOIN event_outbox o USING(run_id,event_id) WHERE run_id=? ORDER BY source_seq",run);
            for(int i=0;i<frames.size();i++){var original=event(frames.get(i));assertThat(rows.get(i).get("raw_json_text")).isEqualTo(original.raw());assertThat(rows.get(i).get("payload_hash")).isEqualTo(original.hash());assertThat(rows.get(i).get("delivery_status")).isEqualTo("DELIVERED");}
            socket.getOutputStream().write((frames.getFirst()+"\n").getBytes(StandardCharsets.UTF_8));assertThat(Protocol.JSON.readTree(reader.readLine()).get("status").stringValue()).isEqualTo("DUPLICATE_RECEIVED");assertThat(count(jdbc,"event_outbox",run)).isEqualTo(60);
        } finally {worker.stop();}
        await(()->!connections.connected(run),1000);
        var pages=json("/internal/v1/runs/"+run+"/outbox?status=DELIVERED&limit=1");assertThat((List<?>)pages.get("items")).hasSize(1);assertThat(((Number)pages.get("nextAfterSeq")).longValue()).isEqualTo(1);
    }
    @Test void lostBusinessResponseResultRollbackRestartAndActualOperationsDatabaseOutage() throws Exception {
        String run=run();admit(frames(run).getFirst());AtomicBoolean lose=new AtomicBoolean(true);AtomicInteger remoteCalls=new AtomicInteger();
        var proxy=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        proxy.createContext("/internal/v1/events/apply",exchange->{
            try {var response=http.send(HttpRequest.newBuilder(URI.create(target+"/internal/v1/events/apply")).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofByteArray(exchange.getRequestBody().readAllBytes())).build(),HttpResponse.BodyHandlers.ofByteArray());remoteCalls.incrementAndGet();exchange.getResponseHeaders().set("Content-Type","application/json");
                if(lose.getAndSet(false)){exchange.sendResponseHeaders(200,0);exchange.getResponseBody().write("{lost".getBytes(StandardCharsets.UTF_8));}
                else {exchange.sendResponseHeaders(response.statusCode(),response.body().length);exchange.getResponseBody().write(response.body());}
            }catch(Exception failure){throw new IOException(failure);}finally{exchange.close();}
        });proxy.start();
        try {
            String url="http://127.0.0.1:"+proxy.getAddress().getPort();assertThat(worker(store,url).tick()).isTrue();assertThat(count(operations,"processed_event",run)).isEqualTo(1);assertThat(stream(run).get("next_source_seq")).isEqualTo(1L);assertThat(head(run).get("attempt_count")).isEqualTo(1);
            clock.value.set(DeliveryStore.instant(head(run).get("next_attempt_at")).plusMillis(1));
            var broken=new DeliveryStore(jdbc,manager,clock,()->jdbc.update("UPDATE event_outbox SET attempt_count=21 WHERE run_id=?",run));
            assertThatThrownBy(()->worker(broken,url).tick()).isInstanceOf(org.springframework.dao.DataAccessException.class);assertThat(head(run).get("delivery_status")).isEqualTo("RETRY_WAIT");assertThat(stream(run).get("next_source_seq")).isEqualTo(1L);assertThat(count(operations,"processed_event",run)).isEqualTo(1);
            clock.value.set(DeliveryStore.instant(head(run).get("next_attempt_at")).plusMillis(1));
            assertThat(worker(new DeliveryStore(jdbc,manager,clock),url).tick()).isTrue();assertThat(head(run).get("delivery_status")).isEqualTo("DELIVERED");assertThat(head(run).get("attempt_count")).isEqualTo(3);assertThat(stream(run).get("next_source_seq")).isEqualTo(2L);assertThat(count(operations,"processed_event",run)).isEqualTo(1);assertThat(remoteCalls.get()).isEqualTo(3);
        }finally{proxy.stop(0);}
        String down=run();admit(frames(down).getFirst());
        boolean blocked=false;
        try {
            admin("ALTER DATABASE operations_db ALLOW_CONNECTIONS false; SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='operations_db';");blocked=true;
            assertThat(worker(store,target).tick()).isTrue();assertThat(head(down).get("delivery_status")).isEqualTo("RETRY_WAIT");assertThat(head(down).get("last_error")).isEqualTo("DB_UNAVAILABLE");assertThat(stream(down).get("next_source_seq")).isEqualTo(1L);
        }finally {if(blocked)admin("ALTER DATABASE operations_db ALLOW_CONNECTIONS true;");}
        clock.value.set(DeliveryStore.instant(head(down).get("next_attempt_at")).plusMillis(1));assertThat(worker(new DeliveryStore(jdbc,manager,clock),target).tick()).isTrue();assertThat(stream(down).get("next_source_seq")).isEqualTo(2L);assertThat(count(operations,"processed_event",down)).isEqualTo(1);
    }
    @Test void gapsPermanentIsolationDependencyAttemptsAndAuditedSameHeadResume() throws Exception {
        String gap=run();var f=frames(gap);var finish=(ObjectNode)f.getLast().deepCopy();finish.put("sourceSeq",2);((ObjectNode)finish.get("payload")).put("uniqueEventCount",2);admit(finish);
        assertThat(store.reserveNext()).isNull();assertThat(stream(gap).get("state")).isEqualTo("GAP_WAIT");clock.value.set(clock.instant().plusMillis(30000));assertThat(store.reserveNext()).isNull();assertThat(stream(gap).get("state")).isEqualTo("PAUSED_GAP");
        admit(f.getFirst());var w=worker(new DeliveryStore(jdbc,manager,clock),target);assertThat(w.tick()).isTrue();assertThat(w.tick()).isTrue();assertThat(stream(gap).get("next_source_seq")).isEqualTo(3L);
        String bad=run();var badFrames=frames(bad);((ObjectNode)badFrames.getFirst().get("payload").get("config").get("equipment").get(0)).put("equipmentId","ASM-02");admit(badFrames.getFirst());admit(badFrames.get(1));w.tick();assertThat(stream(bad).get("state")).isEqualTo("BLOCKED");assertThat(head(bad).get("delivery_status")).isEqualTo("QUARANTINED");assertThat(stream(bad).get("next_source_seq")).isEqualTo(1L);assertThat(stream(bad).get("diagnostic_rejected_count")).isEqualTo(1L);assertThat(count(operations,"processed_event",bad)).isEqualTo(1);
        assertThatThrownBy(()->store.resume(bad,1,"tester","cannot skip rejected fact")).isInstanceOf(DeliveryProblem.class);
        String good=run();admit(frames(good).getFirst());w.tick();assertThat(stream(good).get("next_source_seq")).isEqualTo(2L);
        String dependent=run();var inspect=frames(dependent).stream().filter(n->n.get("eventType").stringValue().equals("INSPECTION_COMPLETED")).findFirst().orElseThrow();inspect.put("sourceSeq",1);admit(inspect);w.tick();assertThat(head(dependent).get("last_error")).isEqualTo("RUN_NOT_READY");clock.value.set(clock.instant().plusMillis(30000));w.tick();assertThat(stream(dependent).get("state")).isEqualTo("PAUSED_DEPENDENCY");assertThat(head(dependent).get("attempt_count")).isEqualTo(1);
        String outage=run();admit(frames(outage).getFirst());int port;try(var free=new java.net.ServerSocket(0)){port=free.getLocalPort();}
        var offline=worker(new DeliveryStore(jdbc,manager,clock),"http://127.0.0.1:"+port);
        for(int i=0;i<20;i++){assertThat(offline.tick()).isTrue();var at=DeliveryStore.instant(head(outage).get("next_attempt_at"));if(at!=null)clock.value.set(at.plusMillis(1));}
        assertThat(stream(outage).get("state")).isEqualTo("PAUSED_RETRY");assertThat(head(outage).get("attempt_count")).isEqualTo(20);assertThat(worker(new DeliveryStore(jdbc,manager,clock),target).tick()).isFalse();assertThat(stream(outage).get("diagnostic_retry_count")).isEqualTo(19L);
        var req=HttpRequest.newBuilder(URI.create(base()+"/internal/v1/runs/"+outage+"/delivery-resume")).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString("{\"sourceSeq\":1,\"operatorId\":\"tester\",\"reason\":\"endpoint restored\"}")).build();
        assertThat(http.send(req,HttpResponse.BodyHandlers.ofString()).statusCode()).isEqualTo(200);assertThat(count(jdbc,"delivery_action",outage)).isEqualTo(1);assertThat(head(outage).get("attempt_count")).isEqualTo(0);w.tick();assertThat(stream(outage).get("next_source_seq")).isEqualTo(2L);assertThat(head(outage).get("total_attempt_count")).isEqualTo(21L);assertThat(stream(outage).get("diagnostic_retry_count")).isEqualTo(20L);
    }
    private void admin(String sql) throws Exception {
        // This helper created an isolated PGPORT. Never act on the Compose database.
        assertThat(System.getenv("INGESTION_DB_URL")).contains(":"+System.getenv("PGPORT")+"/ingestion_db");
        var p=new ProcessBuilder(System.getenv("FACTORY_PSQL"),"--no-psqlrc","--dbname=postgres","-v","ON_ERROR_STOP=1","-c",sql).redirectErrorStream(true).start();String output=new String(p.getInputStream().readAllBytes(),StandardCharsets.UTF_8);assertThat(p.waitFor()).withFailMessage("%s",output).isZero();
    }
}
