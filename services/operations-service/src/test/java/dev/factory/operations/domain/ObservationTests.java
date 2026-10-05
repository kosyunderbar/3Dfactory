package dev.factory.operations.domain;

import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class ObservationTests {
    @Test void freshnessBoundariesClockLeadAndNoDataAreExplicit() {
        Instant now=Instant.parse("2026-10-05T09:00:00.000Z");
        for(var pair:Map.of(2999,"FRESH",3000,"STALE",9999,"STALE",10000,"EXPIRED").entrySet())
            assertThat(Observation.freshness(now,now.minusMillis(pair.getKey()),false).get("state")).isEqualTo(pair.getValue());
        assertThat(Observation.freshness(now,null,false).get("sourceAgeMs")).isNull();
        assertThat(Observation.freshness(now,now.plusMillis(5001),false).get("state")).isEqualTo("UNKNOWN");
        assertThat(Observation.freshness(now,now.minusSeconds(20),true).get("state")).isEqualTo("ARCHIVED");
    }
    @Test void statusPriorityDoesNotInventLiveOrConfirmedFinish() {
        Instant now=Instant.parse("2026-10-05T09:00:00.000Z");var d=Observation.unavailable("run-20261005-unit","simulator-01");var fresh=Observation.freshness(now,now,false);
        assertThat(Observation.status("ACTIVE",false,false,false,null,fresh,d,now)).isEqualTo("WAITING");
        assertThat(Observation.status("ACTIVE",false,true,false,"RUNNING",fresh,d,now)).isEqualTo("RESTORING");
        assertThat(Observation.status("ACTIVE",false,true,true,"RUNNING",fresh,d,now)).isEqualTo("UNKNOWN");
        assertThat(Observation.finished(5L,d)).isFalse();d.put("diagnosticState","AVAILABLE");d.put("pendingCount",0);d.put("nextSourceSeq",6);d.put("sourceConnected",true);d.put("streamState","ACTIVE");
        assertThat(Observation.finished(5L,d)).isTrue();
        assertThat(Observation.status("BLOCKED",true,true,true,"FINISHED",fresh,d,now)).isEqualTo("BLOCKED");
        assertThat(Observation.status("ACTIVE",true,true,true,"FINISHED",fresh,d,now)).isEqualTo("FINISHED");
        assertThat(Observation.status("ACTIVE",false,true,true,"RUNNING",fresh,d,now)).isEqualTo("LIVE");
        d.put("pendingCount",1);d.put("oldestPendingReceivedAt",EventSyntax.time(now.minusMillis(999)));
        assertThat(Observation.status("ACTIVE",false,true,true,"PAUSED",fresh,d,now)).isEqualTo("PAUSED");
        d.put("oldestPendingReceivedAt",EventSyntax.time(now.minusMillis(1000)));
        assertThat(Observation.status("ACTIVE",false,true,true,"PAUSED",fresh,d,now)).isEqualTo("CATCHING_UP");
        d.put("diagnosticState","UNAVAILABLE");d.put("streamState","PAUSED_GAP");
        assertThat(Observation.status("ACTIVE",false,true,true,"RUNNING",fresh,d,now)).isEqualTo("BLOCKED");
    }
}
