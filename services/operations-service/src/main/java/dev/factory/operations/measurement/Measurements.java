package dev.factory.operations.measurement;

import java.io.*;
import java.nio.file.*;

/** Opt-in local measurement, disabled by default. No protocol fields or business writes. */
public final class Measurements {
    private static final String PATH=System.getProperty("factory.measurement.file","");
    private static BufferedWriter output;
    private static boolean failed;
    private static long rows;
    static {
        if(!PATH.isBlank()) Runtime.getRuntime().addShutdownHook(new Thread(()->{
            synchronized(Measurements.class) {try {if(output!=null)output.close();}catch(IOException ignored){}}
        },"measurement-close"));
    }
    private Measurements() {}
    public static long start(){return PATH.isBlank()?0:System.nanoTime();}
    public static void record(String phase,String run,String event,long seq,String status,long start) {
        if(start==0)return;
        interval(phase,run,event,seq,status,start,System.nanoTime(),System.currentTimeMillis());
    }
    public static synchronized void interval(String phase,String run,String event,long seq,String status,long start,long end,long wall) {
        if(start==0 || failed)return;
        try {
            if(output==null)output=Files.newBufferedWriter(Path.of(PATH),StandardOpenOption.CREATE,StandardOpenOption.APPEND);
            // Covers all twelve nominal trials, including trace overhead and retries.
            if(++rows>2000000){failed=true;output.write("LIMIT_REACHED\n");output.flush();return;}
            output.write(phase+","+run+","+event+","+seq+","+status+","+start+","+end+","+wall+","+ProcessHandle.current().pid()+"\n");
            if(rows%200==0)output.flush();
        }catch(IOException failure){failed=true;System.err.println("Measurement file unavailable; business processing continues");}
    }
}
