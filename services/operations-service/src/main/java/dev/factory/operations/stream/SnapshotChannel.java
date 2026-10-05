package dev.factory.operations.stream;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.function.LongSupplier;
import jakarta.servlet.*;

/** Non-blocking: one current frame and one replaceable latest snapshot, never a growing queue. */
final class SnapshotChannel implements WriteListener {
    private final ServletOutputStream output;
    private final Runnable close;
    private final LongSupplier now;
    private byte[] current,pending;
    private int offset;
    private long started;
    private boolean closed;
    SnapshotChannel(ServletOutputStream output,Runnable close,LongSupplier now){this.output=output;this.close=close;this.now=now;}
    synchronized void offer(byte[] frame){
        if(closed) return;
        if(current==null){current=frame;offset=0;started=now.getAsLong();}else pending=frame;
        drain();
    }
    synchronized void heartbeat(){if(!closed && current==null && pending==null) offer(": heartbeat\n\n".getBytes(StandardCharsets.UTF_8));}
    synchronized void deadline(){if(!closed && current!=null && now.getAsLong()-started>=5_000_000_000L) finish();}
    synchronized void finish(){if(closed)return;closed=true;current=null;pending=null;close.run();}
    synchronized int retainedFrames(){return (current==null?0:1)+(pending==null?0:1);}
    @Override public synchronized void onWritePossible(){drain();}
    @Override public synchronized void onError(Throwable error){finish();}
    private void drain(){
        try {
            while(!closed && current!=null && output.isReady()){
                if(offset<current.length){int count=Math.min(8192,current.length-offset);output.write(current,offset,count);offset+=count;}
                else {output.flush();if(!output.isReady())return;current=pending;pending=null;offset=0;started=now.getAsLong();}
            }
        }catch(IOException | RuntimeException failure){finish();}
    }
}
