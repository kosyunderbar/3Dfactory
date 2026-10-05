package dev.factory.ingestion.receiver;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named="FACTORY_INGESTION_TESTS",matches="true")
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.NONE,properties={"factory.tcp.enabled=false", "factory.delivery.enabled=false","management.endpoint.health.group.readiness.include=readinessState,db"})
class EventStoreTests {
    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager manager;
    private final List<String> runs=new ArrayList<>();
    private String run() { String id="run-20261005-"+UUID.randomUUID().toString().replace("-",""); runs.add(id); return id; }
    static String fixture(String run,long seq) {
        return "{\"schemaVersion\":1,\"eventId\":\""+UUID.randomUUID()+"\",\"runId\":\""+run+"\",\"sourceId\":\"simulator-01\",\"sourceSeq\":"+seq+
            ",\"eventType\":\"RUN_FINISHED\",\"occurredAt\":\"2026-10-05T00:00:00.000Z\",\"payload\":{\"reason\":\"DRAINED\",\"uniqueEventCount\":"+seq+"}}";
    }
    private Protocol.Event parse(String raw) { return Protocol.parse(raw.getBytes(StandardCharsets.UTF_8)); }
    private EventStore store() { return new EventStore(jdbc,new TransactionTemplate(manager)); }
    private long count(String table,String run) { return jdbc.queryForObject("SELECT count(*) FROM "+table+" WHERE run_id=?",Long.class,run); }
    @AfterEach void cleanup() { for(String run:runs) { jdbc.update("DELETE FROM event_outbox WHERE run_id=?",run); jdbc.update("DELETE FROM raw_event WHERE run_id=?",run); jdbc.update("DELETE FROM delivery_stream WHERE run_id=?",run); } }

