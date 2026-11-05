"""
Credit report data model.

A CreditReport is a structured record of a consumer's credit history.
All monetary values are stored as integer cents to keep the model
float-free before WAD-18 conversion in the score engine.

Account types:
  revolving   — credit cards, HELOCs
  installment — auto, personal, student loans
  mortgage    — home loans
  open        — charge cards (paid in full monthly)

Payment status codes (standard Metro 2):
  OK  — paid as agreed
  30  — 30 days late
  60  — 60 days late
  90  — 90 days late
  120 — 120+ days late
  CO  — charged off
  FC  — foreclosure
"""

import json, os

ACCOUNT_TYPES = frozenset(["revolving", "installment", "mortgage", "open"])
PAYMENT_CODES = frozenset(["OK", "30", "60", "90", "120", "CO", "FC"])


class Tradeline:
    """One credit account (tradeline) on the report."""

    def __init__(self, account_id: str, account_type: str,
                 balance_cents: int, limit_cents: int,
                 opened_months_ago: int, payment_history: list,
                 is_closed: bool = False):
        if account_type not in ACCOUNT_TYPES:
            raise ValueError("unknown account type: %r" % account_type)
        for code in payment_history:
            if code not in PAYMENT_CODES:
                raise ValueError("unknown payment code: %r" % code)
        if balance_cents < 0:
            raise ValueError("balance cannot be negative")
        if limit_cents < 0:
            raise ValueError("limit cannot be negative")
        if opened_months_ago < 0:
            raise ValueError("age cannot be negative")

        self.account_id       = str(account_id)
        self.account_type     = account_type
        self.balance_cents    = int(balance_cents)
        self.limit_cents      = int(limit_cents)
        self.opened_months_ago = int(opened_months_ago)
        self.payment_history  = list(payment_history)
        self.is_closed        = bool(is_closed)

    def on_time_count(self) -> int:
        return sum(1 for p in self.payment_history if p == "OK")

    def total_payment_count(self) -> int:
        return len(self.payment_history)

    def to_dict(self) -> dict:
        return {
            "account_id":        self.account_id,
            "account_type":      self.account_type,
            "balance_cents":     self.balance_cents,
            "limit_cents":       self.limit_cents,
            "opened_months_ago": self.opened_months_ago,
            "payment_history":   self.payment_history,
            "is_closed":         self.is_closed,
        }


class HardInquiry:
    """A hard credit pull (e.g., credit application)."""

    def __init__(self, inquiry_id: str, months_ago: int):
        if months_ago < 0:
            raise ValueError("inquiry age cannot be negative")
        self.inquiry_id = str(inquiry_id)
        self.months_ago = int(months_ago)

    def to_dict(self) -> dict:
        return {"inquiry_id": self.inquiry_id, "months_ago": self.months_ago}


class CreditReport:
    """Complete credit report for one consumer."""

    def __init__(self, consumer_id: str, tradelines: list,
                 hard_inquiries: list, report_date_iso: str):
        self.consumer_id      = str(consumer_id)
        self.tradelines       = list(tradelines)
        self.hard_inquiries   = list(hard_inquiries)
        self.report_date_iso  = str(report_date_iso)

    # ── aggregate helpers (integer arithmetic only) ──────────────────────

    def total_balance_cents(self) -> int:
        return sum(t.balance_cents for t in self.tradelines
                   if not t.is_closed)

    def revolving_balance_cents(self) -> int:
        """Balance on revolving and open accounts only (used for utilisation)."""
        return sum(t.balance_cents for t in self.tradelines
                   if t.account_type in ("revolving", "open")
                   and not t.is_closed)

    def total_limit_cents(self) -> int:
        return sum(t.limit_cents for t in self.tradelines
                   if t.account_type in ("revolving", "open")
                   and not t.is_closed)

    def all_on_time(self) -> int:
        return sum(t.on_time_count() for t in self.tradelines)

    def all_payments(self) -> int:
        return sum(t.total_payment_count() for t in self.tradelines)

    def account_type_count(self) -> int:
        return len({t.account_type for t in self.tradelines})

    def weighted_avg_age_months(self) -> int:
        """Balance-weighted average age in months (integer arithmetic)."""
        if not self.tradelines:
            return 0
        total_weight = sum(max(1, t.balance_cents) for t in self.tradelines)
        if total_weight == 0:
            return sum(t.opened_months_ago for t in self.tradelines) // len(self.tradelines)
        weighted = sum(t.opened_months_ago * max(1, t.balance_cents)
                       for t in self.tradelines)
        return weighted // total_weight

    def recent_hard_inquiries(self, within_months: int = 12) -> int:
        return sum(1 for h in self.hard_inquiries
                   if h.months_ago <= within_months)

    def to_dict(self) -> dict:
        return {
            "consumer_id":    self.consumer_id,
            "report_date":    self.report_date_iso,
            "tradelines":     [t.to_dict() for t in self.tradelines],
            "hard_inquiries": [h.to_dict() for h in self.hard_inquiries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CreditReport":
        tradelines = [
            Tradeline(
                account_id       = t["account_id"],
                account_type     = t["account_type"],
                balance_cents    = t["balance_cents"],
                limit_cents      = t["limit_cents"],
                opened_months_ago= t["opened_months_ago"],
                payment_history  = t["payment_history"],
                is_closed        = t.get("is_closed", False),
            )
            for t in d.get("tradelines", [])
        ]
        inquiries = [
            HardInquiry(h["inquiry_id"], h["months_ago"])
            for h in d.get("hard_inquiries", [])
        ]
        return cls(
            consumer_id    = d["consumer_id"],
            tradelines     = tradelines,
            hard_inquiries = inquiries,
            report_date_iso= d.get("report_date", ""),
        )

    @classmethod
    def from_json(cls, path: str) -> "CreditReport":
        with open(path) as fh:
            return cls.from_dict(json.load(fh))
