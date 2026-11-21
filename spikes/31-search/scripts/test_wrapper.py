import time, json, os, sys, sqlite3, statistics as st, wor_search, jammi
rows = [(r["id"], r["body"]) for r in json.load(open("data/stories.json"))]
qs = [l.strip() for l in open("/Volumes/Expansion/code/wisdomofreddit/random_queries.txt") if l.strip()]
body = dict(rows)
for mult in (1, 4):
    R = [(f"{i}_{m}" if mult > 1 else i, b) for m in range(mult) for i, b in rows]
    t = time.time(); ix = wor_search.Bm25(R); b = time.time() - t
    ms = []
    for q in qs:
        t = time.time(); hits = ix.search(q, 25)
        _ = [body[h[0].rsplit("_",1)[0] if mult>1 else h[0]] for h in hits]   # hydrate from a dict (stands in for sqlite by id)
        ms.append((time.time() - t) * 1000)
    ms.sort()
    print(json.dumps({"rows": len(ix), "build_s": round(b, 2), "query_ms_median": round(st.median(ms), 2), "query_ms_p95": round(ms[int(.95*len(ms))], 2)}))
ix = wor_search.Bm25(rows)
db = jammi.connect("file://" + os.path.abspath("idx/jammi_lex"))
same = 0
for q in qs[:40]:
    a = [h[0] for h in ix.search(q, 10)]
    t = db.lexical_search("stories", text=q, k=10, select=["id"])
    b = t.column("id").to_pylist() if t.num_rows else []
    same += a == b
print("identical top-10 vs Jammi python lexical_search:", same, "/ 40")
print("rrf:", wor_search.rrf([["a","b"],["b","c"]]))
