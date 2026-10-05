package dev.factory.operations.stream;

import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import dev.factory.operations.domain.*;
import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named="FACTORY_STREAM_TESTS",matches="true")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="factory.ingestion-diagnostic-url=http://127.0.0.1:1")
class StreamIntegrationTests {
    @Autowired EventApplication application;
    @Autowired JdbcTemplate jdbc;
    @Autowired ViewPublisher views;
    @Autowired SnapshotStreams streams;
    @Autowired WebServerApplicationContext context;
    final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
    final List<InputStream> opened=new ArrayList<>();
    String run;
    String url(String path){return "http://127.0.0.1:"+context.getWebServer().getPort()+path;}
    HttpResponse<InputStream> open(String run,String last) throws Exception {
        var builder=HttpRequest.newBuilder(URI.create(url("/api/v1/runs/"+run+"/stream"))).timeout(Duration.ofSeconds(3));if(last!=null)builder.header("Last-Event-ID",last);
        var response=client.send(builder.GET().build(),HttpResponse.BodyHandlers.ofInputStream());opened.add(response.body());return response;
    }
    record Frame(String id,JsonNode value) {}
    Frame snapshot(InputStream body) throws Exception {
        return CompletableFuture.supplyAsync(()->{
            try {var reader=new BufferedReader(new InputStreamReader(body,StandardCharsets.UTF_8));String id=null,event=null,data=null,line;
                while((line=reader.readLine())!=null){if(line.startsWith("id: "))id=line.substring(4);if(line.startsWith("event: "))event=line.substring(7);if(line.startsWith("data: "))data=line.substring(6);if(line.isEmpty() && "factory-snapshot".equals(event))return new Frame(id,EventSyntax.JSON.readTree(data));}throw new IllegalStateException("No snapshot");
            }catch(IOException e){throw new UncheckedIOException(e);}
        }).get(3,TimeUnit.SECONDS);
    }
    @AfterEach void cleanup() throws Exception {
        for(var body:opened)body.close();waitFor(()->streams.connections()==0);
        if(run!=null)for(String table:List.of("factory_snapshot","inspection_result","operation_history","transport_history","alarm","event_projection","processed_event","body","factory_buffer","equipment","vehicle","simulation_run"))jdbc.update("DELETE FROM "+table+" WHERE run_id=?",run);
    }
    void waitFor(java.util.function.BooleanSupplier predicate) throws Exception {long until=System.nanoTime()+4_000_000_000L;while(!predicate.getAsBoolean()){if(System.nanoTime()>until)throw new AssertionError("Stream cleanup timeout");Thread.sleep(25);}}
    @Test void actualHttpStreamSharesRestBundleReconnectsLatestAndLimitsConnections() throws Exception {
        String absent="run-20261005-"+UUID.randomUUID().toString().replace("-","");var missing=open(absent,null);assertThat(missing.statusCode()).isEqualTo(404);assertThat(new String(missing.body().readAllBytes(),StandardCharsets.UTF_8)).contains("RUN_NOT_FOUND");
        run="run-20261005-"+UUID.randomUUID().toString().replace("-","");var lines=Files.readAllLines(Path.of("src/test/resources/factory-scenario.ndjson"));
        var start=(ObjectNode)EventSyntax.JSON.readTree(lines.getFirst());String old=start.get("runId").stringValue();start.put("runId",run);start.put("eventId",UUID.randomUUID().toString());
        var parsed=EventSyntax.parse(start.toString().replace(old,run).getBytes(StandardCharsets.UTF_8));assertThat(application.apply(parsed,Instant.now()).http()).isEqualTo(200);
        var rest=views.current(run);var first=open(run,null);assertThat(first.statusCode()).isEqualTo(200);assertThat(first.headers().firstValue("Content-Type").orElseThrow()).startsWith("text/event-stream");assertThat(first.headers().firstValue("Cache-Control")).contains("no-store");assertThat(first.headers().firstValue("X-Accel-Buffering")).contains("no");
        var frame=snapshot(first.body());assertThat(frame.id()).isEqualTo(frame.value().get("serverEpoch").stringValue()+":"+frame.value().get("revision").longValue());assertThat(frame.value().get("runId").stringValue()).isEqualTo(run);assertThat(frame.value().get("dataStatus").stringValue()).isEqualTo("WAITING");assertThat(frame.value().get("sourceSeq").isNull()).isTrue();assertThat(frame.value().get("serverEpoch").stringValue()).isEqualTo(rest.get("serverEpoch"));assertThat(frame.value().get("revision").longValue()).isGreaterThanOrEqualTo(((Number)rest.get("revision")).longValue());
        first.body().close();waitFor(()->streams.connections()==0);
        var reconnect=open(run,frame.id());var latest=snapshot(reconnect.body());assertThat(latest.value().get("revision").longValue()).isGreaterThanOrEqualTo(frame.value().get("revision").longValue());reconnect.body().close();waitFor(()->streams.connections()==0);
        for(int i=0;i<20;i++)assertThat(open(run,null).statusCode()).isEqualTo(200);
        var excess=open(run,null);assertThat(excess.statusCode()).isEqualTo(429);assertThat(excess.headers().firstValue("Retry-After")).contains("2");assertThat(new String(excess.body().readAllBytes(),StandardCharsets.UTF_8)).contains("STREAM_LIMIT");
    }
}
