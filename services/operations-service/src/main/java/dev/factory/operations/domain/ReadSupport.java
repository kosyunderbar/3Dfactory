package dev.factory.operations.domain;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import static dev.factory.operations.domain.ModelRules.text;

public final class ReadSupport {
    private ReadSupport() {}
    public static Map<String,Object> map(Object... pairs) {
        var result=new LinkedHashMap<String,Object>(); for(int i=0;i<pairs.length;i+=2) result.put((String)pairs[i],pairs[i+1]); return result;
    }
    public static String time(Object value) { return value==null?null:EventSyntax.time(((Timestamp)value).toInstant()); }
    public static Map<String,Object> quality(JdbcTemplate jdbc,String run,Instant from,Instant to) {
        String sql="SELECT count(*) AS n,count(*) FILTER(WHERE result='PASS') AS pass,count(*) FILTER(WHERE result='FAIL') AS fail FROM inspection_result WHERE run_id=?";
        Object[] args=from==null?new Object[]{run}:new Object[]{run,Timestamp.from(from),Timestamp.from(to)};
        if(from!=null) sql+=" AND inspected_at>=? AND inspected_at<?";
        var row=jdbc.queryForMap(sql,args); long n=((Number)row.get("n")).longValue(),pass=((Number)row.get("pass")).longValue(),fail=((Number)row.get("fail")).longValue();
        return map("inspectedCount",n,"passCount",pass,"failCount",fail,"failRate",n==0?null:(double)fail/n);
    }
    public static Map<String,Object> event(Map<String,Object> row) {
        return map("eventId",row.get("event_id").toString(),"sourceSeq",row.get("source_seq"),"eventType",row.get("type"),"occurredAt",time(row.get("occurred_at")),"receivedAt",time(row.get("received_at")),"appliedAt",time(row.get("applied_at")),"cellId",row.get("cell_id"),"bodyId",row.get("body_id"),"vehicleId",row.get("vehicle_id"),"payload",EventSyntax.JSON.readTree(row.get("payload").toString()));
    }
    public static Map<String,Object> alarm(Map<String,Object> row,Instant asOf) {
        Object resolved=row.get("resolved_at"),ack=row.get("acknowledged_at");
        if(resolved!=null && ((Timestamp)resolved).toInstant().isAfter(asOf)) resolved=null;
        if(ack!=null && ((Timestamp)ack).toInstant().isAfter(asOf)) ack=null;
        return map("alarmId",row.get("alarm_id").toString(),"runId",row.get("run_id"),"type",row.get("type"),"severity",row.get("severity"),"targetId",row.get("target_id"),"occurredAt",time(row.get("occurred_at")),"conditionActive",resolved==null,"resolvedAt",time(resolved),"acknowledgedAt",time(ack),"acknowledgedBy",ack==null?null:row.get("acknowledged_by"),"message",row.get("message"));
    }
}
