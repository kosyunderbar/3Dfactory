package dev.factory.ingestion.delivery;

public final class DeliveryProblem extends RuntimeException {
    final int http;
    final String code;
    public DeliveryProblem(int http,String code){super(code);this.http=http;this.code=code;}
}
