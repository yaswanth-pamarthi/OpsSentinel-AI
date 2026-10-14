# Original guide coverage

Core functional requirements are mapped below. Detailed contracts and acceptance evidence are in the technical companion.

| Guide ID | Implemented process | Source | Verification |
|---|---|---|---|
| FR-01 | Monitored services and dependencies | models.py Service; /services routes | Three seeded services and service catalog UI |
| FR-02 | Paste/upload/JSON ingestion | main.py log routes; ingestion.py ingest | API replay plus upload-format browser screen and parser diagnostics |
| FR-03 | Three canonical parsers | ingestion.py normalize/redact | JSON, key=value, common text, malformed and UTC tests |
| FR-04 | Configurable detection policies | Rule model; /rules routes; RuleManager.tsx | Six enabled rules; commander authorization and threshold tests |
| FR-05 | Deduplicated alert/incident creation | detection.py evaluate/freeze | Repeated scenario evaluation produces zero duplicate alerts |
| FR-06 | Error grouping and chronology | ingestion.py signature; rca.py analyze; Log Analysis node | Grouped signatures, traces and ordered frozen event IDs |
| FR-07 | Ranked causal hypotheses | rca.py analyze; Hypothesis model | Valid event IDs, score breakdown, alternatives and missing evidence |
| FR-08 | Runbooks and historical incidents | knowledge.py; knowledge/runbook endpoints | Local nomic/pgvector retrieval; reports indexed by service/environment |
| FR-09 | Separate remediation procedures | rca.py proposal_from_knowledge; Runbook node | Risk-marked diagnosis/containment/fix/rollback/validation sections |
| FR-10 | Engineer approval/rejection/revision | /proposals/{id}/decision; graph interrupt | Authenticated human gate; execution remains false |
| FR-11 | Append-only incident history | Timeline/IncidentEvent models; migration 002 | Database-level immutable update tests and browser timeline |
| FR-12 | Final incident report and learning | Incident Report node; /report; reports.py | Validated closed incidents; PDF/DOCX downloads; historical indexing |

## Non-functional requirements and implementation choices

| Requirement | Implementation / evidence |
|---|---|
| Local zero paid API/cloud dependency | Native Ollama, local pgvector database, local files and frontend/backend. |
| Laptop performance | Measured complete real-LLM paths in execution-results.json; ingestion-benchmark.json for operations. |
| Pinned dependencies | requirements.txt and package-lock.json; Python 3.12 and Node 24. |
| Least privilege | Server JWT roles; procurement object ownership; no agent execution tools. |
| Explainability | Exact document/page/chunk/excerpt or frozen event IDs; deterministic factor/evidence scoring. |
| Reliable repeat operations | Source hashes, unique constraints, PROCESSED reuse, episode dedupe, one approval, existing report reuse. |
| Observability | Persisted runs, errors, prompt/schema versions, model metadata and node timestamps. |
| Human review and durable pause | LangGraph interrupt + Command resume with SQLite checkpoints; relational approvals. |
| Reproducibility and demo | Setup/Start/Doctor/Test scripts, sample data, screenshots, video and recorded validation. |

## Guide scope boundaries

The original documents specify local MVPs and exclude production cloud/ERP/ITSM/SSO integrations, autonomous operations, statistical anomaly models and real notifications. OCR is optional. These are described in the interview companion without inventing a deployed capability. The concrete prepared quotation extractor supports one labelled line item and flags unsupported inputs for review.

## Hardware-specific and operational choices

Qwen3 1.7B is the guide's permitted fallback for the measured 4 GB VRAM. Both projects use separate database/API/UI ports. SQLite holds durable local LangGraph checkpoints, while PostgreSQL holds relational evidence and decisions. GPU calls are serialized inside each application; run one project's inference at a time. Operations sample logs now cover 20 minutes so the ten-minute recovery gate can be exercised.

## Evidence artifacts

execution-results.json, browser-results.json, pytest-results.xml, screenshots/, demo/walkthrough.webm, source tests, pinned manifests and migration files.