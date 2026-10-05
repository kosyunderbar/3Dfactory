package dev.factory.ingestion.delivery;

import java.time.Clock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.boot.autoconfigure.condition.*;
import org.springframework.boot.health.contributor.*;

@Configuration
@Profile("!bootstrap")
public class DeliveryConfiguration {
    @Bean @ConditionalOnMissingBean(Clock.class) Clock deliveryClock(){return Clock.systemUTC();}
    @Bean SourceConnections sourceConnections(){return new SourceConnections();}
    @Bean DeliveryStore deliveryStore(JdbcTemplate jdbc,PlatformTransactionManager manager,Clock clock){return new DeliveryStore(jdbc,manager,clock);}
    @Bean OperationsClient operationsClient(@Value("${factory.delivery.operations-url:http://127.0.0.1:8082}") String url){return new OperationsClient(url);}
    @Bean @ConditionalOnProperty(name="factory.delivery.enabled",havingValue="true",matchIfMissing=true)
    DeliveryWorker deliveryWorker(DeliveryStore store,OperationsClient client){return new DeliveryWorker(store,client);}
    @Bean @ConditionalOnProperty(name="factory.delivery.enabled",havingValue="true",matchIfMissing=true)
    HealthIndicator deliveryHealthIndicator(DeliveryWorker worker){return ()->worker.isRunning()?Health.up().build():Health.down().build();}
}
