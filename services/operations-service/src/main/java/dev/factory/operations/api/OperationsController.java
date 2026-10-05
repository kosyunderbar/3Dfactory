package dev.factory.operations.api;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.*;
import java.time.*;
import java.util.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import dev.factory.operations.domain.*;
import static dev.factory.operations.domain.ReadSupport.map;

@RestController
@Profile("!bootstrap")
public class OperationsController {
    private final EventApplication events;
    private final HistoryQueries history;
    private final ViewPublisher views;
    private final JdbcTemplate jdbc;
    private final AlarmService alarms;
    private final TransactionTemplate tx;
    public OperationsController(EventApplication events,HistoryQueries history,ViewPublisher views,JdbcTemplate jdbc,AlarmService alarms,TransactionTemplate tx) {this.events=events;this.history=history;this.views=views;this.jdbc=jdbc;this.alarms=alarms;this.tx=tx;}
    @PostMapping("/internal/v1/events/apply")
    public ResponseEntity<EventApplication.Result> apply(HttpServletRequest request) {
        EventSyntax.Event event=null;
        try {
            media(request); byte[] bytes=read(request,524288); JsonNode n=parse(bytes);
            if(n==null || !n.isObject() || !new HashSet<>(n.propertyNames()).equals(Set.of("protocolVersion","rawEvent","eventSha256","receivedAt"))) return reply(EventApplication.response(null,400,"REJECTED","INVALID_DELIVERY",null,null));
            if(!n.get("protocolVersion").isIntegralNumber() || !n.get("protocolVersion").canConvertToInt() || n.get("protocolVersion").intValue()!=1) return reply(EventApplication.response(null,400,"REJECTED","UNSUPPORTED_PROTOCOL",null,null));
            if(!n.get("rawEvent").isString() || !n.get("eventSha256").isString()) throw new IllegalArgumentException();
            var encoded=StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(n.get("rawEvent").stringValue()));
            byte[] raw=new byte[encoded.remaining()];encoded.get(raw);Instant received;
            try {received=EventSyntax.timestamp(n.get("receivedAt"));}catch(RuntimeException bad){throw new IllegalArgumentException(bad);}
            if(raw.length<1 || raw.length>65535 || !EventSyntax.hash(raw).equals(n.get("eventSha256").stringValue())) throw new IllegalArgumentException();
            try {event=EventSyntax.parse(raw);}
            catch(EventSyntax.Invalid invalid) {
                if(invalid.identity==null) return reply(EventApplication.response(null,400,"REJECTED","INVALID_DELIVERY",null,null));
                // Original IDs and bytes are retained; rejection projection has no guessed business references.
                var fallback=EventSyntax.JSON.createObjectNode();fallback.put("eventType","INVALID_EVENT");fallback.set("payload",EventSyntax.JSON.createObjectNode());
                event=new EventSyntax.Event(invalid.identity,invalid.hash,n.get("rawEvent").stringValue(),fallback,received);
                return reply(events.rejectInvalid(event,received));
            }
            return reply(events.apply(event,received));
        } catch(ApiProblem p) {return reply(EventApplication.response(event,p.http,"REJECTED",p.code.equals("PAYLOAD_TOO_LARGE")?"DELIVERY_TOO_LARGE":p.code,null,null));}
        catch(IOException | IllegalArgumentException bad) {return reply(EventApplication.response(null,400,"REJECTED","INVALID_DELIVERY",null,null));}
        catch(RuntimeException unavailable) {return reply(EventApplication.response(event,503,"RETRY_LATER","DB_UNAVAILABLE",null,null));}
    }
    private ResponseEntity<EventApplication.Result> reply(EventApplication.Reply reply) {var builder=ResponseEntity.status(reply.http()).cacheControl(CacheControl.noStore());if(reply.body().retryAfterMs()!=null) builder.header("Retry-After",String.valueOf((reply.body().retryAfterMs()+999)/1000));return builder.body(reply.body());}
    @GetMapping("/api/v1/factory/layout") public Map<String,Object> layout(@RequestParam Map<String,String> q) {HistoryQueries.fields(q,"runId");return history.layout(q.get("runId"));}
    @GetMapping("/api/v1/runs") public Map<String,Object> runs(@RequestParam Map<String,String> q) {return history.page("runs",null,q);}
    @GetMapping("/api/v1/runs/{run}/snapshot") public Map<String,Object> snapshot(@PathVariable String run,@RequestParam Map<String,String> q) {HistoryQueries.fields(q,"");HistoryQueries.runId(run);return views.current(run);}
    @GetMapping("/api/v1/runs/{run}/{collection:equipment|buffers|bodies|vehicles}/{id}") public Map<String,Object> detail(@PathVariable String run,@PathVariable String collection,@PathVariable String id,@RequestParam Map<String,String> q) {
        HistoryQueries.fields(q,"");history.exists(run);String table=switch(collection){case "equipment"->"equipment";case "buffers"->"factory_buffer";case "bodies"->"body";default->"vehicle";};String column=switch(collection){case "equipment"->"equipment_id";case "buffers"->"buffer_id";case "bodies"->"body_id";default->"vehicle_id";};
        if(jdbc.queryForObject("SELECT count(*) FROM "+table+" WHERE run_id=? AND "+column+"=?",Long.class,run,id)==0) throw new ApiProblem(404,"RESOURCE_NOT_FOUND");
        var view=views.current(run);JsonNode data=EventSyntax.JSON.valueToTree(view.get(collection));Object item=null;String field=switch(collection){case "equipment"->"equipmentId";case "buffers"->"bufferId";case "bodies"->"bodyId";default->"vehicleId";};
        for(var node:data) if(id.equals(ModelRules.text(node,field))) {item=node;break;}var result=envelope(view);result.put("data",item);return result;
    }
    @GetMapping("/api/v1/runs/{run}/tags/{tag}/body") public Map<String,Object> tag(@PathVariable String run,@PathVariable String tag,@RequestParam Map<String,String> q) {history.exists(run);var bodies=jdbc.queryForList("SELECT body_id FROM body WHERE run_id=? AND tag_id=?",String.class,run,tag);if(bodies.isEmpty()) throw new ApiProblem(404,"RESOURCE_NOT_FOUND");return detail(run,"bodies",bodies.getFirst(),q);}
    @GetMapping("/api/v1/runs/{run}/events") public Map<String,Object> eventPage(@PathVariable String run,@RequestParam Map<String,String> q) {return history.page("events",run,q);}
    @GetMapping("/api/v1/runs/{run}/alarms") public Map<String,Object> alarmPage(@PathVariable String run,@RequestParam Map<String,String> q) {return history.page("alarms",run,q);}
    @GetMapping("/api/v1/runs/{run}/quality") public Map<String,Object> quality(@PathVariable String run,@RequestParam Map<String,String> q) {history.exists(run);return history.qualityPage(run,q,delivery(run));}
    @GetMapping("/api/v1/runs/{run}/trends") public Map<String,Object> trends(@PathVariable String run,@RequestParam Map<String,String> q) {history.exists(run);return history.trends(run,q,delivery(run));}
    @GetMapping("/api/v1/system/status") public Map<String,Object> status(@RequestParam Map<String,String> q) {HistoryQueries.fields(q,"runId");String run=q.get("runId");history.exists(run);var status=views.currentStatus(run);var v=status.view();var result=envelope(v);result.put("data",map("operationsState",status.operationsState(),"delivery",v.get("delivery")));return result;}
    @PostMapping("/api/v1/alarms/{alarm}/acknowledge") public Map<String,Object> acknowledge(@PathVariable String alarm,HttpServletRequest request,@RequestParam Map<String,String> q) throws IOException {
        HistoryQueries.fields(q,"");if(!alarm.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")) throw new ApiProblem(400,"INVALID_BODY");
        media(request);JsonNode n;try {n=parse(read(request,1024));if(n==null || !n.isObject() || !new HashSet<>(n.propertyNames()).equals(Set.of("operatorId")) || !n.get("operatorId").isString() || !n.get("operatorId").stringValue().matches("[a-zA-Z0-9_-]{1,64}")) throw new IllegalArgumentException();}
        catch(ApiProblem p){throw p;}catch(RuntimeException e){throw new ApiProblem(400,"INVALID_BODY");}return alarms.acknowledge(alarm,n.get("operatorId").stringValue(),tx);
    }
    @SuppressWarnings("unchecked") private Map<String,Object> delivery(String run) {return (Map<String,Object>)views.current(run).get("delivery");}
    private Map<String,Object> envelope(Map<String,Object> view) {var result=new LinkedHashMap<String,Object>();for(String k:List.of("schemaVersion","runId","sourceId","serverEpoch","revision","publishedAt","viewAsOfAt","snapshotCapturedAt","sourceSeq","runState","simElapsedMs","observedAfterEpoch","dataStatus","freshness","delivery")) result.put(k,view.get(k));return result;}
    private static void media(HttpServletRequest r) {try {var media=MediaType.parseMediaType(r.getContentType());if(!media.getType().equalsIgnoreCase("application") || !media.getSubtype().equalsIgnoreCase("json")|| media.getCharset()!=null&&!media.getCharset().equals(StandardCharsets.UTF_8)||r.getHeader("Content-Encoding")!=null&&!r.getHeader("Content-Encoding").equals("identity")) throw new IllegalArgumentException();}catch(RuntimeException e){throw new ApiProblem(415,"UNSUPPORTED_MEDIA_TYPE");}}
    private static byte[] read(HttpServletRequest r,int max) throws IOException {if(r.getContentLengthLong()>max) throw new ApiProblem(413,"PAYLOAD_TOO_LARGE");byte[] bytes=r.getInputStream().readNBytes(max+1);if(bytes.length>max) throw new ApiProblem(413,"PAYLOAD_TOO_LARGE");return bytes;}
    private static JsonNode parse(byte[] bytes) {try {String raw=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();if(raw.startsWith("\ufeff"))throw new IllegalArgumentException();return EventSyntax.JSON.readTree(raw);}catch(CharacterCodingException | RuntimeException e){throw new IllegalArgumentException(e);}}
}
