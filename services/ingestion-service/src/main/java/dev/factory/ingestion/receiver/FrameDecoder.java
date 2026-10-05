package dev.factory.ingestion.receiver;

import java.io.ByteArrayOutputStream;
import java.time.Instant;
import java.util.function.BiConsumer;

/** Byte framing precedes UTF-8 decoding. A partial frame has one deadline from its first byte. */
public final class FrameDecoder {
    private final ByteArrayOutputStream partial=new ByteArrayOutputStream();
    private long started;
    private Instant received;
    public void feed(byte[] input,int length,long now,Instant wall,BiConsumer<byte[],Instant> complete) {
        checkDeadline(now);
        for(int i=0;i<length;i++) {
            if(partial.size()==0 && received==null) { started=now; received=wall; }
            if(input[i]=='\n') {
                byte[] raw=partial.toByteArray(); Instant first=received;
                partial.reset(); received=null; complete.accept(raw,first);
            } else {
                partial.write(input[i]);
                if(partial.size()>65535) throw new Protocol.Invalid("FRAME_TOO_LARGE",null,null);
            }
        }
    }
    public void checkDeadline(long now) {
        if(received!=null && now-started>=3_000_000_000L) throw new Protocol.Invalid("FRAME_TIMEOUT",null,null);
    }
    public byte[] preview() { return java.util.Arrays.copyOf(partial.toByteArray(),Math.min(partial.size(),1024)); }
    public Instant firstReceivedAt() { return received; }
    // On EOF a partial frame is intentionally discarded, with no success acknowledgment.
}
