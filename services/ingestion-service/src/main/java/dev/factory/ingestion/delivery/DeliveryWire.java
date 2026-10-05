package dev.factory.ingestion.delivery;

import java.nio.charset.*;
import java.nio.ByteBuffer;
import java.time.*;
import java.util.*;
import tools.jackson.databind.JsonNode;
import dev.factory.ingestion.receiver.Protocol;

/** Classifies the v1 reply. A TCP ACK and an HTTP 200 alone are not business completion. */
public final class DeliveryWire {
    public enum Action { DELIVERED, RETRY, DEPENDENCY, BLOCKED, QUARANTINED, CONFIG }
    public record Decision(Action action,String code,long delayMs,JsonNode response) {}
    private static final Set<String> FIELDS=Set.of("protocolVersion","kind","runId","sourceId","eventId","sourceSeq","eventSha256","status","code","appliedAt","recordedAt","retryAfterMs");
    private static final Set<String> SUCCESS=Set.of("OK","STALE_SNAPSHOT_RECORDED","FACT_ALREADY_RECORDED");
    private static final Set<String> PERMANENT=Set.of("MODEL_INVALID","BUSINESS_ID_CONFLICT","INVALID_EVENT");
    private static final Set<String> CONFLICT=Set.of("ID_CONFLICT","SEQUENCE_CONFLICT","SOURCE_CONFLICT");
    private DeliveryWire() {}
    public static Decision retry(String code) {return new Decision(Action.RETRY,code,0,null);}
    public static Instant time(JsonNode n) {
        if(n==null || !n.isString() || !n.stringValue().matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z")) throw new IllegalArgumentException();
        Instant at=Instant.parse(n.stringValue());if(!Protocol.time(at).equals(n.stringValue())) throw new IllegalArgumentException();return at;
    }
    public static Decision classify(DeliveryStore.Head head,int http,byte[] bytes,String retryHeader,boolean jsonUtf8) {
        if(Set.of(400,404,405,413,415).contains(http)) return new Decision(Action.CONFIG,"HTTP_"+http,0,preview(http,bytes));
        if(http!=200 && http!=409 && http!=422 && http!=429 && (http<500 || http>599)) return new Decision(Action.CONFIG,"UNEXPECTED_HTTP_STATUS",0,preview(http,bytes));
        JsonNode n;
        try {
            if(!jsonUtf8) throw new IllegalArgumentException();
            String text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            if(text.startsWith("\ufeff")) throw new IllegalArgumentException();n=Protocol.JSON.readTree(text);if(n==null) throw new IllegalArgumentException();
        } catch(Exception broken) {
            if(http==200 || http>=500 || http==429) return temporary(http,bytes,retryHeader);
            return new Decision(Action.CONFIG,"MALFORMED_RESPONSE",0,preview(http,bytes));
        }
        try {
            if(!n.isObject() || !new HashSet<>(n.propertyNames()).equals(FIELDS) || !n.get("protocolVersion").isIntegralNumber() || !n.get("protocolVersion").canConvertToInt() || n.get("protocolVersion").intValue()!=1 || !"APPLICATION_RESULT".equals(text(n,"kind"))) throw new IllegalArgumentException();
            var id=head.identity();
            if(!id.runId().equals(text(n,"runId")) || !id.sourceId().equals(text(n,"sourceId")) || !id.eventId().equals(text(n,"eventId")) || !head.hash().equals(text(n,"eventSha256")) || !n.get("sourceSeq").isIntegralNumber() || !n.get("sourceSeq").canConvertToLong() || id.sourceSeq()!=n.get("sourceSeq").longValue()) return new Decision(Action.CONFIG,"RESPONSE_ID_MISMATCH",0,n);
            String status=text(n,"status"),code=text(n,"code");
            if(http==200 && Set.of("APPLIED","DUPLICATE_APPLIED").contains(status) && SUCCESS.contains(code)) {
                time(n.get("appliedAt"));time(n.get("recordedAt"));nil(n,"retryAfterMs");return new Decision(Action.DELIVERED,code,0,n);
            }
            if(status.equals("REJECTED") && ((http==422 && PERMANENT.contains(code)) || (http==409 && CONFLICT.contains(code)))) {
                nil(n,"appliedAt");time(n.get("recordedAt"));nil(n,"retryAfterMs");return new Decision(Action.QUARANTINED,code,0,n);
            }
            if(status.equals("RETRY_LATER") && ((http==409 && Set.of("RUN_NOT_READY","REFERENCE_NOT_READY","RUN_BLOCKED").contains(code)) || (http==429 && code.equals("OPERATIONS_BUSY")) || (http>=500 && Set.of("DB_UNAVAILABLE","TEMPORARY_FAILURE").contains(code)))) {
                nil(n,"appliedAt");nil(n,"recordedAt");var ms=n.get("retryAfterMs");
                if(!ms.isIntegralNumber() || !ms.canConvertToInt() || ms.intValue()<1 || ms.intValue()>30000) throw new IllegalArgumentException();
                long delay=Math.max(ms.intValue(),headerDelay(retryHeader));
                Action action=code.equals("RUN_BLOCKED")?Action.BLOCKED:Set.of("RUN_NOT_READY","REFERENCE_NOT_READY").contains(code)?Action.DEPENDENCY:Action.RETRY;
                return new Decision(action,code,delay,n);
            }
            throw new IllegalArgumentException();
        } catch(RuntimeException mismatch) {return new Decision(Action.CONFIG,"INVALID_APPLICATION_RESULT",0,n);}
    }
    private static Decision temporary(int http,byte[] raw,String header) {
        try {return new Decision(Action.RETRY,http==200?"MALFORMED_RESPONSE":"HTTP_"+http,headerDelay(header),preview(http,raw));}
        catch(RuntimeException invalid) {return new Decision(Action.CONFIG,"INVALID_RETRY_AFTER",0,preview(http,raw));}
    }
    private static String text(JsonNode n,String field) {var v=n.get(field);if(v==null || !v.isString()) throw new IllegalArgumentException();return v.stringValue();}
    private static void nil(JsonNode n,String field) {if(!n.get(field).isNull()) throw new IllegalArgumentException();}
    private static long headerDelay(String value) {
        if(value==null) return 0;
        if(!value.matches("[0-9]{1,8}")) throw new IllegalArgumentException();long seconds=Long.parseLong(value);if(seconds<1 || seconds>30) throw new IllegalArgumentException();return seconds*1000;
    }
    private static JsonNode preview(int http,byte[] raw) {
        return Protocol.JSON.valueToTree(Map.of("httpStatus",http,"bodyPreview",new String(Arrays.copyOf(raw,Math.min(raw.length,1024)),StandardCharsets.UTF_8),"previewTruncated",raw.length>1024));
    }
    public static long delay(int failures,long requested,double jitter) {
        if(failures<1 || failures>20 || requested<0 || requested>30000 || jitter<0 || jitter>1) throw new IllegalArgumentException();
        long base=Math.min(500L<<(failures-1),30000L);return Math.max(requested,Math.min(30000L,base+(long)(base*0.1*jitter)));
    }
}
