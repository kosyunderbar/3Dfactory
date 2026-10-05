package dev.factory.ingestion.delivery;

import java.util.concurrent.ThreadLocalRandom;
import java.util.function.DoubleSupplier;
import org.slf4j.*;
import org.springframework.context.SmartLifecycle;

/** P0: one instance, one worker; one in-flight head. No HTTP inside a database transaction. */
public final class DeliveryWorker implements SmartLifecycle {
    private static final Logger log=LoggerFactory.getLogger(DeliveryWorker.class);
    private final DeliveryStore store;
    private final OperationsClient client;
    private final DoubleSupplier jitter;
    private volatile boolean running;
    private Thread thread;
    public DeliveryWorker(DeliveryStore store,OperationsClient client){this(store,client,()->ThreadLocalRandom.current().nextDouble());}
    DeliveryWorker(DeliveryStore store,OperationsClient client,DoubleSupplier jitter){this.store=store;this.client=client;this.jitter=jitter;}
    public synchronized boolean tick(){
        var head=store.reserveNext();if(head==null) return false;
        var result=client.apply(head);if(Thread.currentThread().isInterrupted()) return false;
        store.complete(head,result,jitter.getAsDouble());return true;
    }
    @Override public synchronized void start(){
        if(running) return;if(thread!=null && thread.isAlive()) throw new IllegalStateException("Delivery worker is still stopping");running=true;
        thread=Thread.ofPlatform().name("ingestion-outbox-delivery").daemon().start(()->{
            try {while(running){try {if(!tick()) Thread.sleep(50);}catch(InterruptedException stop){Thread.currentThread().interrupt();break;}catch(RuntimeException failure){log.warn("Delivery database/result was not confirmed; original head retained");try{Thread.sleep(500);}catch(InterruptedException stop){Thread.currentThread().interrupt();break;}}}}
            finally {running=false;}
        });
    }
    @Override public void stop(){running=false;Thread worker=thread;if(worker!=null){worker.interrupt();if(worker!=Thread.currentThread())try{worker.join(5500);}catch(InterruptedException stop){Thread.currentThread().interrupt();}}}
    @Override public boolean isRunning(){return running && thread!=null && thread.isAlive();}
}
