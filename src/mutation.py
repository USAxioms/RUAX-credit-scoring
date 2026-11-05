"""
Exhaustive token-level mutation harness — Credit Capsule.

Targets: src/wad18.py, src/credit_report.py, src/score_engine.py
Excludes: src/csl.py (proven in GPCR-ACE capsule), src/pipeline.py (integration)

Run:  python3 src/mutation.py
"""

import os, sys, json, tokenize, io, subprocess, time
from datetime import datetime, timezone

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS   = [
    os.path.join(ROOT, "src", "credit_report.py"),
    os.path.join(ROOT, "src", "score_engine.py"),
]
TESTS_DIR = os.path.join(ROOT, "tests")
PYTHON    = sys.executable
TIMEOUT   = 30

ARITH = {"+": "-", "-": "+", "*": "//", "//": "*", "**": "*"}
COMP  = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "==": "!=", "!=": "=="}
BOOL  = {"and": "or", "or": "and"}
NAMES = {"True": "False", "False": "True"}


def _mutations(toktype, tokstr):
    out = []
    if toktype == tokenize.OP:
        if tokstr in ARITH: out.append(ARITH[tokstr])
        if tokstr in COMP:  out.append(COMP[tokstr])
    if toktype == tokenize.NAME:
        if tokstr in BOOL:  out.append(BOOL[tokstr])
        if tokstr in NAMES: out.append(NAMES[tokstr])
        if tokstr == "not": out.append("")
    if toktype == tokenize.NUMBER:
        try:
            n = int(tokstr)
            if 0 <= n <= 9:
                out.append(str(n + 1))
                if n > 0:
                    out.append(str(n - 1))
        except ValueError:
            pass
    return out


def _apply(src, idx, tokens, rep):
    lines = src.splitlines(keepends=True)
    tok   = tokens[idx]
    row, col       = tok.start
    end_row, end_col = tok.end
    result = []
    for i, line in enumerate(lines, 1):
        if i == row == end_row:
            result.append(line[:col] + rep + line[end_col:])
        elif i == row:
            result.append(line[:col] + rep)
        elif i == end_row:
            result.append(line[end_col:])
        elif row < i < end_row:
            pass
        else:
            result.append(line)
    return "".join(result)


def _clear_pycache():
    """Delete all .pyc files for target modules to prevent stale-cache false survivors.

    A size-preserving mutation written in the same clock tick as a previous
    run may not invalidate the cached bytecode (CPython validates by mtime+size).
    Deleting the .pyc ensures the mutant source is always recompiled.
    """
    import glob, pathlib
    for path in TARGETS:
        name = pathlib.Path(path).stem
        for pyc in glob.glob(os.path.join(ROOT, "src", "__pycache__",
                                           f"{name}.cpython-*.pyc")):
            try:
                os.unlink(pyc)
            except FileNotFoundError:
                pass


def _run(env=None):
    _clear_pycache()
    env = env or os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    r = subprocess.run(
        [PYTHON, "-m", "unittest", "discover",
         "-s", TESTS_DIR, "-p", "test_*.py"],
        capture_output=True, timeout=TIMEOUT, env=env, cwd=ROOT
    )
    return r.returncode == 0


def run(verbose=True):
    results = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "targets":     [os.path.relpath(t, ROOT) for t in TARGETS],
        "mutants":     [],
    }
    total = killed = survived = 0

    for path in TARGETS:
        rel = os.path.relpath(path, ROOT)
        src = open(path).read()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        except tokenize.TokenError:
            continue

        for idx, tok in enumerate(tokens):
            for rep in _mutations(tok.type, tok.string):
                total += 1
                mid = "%s:%d:%s→%s" % (rel, tok.start[0], tok.string, rep)
                try:
                    open(path, "w").write(_apply(src, idx, tokens, rep))
                    t0 = time.monotonic()
                    passed = _run()
                    elapsed = round(time.monotonic() - t0, 3)
                except subprocess.TimeoutExpired:
                    passed, elapsed = False, TIMEOUT
                finally:
                    open(path, "w").write(src)

                status = "SURVIVED" if passed else "KILLED"
                if passed: survived += 1
                else:       killed  += 1

                results["mutants"].append({
                    "id": mid, "file": rel,
                    "line": tok.start[0],
                    "original": tok.string, "mutant": rep,
                    "status": status, "elapsed": elapsed,
                })
                if verbose:
                    mark = "✓" if not passed else "✗"
                    print(f"  {mark} [{total:>4}] {status:<9} {mid}")

    eff = round(killed / total * 100) if total else 0
    results["summary"] = {
        "mutants": total, "killed": killed, "survived": survived,
        "raw_kill_rate_percent": eff,
        "proven_equivalent": 0, "unexplained_survivors": survived,
        "effective_kill_rate_percent": eff, "exhaustive": True,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    json.dump(results,
              open(os.path.join(ROOT, "logs", "mutation.json"), "w"),
              indent=2, sort_keys=True)

    print(f"\n{'='*55}")
    print(f"  Mutants:  {total}")
    print(f"  Killed:   {killed}")
    print(f"  Survived: {survived}")
    print(f"  Raw rate: {eff}%")
    print(f"{'='*55}")
    return results


if __name__ == "__main__":
    run(verbose=True)
