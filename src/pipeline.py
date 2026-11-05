"""
Credit Capsule Pipeline

Loads reference reports → scores each in WAD-18 → commits every result
to the Cognitive State Ledger → writes logs → produces a certificate.

Run:  python3 src/pipeline.py
"""

import sys, os, json, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from credit_report import CreditReport
from score_engine  import score as compute_score
from csl           import CSL
import wad18 as W

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA     = os.path.join(ROOT, "data", "reference_reports.json")
LOG_DIR  = os.path.join(ROOT, "logs")
LEDGER   = os.path.join(ROOT, "audit", "csl_ledger.json")


def run():
    os.makedirs(LOG_DIR, exist_ok=True)
    csl = CSL(LEDGER)

    # ── BLOCK 0: GENESIS ─────────────────────────────────────────────────
    csl.append({
        "capsule":      "credit-capsule",
        "version":      "1.0.0",
        "data_source":  DATA,
        "arithmetic":   "WAD-18 exact integer (18 decimal digits)",
        "algorithm":    "S = 300 + floor(550 * (0.35P + 0.30U + 0.15A + 0.10M + 0.10I))",
        "weights":      {"P": "0.35", "U": "0.30", "A": "0.15",
                         "M": "0.10", "I": "0.10"},
        "score_range":  [300, 850],
        "network":      "DISABLED — blockchain anchoring deferred",
        "fixed_point":  "Score is a closed-form deterministic function; "
                        "E* = R(E*) satisfied by algebraic identity on first evaluation.",
    }, label="GENESIS")
    print(f"[CSL 0] Genesis.  H = {csl.root_hash()[:20]}...")

    # ── Load reports ─────────────────────────────────────────────────────
    raw = json.load(open(DATA))
    reports_data = raw["reports"]
    all_results  = []

    for rd in reports_data:
        report  = CreditReport.from_dict(rd)
        result  = compute_score(report)
        label   = rd.get("label", report.consumer_id)
        exp_min = rd.get("expected_score_min", 300)

        # ── CSL block per consumer ────────────────────────────────────────
        csl.append({
            "consumer_id":      result["consumer_id"],
            "label":            label,
            "score_int":        result["score_int"],
            "composite_str":    result["composite_str"],
            "P_str":            result["P_str"],
            "U_str":            result["U_str"],
            "A_str":            result["A_str"],
            "M_str":            result["M_str"],
            "I_str":            result["I_str"],
            "weights_sum_one":  result["weights_sum_to_one"],
            "expected_min":     exp_min,
            "meets_expected":   result["score_int"] >= exp_min,
            "n_tradelines":     result["n_tradelines"],
            "utilization_pct":  (
                round(100 * result["total_balance_cents"] /
                      max(1, result["total_limit_cents"]), 1)
                if result["total_limit_cents"] > 0 else 0
            ),
        }, label=label)

        result["expected_min"]  = exp_min
        result["meets_expected"]= result["score_int"] >= exp_min
        all_results.append(result)

        print(f"  [{label}]  score={result['score_int']}  "
              f"Φ={result['composite_str']}  "
              f"({'✓' if result['meets_expected'] else '✗'} ≥{exp_min})")

    # ── FINAL BLOCK: summary ──────────────────────────────────────────────
    all_pass = all(r["meets_expected"] for r in all_results)
    csl.append({
        "n_reports":     len(all_results),
        "all_pass":      all_pass,
        "H_final":       csl.root_hash(),
        "blockchain":    "PENDING — network disabled",
        "polygon_payload": {"data": "0x" + csl.root_hash()},
    }, label="FINALIZATION")

    # ── Write score log ───────────────────────────────────────────────────
    score_log = {
        "results":    all_results,
        "n_reports":  len(all_results),
        "all_pass":   all_pass,
        "H_final":    csl.root_hash(),
        "arithmetic": "WAD-18",
    }
    json.dump(score_log,
              open(os.path.join(LOG_DIR, "scores.json"), "w"),
              indent=2, sort_keys=True)

    print(f"\n{'='*55}")
    print(f"  Reports:  {len(all_results)}")
    print(f"  All pass: {all_pass}")
    print(f"  H_final:  {csl.root_hash()[:32]}...")
    print(f"{'='*55}")

    return score_log


if __name__ == "__main__":
    run()
