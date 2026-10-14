# Symptoms
Critical HTTP 500 service unavailable and error rate critical; sustained 5XX requests.
# Diagnosis
Inspect read-only service error groups, dependency health and recent changes.
# Containment
Reduce simulated traffic.
# Permanent fix
Apply a reviewed simulated service configuration correction after confirming the failing dependency.
# Rollback
Restore previous reviewed configuration.
# Validation
Confirm healthy recovery events for ten minutes.