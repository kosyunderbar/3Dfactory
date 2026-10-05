package dev.factory.operations.stream;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.context.SmartLifecycle;
import org.slf4j.*;
import dev.factory.operations.api.ApiProblem;
import dev.factory.operations.domain.*;

/** HTTP subscribers use the same immutable run bundle as REST. No event replay or DB ownership change. */
public final class SnapshotStreams implements SmartLifecycle {
    private static final Logger log=LoggerFactory.getLogger(SnapshotStreams.class);
    private static final byte[] RETRY="retry: 2000\n\n".getBytes(StandardCharsets.UTF_8);
    private final ViewPublisher views;
    private final AtomicInteger slots=new AtomicInteger();
    private final Set<Client> clients=ConcurrentHashMap.newKeySet();
    private volatile boolean running;
    private ScheduledExecutorService publications,deadlines;
    public SnapshotStreams(ViewPublisher views){this.views=views;}
    public void open(String run,HttpServletRequest request,HttpServletResponse response) throws IOException {
        if(!running)throw new ApiProblem(503,"VIEW_NOT_READY");
        if(slots.incrementAndGet()>20){slots.decrementAndGet();throw new ApiProblem(429,"STREAM_LIMIT");}
        boolean attached=false;AsyncContext context=null;Client client=null;
        try {
            var first=views.current(run);byte[] frame=frame(first);
            response.setStatus(200);response.setContentType("text/event-stream");response.setCharacterEncoding("UTF-8");response.setHeader("Cache-Control","no-store");response.setHeader("X-Accel-Buffering","no");
            context=request.startAsync(request,response);context.setTimeout(0);
            client=new Client(run,context,response.getOutputStream());clients.add(client);attached=true;
            context.addListener(client);client.output.setWriteListener(client.channel);
            client.channel.offer(RETRY);client.offer(first,frame);
        }catch(IOException | RuntimeException failure){if(attached)client.channel.finish();throw failure;}
        finally{if(!attached){slots.decrementAndGet();if(context!=null)context.complete();}}
    }
    static byte[] frame(Map<String,Object> view){
        byte[] json=EventSyntax.JSON.writeValueAsBytes(view);if(json.length>524288)throw new ApiProblem(503,"VIEW_NOT_READY");
        String prefix="id: "+view.get("serverEpoch")+":"+view.get("revision")+"\nevent: factory-snapshot\ndata: ";
        byte[] head=prefix.getBytes(StandardCharsets.UTF_8),frame=new byte[head.length+json.length+2];System.arraycopy(head,0,frame,0,head.length);System.arraycopy(json,0,frame,head.length,json.length);frame[frame.length-2]='\n';frame[frame.length-1]='\n';return frame;
    }
    private void publish(){
        if(!running)return;long now=System.nanoTime();
        var groups=new HashMap<String,List<Client>>();for(var c:clients)groups.computeIfAbsent(c.run,k->new ArrayList<>()).add(c);
        for(var entry:groups.entrySet()){
            try {var view=views.current(entry.getKey());byte[] bytes=frame(view);for(var c:entry.getValue())if(now-c.lastOffer>=500_000_000L)c.offer(view,bytes);}
            catch(RuntimeException unavailable){log.warn("SSE bundle unavailable; subscribers closed without a replacement state");for(var c:entry.getValue())c.channel.finish();}
        }
    }
    private void watch(){if(!running)return;long now=System.nanoTime();for(var c:clients){c.channel.deadline();if(now-c.lastHeartbeat>=5_000_000_000L){c.channel.heartbeat();c.lastHeartbeat=now;}}}
    @Override public synchronized void start(){if(running)return;running=true;
        publications=Executors.newSingleThreadScheduledExecutor(r->Thread.ofPlatform().daemon().name("operations-sse-publications").unstarted(r));
        deadlines=Executors.newSingleThreadScheduledExecutor(r->Thread.ofPlatform().daemon().name("operations-sse-deadlines").unstarted(r));
        publications.scheduleWithFixedDelay(this::publish,500,500,TimeUnit.MILLISECONDS);deadlines.scheduleWithFixedDelay(this::watch,100,100,TimeUnit.MILLISECONDS);
    }
    @Override public void stop(){running=false;if(publications!=null)publications.shutdownNow();if(deadlines!=null)deadlines.shutdownNow();for(var c:clients)c.channel.finish();}
    @Override public boolean isRunning(){return running;}
    public int connections(){return slots.get();}
    private final class Client implements AsyncListener {
        final String run;final AsyncContext context;final ServletOutputStream output;final SnapshotChannel channel;
        volatile long lastOffer=0,lastHeartbeat=System.nanoTime();String lastId;
        Client(String run,AsyncContext context,ServletOutputStream output){this.run=run;this.context=context;this.output=output;channel=new SnapshotChannel(output,this::remove,System::nanoTime);}
        synchronized void offer(Map<String,Object> view,byte[] bytes){String id=view.get("serverEpoch")+":"+view.get("revision");if(id.equals(lastId))return;lastId=id;lastOffer=System.nanoTime();channel.offer(bytes);}
        void remove(){if(clients.remove(this)){slots.decrementAndGet();try{context.complete();}catch(RuntimeException alreadyClosed){}}}
        @Override public void onComplete(AsyncEvent event){channel.finish();}
        @Override public void onError(AsyncEvent event){channel.finish();}
        @Override public void onTimeout(AsyncEvent event){channel.finish();}
        @Override public void onStartAsync(AsyncEvent event){}
    }
}
