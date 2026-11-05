"""
Credit Capsule — comprehensive test suite.

Zero third-party dependencies beyond the standard library.
Every test is labelled with what it kills or what obligation it covers.
"""

import sys, os, json, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from credit_report import CreditReport, Tradeline, HardInquiry
from score_engine  import (
    factor_payment, factor_utilization, factor_age,
    factor_mix, factor_inquiry, composite, score_from_composite,
    score, W_SUM, W_PAYMENT, W_UTILIZATION, W_AGE, W_MIX, W_INQUIRY,
)
from csl import CSL, IntegrityError

SCALE = W.SCALE
ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _make_report(
        balance_cents=0, limit_cents=100_000,
        payment_history=None, opened_months=60,
        account_type="revolving", inquiries=0):
    tl = Tradeline(
        account_id="T1", account_type=account_type,
        balance_cents=balance_cents, limit_cents=limit_cents,
        opened_months_ago=opened_months,
        payment_history=payment_history or ["OK"] * 24,
    )
    inqs = [HardInquiry("I%d" % i, i+1) for i in range(inquiries)]
    return CreditReport("TEST", [tl], inqs, "2026-11-01")


def _empty_report():
    return CreditReport("TEST", [], [], "2026-11-01")


# ══════════════════════════════════════════════════════════
# WAD-18 arithmetic
# ══════════════════════════════════════════════════════════

class TestWAD18(unittest.TestCase):

    def test_weights_sum_to_exactly_one(self):
        """PO4. The five weights must sum to exactly ONE in WAD-18."""
        self.assertEqual(W_SUM, W.ONE)

    def test_from_cents_100_cents_is_one_dollar(self):
        """from_cents converts integer cents to WAD-18."""
        self.assertEqual(W.from_cents(100), W.ONE)

    def test_from_cents_zero(self):
        self.assertEqual(W.from_cents(0), 0)

    def test_clamp_below_lo(self):
        self.assertEqual(W.clamp(-W.ONE, W.ZERO, W.ONE), W.ZERO)

    def test_clamp_above_hi(self):
        self.assertEqual(W.clamp(2 * W.ONE, W.ZERO, W.ONE), W.ONE)

    def test_clamp_within(self):
        half = W.ONE // 2
        self.assertEqual(W.clamp(half, W.ZERO, W.ONE), half)

    def test_no_floats_in_arithmetic(self):
        with self.assertRaises(TypeError):
            W.assert_wad(0.5)

    def test_div_exact(self):
        """1 / 4 = 0.25 exactly in WAD-18."""
        result = W.div(W.ONE, W.from_int(4))
        self.assertEqual(result, W.from_str("0.250000000000000000"))

    def test_mul_half_even_rounding(self):
        self.assertEqual(W._rhe(5, 2), 2)   # 2.5 → 2 (even)
        self.assertEqual(W._rhe(7, 2), 4)   # 3.5 → 4 (even)

    def test_score_range_constants(self):
        self.assertEqual(W.to_score_int(W.SCORE_MIN), 300)
        self.assertEqual(W.to_score_int(W.SCORE_MAX), 850)


# ══════════════════════════════════════════════════════════
# Credit report model
# ══════════════════════════════════════════════════════════

