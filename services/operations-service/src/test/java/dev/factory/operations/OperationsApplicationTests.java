package dev.factory.operations;

import javax.sql.DataSource;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        useMainMethod = SpringBootTest.UseMainMethod.ALWAYS)
@ActiveProfiles("bootstrap")
class OperationsApplicationTests {
    @Autowired
    private WebServerApplicationContext context;

    @Test
    void bootstrapStartsItsOwnWebServerWithoutPretendingDatabaseIsReady() throws Exception {
        assertThat(context.getEnvironment().getProperty("spring.application.name"))
                .isEqualTo("operations-service");
        assertThat(context.getWebServer().getPort()).isPositive();
        assertThat(context.getBeansOfType(DataSource.class)).isEmpty();
        assertThat(context.getBeansOfType(Flyway.class)).isEmpty();
        var client = HttpClient.newHttpClient();
        String base = "http://127.0.0.1:" + context.getWebServer().getPort();
        var readiness = client.send(HttpRequest.newBuilder(URI.create(base + "/readyz")).GET().build(),
                HttpResponse.BodyHandlers.ofString());
        var liveness = client.send(HttpRequest.newBuilder(URI.create(base + "/livez")).GET().build(),
                HttpResponse.BodyHandlers.discarding());
        assertThat(readiness.statusCode()).isEqualTo(503);
        assertThat(readiness.body()).contains("OUT_OF_SERVICE");
        assertThat(liveness.statusCode()).isEqualTo(200);
    }
}
