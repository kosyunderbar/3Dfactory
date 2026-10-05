package dev.factory.operations.domain;

import java.time.*;
import java.util.*;
import static dev.factory.operations.domain.ReadSupport.map;

/** Time/diagnostic facts, independent of physical state. UNKNOWN never becomes LIVE by assumption. */
public final class Observation {
    private Observation() {}
    public static Map<String,Object> unavailable(String run,String source) {
        var d=map("runId",run,"sourceId",source,"sampledAt",null,"sourceConnected",null,"lastReceivedAt",null,"lastAcceptedSeq",null,"nextSourceSeq",null,"streamState",null,"blockedSeq",null,"blockedCode",null,"pendingCount",null,"pendingBytes",null,"oldestPendingReceivedAt",null,"retryCount",null,"rejectedCount",null,"diagnosticState","UNAVAILABLE"); return d;
    }
    public static Map<String,Object> freshness(Instant now,Instant captured,boolean finished) {
        Long age=captured==null?null:Math.max(0,Duration.between(captured,now).toMillis()),lead=captured==null?null:Math.max(0,Duration.between(now,captured).toMillis());
        String state=captured==null?"NO_DATA":lead>5000?"UNKNOWN":finished?"ARCHIVED":age<3000?"FRESH":age<10000?"STALE":"EXPIRED";
        return map("evaluatedAt",EventSyntax.time(now),"sourceAgeMs",age,"clockLeadMs",lead,"state",state,"staleAfterMs",3000,"disconnectAfterMs",10000);
    }
    public static boolean available(Map<String,Object> delivery) { return "AVAILABLE".equals(delivery.get("diagnosticState")); }
    public static boolean finished(Long finishedSeq,Map<String,Object> d) { return finishedSeq!=null && available(d) && ((Number)d.get("pendingCount")).longValue()==0 && ((Number)d.get("nextSourceSeq")).longValue()>finishedSeq; }
    public static boolean blocked(String state,Map<String,Object> d) { String stream=(String)d.get("streamState"); return state.equals("BLOCKED") || stream!=null && (stream.equals("BLOCKED") || stream.startsWith("PAUSED_")); }
    public static String status(String processing,boolean finished,boolean snapshot,boolean observed,String runState,Map<String,Object> f,Map<String,Object> d,Instant now) {
        if(blocked(processing,d)) return "BLOCKED";
        if(finished) return "FINISHED";
        if(!snapshot) return "WAITING";
        if(!observed) return "RESTORING";
        if(!available(d) || f.get("state").equals("UNKNOWN")) return "UNKNOWN";
        if(Boolean.FALSE.equals(d.get("sourceConnected")) || f.get("state").equals("EXPIRED")) return "DISCONNECTED";
        if(f.get("state").equals("STALE")) return "STALE";
        boolean lag=d.get("pendingCount")!=null && ((Number)d.get("pendingCount")).longValue()>0 && d.get("oldestPendingReceivedAt")!=null && Duration.between(Instant.parse((String)d.get("oldestPendingReceivedAt")),now).toMillis()>=1000;
        if(lag || Set.of("RETRY_WAIT","GAP_WAIT").contains(String.valueOf(d.get("streamState")))) return "CATCHING_UP";
        if("PAUSED".equals(runState)) return "PAUSED";
        return "LIVE";
    }
}
