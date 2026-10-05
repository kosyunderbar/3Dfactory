import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/** Container probe: exit code only, no response/configuration logging. */
public final class HttpProbe {
    public static void main(String[] args) {
        try {
            var request = HttpRequest.newBuilder(URI.create(args[0]))
                .timeout(Duration.ofSeconds(3)).GET().build();
            var client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            var response = client.send(request, HttpResponse.BodyHandlers.discarding());
            System.exit(response.statusCode() == 200 ? 0 : 1);
        } catch (Exception exception) {
            System.exit(1);
        }
    }
}
