package dev.factory.operations.domain;

import java.time.Clock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.*;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;

@Configuration
@Profile("!bootstrap")
@EnableScheduling
public class OperationsConfiguration {
    @Bean @ConditionalOnMissingBean(Clock.class) Clock operationsClock() {return Clock.systemUTC();}
    @Bean TransactionTemplate operationsTransaction(PlatformTransactionManager manager) {return new TransactionTemplate(manager);}
    @Bean EventApplication eventApplication(JdbcTemplate jdbc,TransactionTemplate tx,Clock clock) {return new EventApplication(jdbc,tx,clock);}
    @Bean AlarmService alarmService(JdbcTemplate jdbc,Clock clock) {return new AlarmService(jdbc,clock);}
    @Bean DeliveryDiagnostics diagnostics(@Value("${factory.ingestion-diagnostic-url:http://127.0.0.1:8081}") String url) {return new DeliveryDiagnostics(url);}
    @Bean ViewPublisher viewPublisher(JdbcTemplate jdbc,PlatformTransactionManager manager,Clock clock,DeliveryDiagnostics diagnostics) {return new ViewPublisher(jdbc,manager,clock,diagnostics);}
    @Bean dev.factory.operations.stream.SnapshotStreams snapshotStreams(ViewPublisher views) {return new dev.factory.operations.stream.SnapshotStreams(views);}
    @Bean HistoryQueries history(JdbcTemplate jdbc,PlatformTransactionManager manager,Clock clock) {var read=new TransactionTemplate(manager);read.setReadOnly(true);read.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);return new HistoryQueries(jdbc,read,clock);}
}
