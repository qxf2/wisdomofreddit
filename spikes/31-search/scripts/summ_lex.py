import json, sys, statistics as st
for e in ["fts5","whoosh","jammi"]:
    L=[json.loads(l) for l in open(f"results/lex_{e}.jsonl")]; h=L[0]; R=L[1:]
    ms=sorted(r["ms"] for r in R); errs=[r for r in R if r["err"]]; zero=[r for r in R if r["n"]==0 and not r["err"]]
    ph=[r for r in R if r["phrase_hits"] is not None and r["n"]>0]
    prec = sum(r["phrase_hits"] for r in ph)/max(1,sum(r["n"] for r in ph))
    print(f"{e:7} first={h['first_query_s']*1000:.0f}ms median={st.median(ms):.1f}ms p95={ms[int(.95*len(ms))]:.1f}ms errors={len(errs)} zero={len(zero)} quoted_q={len(ph)} phrase_precision={prec:.2f} total_hits={sum(r['n'] for r in R)}")
    for r in errs[:3]: print("   err:", r["q"], r["err"][:120])
