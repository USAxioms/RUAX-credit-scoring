# RUAX-Deterministically Verifiable Credit Scoring Engine and Mutation Audit Suite using WAD18 Fixed-Point Arithmetic
**Author:** Michael Aaron Russell  
**ORCID:** 0009-0001-3360-6709  

A deterministic credit scoring and evaluation system utilizing WAD18 fixed-point arithmetic, featuring modular source engines, test suites, mutation testing frameworks, and auditable ledger logs for rigorous financial verification.

## Architecture Overview

The repository is organized into distinct functional modules ensuring zero-drift computation, strict auditability, and comprehensive test coverage:

* **`credit-capsule/src/`**: Core operational modules[span_0](start_span)[span_0](end_span)
  * **`wad18.py`**: Implements $10^{18}$ WAD fixed-point arithmetic to eliminate floating-point calculation drift[span_1](start_span)[span_1](end_span)
  * **`score_engine.py`**: Executes deterministic credit scoring algorithms[span_2](start_span)[span_2](end_span)
  * **`credit_report.py`**: Generates structured, verifiable credit reports and statements[span_3](start_span)[span_3](end_span)
  * **`pipeline.py`**: Orchestrates end-to-end evaluation and data flows[span_4](start_span)[span_4](end_span)
  * **`csl.py`**: Manages cryptographic and symbolic ledger components[span_5](start_span)[span_5](end_span)
  * **`mutation.py`**: Drives mutation testing routines for logic validation[span_6](start_span)[span_6](end_span)

* **`credit-capsule/spec/`**: Formal specifications and equivalency manifests[span_7](start_span)[span_7](end_span)
  * **`mutation_equivalents.json`**: Tracks equivalent mutants for rigorous test suite optimization[span_8](start_span)[span_8](end_span)

* **`credit-capsule/audit/`**: Immutable ledger records[span_9](start_span)[span_9](end_span)
  * **`csl_ledger.json`**: Chronological ledger ensuring verifiable audit trails[span_10](start_span)[span_10](end_span)

* **`credit-capsule/logs/`**: Execution and scoring telemetry[span_11](start_span)[span_11](end_span)
  * **`mutation.json`**: Detailed mutation test execution logs[span_12](start_span)[span_12](end_span)
  * **`scores.json`**: Historical evaluation scores and trace logs[span_13](start_span)[span_13](end_span)

* **`credit-capsule/tests/`**: Comprehensive testing suites[span_14](start_span)[span_14](end_span)
  * **`test_all.py`**: Full integration and regression test harness[span_15](start_span)[span_15](end_span)
  * **`test_survivors.py`**: Validates mutation test survival boundaries[span_16](start_span)[span_16](end_span)
  * **`test_gap_audit.py`**: Performs coverage and gap auditing on financial models[span_17](start_span)[span_17](end_span)

* **`credit-capsule/data/`**: Reference datasets[span_18](start_span)[span_18](end_span)
  * **`reference_reports.json`**: Baseline credit report benchmarks for validation[span_19](start_span)[span_19](end_span)

## License

This project is licensed under the MIT License. See the LICENSE file for details.
