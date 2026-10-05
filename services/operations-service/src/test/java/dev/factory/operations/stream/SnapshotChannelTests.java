package dev.factory.operations.stream;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.*;
import jakarta.servlet.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class SnapshotChannelTests {
    @Test void slowOutputKeepsOnlyLatestAndTimesOutWithoutBlockingOtherClients() throws Exception {
        var time=new AtomicLong();var closed=new AtomicInteger();var out=new Output();
        var channel=new SnapshotChannel(out,closed::incrementAndGet,time::get);
        channel.offer(bytes("first"));channel.offer(bytes("obsolete"));channel.offer(bytes("latest"));
        assertThat(channel.retainedFrames()).isEqualTo(2);assertThat(out.bytes.size()).isZero();
        out.ready=true;channel.onWritePossible();assertThat(out.bytes.toString(StandardCharsets.UTF_8)).isEqualTo("firstlatest");assertThat(channel.retainedFrames()).isZero();
        out.ready=false;channel.offer(bytes("blocked"));time.set(4_999_999_999L);channel.deadline();assertThat(closed).hasValue(0);
        time.incrementAndGet();channel.deadline();assertThat(closed).hasValue(1);assertThat(channel.retainedFrames()).isZero();channel.onError(new IOException());assertThat(closed).hasValue(1);
        var healthy=new Output();healthy.ready=true;var other=new SnapshotChannel(healthy,()->{},time::get);other.offer(bytes("independent"));assertThat(healthy.bytes.toString(StandardCharsets.UTF_8)).isEqualTo("independent");
    }
    private static byte[] bytes(String value){return value.getBytes(StandardCharsets.UTF_8);}
    static final class Output extends ServletOutputStream {
        boolean ready;final ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        @Override public boolean isReady(){return ready;}
        @Override public void setWriteListener(WriteListener listener){}
        @Override public void write(int b){if(!ready)throw new IllegalStateException();bytes.write(b);}
    }
}