class TestCreditReport(unittest.TestCase):

    def test_rejects_unknown_account_type(self):
        with self.assertRaises(ValueError):
            Tradeline("X", "savings", 0, 1000, 12, ["OK"])

    def test_rejects_unknown_payment_code(self):
        with self.assertRaises(ValueError):
            Tradeline("X", "revolving", 0, 1000, 12, ["GOOD"])

    def test_rejects_negative_balance(self):
        with self.assertRaises(ValueError):
            Tradeline("X", "revolving", -1, 1000, 12, ["OK"])

    def test_on_time_count(self):
        tl = Tradeline("X", "revolving", 0, 1000, 12,
                       ["OK", "30", "OK", "OK", "60", "OK"])
        self.assertEqual(tl.on_time_count(), 4)
        self.assertEqual(tl.total_payment_count(), 6)

    def test_total_balance_excludes_closed(self):
        open_tl   = Tradeline("A", "revolving", 50000, 100000, 12, ["OK"])
        closed_tl = Tradeline("B", "revolving", 30000, 100000, 12,
                              ["OK"], is_closed=True)
        r = CreditReport("C", [open_tl, closed_tl], [], "2026-01-01")
        self.assertEqual(r.total_balance_cents(), 50000)

    def test_total_limit_revolving_only(self):
        rev   = Tradeline("A", "revolving",    0, 100000, 12, ["OK"])
        inst  = Tradeline("B", "installment",  0, 200000, 12, ["OK"])
        r = CreditReport("C", [rev, inst], [], "2026-01-01")
        self.assertEqual(r.total_limit_cents(), 100000)

    def test_account_type_count(self):
        r = _make_report()
        self.assertEqual(r.account_type_count(), 1)

    def test_recent_inquiries_window(self):
        inqs = [HardInquiry("A", 6), HardInquiry("B", 13), HardInquiry("C", 24)]
        r = CreditReport("X", [], inqs, "2026-01-01")
        self.assertEqual(r.recent_hard_inquiries(within_months=12), 1)

    def test_roundtrip_json(self):
        r = _make_report(balance_cents=50000, limit_cents=100000)
        r2 = CreditReport.from_dict(r.to_dict())
        self.assertEqual(r2.total_balance_cents(), 50000)
        self.assertEqual(r2.total_limit_cents(), 100000)

    def test_empty_report_aggregates(self):
        r = _empty_report()
        self.assertEqual(r.total_balance_cents(), 0)
        self.assertEqual(r.total_limit_cents(), 0)
        self.assertEqual(r.all_payments(), 0)
        self.assertEqual(r.account_type_count(), 0)


# ══════════════════════════════════════════════════════════
# Sub-factors
# ══════════════════════════════════════════════════════════

class TestFactorPayment(unittest.TestCase):

    def test_all_on_time_gives_one(self):
        r = _make_report(payment_history=["OK"] * 24)
        self.assertEqual(factor_payment(r), W.ONE)

    def test_no_payments_gives_zero(self):
        """No payment history → P = 0 (unknown, not perfect).
        Thin-file consumers are handled holistically by score() which
        returns 300 immediately when no tradelines are present."""
        r = _empty_report()
        self.assertEqual(factor_payment(r), W.ZERO)

    def test_half_on_time_gives_half(self):
        r = _make_report(payment_history=["OK", "30"] * 12)
        self.assertEqual(factor_payment(r), W.div(W.from_int(12), W.from_int(24)))

    def test_zero_on_time_gives_zero(self):
        r = _make_report(payment_history=["30"] * 12)
        self.assertEqual(factor_payment(r), W.ZERO)

    def test_result_in_unit_interval(self):
        for hist in [["OK"]*24, ["30"]*24, ["OK","30"]*12]:
            r = _make_report(payment_history=hist)
            p = factor_payment(r)
            self.assertGreaterEqual(p, W.ZERO)
            self.assertLessEqual(p, W.ONE)


