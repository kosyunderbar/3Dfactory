package dev.factory.ingestion.delivery;

import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.springframework.http.MediaType;
import dev.factory.ingestion.receiver.Protocol;

/** No database connection or transaction is retained by this HTTP call. */
public final class OperationsClient {
    private final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofMillis(1000)).followRedirects(HttpClient.Redirect.NEVER).build();
    private final URI endpoint;
    public OperationsClient(String base) {
        var uri=URI.create(base);if(!Set.of("http","https").contains(uri.getScheme()) || uri.getHost()==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null) throw new IllegalArgumentException("Invalid operations base URL");
        endpoint=URI.create(base.replaceAll("/$","")+"/internal/v1/events/apply");
    }
    public DeliveryWire.Decision apply(DeliveryStore.Head head) {
        long start=dev.factory.ingestion.measurement.Measurements.start();
        DeliveryWire.Decision reply=applyInternal(head);
        var id=head.identity();
        dev.factory.ingestion.measurement.Measurements.record("delivery-http",id.runId(),id.eventId(),id.sourceSeq(),reply.action().name(),start);
        return reply;
    }
    private DeliveryWire.Decision applyInternal(DeliveryStore.Head head) {
        var envelope=new LinkedHashMap<String,Object>();envelope.put("protocolVersion",1);envelope.put("rawEvent",head.raw());envelope.put("eventSha256",head.hash());envelope.put("receivedAt",Protocol.time(head.received()));
        byte[] body=Protocol.JSON.writeValueAsBytes(envelope);
        if(body.length>524288) return new DeliveryWire.Decision(DeliveryWire.Action.CONFIG,"DELIVERY_TOO_LARGE",0,null);
        try {
            var response=client.sendAsync(HttpRequest.newBuilder(endpoint).timeout(Duration.ofMillis(5000)).header("Content-Type","application/json; charset=utf-8").POST(HttpRequest.BodyPublishers.ofByteArray(body)).build(),info->new LimitedBody());
            HttpResponse<byte[]> result;
            try {result=response.get(5000,TimeUnit.MILLISECONDS);}finally {if(!response.isDone()) response.cancel(true);}
            boolean json=false;
            try {var media=MediaType.parseMediaType(result.headers().firstValue("Content-Type").orElse(""));json=media.getType().equalsIgnoreCase("application") && media.getSubtype().equalsIgnoreCase("json") && (media.getCharset()==null || media.getCharset().equals(StandardCharsets.UTF_8));}catch(RuntimeException ignored){}
            return DeliveryWire.classify(head,result.statusCode(),result.body(),result.headers().firstValue("Retry-After").orElse(null),json);
        }catch(InterruptedException interrupted){Thread.currentThread().interrupt();return DeliveryWire.retry("DELIVERY_INTERRUPTED");}
        catch(Exception failure){return DeliveryWire.retry("HTTP_UNCONFIRMED");}
    }
}
