# Rule playbooks

Proven fixes for common rules. These are guidance: always check the actual code.

## java/sql-injection (CodeQL), java:S3649 / java:S2077 (Sonar)
**Fix:** replace string concatenation with a `PreparedStatement` and `?` bind parameters
(`ps.setString(1, value)`). Keep try-with-resources for the statement and the `ResultSet`. If
table or column names are dynamic, validate them against an allowlist; you cannot bind them.
**Test:** if H2 is on the test classpath, use `jdbc:h2:mem:<name>;DB_CLOSE_DELAY=-1`, create the
table, and insert synthetic rows. Assert that a normal ID returns its rows and that an injection
payload such as `"x' OR '1'='1"` returns **no** rows.
**Risk:** low.

## java:S2245 (Sonar), java/insecure-randomness (CodeQL)
**Fix:** `java.util.Random` → `java.security.SecureRandom` (a single instance in a field is fine,
and it is thread-safe). Change only the type and the import. Keep the output format the same.
**Test:** keep or extend the format test. Optionally check that values are not constant across
calls. Do not test "randomness" statistically.
**Risk:** low.

## java:S108 / java:S1166 / java:S2486 (Sonar): empty or swallowed catch
**Fix:** do not leave the block empty. Either rethrow as a meaningful unchecked exception with the
cause (`throw new IllegalArgumentException("Invalid patientPay: " + value, e)`), or handle it
explicitly if the method's contract says invalid input has a defined result. In that case, add a
comment explaining why, plus logging if a logger already exists in the class.
**Test:** `assertThrows(IllegalArgumentException.class, ...)` for invalid input, plus a
valid-input case that keeps the existing behaviour.
**Risk:** medium (invalid input now throws instead of returning a default). Say so in the review.

## java:S2095 (Sonar): resources not closed
**Fix:** try-with-resources. **Test:** exercise the path. **Risk:** low.

## java:S1192 (Sonar): duplicated string literals
**Fix:** a `private static final` constant in the same class. **Test:** the existing tests are
enough. **Risk:** low.

## java/path-injection (CodeQL)
**Fix:** resolve the path against a fixed base directory, `normalize()` it, and reject it unless
`resolved.startsWith(base)`. **Test:** `../` input is rejected and a normal name works.
**Risk:** medium.
