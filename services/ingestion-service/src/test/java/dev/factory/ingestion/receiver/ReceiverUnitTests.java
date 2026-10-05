package dev.factory.ingestion.receiver;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ReceiverUnitTests {
    @Test void fragmentedUtf8MultipleFramesSizeAndFixedDeadline() {
        byte[] line="{\"x\":\"가\"}\n{}\n".getBytes(StandardCharsets.UTF_8);
        List<String> frames=new ArrayList<>(); FrameDecoder decoder=new FrameDecoder();
        for(byte b:line) decoder.feed(new byte[]{b},1,0,Instant.EPOCH,(raw,at)->frames.add(new String(raw,StandardCharsets.UTF_8)));
        assertThat(frames).containsExactly("{\"x\":\"가\"}","{}");
        decoder=new FrameDecoder(); frames.clear();
        decoder.feed(line,line.length,0,Instant.EPOCH,(raw,at)->frames.add(new String(raw,StandardCharsets.UTF_8)));
        assertThat(frames).hasSize(2);
        FrameDecoder deadline=new FrameDecoder();
        deadline.feed(new byte[]{'a'},1,0,Instant.EPOCH,(raw,at)->{});
        deadline.feed(new byte[]{'b'},1,2_900_000_000L,Instant.EPOCH,(raw,at)->{});
        assertThat(assertThrows(Protocol.Invalid.class,()->deadline.checkDeadline(3_000_000_000L)).code).isEqualTo("FRAME_TIMEOUT");
        FrameDecoder large=new FrameDecoder(); byte[] max=new byte[65536]; Arrays.fill(max,(byte)' '); max[65535]='\n';
        large.feed(max,max.length,0,Instant.EPOCH,(raw,at)->assertThat(raw).hasSize(65535));
        Arrays.fill(max,(byte)' ');
        assertThat(assertThrows(Protocol.Invalid.class,()->large.feed(max,max.length,0,Instant.EPOCH,(raw,at)->{})).code).isEqualTo("FRAME_TOO_LARGE");
    }
    @Test void strictJsonAllCatalogKindsAndNestedSchemaBounds() throws Exception {
        var catalog=Protocol.JSON.readTree(Files.readString(Path.of("../../contracts/v1/examples/event-catalog.json")));
        assertThat(catalog.size()).isEqualTo(17);
        for(var event:catalog) assertThat(Protocol.parse(event.toString().getBytes(StandardCharsets.UTF_8)).identity()).isNotNull();
        for(var pair:List.of(new String[]{"{\"x\":1,\"x\":2}","INVALID_JSON"},new String[]{"{\"x\":NaN}","INVALID_JSON"},
                new String[]{"{} {}","INVALID_JSON"},new String[]{"\ufeff{}","INVALID_FRAME"},new String[]{"{}\r","INVALID_FRAME"},new String[]{"","INVALID_FRAME"}))
            assertThat(assertThrows(Protocol.Invalid.class,()->Protocol.parse(pair[0].getBytes(StandardCharsets.UTF_8))).code).isEqualTo(pair[1]);
        assertThat(assertThrows(Protocol.Invalid.class,()->Protocol.parse(new byte[]{(byte)0xff})).code).isEqualTo("INVALID_UTF8");
        String config=catalog.get(0).toString();
        for(String changed:List.of(config.replaceAll("\"capacity\":3","\"capacity\":5"),
            config.replaceAll("\"workDurationMs\":[0-9]+","\"workDurationMs\":true")))
            assertThat(assertThrows(Protocol.Invalid.class,()->Protocol.parse(changed.getBytes(StandardCharsets.UTF_8))).code).isEqualTo("SCHEMA_INVALID");
        for(var item:catalog) if(item.get("eventType").stringValue().equals("INSPECTION_COMPLETED")) {
            String wrongEquipment=item.toString().replace("QC-01","ASM-01");
            assertThat(assertThrows(Protocol.Invalid.class,()->Protocol.parse(wrongEquipment.getBytes(StandardCharsets.UTF_8))).code).isEqualTo("SCHEMA_INVALID");
        }
        String raw=EventStoreTests.fixture("run-20261005-unit",1);
        for(String changed:List.of(raw.replace("\"sourceSeq\":1","\"sourceSeq\":true"),raw.replace("DRAINED","UNKNOWN"),
                raw.replace("2026-10-05T00:00:00.000Z","2026-02-30T00:00:00.000Z"),raw.replace("\"reason\":","\"extra\":0,\"reason\":")))
            assertThat(assertThrows(Protocol.Invalid.class,()->Protocol.parse(changed.getBytes(StandardCharsets.UTF_8))).code).isEqualTo("SCHEMA_INVALID");
        var unknown=assertThrows(Protocol.Invalid.class,()->Protocol.parse(raw.replace("schemaVersion\":1","schemaVersion\":2").getBytes(StandardCharsets.UTF_8)));
        assertThat(unknown.code).isEqualTo("UNSUPPORTED_SCHEMA"); assertThat(unknown.identity).isNotNull();
        var missing=assertThrows(Protocol.Invalid.class,()->Protocol.parse(raw.replace("simulator-01","bad-source").getBytes(StandardCharsets.UTF_8)));
        assertThat(missing.identity).isNull();
    }
    @Test void queueCapsCountAndBytesWithoutAdmittingBusyFrame() throws Exception {
        for(boolean byteLimit:List.of(false,true)) {
            var entered=new CountDownLatch(1); var release=new CountDownLatch(1);
            try(var queue=new AdmissionQueue(byteLimit?128:1,byteLimit?3:8388608,(raw,at)->{
                entered.countDown(); try { release.await(); } catch(InterruptedException e) { throw new RuntimeException(e); }
                return Protocol.Ack.of(null,null,"RETRY_LATER","INGESTION_BUSY",at);
            })) {
                var active=queue.offer(new byte[]{1},Instant.EPOCH); assertThat(entered.await(1,TimeUnit.SECONDS)).isTrue();
                var waiting=queue.offer(new byte[]{1,2},Instant.EPOCH); assertThat(waiting).isNotNull();
                assertThat(queue.offer(new byte[]{1},Instant.EPOCH)).isNull();
                release.countDown(); assertThat(active.get(1,TimeUnit.SECONDS)).isNotNull(); assertThat(waiting.get(1,TimeUnit.SECONDS)).isNotNull();
            } finally { release.countDown(); }
        }
    }
}
