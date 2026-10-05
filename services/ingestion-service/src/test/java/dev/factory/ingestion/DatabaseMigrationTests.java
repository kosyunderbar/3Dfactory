package dev.factory.ingestion;

import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

@EnabledIfEnvironmentVariable(named = "FACTORY_DATABASE_TESTS", matches = "true")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE, properties = {"debug=false", "factory.tcp.enabled=false", "factory.delivery.enabled=false", "management.endpoint.health.group.readiness.include=readinessState,db"},
        useMainMethod = SpringBootTest.UseMainMethod.ALWAYS)
class DatabaseMigrationTests {
    @Autowired private JdbcTemplate jdbc;
    @Autowired private Flyway flyway;
    @Autowired private Environment environment;

    @Test
    void migrationsPreserveDataAndAppCanOnlyWriteItsOwnDatabase() throws Exception {
        assertThat(flyway.info().applied()).hasSize(2);
        assertThat(jdbc.queryForObject("SELECT current_database()", String.class)).isEqualTo("ingestion_db");
        assertThat(jdbc.queryForObject("SELECT current_user", String.class)).isEqualTo("ingestion_app");
        assertThat(jdbc.queryForObject("SELECT rolname FROM pg_roles WHERE rolname=current_user AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls", String.class)).isEqualTo("ingestion_app");
        String runId = "run-20261005-" + UUID.randomUUID().toString().replace("-", "");
        jdbc.update("INSERT INTO delivery_stream (run_id,source_id) VALUES (?, 'simulator-01')", runId);
        try {
            assertThat(flyway.migrate().migrationsExecuted).isZero();
            assertThat(jdbc.queryForObject("SELECT count(*) FROM delivery_stream WHERE run_id=?", Integer.class, runId)).isEqualTo(1);
            String ownUrl = environment.getRequiredProperty("INGESTION_DB_URL");
            String username = environment.getRequiredProperty("INGESTION_DB_USERNAME");
            String password = environment.getRequiredProperty("INGESTION_DB_PASSWORD");
            for (String database : new String[] {"operations_db", "postgres"}) {
                SQLException failure = assertThrows(SQLException.class, () -> {
                    try (var connection = DriverManager.getConnection(ownUrl.replace("/ingestion_db", "/" + database), username, password)) {
                        throw new AssertionError("Unexpected cross-database connection");
                    }
                });
                assertThat(failure.getSQLState()).isEqualTo("42501");
            }
            assertThat(jdbc.queryForObject("SELECT has_schema_privilege(current_user,'public','CREATE')", Boolean.class)).isFalse();
            assertThat(jdbc.queryForObject("SELECT has_table_privilege(current_user,'flyway_schema_history','UPDATE')", Boolean.class)).isFalse();
            try (var connection = DriverManager.getConnection(ownUrl, username, password);
                    var statement = connection.createStatement()) {
                SQLException denied = assertThrows(SQLException.class,
                        () -> statement.execute("CREATE TABLE public.permission_probe (id integer)"));
                assertThat(denied.getSQLState()).isEqualTo("42501");
            }
        } finally {
            jdbc.update("DELETE FROM delivery_stream WHERE run_id=?", runId);
        }
    }
}
