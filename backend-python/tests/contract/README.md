# Java/Python contract runner

The runner sends each manifest request to both services and writes a JSON report
containing sanitized snapshots and path-specific differences.

```bash
export JAVA_BASE_URL=http://127.0.0.1:8100
export PYTHON_BASE_URL=http://127.0.0.1:8200
export CONTRACT_VISITOR_TOKEN=fixture-raw-token
export CONTRACT_SESSION_ID=fixture-session
export CONTRACT_FEATURED_ID=fixture-featured
reactor-contract tests/contract/cases/initial.json --output build/contract-report.json
```

Record a sanitized Java-only golden before an endpoint is implemented in Python:

```bash
reactor-contract tests/contract/cases/initial.json \
  --record-java --output tests/contract/golden/java-initial.json
```

SSE uses a separate runner so its termination mode, heartbeats and ordered events
remain visible. The request body must be a checked-in, non-paying local fixture:

```bash
reactor-sse-contract /local/fake-agent-stream --method POST \
  --body tests/contract/fixtures/fake-agent-request.json \
  --ignore-pointer /requestId --output build/sse-contract-report.json
```

Cases whose required fixture environment is missing are reported as skipped.
Nondeterministic JSON values must be listed per case as JSON pointers. `*` is
supported for arrays or objects; there is deliberately no global ignore list.
Cookie values are never written to reports: deterministic values use a SHA-256
fingerprint and explicitly allowlisted random values use a fixed marker. Cookie
name and attributes remain part of the comparison.

Use only the dedicated test database and local service fakes. None of the
initial cases invokes an Agent run or paid model.