class TestFactorUtilization(unittest.TestCase):

    def test_zero_balance_gives_one(self):
        r = _make_report(balance_cents=0, limit_cents=100_000)
        self.assertEqual(factor_utilization(r), W.ONE)

    def test_full_utilization_gives_zero(self):
        r = _make_report(balance_cents=100_000, limit_cents=100_000)
        self.assertEqual(factor_utilization(r), W.ZERO)

    def test_half_utilization(self):
        r = _make_report(balance_cents=50_000, limit_cents=100_000)
        self.assertEqual(factor_utilization(r), W.div(W.from_int(1), W.from_int(2)))

    def test_no_revolving_limit_gives_one(self):
        """Installment accounts have no credit limit — perfect util."""
        r = _make_report(account_type="installment",
                         balance_cents=50_000, limit_cents=200_000)
        self.assertEqual(factor_utilization(r), W.ONE)

    def test_over_limit_clamped_to_zero(self):
        """Balance > limit should clamp to zero (not negative)."""
        r = _make_report(balance_cents=150_000, limit_cents=100_000)
        self.assertEqual(factor_utilization(r), W.ZERO)

    def test_result_in_unit_interval(self):
        for bal, lim in [(0, 100_000), (50_000, 100_000), (100_000, 100_000),
                         (150_000, 100_000)]:
            r = _make_report(balance_cents=bal, limit_cents=lim)
            u = factor_utilization(r)
            self.assertGreaterEqual(u, W.ZERO)
            self.assertLessEqual(u, W.ONE)


class TestFactorAge(unittest.TestCase):

    def test_120_months_gives_one(self):
        r = _make_report(opened_months=120)
        self.assertEqual(factor_age(r), W.ONE)

    def test_60_months_gives_half(self):
        r = _make_report(opened_months=60)
        self.assertEqual(factor_age(r), W.div(W.from_int(60), W.from_int(120)))

    def test_zero_months_gives_zero(self):
        r = _make_report(opened_months=0)
        self.assertEqual(factor_age(r), W.ZERO)

    def test_over_120_clamped_to_one(self):
        r = _make_report(opened_months=240)
        self.assertEqual(factor_age(r), W.ONE)

    def test_no_tradelines_gives_zero(self):
        r = _empty_report()
        self.assertEqual(factor_age(r), W.ZERO)


class TestFactorMix(unittest.TestCase):

    def test_one_type_gives_quarter(self):
        r = _make_report()
        self.assertEqual(factor_mix(r),
                         W.div(W.from_int(1), W.from_int(4)))

    def test_four_types_gives_one(self):
        tls = [
            Tradeline("A", "revolving",   0, 100_000, 60, ["OK"]),
            Tradeline("B", "installment", 0, 200_000, 60, ["OK"]),
            Tradeline("C", "mortgage",    0, 300_000, 60, ["OK"]),
            Tradeline("D", "open",        0,       0, 60, ["OK"]),
        ]
        r = CreditReport("X", tls, [], "2026-01-01")
        self.assertEqual(factor_mix(r), W.ONE)

    def test_no_tradelines_gives_zero(self):
        r = _empty_report()
        self.assertEqual(factor_mix(r), W.ZERO)

    def test_result_in_unit_interval(self):
        r = _make_report()
        m = factor_mix(r)
        self.assertGreaterEqual(m, W.ZERO)
        self.assertLessEqual(m, W.ONE)


class TestFactorInquiry(unittest.TestCase):

    def test_zero_inquiries_gives_one(self):
        r = _make_report(inquiries=0)
        self.assertEqual(factor_inquiry(r), W.ONE)

    def test_one_inquiry_reduces_by_ten_percent(self):
        r = _make_report(inquiries=1)
        expected = W.clamp(W.ONE - W.from_str("0.100000000000000000"),
                           W.ZERO, W.ONE)
        self.assertEqual(factor_inquiry(r), expected)

    def test_ten_or_more_inquiries_clamped_to_zero(self):
        r = _make_report(inquiries=10)
        self.assertEqual(factor_inquiry(r), W.ZERO)

    def test_inquiries_older_than_12m_not_counted(self):
        inqs = [HardInquiry("A", 13), HardInquiry("B", 24)]
        r = CreditReport("X", [
            Tradeline("T", "revolving", 0, 100_000, 60, ["OK"])
        ], inqs, "2026-01-01")
        self.assertEqual(factor_inquiry(r), W.ONE)

    def test_result_always_nonnegative(self):
        for n in range(15):
            r = _make_report(inquiries=n)
            self.assertGreaterEqual(factor_inquiry(r), W.ZERO)


