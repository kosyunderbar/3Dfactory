package dev.factory.operations.domain;

import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import static dev.factory.operations.domain.ModelRules.text;
import static dev.factory.operations.domain.ReadSupport.*;

/** Alarm confirmation never changes the physical condition, model snapshot or transport reservation. */
public final class AlarmService {
    private final JdbcTemplate jdbc;
    private final Clock clock;
    public AlarmService(JdbcTemplate jdbc,Clock clock) { this.jdbc=jdbc;this.clock=clock; }
    public void physical(String run,JsonNode snapshot,Instant now) {
        Instant captured=EventSyntax.timestamp(snapshot.get("capturedAt"));
        if(Duration.between(captured,now).toMillis()>=3000 || captured.isAfter(now.plusMillis(5000))) return;
        for(var cell:snapshot.get("equipment")) condition(run,text(cell,"cellId"),"EQUIPMENT_DOWN",text(cell,"state").equals("DOWN"),now);
        for(var bay:snapshot.get("buffers")) condition(run,text(bay,"bufferId"),"BUFFER_FULL",bay.get("availableSlots").intValue()==0,now);
    }
    public void observation(String run,String source,String processing,boolean finished,boolean observed,Map<String,Object> freshness,Map<String,Object> delivery,Instant now) {
        condition(run,run,"PROCESSING_BLOCKED",Observation.blocked(processing,delivery),now);
        if(finished) { condition(run,source,"SOURCE_STALE",false,now); condition(run,source,"SOURCE_DISCONNECTED",false,now); return; }
        if(!observed || Set.of("NO_DATA","UNKNOWN","ARCHIVED").contains((String)freshness.get("state"))) return;
        String state=(String)freshness.get("state");
        condition(run,source,"SOURCE_STALE",Set.of("STALE","EXPIRED").contains(state),now);
        if(state.equals("EXPIRED")) condition(run,source,"SOURCE_DISCONNECTED",true,now);
        else if(Observation.available(delivery)) condition(run,source,"SOURCE_DISCONNECTED",Boolean.FALSE.equals(delivery.get("sourceConnected")),now);
        // Missing diagnostic samples never prove a physical recovery or disconnection.
    }
    private void condition(String run,String target,String type,boolean active,Instant now) {
        var existing=jdbc.queryForList("SELECT alarm_id FROM alarm WHERE run_id=? AND target_id=? AND type=? AND resolved_at IS NULL",run,target,type);
        if(active) {
            if(existing.isEmpty()) jdbc.update("INSERT INTO alarm(alarm_id,run_id,target_id,type,severity,occurred_at,last_observed_at,message) VALUES (?::uuid,?,?,?,?,?,?,?)",UUID.randomUUID().toString(),run,target,type,Set.of("EQUIPMENT_DOWN","SOURCE_DISCONNECTED","PROCESSING_BLOCKED").contains(type)?"CRITICAL":"WARNING",Timestamp.from(now),Timestamp.from(now),message(type));
            else jdbc.update("UPDATE alarm SET last_observed_at=? WHERE alarm_id=?",Timestamp.from(now),existing.getFirst().get("alarm_id"));
        } else if(!existing.isEmpty()) jdbc.update("UPDATE alarm SET resolved_at=?,last_observed_at=? WHERE alarm_id=?",Timestamp.from(now),Timestamp.from(now),existing.getFirst().get("alarm_id"));
    }
    private String message(String type) { return switch(type) { case "EQUIPMENT_DOWN"->"셀 고장 상태가 확인되었습니다."; case "BUFFER_FULL"->"대기와 예약으로 버퍼의 모든 슬롯이 사용 중입니다."; case "SOURCE_STALE"->"공장 상태 보고가 3초 이상 오래되었습니다."; case "SOURCE_DISCONNECTED"->"공장 연결 또는 10초 상태 보고를 확인해야 합니다."; default->"사건 업무 처리가 중단되었습니다."; }; }
    public Map<String,Object> acknowledge(String alarm,String operator,TransactionTemplate tx) {
        return tx.execute(status->{
            var rows=jdbc.queryForList("SELECT run_id FROM alarm WHERE alarm_id=?::uuid",alarm);
            if(rows.isEmpty()) throw new dev.factory.operations.api.ApiProblem(404,"RESOURCE_NOT_FOUND");
            String run=rows.getFirst().get("run_id").toString(); jdbc.queryForList("SELECT pg_advisory_xact_lock(hashtextextended(?,7304001))",run);
            Instant now=clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MILLIS); jdbc.update("UPDATE alarm SET acknowledged_at=?,acknowledged_by=? WHERE alarm_id=?::uuid AND acknowledged_at IS NULL",Timestamp.from(now),operator,alarm);
            return map("schemaVersion",1,"runId",run,"viewAsOfAt",EventSyntax.time(now),"alarm",alarm(jdbc.queryForMap("SELECT * FROM alarm WHERE alarm_id=?::uuid",alarm),now));
        });
    }
}