    @Test void commitDuplicatesConflictsAndNewOnlyCaps() {
        String run=run(); var event=parse(fixture(run,1)); Instant received=Instant.now();
        var store=new EventStore(jdbc,new TransactionTemplate(manager),new EventStore.Limits(1,134217728,50000,536870912,250000,1073741824),()->{});
        var ack=store.receive(event,received); assertThat(ack.status()).isEqualTo("RECEIVED");
        assertThat(Instant.parse(ack.committedAt())).isAfterOrEqualTo(received);
        assertThat(count("raw_event",run)).isEqualTo(1); assertThat(count("event_outbox",run)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT next_source_seq FROM delivery_stream WHERE run_id=?",Long.class,run)).isEqualTo(1);
        var dup=store.receive(event,Instant.now()); assertThat(dup.status()).isEqualTo("DUPLICATE_RECEIVED"); assertThat(dup.receivedAt()).isEqualTo(ack.receivedAt());
        assertThat(store.receive(parse(event.raw()+" "),received).code()).isEqualTo("ID_CONFLICT");
        assertThat(store.receive(parse(event.raw().replace("\"sourceSeq\":1","\"sourceSeq\":2")),received).code()).isEqualTo("ID_CONFLICT");
        assertThat(store.receive(parse(fixture(run,1)),received).code()).isEqualTo("SEQUENCE_CONFLICT");
        assertThat(store.receive(parse(fixture(run,2).replace("simulator-01","simulator-02")),received).code()).isEqualTo("SOURCE_CONFLICT");
        assertThat(store.receive(parse(fixture(run,2)),received).code()).isEqualTo("OUTBOX_FULL");
        assertThat(count("raw_event",run)).isEqualTo(1); assertThat(count("event_outbox",run)).isEqualTo(1);
        for(var limits:List.of(new EventStore.Limits(5000,1,50000,536870912,250000,1073741824),
            new EventStore.Limits(5000,134217728,1,536870912,250000,1073741824),new EventStore.Limits(5000,134217728,50000,1,250000,1073741824),
            new EventStore.Limits(5000,134217728,50000,536870912,1,1073741824),new EventStore.Limits(5000,134217728,50000,536870912,250000,1))) {
            var capped=new EventStore(jdbc,new TransactionTemplate(manager),limits,()->{});
            assertThat(capped.receive(event,received).status()).isEqualTo("DUPLICATE_RECEIVED");
            assertThat(capped.receive(parse(fixture(run,2)),received).code()).isIn("OUTBOX_FULL","HISTORY_LIMIT");
        }
        String future=fixture(run(),1).replace("2026-10-05T00:00:00.000Z",Protocol.time(received.plusSeconds(6)));
        assertThat(store().receive(parse(future),received).code()).isEqualTo("CLOCK_AHEAD");
        assertThat(store().receive(parse(future.replace(Protocol.time(received.plusSeconds(6)),Protocol.time(received.plusSeconds(5)))),received).status()).isEqualTo("RECEIVED");
    }
    @Test void realRollbackBetweenRawAndOutboxLeavesNoStreamOrRows() {
        String run=run(); var event=parse(fixture(run,1));
        var broken=new EventStore(jdbc,new TransactionTemplate(manager),EventStore.Limits.V1,()->{
            assertThat(count("raw_event",run)).isEqualTo(1);
            jdbc.update("INSERT INTO event_outbox(run_id,event_id,attempt_count) VALUES (?,?::uuid,21)",run,event.identity().eventId());
        });
        var ack=broken.receive(event,Instant.now()); assertThat(ack.code()).isEqualTo("DB_UNAVAILABLE"); assertThat(ack.committedAt()).isNull();
        for(String table:List.of("raw_event","event_outbox","delivery_stream")) assertThat(count(table,run)).isZero();
        assertThat(store().receive(event,Instant.now()).status()).isEqualTo("RECEIVED");
    }
    @Test void realTcpCommitLostAckPipeliningMalformedAndPartialDisconnect() throws Exception {
        Path log=Files.createTempDirectory("factory-ingestion-test-").resolve("reject.ndjson");
        var receiver=new TcpReceiver("127.0.0.1",0,store(),new RejectionLog(log)); receiver.start();
        try {
            String run=run(); String raw=fixture(run,1);
            try(Socket socket=connect(receiver)) {
                socket.getOutputStream().write((raw+"\n").getBytes(StandardCharsets.UTF_8)); socket.shutdownOutput();
                // Observe commit through another DB connection while deliberately never reading the ACK.
                long deadline=System.nanoTime()+2_000_000_000L;
                while(count("event_outbox",run)==0 && System.nanoTime()<deadline) Thread.sleep(10);
                assertThat(count("event_outbox",run)).isEqualTo(1);
            }
            try(Socket socket=connect(receiver)) {
                byte[] frames=(raw+"\n"+fixture(run,2)+"\n").getBytes(StandardCharsets.UTF_8);
                socket.getOutputStream().write(frames,0,3); socket.getOutputStream().write(frames,3,frames.length-3);
                var reader=new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8));
                assertThat(Protocol.JSON.readTree(reader.readLine()).get("status").stringValue()).isEqualTo("DUPLICATE_RECEIVED");
                assertThat(Protocol.JSON.readTree(reader.readLine()).get("status").stringValue()).isEqualTo("RECEIVED");
                assertThat(count("raw_event",run)).isEqualTo(2); assertThat(count("event_outbox",run)).isEqualTo(2);
            }
            try(Socket socket=connect(receiver)) {
                socket.getOutputStream().write(fixture(run,3).getBytes(StandardCharsets.UTF_8)); socket.shutdownOutput();
                assertThat(socket.getInputStream().read()).isEqualTo(-1); assertThat(count("raw_event",run)).isEqualTo(2);
            }
            for(byte[] invalid:List.of("{bad}\n".getBytes(StandardCharsets.UTF_8),new byte[]{(byte)0xff,'\n'},new byte[65536])) {
                try(Socket socket=connect(receiver)) {
                    socket.getOutputStream().write(invalid);
                    var ack=Protocol.JSON.readTree(new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8)).readLine());
                    assertThat(ack.get("status").stringValue()).isEqualTo("REJECTED");
                    assertThat(ack.get("code").stringValue()).isIn("INVALID_JSON","INVALID_UTF8","FRAME_TOO_LARGE");
                }
            }
            try(Socket socket=connect(receiver)) {
                socket.getOutputStream().write((fixture(run,3)+"\n").getBytes(StandardCharsets.UTF_8));
                socket.getOutputStream().write(new byte[65536]);
                var reader=new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8));
                assertThat(Protocol.JSON.readTree(reader.readLine()).get("status").stringValue()).isEqualTo("RECEIVED");
                assertThat(Protocol.JSON.readTree(reader.readLine()).get("code").stringValue()).isEqualTo("FRAME_TOO_LARGE");
                assertThat(count("event_outbox",run)).isEqualTo(3);
            }
            try(Socket socket=connect(receiver)) {
                socket.getOutputStream().write(new byte[]{'{'});
                var reader=new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8));
                assertThat(Protocol.JSON.readTree(reader.readLine()).get("code").stringValue()).isEqualTo("FRAME_TIMEOUT");
            }
            assertThat(Files.readAllLines(log)).hasSize(5);
            List<Socket> held=new ArrayList<>();
            try {
                long drained=System.nanoTime()+1_000_000_000L;
                while(receiver.activeConnections()>0 && System.nanoTime()<drained) Thread.sleep(5);
                for(int i=0;i<8;i++) held.add(connect(receiver));
                long accepted=System.nanoTime()+1_000_000_000L;
                while(receiver.activeConnections()<8 && System.nanoTime()<accepted) Thread.sleep(5);
                assertThat(receiver.activeConnections()).isEqualTo(8);
                try(Socket ninth=connect(receiver)) { assertThat(ninth.getInputStream().read()).isEqualTo(-1); }
            } finally { for(Socket socket:held) socket.close(); }
            // An unavailable diagnostic file must not claim a successfully recorded rejection.
            var brokenLog=new TcpReceiver("127.0.0.1",0,store(),new RejectionLog(log.getParent())); brokenLog.start();
            try(Socket socket=connect(brokenLog)) {
                socket.getOutputStream().write("{bad}\n".getBytes(StandardCharsets.UTF_8));
                var ack=Protocol.JSON.readTree(new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8)).readLine());
                assertThat(ack.get("code").stringValue()).isEqualTo("DIAGNOSTIC_UNAVAILABLE");
            } finally { brokenLog.stop(); }
        } finally { receiver.stop(); }
    }
    private Socket connect(TcpReceiver receiver) throws IOException { var socket=new Socket("127.0.0.1",receiver.boundPort()); socket.setSoTimeout(5000); return socket; }
}
