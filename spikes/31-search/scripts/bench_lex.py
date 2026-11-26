"""Run random_queries.txt through one lexical engine. Output JSON lines per query."""
import sys, time, json, re, os, sqlite3
engine, qfile, out = sys.argv[1], sys.argv[2], sys.argv[3]
queries = [l.strip() for l in open(qfile) if l.strip()]
K = 25
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()
def phrase_hits(q, bodies):
    m = re.fullmatch(r'"(.+)"', q)
    if not m: return None
    p = " " + norm(m.group(1)) + " "
    return sum(p in " " + norm(b) + " " for b in bodies)
if engine == "fts5":
    con = sqlite3.connect("idx/fts5.db")
    def run(q):
        return [r[0] for r in con.execute("select body from fts where fts match ? order by bm25(fts) limit ?", (q, K))]
elif engine == "whoosh":
    from whoosh import index
    from whoosh.qparser import QueryParser
    ix = index.open_dir("idx/whoosh", indexname="wor"); s = ix.searcher(); p = QueryParser("comment", ix.schema)
    def run(q): return [h["comment"] for h in s.search(p.parse(q), limit=K)]
elif engine == "jammi":
    import jammi
    db = jammi.connect("file://" + os.path.abspath("idx/jammi_lex"))
    def run(q): return db.lexical_search("stories", text=q, k=K, select=["id","body"]).column("body").to_pylist()
t = time.time(); run("warm up query"); first = time.time() - t
for q in queries:
    try: run(q)
    except Exception: pass   # pass 1 warms caches; pass 2 is timed
with open(out, "w") as f:
    f.write(json.dumps({"engine": engine, "first_query_s": first}) + "\n")
    for q in queries:
        t = time.time()
        try: bodies = run(q); err = None
        except Exception as e: bodies, err = [], repr(e)[:200]
        dt = time.time() - t
        f.write(json.dumps({"q": q, "ms": dt*1000, "n": len(bodies), "err": err, "phrase_hits": phrase_hits(q, bodies)}) + "\n")
print(engine, "done")
