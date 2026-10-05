package dev.factory.operations.domain;

import java.util.*;
import tools.jackson.databind.JsonNode;
import static dev.factory.operations.domain.RuleViolation.*;

/** Internal consistency of a complete report. Never recompute or move physical factory objects. */
public final class ModelRules {
    public static final List<String> CELLS=List.of("ASM-01","ASM-02","QC-01");
    private ModelRules() {}
    public static String text(JsonNode n,String key) { JsonNode v=n.get(key); return v==null||v.isNull()?null:v.stringValue(); }
    public static Map<String,JsonNode> index(JsonNode array,String key) {
        var result=new LinkedHashMap<String,JsonNode>();
        for(var item:array) model(result.put(text(item,key),item)==null);
        return result;
    }
    public static String place(JsonNode n) { return text(n,"locationType")+":"+text(n,"locationId"); }
    public static String bodyPlace(JsonNode n) { return place(n)+":"+text(n,"locationSlotId"); }
    private static boolean pointEqual(JsonNode a,JsonNode b) { return a.get("x").doubleValue()==b.get("x").doubleValue() && a.get("y").doubleValue()==b.get("y").doubleValue(); }
    public static void configuration(JsonNode config) {
        var equipment=index(config.get("equipment"),"cellId"); var bays=index(config.get("buffers"),"bufferId");
        model(equipment.keySet().equals(new HashSet<>(CELLS)) && bays.size()==3);
        var locations=new HashMap<String,JsonNode>();
        for(var location:config.get("locations")) model(locations.put(place(location),location)==null);
        var expected=new HashSet<>(List.of("INPUT:BODY-IN","RESULT:GOOD","RESULT:HOLD","STORE:PARTS-STORE","PARTS_DOCK:PARTS-ASM-01","PARTS_DOCK:PARTS-ASM-02"));
        for(String cell:CELLS) { expected.add("CELL:"+cell); expected.add("BUFFER:BAY-"+cell); }
        model(locations.keySet().equals(expected));
        for(String cell:CELLS) {
            var e=equipment.get(cell); model(cell.equals(text(e,"equipmentId")) && ("BAY-"+cell).equals(text(e,"bufferId")));
            var b=bays.get("BAY-"+cell); model(b!=null && cell.equals(text(b,"cellId")));
            for(int i=0;i<b.get("capacity").intValue();i++) model(("BAY-"+cell+"-S"+(i+1)).equals(b.get("slotIds").get(i).stringValue()));
        }
        var vehicles=index(config.get("vehicles"),"vehicleId"); int agv=0,amr=0;
        for(var v:vehicles.values()) {
            String kind=text(v,"kind"); model(text(v,"vehicleId").startsWith(kind+"-") && locations.containsKey(place(v.get("home"))));
            if(kind.equals("AGV")) agv++; else amr++;
        }
        model(agv==2 && amr==1);
        var routes=index(config.get("routes"),"routeId"); var signatures=new HashSet<String>();
        var allowed=new HashSet<>(List.of("BODY:INPUT:BODY-IN>BUFFER:BAY-ASM-01","BODY:CELL:ASM-01>BUFFER:BAY-ASM-02","BODY:CELL:ASM-02>BUFFER:BAY-QC-01", "BODY:CELL:QC-01>RESULT:GOOD","BODY:CELL:QC-01>RESULT:HOLD","PARTS:STORE:PARTS-STORE>PARTS_DOCK:PARTS-ASM-01","PARTS:STORE:PARTS-STORE>PARTS_DOCK:PARTS-ASM-02"));
        for(var r:routes.values()) {
            String source=place(r.get("source")),destination=place(r.get("destination"));
            model(locations.containsKey(source) && locations.containsKey(destination));
            var points=r.get("points"); model(pointEqual(locations.get(source),points.get(0)) && pointEqual(locations.get(destination),points.get(points.size()-1)));
            model(signatures.add(text(r,"cargoType")+":"+source+">"+destination));
        }
        model(signatures.equals(allowed));
    }
    public static void transport(JsonNode t,JsonNode config) {
        var routes=index(config.get("routes"),"routeId"); var vehicles=index(config.get("vehicles"),"vehicleId");
        reference(routes.containsKey(text(t,"routeId")) && vehicles.containsKey(text(t,"vehicleId")));
        JsonNode route=routes.get(text(t,"routeId")),vehicle=vehicles.get(text(t,"vehicleId"));
        String cargo=text(t,"cargoType"),state=text(t,"status"); boolean body=cargo.equals("BODY");
        model(cargo.equals(text(route,"cargoType")) && route.get("source").equals(t.get("source")) && route.get("destination").equals(t.get("destination")));
        model((body?"AGV":"AMR").equals(text(vehicle,"kind")));
        model((text(t,"bodyId")!=null)==body && (text(t,"partsKitId")!=null)!=body);
        boolean reserved=body && text(t.get("destination"),"locationType").equals("BUFFER");
        model((text(t,"reservationId")!=null)==reserved && (text(t,"slotId")!=null)==reserved);
        if(reserved) {
            var bay=index(config.get("buffers"),"bufferId").get(text(t.get("destination"),"locationId"));
            model(bay!=null && contains(bay.get("slotIds"),text(t,"slotId")));
        }
        boolean started=Set.of("IN_TRANSIT","COMPLETED").contains(state),complete=state.equals("COMPLETED"),cancelled=state.equals("CANCELLED");
        model((text(t,"startedAt")!=null)==started && (text(t,"completedAt")!=null)==complete && (text(t,"cancelledAt")!=null)==cancelled);
        model(Objects.equals(text(t,"cancelReason"),cancelled?"SCENARIO_CANCEL":null) && (!cancelled||body));
        for(String field:List.of("startedAt","completedAt","cancelledAt")) if(text(t,field)!=null)
            model(!EventSyntax.timestamp(t.get(field)).isBefore(EventSyntax.timestamp(t.get("assignedAt"))));
        if(complete) model(!EventSyntax.timestamp(t.get("completedAt")).isBefore(EventSyntax.timestamp(t.get("startedAt"))));
    }
    public static boolean contains(JsonNode array,String value) { for(var item:array) if(item.isString() && item.stringValue().equals(value)) return true; return false; }
    public static void snapshot(JsonNode state,JsonNode config,Map<String,JsonNode> registered) {
        var cells=index(state.get("equipment"),"cellId"); var bays=index(state.get("buffers"),"bufferId");
        var bodies=index(state.get("bodies"),"bodyId"); var vehicles=index(state.get("vehicles"),"vehicleId"); var trips=index(state.get("activeTransports"),"transportId");
        var configuredBays=index(config.get("buffers"),"bufferId"); var configuredVehicles=index(config.get("vehicles"),"vehicleId");
        model(cells.keySet().equals(new HashSet<>(CELLS)) && bays.keySet().equals(configuredBays.keySet()) && vehicles.keySet().equals(configuredVehicles.keySet()));
        reference(registered.keySet().equals(bodies.keySet()));
        var owners=new HashMap<String,List<String>>(); for(String id:bodies.keySet()) owners.put(id,new ArrayList<>());
        var reservedTrips=new HashSet<String>();
        for(var cell:cells.values()) {
            String id=text(cell,"cellId"),status=text(cell,"state"),body=text(cell,"bodyId"),op=text(cell,"operationId"),resume=text(cell,"resumeState"),reason=text(cell,"blockedReason");
            model(id.equals(text(cell,"equipmentId")) && (status.equals("DOWN")== (resume!=null)));
            String effective=status.equals("DOWN")?resume:status;
            model(Set.of("IDLE","RUNNING","BLOCKED").contains(effective));
            model((body!=null)==(op!=null));
            if(effective.equals("IDLE")) model(body==null && cell.get("remainingWorkMs").longValue()==0 && text(cell,"destinationCellId")==null);
            else {
                model(body!=null); model(bodies.containsKey(body)); owners.get(body).add("CELL:"+id+":null");
                model(text(bodies.get(body),"status").equals(effective.equals("RUNNING")?"PROCESSING":(id.equals("QC-01")?"COMPLETED":"WAITING_UNLOAD")));
                if(effective.equals("BLOCKED")) model(cell.get("remainingWorkMs").longValue()==0);
            }
            model((reason!=null)==effective.equals("BLOCKED"));
            if(text(cell,"destinationCellId")!=null) model(text(cell,"destinationCellId").equals(id.equals("ASM-01")?"ASM-02":"QC-01") && !id.equals("QC-01"));
        }
        for(var bay:bays.values()) {
            JsonNode configured=configuredBays.get(text(bay,"bufferId"));
            int capacity=bay.get("capacity").intValue(),waiting=0,inbound=0;
            model(configured.get("capacity").intValue()==capacity && bay.get("slots").size()==capacity && Objects.equals(text(bay,"cellId"),text(configured,"cellId")));
            int i=0;
            for(var slot:bay.get("slots")) {
                model(configured.get("slotIds").get(i++).stringValue().equals(text(slot,"slotId")));
                String status=text(slot,"status"),body=text(slot,"bodyId"),vehicle=text(slot,"vehicleId"),tid=text(slot,"transportId"),reservation=text(slot,"reservationId");
                if(status.equals("FREE")) model(body==null && vehicle==null && tid==null && reservation==null);
                else {
                    model(bodies.containsKey(body));
                    if(status.equals("OCCUPIED")) { waiting++; model(vehicle==null && ((tid==null)==(reservation==null))); owners.get(body).add("BUFFER:"+text(bay,"bufferId")+":"+text(slot,"slotId")); }
                    else {
                        inbound++; model(trips.containsKey(tid)); var t=trips.get(tid);
                        model(place(t.get("destination")).equals("BUFFER:"+text(bay,"bufferId")));
                        for(String key:List.of("bodyId","vehicleId","reservationId","slotId")) model(text(slot,key)!=null && Objects.equals(text(slot,key),text(t,key)));
                        model(reservedTrips.add(tid));
                    }
                }
            }
            model(waiting==bay.get("waitingCount").intValue() && inbound==bay.get("reservedInboundCount").intValue() && capacity-waiting-inbound==bay.get("availableSlots").intValue() && waiting+inbound<=capacity);
        }
        for(var vehicle:vehicles.values()) {
            model(Objects.equals(text(vehicle,"kind"),text(configuredVehicles.get(text(vehicle,"vehicleId")),"kind")));
            String body=text(vehicle,"bodyId"),kit=text(vehicle,"partsKitId"),tid=text(vehicle,"transportId"),phase=text(vehicle,"state");
            if(body!=null) { model(bodies.containsKey(body)); owners.get(body).add("VEHICLE:"+text(vehicle,"vehicleId")+":null"); }
            if(Set.of("IDLE","RETURNING").contains(phase)) model(body==null && kit==null && tid==null);
            else { model(trips.containsKey(tid)); model(Objects.equals(text(trips.get(tid),"vehicleId"),text(vehicle,"vehicleId"))); }
            if(Set.of("TO_PICKUP","LOADING").contains(phase)) model(body==null && kit==null);
            if(Set.of("MOVING","UNLOADING").contains(phase)) model((body!=null) != (kit!=null));
        }
        for(var body:bodies.values()) {
            String id=text(body,"bodyId"),kind=text(body,"locationType"),location=text(body,"locationId"),tid=text(body,"transportId");
            var registration=registered.get(id);
            for(String key:List.of("tagId","modelCode","specCode")) model(Objects.equals(text(body,key),text(registration,key)));
            model(Objects.equals(text(body,"lastObservedAt"),text(state,"capturedAt")));
            if(kind.equals("INPUT") || kind.equals("RESULT")) { model(kind.equals("INPUT")?location.equals("BODY-IN"):Set.of("GOOD","HOLD").contains(location)); owners.get(id).add(bodyPlace(body)); }
            model(owners.get(id).equals(List.of(bodyPlace(body))));
            model(Objects.equals(text(body,"currentCellId"),kind.equals("CELL")?location:null) && (text(body,"locationSlotId")!=null)==kind.equals("BUFFER"));
            var completed=new ArrayList<String>(); for(var c:body.get("completedCellIds")) completed.add(c.stringValue());
            model(completed.size()<=3 && completed.equals(CELLS.subList(0,completed.size())) && Objects.equals(text(body,"nextCellId"),completed.size()==3?null:CELLS.get(completed.size())));
            boolean inspected=!text(body,"inspectionResult").equals("NOT_INSPECTED"); model(inspected==(text(body,"inspectedAt")!=null) && inspected==text(body,"status").equals("COMPLETED"));
            if(inspected) model(completed.size()==3);
            if(tid!=null) { model(trips.containsKey(tid)); model(Objects.equals(text(trips.get(tid),"bodyId"),id) && Objects.equals(text(body,"reservationId"),text(trips.get(tid),"reservationId"))); }
            else model(text(body,"reservationId")==null && !kind.equals("VEHICLE"));
        }
        var expectedReservations=new HashSet<String>(); var usedVehicles=new HashSet<String>(); var usedBodies=new HashSet<String>();
        for(var t:trips.values()) {
            transport(t,config); model(Set.of("ASSIGNED","IN_TRANSIT").contains(text(t,"status")));
            model(usedVehicles.add(text(t,"vehicleId"))); var v=vehicles.get(text(t,"vehicleId")); model(Objects.equals(text(v,"transportId"),text(t,"transportId")));
            boolean body=text(t,"cargoType").equals("BODY"),assigned=text(t,"status").equals("ASSIGNED");
            if(body) {
                String bid=text(t,"bodyId"); model(usedBodies.add(bid)); model(bodies.containsKey(bid)); var b=bodies.get(bid);
                model(Objects.equals(text(b,"transportId"),text(t,"transportId")));
                if(text(t,"reservationId")!=null) expectedReservations.add(text(t,"transportId"));
                if(assigned) model(place(b).equals(place(t.get("source"))) && text(v,"bodyId")==null);
                else model(place(b).equals("VEHICLE:"+text(v,"vehicleId")) && Objects.equals(text(v,"bodyId"),bid));
            } else if(!assigned) model(Objects.equals(text(v,"partsKitId"),text(t,"partsKitId")));
            model(assigned?Set.of("TO_PICKUP","LOADING").contains(text(v,"state")):Set.of("MOVING","UNLOADING").contains(text(v,"state")));
        }
        model(reservedTrips.equals(expectedReservations));
    }
}
