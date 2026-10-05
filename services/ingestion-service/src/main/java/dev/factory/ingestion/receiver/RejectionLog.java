package dev.factory.ingestion.receiver;

import java.io.IOException;
import java.nio.file.*;
import java.time.Instant;
import java.util.LinkedHashMap;

/** Dedicated bounded diagnostic log; never writes rejected inputs to raw_event/outbox. */
public final class RejectionLog {
    private final Path path;
    public RejectionLog(Path path) { this.path=path; }
    public synchronized boolean record(Protocol.Ack ack,byte[] raw) {
        try {
            Path parent=path.toAbsolutePath().getParent(); Files.createDirectories(parent);
            var row=new LinkedHashMap<String,Object>();
            row.put("timestamp",Protocol.time(Instant.now())); row.put("code",ack.code());
            row.put("runId",ack.runId()); row.put("sourceId",ack.sourceId()); row.put("eventId",ack.eventId());
            row.put("sourceSeq",ack.sourceSeq()); row.put("eventSha256",ack.eventSha256());
            row.put("previewBase64",java.util.Base64.getEncoder().encodeToString(java.util.Arrays.copyOf(raw,Math.min(raw.length,1024))));
            byte[] line=(Protocol.JSON.writeValueAsString(row)+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            if(Files.exists(path) && Files.size(path)+line.length>10485760) {
                Files.deleteIfExists(Path.of(path+".2"));
                if(Files.exists(Path.of(path+".1"))) Files.move(Path.of(path+".1"),Path.of(path+".2"),StandardCopyOption.REPLACE_EXISTING);
                Files.move(path,Path.of(path+".1"),StandardCopyOption.REPLACE_EXISTING);
            }
            Files.write(path,line,StandardOpenOption.CREATE,StandardOpenOption.APPEND); return true;
        } catch(IOException | RuntimeException failure) { return false; }
    }
}