# ══════════════════════════════════════════════════════════
# Composite and score
# ══════════════════════════════════════════════════════════

class TestComposite(unittest.TestCase):

    def test_all_ones_gives_one(self):
        phi = composite(W.ONE, W.ONE, W.ONE, W.ONE, W.ONE)
        self.assertEqual(phi, W.ONE)

    def test_all_zeros_gives_zero(self):
        phi = composite(W.ZERO, W.ZERO, W.ZERO, W.ZERO, W.ZERO)
        self.assertEqual(phi, W.ZERO)

    def test_rejects_float(self):
        with self.assertRaises(TypeError):
            composite(W.ONE, W.ONE, W.ONE, W.ONE, 0.5)

    def test_result_in_unit_interval(self):
        import random; random.seed(42)
        for _ in range(20):
            vals = [W.from_str("0.%018d" % random.randint(0, 10**18 - 1))
                    for _ in range(5)]
            phi = composite(*vals)
            self.assertGreaterEqual(phi, W.ZERO)
            self.assertLessEqual(phi, W.ONE)


class TestScoreFromComposite(unittest.TestCase):

    def test_zero_composite_gives_300(self):
        s = score_from_composite(W.ZERO)
        self.assertEqual(W.to_score_int(s), 300)

    def test_one_composite_gives_850(self):
        s = score_from_composite(W.ONE)
        self.assertEqual(W.to_score_int(s), 850)

    def test_half_composite_gives_575(self):
        s = score_from_composite(W.div(W.ONE, W.from_int(2)))
        self.assertEqual(W.to_score_int(s), 575)

    def test_score_always_in_range(self):
        for pct in range(0, 101, 10):
            phi = W.div(W.from_int(pct), W.from_int(100))
            s = score_from_composite(phi)
            si = W.to_score_int(s)
            self.assertGreaterEqual(si, 300)
            self.assertLessEqual(si, 850)


# ══════════════════════════════════════════════════════════
# PO3: Dominance — better report → higher score
# ══════════════════════════════════════════════════════════

class TestDominance(unittest.TestCase):
    """PO3: the score function is monotone in report quality."""

    def test_better_payment_history_raises_score(self):
        r_good = _make_report(payment_history=["OK"] * 24)
        r_bad  = _make_report(payment_history=["30"] * 24)
        self.assertGreater(
            score(r_good)["score_int"],
            score(r_bad)["score_int"]
        )

    def test_lower_utilization_raises_score(self):
        r_low  = _make_report(balance_cents=10_000,  limit_cents=100_000)
        r_high = _make_report(balance_cents=90_000,  limit_cents=100_000)
        self.assertGreater(
            score(r_low)["score_int"],
            score(r_high)["score_int"]
        )

    def test_older_account_raises_score(self):
        r_old  = _make_report(opened_months=120)
        r_new  = _make_report(opened_months=6)
        self.assertGreater(
            score(r_old)["score_int"],
            score(r_new)["score_int"]
        )

    def test_more_account_types_raises_score(self):
        r_one = _make_report()
        tls_four = [
            Tradeline("A", "revolving",   0, 100_000, 60, ["OK"] * 24),
            Tradeline("B", "installment", 0, 200_000, 60, ["OK"] * 24),
            Tradeline("C", "mortgage",    0, 300_000, 60, ["OK"] * 24),
            Tradeline("D", "open",        0,       0, 60, ["OK"] * 24),
        ]
        r_four = CreditReport("X", tls_four, [], "2026-01-01")
        self.assertGreater(
            score(r_four)["score_int"],
            score(r_one)["score_int"]
        )

    def test_fewer_inquiries_raises_score(self):
        r_none = _make_report(inquiries=0)
        r_many = _make_report(inquiries=5)
        self.assertGreater(
            score(r_none)["score_int"],
            score(r_many)["score_int"]
        )

    def test_empty_report_gives_minimum(self):
        """Thin file: no tradelines → score 300 (insufficient history)."""
        r = _empty_report()
        result = score(r)
        self.assertEqual(result["score_int"], 300)
        self.assertTrue(result.get("thin_file", False))


