package dev.factory.ingestion.receiver;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
class TrafficContractTests {
    @Test void optionalTrafficExtensionAndLegacyEventsHaveStrictShapes() throws Exception {
        for(String file:new String[]{"factory-scenario.ndjson","traffic-scenario.ndjson","direct-delivery-scenario.ndjson","lane-traffic-scenario.ndjson","lane-traffic-v4-scenario.ndjson","parts-supply-scenario.ndjson"})
            for(String line:Files.readAllLines(Path.of("src/test/resources/"+file)))
                assertThatCode(()->Protocol.parse(line.getBytes(StandardCharsets.UTF_8))).doesNotThrowAnyException();
        for(String line:Files.readAllLines(Path.of("src/test/resources/traffic-scenario.ndjson"))) {
            if(line.contains("PRIORITY_REDISPATCH"))
                assertThatThrownBy(()->Protocol.parse(line.replace("PRIORITY_REDISPATCH","UNKNOWN").getBytes(StandardCharsets.UTF_8))).isInstanceOf(Protocol.Invalid.class);
            for(String changed:new String[]{line.replace("\"vehicleRadius\":24", "\"vehicleRadius\":1"),line.replace("\"waiting\":false", "\"waiting\":1"),line.replace("\"elapsedMs\":", "\"unknown\":")})
                if(!changed.equals(line)) assertThatThrownBy(()->Protocol.parse(changed.getBytes(StandardCharsets.UTF_8))).isInstanceOf(Protocol.Invalid.class);
        }
    }
}
