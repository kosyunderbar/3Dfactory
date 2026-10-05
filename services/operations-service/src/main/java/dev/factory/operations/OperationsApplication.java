package dev.factory.operations;

import dev.factory.operations.configuration.DatabaseSettingsGuard;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class OperationsApplication {
    public static void main(String[] args) {
        SpringApplication application = new SpringApplication(OperationsApplication.class);
        application.addListeners(new DatabaseSettingsGuard());
        application.run(args);
    }
}
