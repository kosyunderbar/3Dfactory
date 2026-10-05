package dev.factory.operations.domain;

/** A domain decision, distinct from SQL/connectivity failures. */
public final class RuleViolation extends RuntimeException {
    public final String code;
    public final boolean retry;
    public RuleViolation(String code, boolean retry) { super(code); this.code=code; this.retry=retry; }
    public static void model(boolean valid) { if(!valid) throw new RuleViolation("MODEL_INVALID",false); }
    public static void conflict(boolean valid) { if(!valid) throw new RuleViolation("BUSINESS_ID_CONFLICT",false); }
    public static void reference(boolean exists) { if(!exists) throw new RuleViolation("REFERENCE_NOT_READY",true); }
}
