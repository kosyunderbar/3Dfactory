package dev.factory.operations.api;
public final class ApiProblem extends RuntimeException {
    public final int http;
    public final String code;
    public ApiProblem(int http,String code) { super(code);this.http=http;this.code=code; }
}