# ══════════════════════════════════════════════════════════
# PO0: Score always in [300, 850]
# ══════════════════════════════════════════════════════════

class TestScoreRange(unittest.TestCase):
    """PO0: feasible domain."""

    def test_score_range_on_reference_reports(self):
        path = os.path.join(ROOT, "data", "reference_reports.json")
        raw  = json.load(open(path))
        for rd in raw["reports"]:
            r = CreditReport.from_dict(rd)
            s = score(r)["score_int"]
            self.assertGreaterEqual(s, 300, f"{rd['consumer_id']}: score {s} < 300")
            self.assertLessEqual(s, 850,   f"{rd['consumer_id']}: score {s} > 850")

    def test_adversarial_extremes(self):
        """Score must stay in [300,850] for any valid input."""
        # Thin file (no tradelines) → minimum score 300
        r_thin = _empty_report()
        self.assertEqual(score(r_thin)["score_int"], 300)

        # Worst with tradelines: maxed out, all late, brand new, 10 inquiries.
        # M = 1/4 = 0.25 still contributes; minimum achievable with tradelines
        # is 313 (not 300), which is > 300 and in range.
        r_worst = _make_report(
            balance_cents=100_000, limit_cents=100_000,
            payment_history=["CO"] * 24, opened_months=0,
            inquiries=10)
        s_worst = score(r_worst)["score_int"]
        self.assertGreaterEqual(s_worst, 300)
        self.assertLessEqual(s_worst, 850)

        # Best possible: zero revolving balance, all on time, 10yr history,
        # 4 account types, no inquiries → score 850
        tls = [
            Tradeline("A", "revolving",   0, 100_000, 120, ["OK"] * 24),
            Tradeline("B", "installment", 0, 200_000, 120, ["OK"] * 24),
            Tradeline("C", "mortgage",    0, 300_000, 120, ["OK"] * 24),
            Tradeline("D", "open",        0,       0, 120, ["OK"] * 24),
        ]
        r_best = CreditReport("BEST", tls, [], "2026-01-01")
        self.assertEqual(score(r_best)["score_int"], 850)


# ══════════════════════════════════════════════════════════
# PO1: Reproducibility
# ══════════════════════════════════════════════════════════

class TestReproducibility(unittest.TestCase):
    """PO1: same input → same output, always."""

    def test_same_report_same_score(self):
        r = _make_report(balance_cents=30_000, limit_cents=100_000,
                         payment_history=["OK"] * 20 + ["30"] * 4,
                         opened_months=72)
        s1 = score(r)["score_int"]
        s2 = score(r)["score_int"]
        self.assertEqual(s1, s2)

    def test_score_is_deterministic_integer(self):
        r = _make_report()
        s = score(r)
        self.assertIsInstance(s["score_int"], int)
        self.assertNotIsInstance(s["score_int"], bool)


# ══════════════════════════════════════════════════════════
# PO2: Constraint satisfaction (all factors in [0,1])
# ══════════════════════════════════════════════════════════

class TestConstraints(unittest.TestCase):
    """PO2: all sub-factors in [0, 1]."""

    def test_all_factors_in_unit_interval(self):
        r = _make_report(balance_cents=50_000, limit_cents=100_000,
                         payment_history=["OK"] * 18 + ["30"] * 6,
                         opened_months=48, inquiries=2)
        for fn, name in [(factor_payment, "P"), (factor_utilization, "U"),
                         (factor_age, "A"), (factor_mix, "M"),
                         (factor_inquiry, "I")]:
            val = fn(r)
            self.assertGreaterEqual(val, W.ZERO, f"{name} < 0")
            self.assertLessEqual(val, W.ONE,    f"{name} > 1")

    def test_weights_are_nonnegative(self):
        for w in [W_PAYMENT, W_UTILIZATION, W_AGE, W_MIX, W_INQUIRY]:
            self.assertGreaterEqual(w, W.ZERO)

    def test_weights_are_at_most_one(self):
        for w in [W_PAYMENT, W_UTILIZATION, W_AGE, W_MIX, W_INQUIRY]:
            self.assertLessEqual(w, W.ONE)


