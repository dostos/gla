#!/usr/bin/env python3
"""Round 6 deeper analysis: token deltas, pair-wise cost deltas, CLI usage."""
import json, re
from pathlib import Path
from collections import defaultdict

R6 = Path("/tmp/eval_round6")
R5 = Path("/tmp/eval_round5")


def find_diag(text: str):
    if not text: return {}
    cands = re.findall(r"\{[\s\S]*?\}", text)
    for c in reversed(cands):
        try:
            d = json.loads(c)
            if isinstance(d, dict) and "root_cause" in d:
                return d
        except Exception:
            pass
    return {}


def load_runs(root: Path):
    rows = {}
    for f in sorted(root.glob("*.json")):
        name = f.stem
        m = re.match(r"^(.*?)_(code_only|with_gpa)_(haiku|sonnet)$", name)
        if not m:
            continue
        scen, mode, model = m.group(1), m.group(2), m.group(3)
        try:
            w = json.loads(f.read_text())
        except Exception:
            continue
        usage = w.get("usage", {}) or {}
        result = w.get("result", "") or ""
        diag = find_diag(result)
        rows[(scen, mode, model)] = dict(
            scenario=scen, mode=mode, model=model,
            cost=float(w.get("total_cost_usd") or 0),
            turns=int(w.get("num_turns") or 0),
            cache_read=int(usage.get("cache_read_input_tokens") or 0),
            cache_create=int(usage.get("cache_creation_input_tokens") or 0),
            input=int(usage.get("input_tokens") or 0),
            output=int(usage.get("output_tokens") or 0),
            self_gpa_queries=int(diag.get("gpa_queries_made") or 0),
            self_files_opened=int(diag.get("framework_files_opened") or 0),
            duration_ms=int(w.get("duration_ms") or 0),
        )
    return rows


def agg(rows, mode, model):
    xs = [r for r in rows.values() if r["mode"] == mode and r["model"] == model]
    n = len(xs) or 1
    return dict(
        n=len(xs),
        cost_avg=sum(r["cost"] for r in xs)/n,
        turns_avg=sum(r["turns"] for r in xs)/n,
        cache_read_avg=sum(r["cache_read"] for r in xs)/n,
        cache_create_avg=sum(r["cache_create"] for r in xs)/n,
        input_avg=sum(r["input"] for r in xs)/n,
        output_avg=sum(r["output"] for r in xs)/n,
        gpa_q_avg=sum(r["self_gpa_queries"] for r in xs)/n,
        files_avg=sum(r["self_files_opened"] for r in xs)/n,
    )


def pair_cost_deltas(rows, model):
    out = []
    scenarios = {r["scenario"] for r in rows.values()}
    for s in sorted(scenarios):
        a = rows.get((s, "code_only", model))
        b = rows.get((s, "with_gpa", model))
        if a and b:
            out.append((s, b["cost"] - a["cost"], b["cache_read"] - a["cache_read"]))
    return out


def main():
    r6 = load_runs(R6)
    r5 = load_runs(R5)
    print(f"R6 runs: {len(r6)}  R5 runs: {len(r5)}")
    total_cost_r6 = sum(r["cost"] for r in r6.values())
    print(f"R6 total cost: ${total_cost_r6:.2f}")
    print()

    print("## Per-mode averages (R6)")
    hdr = f"{'mode':<10}{'model':<8}{'n':>3}{'cost':>8}{'turns':>7}{'cache_r':>10}{'cache_c':>10}{'files':>7}{'gpa_q':>7}"
    print(hdr)
    for mode in ("code_only","with_gpa"):
        for model in ("haiku","sonnet"):
            a = agg(r6, mode, model)
            print(f"{mode:<10}{model:<8}{a['n']:>3}{a['cost_avg']:>8.3f}{a['turns_avg']:>7.1f}{int(a['cache_read_avg']):>10d}{int(a['cache_create_avg']):>10d}{a['files_avg']:>7.1f}{a['gpa_q_avg']:>7.1f}")

    print()
    print("## Per-mode averages (R5, reference)")
    print(hdr)
    for mode in ("code_only","with_gpa"):
        for model in ("haiku","sonnet"):
            a = agg(r5, mode, model)
            print(f"{mode:<10}{model:<8}{a['n']:>3}{a['cost_avg']:>8.3f}{a['turns_avg']:>7.1f}{int(a['cache_read_avg']):>10d}{int(a['cache_create_avg']):>10d}{a['files_avg']:>7.1f}{a['gpa_q_avg']:>7.1f}")

    print()
    print("## R5 vs R6 Δ (with_gpa minus code_only)")
    print(f"{'round':<6}{'model':<8}{'Δcost':>10}{'Δturns':>9}{'Δcache_r':>12}{'Δcache_c':>12}")
    for label, rows in (("R5", r5), ("R6", r6)):
        for model in ("haiku","sonnet"):
            c = agg(rows, "code_only", model)
            g = agg(rows, "with_gpa", model)
            print(f"{label:<6}{model:<8}{(g['cost_avg']-c['cost_avg']):>+10.3f}{(g['turns_avg']-c['turns_avg']):>+9.1f}{int(g['cache_read_avg']-c['cache_read_avg']):>+12d}{int(g['cache_create_avg']-c['cache_create_avg']):>+12d}")

    print()
    print("## Pair-wise cost+cache_read deltas (with_gpa − code_only)")
    for label, rows in (("R5", r5), ("R6", r6)):
        for model in ("haiku","sonnet"):
            deltas = pair_cost_deltas(rows, model)
            cheaper = sum(1 for _,d,_ in deltas if d < 0)
            more    = sum(1 for _,d,_ in deltas if d > 0)
            total   = len(deltas)
            net_cost = sum(d for _,d,_ in deltas)
            cache_cheaper = sum(1 for _,_,c in deltas if c < 0)
            cache_more = sum(1 for _,_,c in deltas if c > 0)
            net_cache = sum(c for _,_,c in deltas)
            print(f"{label} {model}: cost cheaper {cheaper}/{total}, costlier {more}/{total}, net Δ=${net_cost:+.3f}   cache_r cheaper {cache_cheaper}/{total}, net Δ={net_cache:+d} tok")

    print()
    print("## CLI tool adoption (with_gpa runs, self-reported gpa_queries_made)")
    for model in ("haiku","sonnet"):
        xs = [r for r in r6.values() if r["mode"]=="with_gpa" and r["model"]==model]
        used = [r for r in xs if r["self_gpa_queries"]>0]
        print(f"R6 {model}: {len(used)}/{len(xs)} ran gpa; mean queries={sum(r['self_gpa_queries'] for r in xs)/max(1,len(xs)):.2f}")
        xs5 = [r for r in r5.values() if r["mode"]=="with_gpa" and r["model"]==model]
        if xs5:
            used5 = [r for r in xs5 if r["self_gpa_queries"]>0]
            print(f"R5 {model}: {len(used5)}/{len(xs5)} ran gpa; mean queries={sum(r['self_gpa_queries'] for r in xs5)/max(1,len(xs5)):.2f}")


if __name__ == "__main__":
    main()
