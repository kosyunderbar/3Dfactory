package dev.factory.operations.configuration;

import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** A web-only scaffold must never advertise database readiness. */
@Component("bootstrap")
@Profile("bootstrap")
public class BootstrapHealthIndicator implements HealthIndicator {
    @Override
    public Health health() {
        return Health.outOfService().build();
    }
}
