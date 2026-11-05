"""
WAD-18: Weak Arithmetic Decidability at 18 exact decimal places.

A value is a Python int n denoting n / 10**18.  All arithmetic is exact
Python-int arithmetic.  No float is constructed anywhere in this module.

Credit-domain usage: all dollar amounts are stored as cents * 10**16,
giving 16 decimal places of subpenny precision, well within 18 digits.
A balance of $10,000.00 = 1_000_000 cents = 1_000_000 * 10**16 WAD-18.
"""

DIGITS = 18
SCALE  = 10 ** DIGITS
ONE    = SCALE
ZERO   = 0

# Credit score range constants (WAD-18)
SCORE_MIN = 300 * SCALE
SCORE_MAX = 850 * SCALE
SCORE_RANGE = (850 - 300) * SCALE   # 550


def _rhe(num, den):
    """Round-half-even: exact rational num/den → WAD-18 integer."""
    if den <= 0:
        raise ValueError("denominator must be positive; got %r" % den)
    q, r = divmod(num, den)
    twice = 2 * r
    if twice > den or (twice == den and (q & 1)):
        q += 1
    return q


def from_str(s):
    """Parse a decimal literal '-9.2' → WAD-18 int."""
    s = s.strip()
    neg = s.startswith("-")
    if neg or s.startswith("+"):
        s = s[1:]
    if "." in s:
        whole, frac = s.split(".", 1)
    else:
        whole, frac = s, ""
    if len(frac) > DIGITS:
        raise ValueError("more than 18 decimal places: %r" % s)
    if not (whole + frac).isdigit() and (whole + frac) != "":
        raise ValueError("not a decimal literal: %r" % s)
    v = int(whole or "0") * SCALE + int((frac + "0" * DIGITS)[:DIGITS] or "0")
    return -v if neg else v


def from_int(i):
    return int(i) * SCALE


def from_cents(cents):
    """Convert integer cents to WAD-18.  $10.00 = 1000 cents."""
    return int(cents) * (SCALE // 100)


def to_str(x, places=4):
    neg = x < 0
    x   = -x if neg else x
    whole, frac = divmod(x, SCALE)
    body = "%d.%0*d" % (whole, DIGITS, frac)
    if places < DIGITS:
        body = body[:-(DIGITS - places)]
    return ("-" + body) if neg else body


def to_score_int(x):
    """Convert WAD-18 credit score to integer in [300, 850]."""
    return int(x // SCALE)


def mul(a, b):
    neg = (a < 0) != (b < 0)
    m   = _rhe(abs(a) * abs(b), SCALE)
    return -m if neg else m


def div(a, b):
    if b == 0:
        raise ZeroDivisionError("WAD-18 division by zero")
    neg = (a < 0) != (b < 0)
    m   = _rhe(abs(a) * SCALE, abs(b))
    return -m if neg else m


def clamp(x, lo, hi):
    """Clamp x to [lo, hi] in WAD-18."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def assert_wad(*xs):
    for x in xs:
        if isinstance(x, float):
            raise TypeError("float in WAD-18 path: %r" % (x,))
        if not isinstance(x, int):
            raise TypeError("not a WAD-18 value: %r" % (x,))
    return True
