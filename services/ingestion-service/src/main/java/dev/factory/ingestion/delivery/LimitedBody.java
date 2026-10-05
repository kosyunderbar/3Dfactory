package dev.factory.ingestion.delivery;

import java.io.ByteArrayOutputStream;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.Flow;

/** Cancellation and a hard byte limit include the response body, not only HTTP headers. */
final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
    private final ByteArrayOutputStream bytes=new ByteArrayOutputStream();
    private final CompletableFuture<byte[]> result=new CompletableFuture<>();
    private Flow.Subscription subscription;
    @Override public CompletionStage<byte[]> getBody(){return result;}
    @Override public void onSubscribe(Flow.Subscription s){subscription=s;s.request(1);}
    @Override public void onNext(List<ByteBuffer> buffers){
        for(var b:buffers){if(bytes.size()+b.remaining()>8192){subscription.cancel();result.completeExceptionally(new IllegalArgumentException("Response body too large"));return;}byte[] piece=new byte[b.remaining()];b.get(piece);bytes.writeBytes(piece);}subscription.request(1);
    }
    @Override public void onError(Throwable e){result.completeExceptionally(e);}
    @Override public void onComplete(){result.complete(bytes.toByteArray());}
}
