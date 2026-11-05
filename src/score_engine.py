"""
Credit Score Engine — WAD-18 exact arithmetic throughout.

The score S ∈ {300, …, 850} is computed as:
  S = 300 + floor(550 × Φ)

where the composite factor Φ ∈ [0, 1] is a weighted sum of five
independently auditable sub-factors:

  Φ = w_P × P + w_U × U + w_A × A + w_M × M + w_I × I

Sub-factors (all in [0, 1], WAD-18):
  P — Payment history:    fraction of on-time payments
  U — Utilization factor: 1 − min(1, balance/limit)  [inverse of utilization]
  A — Age factor:         min(1, avg_age_months / 120)
  M — Mix factor:         account_type_count / 4
  I — Inquiry factor:     max(0, 1 − inquiries × 0.10)

Weights (sum to exactly 1 in WAD-18):
  w_P = 0.35
  w_U = 0.30
  w_A = 0.15
  w_M = 0.10
  w_I = 0.10

All intermediate values are WAD-18 integers.  No float is constructed.
The only integer→WAD-18 conversion sites are from_int() and from_cents();
the boundary is enforced by assert_wad() checks at the engine entry.

Special cases (all documented and tested):
  - No tradelines: Φ = 0, S = 300 (minimum score)
  - No revolving/open accounts: U = 1.0 (perfect utilization)
  - Total limit = 0: U = 1.0 (no revolving credit → no utilization penalty)
  - No payments on record: P = 1.0 (benefit of the doubt)
  - Age = 0 months: A = 0.0
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wad18 as W
from credit_report import CreditReport

# ── Weights (WAD-18) ──────────────────────────────────────────────────────

W_PAYMENT     = W.from_str("0.350000000000000000")
W_UTILIZATION = W.from_str("0.300000000000000000")
W_AGE         = W.from_str("0.150000000000000000")
W_MIX         = W.from_str("0.100000000000000000")
W_INQUIRY     = W.from_str("0.100000000000000000")

# Weight sum must equal ONE (verified in tests)
W_SUM = W_PAYMENT + W_UTILIZATION + W_AGE + W_MIX + W_INQUIRY

# Normalisation constants (WAD-18)
AGE_NORMALISER  = W.from_int(120)    # 120 months = 10 years → A = 1.0
MIX_NORMALISER  = W.from_int(4)      # 4 account types max
INQ_PENALTY     = W.from_str("0.100000000000000000")  # per inquiry
SCORE_BASE      = W.from_int(300)
SCORE_RANGE_WAD = W.from_int(550)


# ── Sub-factor computations ───────────────────────────────────────────────

def factor_payment(report: CreditReport) -> int:
    """P = on_time / total.  [WAD-18]

    If no payments are on record the consumer has no established payment
    history; this is scored as P = 0 (not 1).  A thin file is not a
    perfect payment record — it is an unknown one, and caution is the
    correct prior.  The thin-file score is determined holistically in the
    full score() function which returns SCORE_MIN immediately when no
    tradelines are present.
    """
    total = report.all_payments()
    if total == 0:
        return W.ZERO                     # no demonstrated history
    on_time = report.all_on_time()
    return W.div(W.from_int(on_time), W.from_int(total))


def factor_utilization(report: CreditReport) -> int:
    """U = 1 − min(1, revolving_balance / revolving_limit),
    or 1 if no revolving limit. [WAD-18]

    Only revolving and open account balances are compared against revolving
    limits — installment and mortgage balances are excluded.  Counting
    mortgage principal against a credit-card limit produces a spurious
    >100% utilisation that does not reflect revolving credit behaviour.
    """
    limit = report.total_limit_cents()
    if limit == 0:
        return W.ONE                      # no revolving credit → perfect
    balance = report.revolving_balance_cents()
    # raw utilization rate (clamped to [0, 1])
    raw = W.clamp(
        W.div(W.from_cents(balance), W.from_cents(limit)),
        W.ZERO, W.ONE
    )
    return W.ONE - raw                    # invert: lower util → higher factor


def factor_age(report: CreditReport) -> int:
    """A = min(1, avg_age_months / 120). [WAD-18]"""
    avg_months = report.weighted_avg_age_months()
    raw = W.div(W.from_int(avg_months), AGE_NORMALISER)
    return W.clamp(raw, W.ZERO, W.ONE)


def factor_mix(report: CreditReport) -> int:
    """M = account_type_count / 4. [WAD-18]"""
    count = report.account_type_count()
    return W.clamp(
        W.div(W.from_int(count), MIX_NORMALISER),
        W.ZERO, W.ONE
    )


def factor_inquiry(report: CreditReport) -> int:
    """I = max(0, 1 − inquiries × 0.10). [WAD-18]"""
    n = report.recent_hard_inquiries(within_months=12)
    penalty = W.mul(W.from_int(n), INQ_PENALTY)
    return W.clamp(W.ONE - penalty, W.ZERO, W.ONE)


# ── Composite score ───────────────────────────────────────────────────────

def composite(P: int, U: int, A: int, M: int, I: int) -> int:
    """Weighted composite Φ ∈ [0, 1]. All inputs and output are WAD-18."""
    W.assert_wad(P, U, A, M, I)
    phi = (W.mul(W_PAYMENT, P)
           + W.mul(W_UTILIZATION, U)
           + W.mul(W_AGE, A)
           + W.mul(W_MIX, M)
           + W.mul(W_INQUIRY, I))
    return W.clamp(phi, W.ZERO, W.ONE)


def score_from_composite(phi: int) -> int:
    """S = 300 + floor(550 × Φ), result in {300, …, 850}. [WAD-18]"""
    W.assert_wad(phi)
    raw = SCORE_BASE + W.mul(SCORE_RANGE_WAD, phi)
    return W.clamp(raw, W.SCORE_MIN, W.SCORE_MAX)


# ── Full pipeline ─────────────────────────────────────────────────────────

def score(report: CreditReport) -> dict:
    """
    Compute the full credit score for a CreditReport.

    Returns a dict with every intermediate WAD-18 value, the five
    sub-factors, the composite, and the final integer score — all
    reproducible from the report alone.
    """
    # Thin file: no tradelines → insufficient history → minimum score.
    # This is not a penalty; it is an acknowledgment that the algorithm
    # cannot evaluate what has not been demonstrated.
    if not report.tradelines:
        return {
            "consumer_id":         report.consumer_id,
            "report_date":         report.report_date_iso,
            "P_payment_wad18":     W.ZERO, "U_utilization_wad18": W.ZERO,
            "A_age_wad18":         W.ZERO, "M_mix_wad18":          W.ZERO,
            "I_inquiry_wad18":     W.ZERO,
            "P_str": "0.000000", "U_str": "0.000000", "A_str": "0.000000",
            "M_str": "0.000000", "I_str": "0.000000",
            "composite_wad18":     W.ZERO,
            "composite_str":       "0.000000",
            "score_wad18":         W.SCORE_MIN,
            "score_int":           300,
            "weight_sum_wad18":    W_SUM,
            "weights_sum_to_one":  W_SUM == W.ONE,
            "n_tradelines": 0, "n_inquiries_12m": 0,
            "total_balance_cents": 0, "total_limit_cents": 0,
            "avg_age_months": 0, "account_types": 0,
            "on_time_payments": 0, "total_payments": 0,
            "thin_file": True,
            "arithmetic": "WAD-18 exact integer throughout",
        }

    P = factor_payment(report)
    U = factor_utilization(report)
    A = factor_age(report)
    M = factor_mix(report)
    I = factor_inquiry(report)
    phi = composite(P, U, A, M, I)
    S   = score_from_composite(phi)

    return {
        "consumer_id":        report.consumer_id,
        "report_date":        report.report_date_iso,
        # sub-factors (WAD-18 strings for readability + raw integers)
        "P_payment_wad18":    P,
        "U_utilization_wad18":U,
        "A_age_wad18":        A,
        "M_mix_wad18":        M,
        "I_inquiry_wad18":    I,
        "P_str":              W.to_str(P, 6),
        "U_str":              W.to_str(U, 6),
        "A_str":              W.to_str(A, 6),
        "M_str":              W.to_str(M, 6),
        "I_str":              W.to_str(I, 6),
        # composite and score
        "composite_wad18":    phi,
        "composite_str":      W.to_str(phi, 6),
        "score_wad18":        S,
        "score_int":          W.to_score_int(S),
        # weight audit
        "weight_sum_wad18":   W_SUM,
        "weights_sum_to_one": W_SUM == W.ONE,
        # input statistics
        "n_tradelines":       len(report.tradelines),
        "n_inquiries_12m":    report.recent_hard_inquiries(12),
        "total_balance_cents":report.total_balance_cents(),
        "total_limit_cents":  report.total_limit_cents(),
        "avg_age_months":     report.weighted_avg_age_months(),
        "account_types":      report.account_type_count(),
        "on_time_payments":   report.all_on_time(),
        "total_payments":     report.all_payments(),
        "arithmetic":         "WAD-18 exact integer throughout",
    }
