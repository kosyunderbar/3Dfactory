package dev.factory.ingestion.receiver;

import java.io.IOException;
import java.net.*;
import java.time.Instant;
import java.util.Set;
import java.util.concurrent.*;
import org.springframework.context.SmartLifecycle;
import dev.factory.ingestion.delivery.SourceConnections;

/** Eight connection readers and one bounded admission/storage worker. HTTP delivery uses a separate worker. */
public final class TcpReceiver implements SmartLifecycle {
    private final String address;
    private final int port;
    private final EventStore store;
    private final RejectionLog diagnostics;
    private final SourceConnections sources;
    private final Semaphore slots=new Semaphore(8);
    private final Set<Socket> connections=ConcurrentHashMap.newKeySet();
    private volatile boolean running;
    private ServerSocket listener;
    private AdmissionQueue queue;
    public TcpReceiver(String address,int port,EventStore store,RejectionLog diagnostics) {
        this(address,port,store,diagnostics,new SourceConnections());
    }
    public TcpReceiver(String address,int port,EventStore store,RejectionLog diagnostics,SourceConnections sources) {
        this.address=address; this.port=port; this.store=store; this.diagnostics=diagnostics;this.sources=sources;
    }
    @Override public synchronized void start() {
        if(running) return;
        try { listener=new ServerSocket(); listener.setReuseAddress(true); listener.bind(new InetSocketAddress(address,port),8); }
        catch(IOException e) { throw new IllegalStateException("Cannot bind ingestion TCP listener",e); }
        queue=new AdmissionQueue(128,8388608,this::handle); running=true;
        Thread.ofPlatform().name("ingestion-tcp-accept").daemon().start(()->{
            while(running) try {
                Socket connection=listener.accept();
                if(!slots.tryAcquire()) { connection.close(); continue; }
                connections.add(connection);sources.opened(connection);
                Thread.ofPlatform().name("ingestion-tcp-reader").daemon().start(()->read(connection));
            } catch(IOException e) { if(running) stop(); }
        });
    }
    private Protocol.Ack handle(byte[] raw,Instant received) {
        Protocol.Ack ack;
        try { ack=store.receive(Protocol.parse(raw),received); }
        catch(Protocol.Invalid invalid) { ack=Protocol.Ack.of(invalid.identity,invalid.hash,"REJECTED",invalid.code,received); }
        return diagnose(ack,raw);
    }
    private Protocol.Ack diagnose(Protocol.Ack ack,byte[] raw) {
        if(ack.status().equals("REJECTED") && (!diagnostics.record(ack,raw) || !store.recordRejected(ack)))
            return Protocol.Ack.of(ack.runId()==null?null:new Protocol.Identity(ack.runId(),ack.sourceId(),ack.eventId(),ack.sourceSeq()),
                ack.eventSha256(),"RETRY_LATER","DIAGNOSTIC_UNAVAILABLE",Instant.parse(ack.receivedAt()));
        return ack;
    }
    private void read(Socket connection) {
        FrameDecoder frames=new FrameDecoder(); byte[] buffer=new byte[4096];
        try(connection) {
            connection.setSoTimeout(200); connection.setTcpNoDelay(true);
            while(running) {
                try {
                    int n=connection.getInputStream().read(buffer); if(n<0) return;
                    frames.feed(buffer,n,System.nanoTime(),Instant.now(),(raw,received)->{
                        var result=queue.offer(raw,received); Protocol.Ack ack;
                        if(result==null) {
                            Protocol.Identity id=null; String hash=Protocol.hash(raw);
                            try { id=Protocol.parse(raw).identity(); } catch(Protocol.Invalid e) { id=e.identity; }
                            ack=Protocol.Ack.of(id,hash,"RETRY_LATER","INGESTION_BUSY",received);
                        } else try { ack=result.get(); }
                        catch(InterruptedException e) { Thread.currentThread().interrupt(); throw new ConnectionEnded(); }
                        catch(ExecutionException e) { throw new ConnectionEnded(); }
                        if(ack.status().equals("RECEIVED") || ack.status().equals("DUPLICATE_RECEIVED")) sources.accepted(connection,ack.runId());
                        write(connection,ack);
                        if(ack.status().equals("REJECTED") || ack.status().equals("RETRY_LATER")) throw new ConnectionEnded();
                    });
                } catch(SocketTimeoutException idle) {
                    try { frames.checkDeadline(System.nanoTime()); }
                    catch(Protocol.Invalid invalid) { framingFailure(connection,frames,invalid); return; }
                } catch(Protocol.Invalid invalid) { framingFailure(connection,frames,invalid); return; }
            }
        } catch(IOException | ConnectionEnded ignored) {
            // A committed event remains stored when an ACK write or the peer connection fails.
        } finally { connections.remove(connection);sources.closed(connection); slots.release(); }
    }
    private void framingFailure(Socket socket,FrameDecoder frames,Protocol.Invalid invalid) {
        write(socket,diagnose(Protocol.Ack.of(null,null,"REJECTED",invalid.code,frames.firstReceivedAt()),frames.preview()));
    }
    private static final class ConnectionEnded extends RuntimeException {}
    private void write(Socket socket,Protocol.Ack ack) {
        try { socket.getOutputStream().write(ack.bytes()); socket.getOutputStream().flush(); }
        catch(IOException e) { throw new ConnectionEnded(); }
    }
    @Override public synchronized void stop() {
        running=false;
        try { if(listener!=null) listener.close(); } catch(IOException ignored) {}
        for(Socket connection:connections) {sources.closed(connection);try { connection.close(); } catch(IOException ignored) {}}
        if(queue!=null) queue.close();
    }
    @Override public boolean isRunning() { return running; }
    int activeConnections() { return connections.size(); }
    public int boundPort() { return listener.getLocalPort(); }
}
