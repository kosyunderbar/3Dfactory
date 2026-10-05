package dev.factory.operations;

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
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE, properties = "debug=false",
        useMainMethod = SpringBootTest.UseMainMethod.ALWAYS)
class DatabaseMigrationTests {
    @Autowired private JdbcTemplate jdbc;
    @Autowired private Flyway flyway;
    @Autowired private Environment environment;

    @Test
    void migrationsPreserveDataAndAppCanOnlyWriteItsOwnDatabase() throws Exception {
        assertThat(flyway.info().applied()).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT current_database()", String.class)).isEqualTo("operations_db");
        assertThat(jdbc.queryForObject("SELECT current_user", String.class)).isEqualTo("operations_app");
        assertThat(jdbc.queryForObject("SELECT rolname FROM pg_roles WHERE rolname=current_user AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls", String.class)).isEqualTo("operations_app");
        String runId = "run-20261005-" + UUID.randomUUID().toString().replace("-", "");
        jdbc.update("INSERT INTO simulation_run (run_id,source_id,started_at,seed,config) VALUES (?, 'simulator-01',now(),42,'{\"purpose\":\"database-permission-probe\"}'::jsonb)", runId);
        try {
            assertThat(flyway.migrate().migrationsExecuted).isZero();
            assertThat(jdbc.queryForObject("SELECT count(*) FROM simulation_run WHERE run_id=?", Integer.class, runId)).isEqualTo(1);
            String ownUrl = environment.getRequiredProperty("OPERATIONS_DB_URL");
            String username = environment.getRequiredProperty("OPERATIONS_DB_USERNAME");
            String password = environment.getRequiredProperty("OPERATIONS_DB_PASSWORD");
            for (String database : new String[] {"ingestion_db", "postgres"}) {
                SQLException failure = assertThrows(SQLException.class, () -> {
                    try (var connection = DriverManager.getConnection(ownUrl.replace("/operations_db", "/" + database), username, password)) {
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
            jdbc.update("DELETE FROM simulation_run WHERE run_id=?", runId);
        }
    }
}
