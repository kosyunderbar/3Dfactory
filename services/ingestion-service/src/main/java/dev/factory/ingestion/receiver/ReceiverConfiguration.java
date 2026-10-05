package dev.factory.ingestion.receiver;

import java.nio.file.Path;
import dev.factory.ingestion.delivery.SourceConnections;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;

@Configuration
@Profile("!bootstrap")
public class ReceiverConfiguration {
    @Bean EventStore eventStore(JdbcTemplate jdbc,PlatformTransactionManager manager) { return new EventStore(jdbc,new TransactionTemplate(manager)); }
    @Bean RejectionLog rejectionLog(@Value("${factory.tcp.rejection-log:./logs/ingestion-rejections.ndjson}") String path) { return new RejectionLog(Path.of(path)); }
    @Bean @ConditionalOnProperty(name="factory.tcp.enabled",havingValue="true",matchIfMissing=true)
    TcpReceiver tcpReceiver(@Value("${factory.tcp.address:127.0.0.1}") String address,
        @Value("${factory.tcp.port:9090}") int port,EventStore store,RejectionLog log,SourceConnections sources) { return new TcpReceiver(address,port,store,log,sources); }
    @Bean @ConditionalOnProperty(name="factory.tcp.enabled",havingValue="true",matchIfMissing=true)
    HealthIndicator tcpHealthIndicator(TcpReceiver receiver) { return ()->receiver.isRunning()?Health.up().build():Health.down().build(); }
}
