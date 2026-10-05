package dev.factory.ingestion.delivery;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.Test;
import dev.factory.ingestion.receiver.Protocol;
import static org.assertj.core.api.Assertions.*;
import static dev.factory.ingestion.delivery.DeliveryStore.map;

class DeliveryWireTests {
    @Test void replyCorrelationStatusTimeAndBoundedBackoff(){
        var id=new Protocol.Identity("run-20261005-wire","simulator-01",UUID.randomUUID().toString(),1);
        var head=new DeliveryStore.Head(id,"{}",Protocol.hash("{}".getBytes(StandardCharsets.UTF_8)),Instant.parse("2026-10-05T09:00:00.000Z"),1,1);
        var body=map("protocolVersion",1,"kind","APPLICATION_RESULT","runId",id.runId(),"sourceId",id.sourceId(),"eventId",id.eventId(),"sourceSeq",1,"eventSha256",head.hash(),"status","APPLIED","code","OK","appliedAt",Protocol.time(head.received()),"recordedAt",Protocol.time(head.received()),"retryAfterMs",null);
        assertThat(classify(head,200,body,null).action()).isEqualTo(DeliveryWire.Action.DELIVERED);
        body.put("status","DUPLICATE_APPLIED");assertThat(classify(head,200,body,null).action()).isEqualTo(DeliveryWire.Action.DELIVERED);
        body.put("eventId",UUID.randomUUID().toString());assertThat(classify(head,200,body,null).action()).isEqualTo(DeliveryWire.Action.CONFIG);body.put("eventId",id.eventId());
        body.put("status","REJECTED");body.put("code","MODEL_INVALID");body.put("appliedAt",null);assertThat(classify(head,422,body,null).action()).isEqualTo(DeliveryWire.Action.QUARANTINED);
        assertThat(classify(head,200,body,null).action()).isEqualTo(DeliveryWire.Action.CONFIG);
        body.put("status","RETRY_LATER");body.put("code","REFERENCE_NOT_READY");body.put("recordedAt",null);body.put("retryAfterMs",500);
        assertThat(classify(head,409,body,"1").delayMs()).isEqualTo(1000);assertThat(classify(head,409,body,"1").action()).isEqualTo(DeliveryWire.Action.DEPENDENCY);
        assertThat(classify(head,409,body,"31").action()).isEqualTo(DeliveryWire.Action.CONFIG);
        body.put("retryAfterMs",30001);assertThat(classify(head,409,body,null).action()).isEqualTo(DeliveryWire.Action.CONFIG);
        assertThat(DeliveryWire.classify(head,200,"{bad".getBytes(StandardCharsets.UTF_8),null,true).action()).isEqualTo(DeliveryWire.Action.RETRY);
        assertThat(DeliveryWire.classify(head,503,new byte[0],null,false).action()).isEqualTo(DeliveryWire.Action.RETRY);
        for(int i=1;i<=20;i++){long base=Math.min(500L<<(i-1),30000L);assertThat(DeliveryWire.delay(i,0,0)).isEqualTo(base);assertThat(DeliveryWire.delay(i,0,1)).isBetween(base,30000L);}
        assertThat(DeliveryWire.delay(1,10000,0)).isEqualTo(10000);
    }
    private DeliveryWire.Decision classify(DeliveryStore.Head head,int http,Map<String,Object> body,String header){return DeliveryWire.classify(head,http,Protocol.JSON.writeValueAsBytes(body),header,true);}
}
