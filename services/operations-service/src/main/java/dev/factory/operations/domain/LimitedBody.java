package dev.factory.operations.domain;

import java.io.ByteArrayOutputStream;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.Flow;

/** HTTP diagnostic body with a hard allocation limit and a cancellable completion future. */
final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
    private final int max;
    private final ByteArrayOutputStream bytes=new ByteArrayOutputStream();
    private final CompletableFuture<byte[]> result=new CompletableFuture<>();
    private Flow.Subscription subscription;
    LimitedBody(int max) {this.max=max;}
    @Override public CompletionStage<byte[]> getBody() {return result;}
    @Override public void onSubscribe(Flow.Subscription subscription) {this.subscription=subscription;subscription.request(1);}
    @Override public void onNext(List<ByteBuffer> buffers) {
        for(var buffer:buffers) {
            if(bytes.size()+buffer.remaining()>max) {subscription.cancel();result.completeExceptionally(new IllegalArgumentException("Diagnostic body too large"));return;}
            byte[] piece=new byte[buffer.remaining()];buffer.get(piece);bytes.writeBytes(piece);
        }
        subscription.request(1);
    }
    @Override public void onError(Throwable error) {result.completeExceptionally(error);}
    @Override public void onComplete() {result.complete(bytes.toByteArray());}
}
