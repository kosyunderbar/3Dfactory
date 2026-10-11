package dev.factory.operations.domain;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
class TrafficContractTests {
    @Test void directDeliveryConfigurationAndOwnershipSnapshotsAreConsistent() throws Exception {
        var events=Files.readAllLines(Path.of("src/test/resources/direct-delivery-scenario.ndjson")).stream()
            .map(s->EventSyntax.parse(s.getBytes(StandardCharsets.UTF_8))).toList();
        var config=events.getFirst().json().get("payload").get("config");
        ModelRules.configuration(config);
        var registered=new java.util.HashMap<String,tools.jackson.databind.JsonNode>();
        for(var event:events) {
            var p=event.json().get("payload");
            switch(event.json().get("eventType").stringValue()) {
                case "BODY_REGISTERED" -> registered.put(p.get("bodyId").stringValue(),p);
                case "FACTORY_SNAPSHOT" -> ModelRules.snapshot(p,config,registered);
                case "TRANSPORT_ASSIGNED","TRANSPORT_STARTED","TRANSPORT_COMPLETED","TRANSPORT_CANCELLED" -> ModelRules.transport(p,config);
            }
        }
    }
    @Test void partsInventoryMatchesBodyConsumptionAndActiveAmrDeliveries() throws Exception {
        var lines=Files.readAllLines(Path.of("src/test/resources/parts-supply-scenario.ndjson"));
        var config=EventSyntax.parse(lines.get(0).getBytes(StandardCharsets.UTF_8)).json().get("payload").get("config");
        ModelRules.configuration(config);
        var registered=new java.util.HashMap<String,tools.jackson.databind.JsonNode>();
        for(String line:lines) {
            var event=EventSyntax.parse(line.getBytes(StandardCharsets.UTF_8)).json();
            var p=event.get("payload");
            if(event.get("eventType").stringValue().equals("BODY_REGISTERED")) registered.put(p.get("bodyId").stringValue(),p);
            if(event.get("eventType").stringValue().equals("FACTORY_SNAPSHOT")) {
                ModelRules.snapshot(p,config,registered);
                var bad=p.deepCopy();
                ((tools.jackson.databind.node.ObjectNode)bad.get("partsSupply").get(0)).put("inbound",99);
                assertThatThrownBy(()->ModelRules.snapshot(bad,config,registered)).isInstanceOf(RuntimeException.class);
                assertThatThrownBy(()->EventSyntax.parse(line.replace("\"capacity\":2", "\"capacity\":0").getBytes(StandardCharsets.UTF_8))).isInstanceOf(EventSyntax.Invalid.class);
            }
        }
    }
    @Test void priorityCancellationRequiresTrafficAndRejectsUnknownReason() throws Exception {
        var lines=Files.readAllLines(Path.of("src/test/resources/traffic-scenario.ndjson"));
        var config=EventSyntax.parse(lines.get(0).getBytes(StandardCharsets.UTF_8)).json().get("payload").get("config");
        String cancellation=lines.stream().filter(s->s.contains("\"eventType\":\"TRANSPORT_CANCELLED\"")).findFirst().orElseThrow();
        var trip=EventSyntax.parse(cancellation.getBytes(StandardCharsets.UTF_8)).json().get("payload");
        assertThatCode(()->ModelRules.transport(trip,config)).doesNotThrowAnyException();
        var legacy=config.deepCopy();
        ((tools.jackson.databind.node.ObjectNode)legacy).remove("traffic");
        assertThatThrownBy(()->ModelRules.transport(trip,legacy)).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(()->EventSyntax.parse(cancellation.replace("PRIORITY_REDISPATCH","UNKNOWN").getBytes(StandardCharsets.UTF_8))).isInstanceOf(EventSyntax.Invalid.class);
    }
    @Test void optionalTrafficExtensionAndLegacyEventsHaveStrictShapes() throws Exception {
        for(String file:new String[]{"factory-scenario.ndjson","traffic-scenario.ndjson","direct-delivery-scenario.ndjson","lane-traffic-scenario.ndjson","lane-traffic-v4-scenario.ndjson","parts-supply-scenario.ndjson"})
            for(String line:Files.readAllLines(Path.of("src/test/resources/"+file)))
                assertThatCode(()->EventSyntax.parse(line.getBytes(StandardCharsets.UTF_8))).doesNotThrowAnyException();
        for(String line:Files.readAllLines(Path.of("src/test/resources/traffic-scenario.ndjson"))) {
            for(String changed:new String[]{line.replace("\"vehicleRadius\":24", "\"vehicleRadius\":1"),line.replace("\"waiting\":false", "\"waiting\":1"),line.replace("\"elapsedMs\":", "\"unknown\":")})
                if(!changed.equals(line)) assertThatThrownBy(()->EventSyntax.parse(changed.getBytes(StandardCharsets.UTF_8))).isInstanceOf(EventSyntax.Invalid.class);
        }
    }
}
