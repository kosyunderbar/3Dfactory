package dev.factory.operations.domain;

import java.net.*;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import org.springframework.http.MediaType;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import static dev.factory.operations.domain.ReadSupport.map;

/** Optional internal HTTP sample. No SQL into ingestion_db; S05 supplies the endpoint. */
public final class DeliveryDiagnostics {
    private record Sample(Map<String,Object> data,Instant checked) {}
    private final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofMillis(500)).build();
    private final URI base;
    private final Map<String,Sample> cache=new HashMap<>();
    public DeliveryDiagnostics(String base) { this.base=URI.create(base); if(!Set.of("http","https").contains(this.base.getScheme()) || this.base.getHost()==null) throw new IllegalArgumentException("Invalid internal diagnostic base URL"); }
    public synchronized Map<String,Object> get(String run,String source,Instant now) {
        Sample sample=cache.get(run);
        if(sample==null || Duration.between(sample.checked(),now).toMillis()>=1000) {
            var prior=sample==null?Observation.unavailable(run,source):new LinkedHashMap<>(sample.data());
            try {
                URI uri=URI.create(base.toString().replaceAll("/$","")+"/internal/v1/runs/"+run+"/delivery-status");
                var pending=client.sendAsync(HttpRequest.newBuilder(uri).timeout(Duration.ofMillis(1000)).GET().build(),info->new LimitedBody(8192));
                HttpResponse<byte[]> response;
                try { response=pending.get(1000,java.util.concurrent.TimeUnit.MILLISECONDS); }
                finally { if(!pending.isDone()) pending.cancel(true); }
                byte[] bytes=response.body();
                if(response.statusCode()!=200) throw new IllegalArgumentException();
                var media=MediaType.parseMediaType(response.headers().firstValue("Content-Type").orElseThrow());
                if(!media.getType().equalsIgnoreCase("application") || !media.getSubtype().equalsIgnoreCase("json") || media.getCharset()!=null && !media.getCharset().equals(StandardCharsets.UTF_8)) throw new IllegalArgumentException();
                String raw=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
                if(raw.startsWith("\ufeff")) throw new IllegalArgumentException();
                var n=EventSyntax.JSON.readTree(raw); validate(n,run,source,now);
                prior=new LinkedHashMap<>(); for(String field:n.propertyNames()) if(!field.equals("protocolVersion")) prior.put(field,EventSyntax.JSON.convertValue(n.get(field),Object.class));
                prior.put("diagnosticState","AVAILABLE");
            } catch(Exception error) { if(error instanceof InterruptedException) Thread.currentThread().interrupt(); prior.put("diagnosticState","UNAVAILABLE"); }
            sample=new Sample(prior,now); cache.put(run,sample);
        }
        var result=new LinkedHashMap<>(sample.data());
        if(result.get("sampledAt")!=null && (Duration.between(Instant.parse((String)result.get("sampledAt")),now).toMillis()>=3000 || Instant.parse((String)result.get("sampledAt")).isAfter(now.plusMillis(5000)))) result.put("diagnosticState","UNAVAILABLE");
        return result;
    }
    void forget(String run) { synchronized(this) { cache.remove(run); } }
    private void validate(JsonNode n,String run,String source,Instant now) {
        Set<String> fields=Set.of("protocolVersion","runId","sourceId","sampledAt","sourceConnected","lastReceivedAt","lastAcceptedSeq","nextSourceSeq","streamState","blockedSeq","blockedCode","pendingCount","pendingBytes","oldestPendingReceivedAt","retryCount","rejectedCount");
        if(n==null || !n.isObject() || !new HashSet<>(n.propertyNames()).equals(fields) || !n.get("protocolVersion").isIntegralNumber() || !n.get("protocolVersion").canConvertToInt() || n.get("protocolVersion").intValue()!=1 || !run.equals(n.get("runId").stringValue()) || !source.equals(n.get("sourceId").stringValue()) || !n.get("sourceConnected").isBoolean()) throw new IllegalArgumentException();
        Instant at=EventSyntax.timestamp(n.get("sampledAt")); if(at.isAfter(now.plusMillis(5000)) || Duration.between(at,now).toMillis()>=3000) throw new IllegalArgumentException();
        for(String key:List.of("lastReceivedAt","oldestPendingReceivedAt")) if(!n.get(key).isNull()) EventSyntax.timestamp(n.get(key));
        for(String key:List.of("lastAcceptedSeq","nextSourceSeq","blockedSeq","pendingCount","pendingBytes","retryCount","rejectedCount")) {
            var v=n.get(key); if(v.isNull() && Set.of("lastAcceptedSeq","blockedSeq").contains(key)) continue;
            if(!v.isIntegralNumber() || !v.canConvertToLong() || v.longValue()<(Set.of("nextSourceSeq","lastAcceptedSeq","blockedSeq").contains(key)?1:0) || v.longValue()>9007199254740991L) throw new IllegalArgumentException();
        }
        if(n.get("pendingCount").longValue()>5000 || n.get("pendingBytes").longValue()>134217728 || (n.get("pendingCount").longValue()>0)==n.get("oldestPendingReceivedAt").isNull() || n.get("blockedSeq").isNull()!=n.get("blockedCode").isNull()) throw new IllegalArgumentException();
        if(!Set.of("ACTIVE","RETRY_WAIT","GAP_WAIT","PAUSED_RETRY","PAUSED_GAP","PAUSED_DEPENDENCY","PAUSED_CONFIG","BLOCKED").contains(n.get("streamState").stringValue())) throw new IllegalArgumentException();
    }
}
