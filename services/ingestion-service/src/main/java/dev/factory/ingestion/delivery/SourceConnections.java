package dev.factory.ingestion.delivery;

import java.net.Socket;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Only a currently open connection with an accepted report proves producer connectivity. */
public final class SourceConnections {
    private final Map<Socket,Set<String>> connections=new ConcurrentHashMap<>();
    public void opened(Socket socket){connections.put(socket,ConcurrentHashMap.newKeySet());}
    public void accepted(Socket socket,String run){var runs=connections.get(socket);if(runs!=null) runs.add(run);}
    public void closed(Socket socket){connections.remove(socket);}
    public boolean connected(String run){return connections.values().stream().anyMatch(runs->runs.contains(run));}
}
