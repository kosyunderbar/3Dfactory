package dev.factory.ingestion;

import dev.factory.ingestion.configuration.DatabaseSettingsGuard;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class IngestionApplication {
    public static void main(String[] args) {
        SpringApplication application = new SpringApplication(IngestionApplication.class);
        application.addListeners(new DatabaseSettingsGuard());
        application.run(args);
    }
}
