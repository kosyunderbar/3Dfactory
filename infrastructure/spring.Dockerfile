FROM eclipse-temurin:21.0.12.1_1-jdk-noble@sha256:70898f0f893a6b772a0f29834d8b022e3ac20b6a0c33a922973cf66342ef56be AS build
RUN apt-get update && apt-get install -y --no-install-recommends unzip && rm -rf /var/lib/apt/lists/*
ARG SERVICE
WORKDIR /build
COPY services/${SERVICE}/ ./
RUN --mount=type=cache,target=/root/.m2,sharing=locked ./mvnw -B -DskipTests package
COPY infrastructure/healthcheck/HttpProbe.java /probe/HttpProbe.java
RUN javac -d /probe /probe/HttpProbe.java

FROM eclipse-temurin:21.0.12.1_1-jre-noble@sha256:22138efd69393501fccd8176ae16b01791ed71ff801b28f0359415389b17c766
WORKDIR /app
COPY --from=build /build/target/*-SNAPSHOT.jar /app/app.jar
COPY --from=build /probe/HttpProbe.class /opt/probes/HttpProbe.class
RUN mkdir -p /var/log/factory && chown 10001:10001 /var/log/factory
USER 10001:10001
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
