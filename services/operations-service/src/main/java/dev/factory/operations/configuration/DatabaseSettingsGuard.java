package dev.factory.operations.configuration;

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
                "OPERATIONS_DB_URL", "OPERATIONS_DB_USERNAME", "OPERATIONS_DB_PASSWORD",
                "OPERATIONS_MIGRATION_USERNAME", "OPERATIONS_MIGRATION_PASSWORD"
        }).filter(key -> {
            String value = environment.getProperty(key);
            return value == null || value.isBlank();
        }).toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("operations-service: missing required DB settings: "
                    + String.join(", ", missing));
        }
        if (!environment.getRequiredProperty("OPERATIONS_DB_URL").startsWith("jdbc:postgresql:")) {
            throw new IllegalStateException("operations-service: OPERATIONS_DB_URL must use jdbc:postgresql:");
        }
    }
}
