"""
Cognitive State Ledger (CSL) — append-only SHA-256 block chain.

Identical contract to the R3 and GPCR-ACE capsules.
Every credit score computation is a signed CSL block.
"""

import hashlib, json, os
from datetime import datetime, timezone

GENESIS_PREV = "0" * 64


class IntegrityError(Exception):
    pass


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _block_hash(i, T_i, S_i, H_prev):
    payload = _canon({"H_prev": H_prev, "S_i": S_i, "T_i": T_i, "i": i})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CSL:
    def __init__(self, path):
        self.path    = path
        self._blocks = []
        if os.path.exists(path):
            with open(path) as fh:
                content = fh.read().strip()
            if content:
                self._blocks = json.loads(content)
                self._verify()

    def append(self, state: dict, label: str = "") -> dict:
        i      = len(self._blocks)
        T_i    = datetime.now(timezone.utc).isoformat()
        H_prev = self._blocks[-1]["H_i"] if self._blocks else GENESIS_PREV
        S_i    = dict(state)
        if label:
            S_i["_label"] = label
        H_i    = _block_hash(i, T_i, S_i, H_prev)
        block  = {"H_i": H_i, "H_prev": H_prev, "S_i": S_i, "T_i": T_i, "i": i}
        self._blocks.append(block)
        self._flush()
        return block

    def root_hash(self) -> str:
        if not self._blocks:
            return GENESIS_PREV
        return self._blocks[-1]["H_i"]

    def verify(self):
        self._verify()
        return True

    def blocks(self):
        return list(self._blocks)

    def _verify(self):
        prev = GENESIS_PREV
        for blk in self._blocks:
            expected = _block_hash(blk["i"], blk["T_i"], blk["S_i"], prev)
            if expected != blk["H_i"]:
                raise IntegrityError(
                    "Hash mismatch at block %d" % blk["i"])
            if blk["H_prev"] != prev:
                raise IntegrityError(
                    "H_prev mismatch at block %d" % blk["i"])
            prev = blk["H_i"]

    def _flush(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(self._blocks, fh, sort_keys=True, indent=2)
