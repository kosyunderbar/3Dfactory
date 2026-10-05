package dev.factory.ingestion.receiver;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.concurrent.CompletableFuture;
import java.util.function.BiFunction;

/** One worker; limits count waiting frames and their exact byte lengths, not just task count. */
public final class AdmissionQueue implements AutoCloseable {
    private record Job(byte[] raw,Instant received,CompletableFuture<Protocol.Ack> future,long enqueued) {}
    private final ArrayDeque<Job> waiting=new ArrayDeque<>();
    private final int countCap;
    private final long byteCap;
    private long bytes;
    private boolean running=true;
    private final Thread worker;
    public AdmissionQueue(int countCap,long byteCap,BiFunction<byte[],Instant,Protocol.Ack> handler) {
        this.countCap=countCap; this.byteCap=byteCap;
        worker=Thread.ofPlatform().name("ingestion-admission").daemon().start(()->{
            while(true) {
                Job job;
                synchronized(this) {
                    while(running && waiting.isEmpty()) try { wait(); } catch(InterruptedException e) { Thread.currentThread().interrupt(); return; }
                    if(!running && waiting.isEmpty()) return;
                    job=waiting.removeFirst(); bytes-=job.raw().length+1;
                }
                try {
                    long end=job.enqueued()==0?0:System.nanoTime(),wall=job.enqueued()==0?0:System.currentTimeMillis();
                    Protocol.Ack ack=handler.apply(job.raw(),job.received());
                    dev.factory.ingestion.measurement.Measurements.interval("ingestion-queue",ack.runId(),ack.eventId(),ack.sourceSeq()==null?0:ack.sourceSeq(),ack.status(),job.enqueued(),end,wall);
                    job.future().complete(ack);
                }
                catch(RuntimeException e) { job.future().completeExceptionally(e); }
            }
        });
    }
    public synchronized CompletableFuture<Protocol.Ack> offer(byte[] raw,Instant received) {
        if(!running || waiting.size()>=countCap || bytes+raw.length+1>byteCap) return null;
        var future=new CompletableFuture<Protocol.Ack>();
        waiting.addLast(new Job(raw,received,future,dev.factory.ingestion.measurement.Measurements.start())); bytes+=raw.length+1; notifyAll(); return future;
    }
    public synchronized void close() {
        running=false;
        for(Job job:waiting) job.future().completeExceptionally(new IllegalStateException("Receiver stopping"));
        waiting.clear(); bytes=0; notifyAll();
    }
}