# ══════════════════════════════════════════════════════════
# Reference report pinned scores
# ══════════════════════════════════════════════════════════

class TestReferenceScores(unittest.TestCase):
    """Pinned scores for the reference reports — regression guard."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, "data", "reference_reports.json")
        raw  = json.load(open(path))
        cls.results = {}
        for rd in raw["reports"]:
            r = CreditReport.from_dict(rd)
            result = score(r)
            cls.results[rd["label"]] = result

    def test_excellent_credit_above_780(self):
        self.assertGreaterEqual(self.results["excellent_credit"]["score_int"], 780)

    def test_fair_credit_above_560(self):
        self.assertGreaterEqual(self.results["fair_credit"]["score_int"], 560)

    def test_thin_file_is_300(self):
        self.assertEqual(self.results["thin_file"]["score_int"], 300)

    def test_good_credit_above_680(self):
        self.assertGreaterEqual(self.results["good_credit"]["score_int"], 680)

    def test_excellent_beats_fair(self):
        self.assertGreater(
            self.results["excellent_credit"]["score_int"],
            self.results["fair_credit"]["score_int"]
        )

    def test_excellent_beats_good(self):
        self.assertGreater(
            self.results["excellent_credit"]["score_int"],
            self.results["good_credit"]["score_int"]
        )

    def test_good_beats_fair(self):
        self.assertGreater(
            self.results["good_credit"]["score_int"],
            self.results["fair_credit"]["score_int"]
        )

    def test_weights_sum_to_one_in_all_results(self):
        for label, result in self.results.items():
            self.assertTrue(result["weights_sum_to_one"],
                            f"{label}: weights do not sum to 1")


# ══════════════════════════════════════════════════════════
# CSL audit chain
# ══════════════════════════════════════════════════════════

class TestCSL(unittest.TestCase):

    def test_chain_integrity_after_pipeline(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            csl = CSL(path)
            b0 = csl.append({"consumer": "A", "score": 720}, "genesis")
            b1 = csl.append({"consumer": "B", "score": 640}, "second")
            b2 = csl.append({"consumer": "C", "score": 580}, "third")
            self.assertTrue(csl.verify())
            self.assertEqual(b1["H_prev"], b0["H_i"])
            self.assertEqual(b2["H_prev"], b1["H_i"])
            self.assertEqual(csl.root_hash(), b2["H_i"])
        finally:
            os.unlink(path)

    def test_tamper_detection(self):
        import json as _json
        with tempfile.NamedTemporaryFile(suffix=".json",
                                         mode="w", delete=False) as f:
            path = f.name
        try:
            csl = CSL(path)
            csl.append({"score": 720})
            csl.append({"score": 640})
            blocks = _json.load(open(path))
            blocks[0]["S_i"]["score"] = 999
            _json.dump(blocks, open(path, "w"))
            with self.assertRaises(IntegrityError):
                CSL(path).verify()
        finally:
            os.unlink(path)

    def test_score_logged_to_csl(self):
        """Each score computation must produce a deterministic, hashable block."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            csl  = CSL(path)
            r    = _make_report(balance_cents=20_000, limit_cents=100_000)
            s    = score(r)
            blk  = csl.append({"score_int": s["score_int"],
                                "composite": s["composite_str"]}, "score")
            self.assertIn("H_i", blk)
            self.assertEqual(len(blk["H_i"]), 64)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
