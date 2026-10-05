package dev.factory.ingestion.delivery;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import dev.factory.ingestion.receiver.Protocol;

@RestController
@Profile("!bootstrap")
public class DeliveryController {
    private final DeliveryStore store;
    private final SourceConnections connections;
    public DeliveryController(DeliveryStore store,SourceConnections connections){this.store=store;this.connections=connections;}
    @GetMapping("/internal/v1/runs/{run}/delivery-status") public Map<String,Object> status(@PathVariable String run,@RequestParam Map<String,String> query){runId(run);fields(query,Set.of());return store.diagnostic(run,connections);}
    @GetMapping("/internal/v1/runs/{run}/outbox") public Map<String,Object> outbox(@PathVariable String run,@RequestParam Map<String,String> query){
        runId(run);fields(query,Set.of("afterSeq","limit","status"));long after=number(query.getOrDefault("afterSeq","0"),0,9007199254740991L);int limit=(int)number(query.getOrDefault("limit","50"),1,200);String status=query.get("status");
        if(status!=null && !Set.of("PENDING","RETRY_WAIT","DELIVERED","QUARANTINED").contains(status)) throw new DeliveryProblem(400,"INVALID_QUERY");return store.outbox(run,after,limit,status);
    }
    @PostMapping("/internal/v1/runs/{run}/delivery-resume") public Map<String,Object> resume(@PathVariable String run,@RequestParam Map<String,String> query,HttpServletRequest request) throws IOException {
        runId(run);fields(query,Set.of());
        try {var media=MediaType.parseMediaType(request.getContentType());if(!media.getType().equalsIgnoreCase("application") || !media.getSubtype().equalsIgnoreCase("json") || media.getCharset()!=null && !media.getCharset().equals(StandardCharsets.UTF_8) || request.getHeader("Content-Encoding")!=null && !request.getHeader("Content-Encoding").equals("identity")) throw new IllegalArgumentException();}catch(RuntimeException invalid){throw new DeliveryProblem(415,"UNSUPPORTED_MEDIA_TYPE");}
        if(request.getContentLengthLong()>2048) throw new DeliveryProblem(413,"PAYLOAD_TOO_LARGE");byte[] raw=request.getInputStream().readNBytes(2049);if(raw.length>2048) throw new DeliveryProblem(413,"PAYLOAD_TOO_LARGE");
        long seq;String operator,reason;
        try {
            String text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(raw)).toString();if(text.startsWith("\ufeff")) throw new IllegalArgumentException();var n=Protocol.JSON.readTree(text);
            if(n==null || !n.isObject() || !new HashSet<>(n.propertyNames()).equals(Set.of("sourceSeq","operatorId","reason")) || !n.get("sourceSeq").isIntegralNumber() || !n.get("sourceSeq").canConvertToLong() || !n.get("operatorId").isString() || !n.get("reason").isString()) throw new IllegalArgumentException();
            seq=n.get("sourceSeq").longValue();operator=n.get("operatorId").stringValue();reason=n.get("reason").stringValue();
            if(seq<1 || seq>9007199254740991L || !operator.matches("[A-Za-z0-9_-]{1,64}") || reason.isBlank() || reason.getBytes(StandardCharsets.UTF_8).length>1024) throw new IllegalArgumentException();
        }catch(RuntimeException | CharacterCodingException invalid){throw new DeliveryProblem(400,"INVALID_BODY");}
        return store.resume(run,seq,operator,reason);
    }
    private static void fields(Map<String,String> query,Set<String> allowed){if(!allowed.containsAll(query.keySet())) throw new DeliveryProblem(400,"INVALID_QUERY");}
    private static long number(String value,long min,long max){try{if(!value.matches("[0-9]{1,16}")) throw new IllegalArgumentException();long n=Long.parseLong(value);if(n<min || n>max) throw new IllegalArgumentException();return n;}catch(RuntimeException invalid){throw new DeliveryProblem(400,"INVALID_QUERY");}}
    private static void runId(String run){try{if(!run.matches("run-[0-9]{8}-[a-z0-9]{3,32}")) throw new IllegalArgumentException();LocalDate.parse(run.substring(4,12),DateTimeFormatter.BASIC_ISO_DATE);}catch(RuntimeException invalid){throw new DeliveryProblem(400,"INVALID_QUERY");}}
}
