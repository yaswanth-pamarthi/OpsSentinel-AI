# Symptoms
Database connection timeout, HTTP 500 request failures and rising latency.
# Diagnosis
Read-only diagnostic: SELECT count(*) FROM pg_stat_activity; Inspect configured pool utilization and session metrics.
# Containment
Reduce incoming traffic using the demo traffic toggle. Risk: reduced throughput.
# Permanent fix
Correct connection-pool sizing and redeploy reviewed configuration in the simulator.
# Rollback
Restore the previous pool configuration if validation fails.
# Validation
Confirm HTTP 5xx below 1% for 10 minutes and healthy recovery events. The MVP records synthetic recovery evidence.
