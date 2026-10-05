package dev.factory.operations.domain;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.util.*;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Independent v1 syntax validator, initially based on the S03 contract implementation. No ingestion code/DB dependency. */
public final class EventSyntax {
    private EventSyntax() {}
    public static final JsonMapper JSON = JsonMapper.builder()
        .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).build();
    private static final DateTimeFormatter TIME = new DateTimeFormatterBuilder().appendInstant(3).toFormatter();
    public record Identity(String runId, String sourceId, String eventId, long sourceSeq) {}
    public record Event(Identity identity, String hash, String raw, JsonNode json, Instant occurredAt) {}
    public static final class Invalid extends RuntimeException {
        public final String code;
        public final Identity identity;
        public final String hash;
        public Invalid(String code, Identity identity, String hash) { super(code); this.code=code; this.identity=identity; this.hash=hash; }
    }
    public static String time(Instant value) { return TIME.format(value); }
    public static String hash(byte[] raw) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw)); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    public static Event parse(byte[] bytes) {
        String hash=hash(bytes), raw;
        try { raw=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
        catch(CharacterCodingException e) { throw new Invalid("INVALID_UTF8",null,hash); }
        if(raw.isEmpty() || raw.charAt(0)=='\ufeff' || raw.indexOf('\r')>=0 || raw.indexOf('\n')>=0)
            throw new Invalid("INVALID_FRAME",null,hash);
        JsonNode node;
        try { node=JSON.readTree(raw); }
        catch(RuntimeException e) { throw new Invalid("INVALID_JSON",null,hash); }
        Identity id=null;
        try { id=identity(node); } catch(RuntimeException ignored) { /* All four identifiers remain null. */ }
        try {
            require(node!=null && node.isObject());
            if(node.has("schemaVersion") && node.get("schemaVersion").isIntegralNumber()
                    && node.get("schemaVersion").longValue()!=1) throw new Invalid("UNSUPPORTED_SCHEMA",id,hash);
            object(node,"schemaVersion:one eventId:uuid runId:run sourceId:source sourceSeq:positive eventType:text occurredAt:time payload:object");
            require(id!=null);
            String kind=node.get("eventType").stringValue();
            payload(kind,node.get("payload"));
            return new Event(id,hash,raw,node,timestamp(node.get("occurredAt")));
        } catch(Invalid e) { throw e; }
        catch(RuntimeException e) { throw new Invalid("SCHEMA_INVALID",id,hash); }
    }
    private static Identity identity(JsonNode n) {
        require(n!=null && n.isObject());
        value(n.get("runId"),"run"); value(n.get("sourceId"),"source");
        value(n.get("eventId"),"uuid"); value(n.get("sourceSeq"),"positive");
        return new Identity(n.get("runId").stringValue(),n.get("sourceId").stringValue(),
            n.get("eventId").stringValue(),n.get("sourceSeq").longValue());
    }
    static void require(boolean condition) { if(!condition) throw new IllegalArgumentException("v1 shape/value mismatch"); }
    private static void pattern(JsonNode n,String regex) { require(n!=null && n.isString() && n.stringValue().matches(regex)); }
    public static Instant timestamp(JsonNode n) {
        pattern(n,"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z");
        Instant instant=Instant.parse(n.stringValue()); require(time(instant).equals(n.stringValue())); return instant;
    }
    private static long integer(JsonNode n,long min,long max) {
        require(n!=null && n.isIntegralNumber() && n.canConvertToLong());
        long v=n.longValue(); require(v>=min && v<=max); return v;
    }
    private static void object(JsonNode n,String spec) {
        require(n!=null && n.isObject()); Set<String> fields=new HashSet<>();
        if(!spec.isEmpty()) for(String item:spec.split(" ")) {
            String[] pair=item.split(":",2); fields.add(pair[0]); value(n.get(pair[0]),pair[1]);
        }
        require(fields.equals(new HashSet<>(n.propertyNames())));
    }
    private static void value(JsonNode n,String type) {
        require(n!=null);
        if(type.endsWith("?")) { if(n.isNull()) return; type=type.substring(0,type.length()-1); }
        if(type.startsWith("[")) {
            require(n.isArray()); String child=type.substring(1,type.length()-1);
            for(JsonNode v:n) value(v,child); return;
        }
        if(type.contains("|")) { require(n.isString() && Arrays.asList(type.split("\\|")).contains(n.stringValue())); return; }
        switch(type) {
            case "SCENARIO_CANCEL", "SIM_DEFECT_01", "QC-01" -> pattern(n,type);
            case "text" -> { require(n.isString() && !n.stringValue().isEmpty()); }
            case "object" -> require(n.isObject());
            case "empty" -> object(n,"");
            case "one" -> integer(n,1,1);
            case "zero" -> integer(n,0,9007199254740991L);
            case "positive" -> integer(n,1,9007199254740991L);
            case "seed" -> integer(n,0,2147483647);
            case "capacity" -> integer(n,2,4);
            case "count" -> integer(n,0,4);
            case "maxBodies" -> integer(n,1,100);
            case "number", "probability", "speed" -> {
                require(n.isNumber() && Double.isFinite(n.doubleValue()));
                if(type.equals("probability")) require(n.doubleValue()>=0 && n.doubleValue()<=1);
                if(type.equals("speed")) require(n.doubleValue()==1);
            }
            case "time" -> timestamp(n);
            case "run" -> { pattern(n,"run-[0-9]{8}-[a-z0-9]{3,32}"); LocalDate.parse(n.stringValue().substring(4,12),DateTimeFormatter.BASIC_ISO_DATE); }
            case "source" -> pattern(n,"simulator-[0-9]{2,4}");
            case "uuid" -> pattern(n,"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
            case "body", "tag", "transport", "operation", "inspection", "kit" -> pattern(n,type+"-[0-9]{5,10}");
            case "reserve" -> pattern(n,"reserve-[0-9]{5,10}");
            case "cell" -> pattern(n,"ASM-01|ASM-02|QC-01");
            case "buffer" -> pattern(n,"BAY-(ASM-01|ASM-02|QC-01)");
            case "slot" -> pattern(n,"BAY-(ASM-01|ASM-02|QC-01)-S[1-4]");
            case "vehicle" -> pattern(n,"(AGV|AMR)-[0-9]{3,6}");
            case "route" -> pattern(n,"ROUTE-[A-Z0-9-]{1,48}");
            case "scenario" -> pattern(n,"scenario-[a-z0-9-]{1,40}");
            case "code" -> pattern(n,"[A-Z0-9-]{1,32}");
            case "locationId" -> pattern(n,"BODY-IN|ASM-01|ASM-02|QC-01|BAY-(ASM-01|ASM-02|QC-01)|(AGV|AMR)-[0-9]{3,6}|GOOD|HOLD|PARTS-STORE|PARTS-ASM-0[12]");
            case "point" -> object(n,"x:number y:number");
            case "location" -> object(n,"locationType:INPUT|CELL|BUFFER|VEHICLE|RESULT|STORE|PARTS_DOCK locationId:locationId");
            case "config" -> configuration(n);
            case "equipmentConfig" -> object(n,"cellId:cell equipmentId:cell bufferId:buffer workDurationMs:positive");
            case "bufferConfig" -> object(n,"bufferId:buffer cellId:cell capacity:capacity slotIds:[slot]");
            case "vehicleConfig" -> object(n,"vehicleId:vehicle kind:AGV|AMR home:location initialPosition:point");
            case "routeConfig" -> { object(n,"routeId:route cargoType:BODY|PARTS source:location destination:location points:[point] travelDurationMs:positive"); require(n.get("points").size()>=2); }
            case "configuredLocation" -> object(n,"locationType:INPUT|CELL|BUFFER|RESULT|STORE|PARTS_DOCK locationId:locationId x:number y:number");
            case "equipment" -> object(n,"cellId:cell equipmentId:cell state:IDLE|RUNNING|BLOCKED|DOWN resumeState:IDLE|RUNNING|BLOCKED? bodyId:body? operationId:operation? remainingWorkMs:zero blockedReason:BUFFER_FULL|NO_VEHICLE|WAITING_PICKUP? destinationCellId:cell?");
            case "bufferState" -> object(n,"bufferId:buffer cellId:cell capacity:capacity waitingCount:count reservedInboundCount:count availableSlots:count slots:[slotState]");
            case "slotState" -> object(n,"slotId:slot status:FREE|RESERVED|OCCUPIED bodyId:body? vehicleId:vehicle? transportId:transport? reservationId:reserve?");
            case "bodyState" -> object(n,"bodyId:body tagId:tag modelCode:code specCode:code status:WAITING|PROCESSING|WAITING_UNLOAD|IN_TRANSIT|COMPLETED locationType:INPUT|CELL|BUFFER|VEHICLE|RESULT locationId:locationId locationSlotId:slot? currentCellId:cell? completedCellIds:[cell] nextCellId:cell? transportId:transport? reservationId:reserve? inspectionResult:NOT_INSPECTED|PASS|FAIL inspectedAt:time? lastObservedAt:time");
            case "vehicleState" -> object(n,"vehicleId:vehicle kind:AGV|AMR state:IDLE|TO_PICKUP|LOADING|MOVING|UNLOADING|RETURNING position:point bodyId:body? partsKitId:kit? transportId:transport?");
            case "transportState" -> object(n,"transportId:transport vehicleId:vehicle routeId:route cargoType:BODY|PARTS status:ASSIGNED|IN_TRANSIT|COMPLETED|CANCELLED bodyId:body? partsKitId:kit? source:location destination:location reservationId:reserve? slotId:slot? assignedAt:time startedAt:time? completedAt:time? cancelledAt:time? cancelReason:SCENARIO_CANCEL?");
            default -> throw new IllegalArgumentException("Unknown internal validator type: "+type);
        }
    }
    private static void configuration(JsonNode n) {
        object(n,"tickMs:positive snapshotIntervalMs:positive speed:speed maxBodies:maxBodies failProbability:probability locations:[configuredLocation] equipment:[equipmentConfig] buffers:[bufferConfig] vehicles:[vehicleConfig] routes:[routeConfig]");
        require(n.get("snapshotIntervalMs").longValue()%n.get("tickMs").longValue()==0);
        for(JsonNode b:n.get("buffers")) require(b.get("slotIds").size()==b.get("capacity").intValue());
        // Registration, unique factory IDs and ownership are validated by S04, not reconstructed here.
    }
    private static void payload(String kind,JsonNode p) {
        switch(kind) {
            case "RUN_STARTED" -> object(p,"seed:seed config:config");
            case "RUN_STATE_CHANGED" -> object(p,"previousState:RUNNING|PAUSED|FINISHED state:RUNNING|PAUSED|FINISHED reason:PAUSE_REQUEST|RESUME_REQUEST|DRAINED");
            case "FACTORY_SNAPSHOT" -> object(p,"runState:RUNNING|PAUSED|FINISHED capturedAt:time simElapsedMs:zero equipment:[equipment] buffers:[bufferState] bodies:[bodyState] vehicles:[vehicleState] activeTransports:[transportState]");
            case "BODY_REGISTERED" -> object(p,"bodyId:body tagId:tag modelCode:code specCode:code createdAt:time initialLocation:location");
            case "SLOT_RESERVED" -> object(p,"reservationId:reserve transportId:transport bufferId:buffer slotId:slot bodyId:body vehicleId:vehicle");
            case "SLOT_RELEASED" -> object(p,"bufferId:buffer slotId:slot bodyId:body reservationId:reserve? transportId:transport? reason:BODY_ENTERED_CELL|CANCEL_BEFORE_DEPARTURE");
            case "BODY_ENTERED_CELL" -> object(p,"bodyId:body cellId:cell bufferId:buffer slotId:slot operationId:operation");
            case "EQUIPMENT_STATE_CHANGED" -> object(p,"cellId:cell equipmentId:cell previousState:IDLE|RUNNING|BLOCKED|DOWN state:IDLE|RUNNING|BLOCKED|DOWN bodyId:body? reason:WORK_STARTED|WORK_COMPLETED|BUFFER_FULL|NO_VEHICLE|WAITING_PICKUP|PICKUP_COMPLETED|FAILURE_INJECTED|RECOVERED");
            case "OPERATION_COMPLETED" -> object(p,"operationId:operation cellId:cell equipmentId:cell unitId:body durationMs:zero");
            case "INSPECTION_COMPLETED" -> object(p,"inspectionId:inspection equipmentId:QC-01 unitId:body result:PASS|FAIL defectCode:SIM_DEFECT_01?");
            case "TRANSPORT_ASSIGNED", "TRANSPORT_STARTED", "TRANSPORT_COMPLETED", "TRANSPORT_CANCELLED" -> value(p,"transportState");
            case "SCENARIO_CHANGED" -> {
                object(p,"scenarioId:scenario action:CELL_DOWN|CELL_RECOVER|TRANSPORT_DELAY|QUALITY_PATTERN|CANCEL_BEFORE_DEPARTURE targetId:text parameters:object");
                switch(p.get("action").stringValue()) {
                    case "TRANSPORT_DELAY" -> { value(p.get("targetId"),"transport"); object(p.get("parameters"),"additionalDelayMs:zero"); }
                    case "QUALITY_PATTERN" -> { value(p.get("targetId"),"run"); object(p.get("parameters"),"results:[PASS|FAIL]"); require(!p.get("parameters").get("results").isEmpty()); }
                    case "CELL_DOWN", "CELL_RECOVER" -> { value(p.get("targetId"),"cell"); object(p.get("parameters"),""); }
                    default -> { value(p.get("targetId"),"transport"); object(p.get("parameters"),""); }
                }
            }
            case "TELEMETRY_UPDATED" -> {
                object(p,"entityType:EQUIPMENT|VEHICLE entityId:text measurements:object position:point?");
                if(p.get("entityType").stringValue().equals("VEHICLE")) { value(p.get("entityId"),"vehicle"); value(p.get("position"),"point"); object(p.get("measurements"),""); }
                else {
                    value(p.get("entityId"),"cell"); require(p.get("position").isNull()); JsonNode m=p.get("measurements");
                    require(m.size()>=1 && m.size()<=2);
                    for(String k:m.propertyNames()) switch(k) { case "temperatureC" -> value(m.get(k),"number"); case "cycleTimeMs" -> value(m.get(k),"zero"); default -> require(false); }
                }
            }
            case "RUN_FINISHED" -> object(p,"reason:DRAINED|MODEL_ERROR uniqueEventCount:positive");
            default -> require(false);
        }
    }
}
