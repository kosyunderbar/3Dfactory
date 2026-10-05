package dev.factory.ingestion.configuration;

import java.util.Arrays;
import java.util.List;

import org.springframework.boot.context.event.ApplicationEnvironmentPreparedEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.Profiles;

/** Fail before creating the connection pool; never include setting values in errors. */
public final class DatabaseSettingsGuard
        implements ApplicationListener<ApplicationEnvironmentPreparedEvent> {
    @Override
    public void onApplicationEvent(ApplicationEnvironmentPreparedEvent event) {
        ConfigurableEnvironment environment = event.getEnvironment();
        if (environment.acceptsProfiles(Profiles.of("bootstrap"))) {
            return;
        }
        List<String> missing = Arrays.stream(new String[] {
                "INGESTION_DB_URL", "INGESTION_DB_USERNAME", "INGESTION_DB_PASSWORD",
                "INGESTION_MIGRATION_USERNAME", "INGESTION_MIGRATION_PASSWORD"
        }).filter(key -> {
            String value = environment.getProperty(key);
            return value == null || value.isBlank();
        }).toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("ingestion-service: missing required DB settings: "
                    + String.join(", ", missing));
        }
        if (!environment.getRequiredProperty("INGESTION_DB_URL").startsWith("jdbc:postgresql:")) {
            throw new IllegalStateException("ingestion-service: INGESTION_DB_URL must use jdbc:postgresql:");
        }
    }
}
