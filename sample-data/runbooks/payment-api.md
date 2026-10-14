# Symptoms
Payment upstream response slow and latency_ms above 2000.
# Diagnosis
Inspect read-only upstream latency and connection metrics; compare traced requests.
# Containment
Enable the simulated graceful degradation toggle.
# Permanent fix
Review upstream timeout configuration and retry budgets.
# Rollback
Restore previous timeout configuration.
# Validation
Confirm healthy payment responses and sustained latency recovery.
