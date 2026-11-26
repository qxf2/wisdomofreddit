"""Top-10 side by side for 10 queries across five setups. Writes results/quality.json."""
import sys, os, json, sqlite3, time, jammi
lex_store, vec_store = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])  # jammi BM25 store; slim ids-only vector store
M = "sentence-transformers/all-MiniLM-L6-v2"; K = 10
Q = [('"dentist here"','kw'),('"best prank"','kw'),('"harry potter"','kw'),('"holocaust survivor"','kw'),('"in soviet russia"','kw'),
     ("frustrating day at the DMV",'writer'),("what a night shift nurse sees",'writer'),("worst job interview ever",'writer'),
     ("getting lost in a foreign country",'writer'),("the moment I knew my marriage was over",'writer')]
db = jammi.connect("file://" + lex_store); vdb = jammi.connect("file://" + vec_store)
fts = sqlite3.connect("idx/fts5.db")
body = dict(sqlite3.connect("idx/fts5.db").execute("select id, body from fts"))
def ids(t): return t.column("id").to_pylist() if t.num_rows else []
out = []
for q, kind in Q:
    try: f5 = [r[0] for r in fts.execute("select id from fts where fts match ? order by bm25(fts) limit 50", (q,))]
    except Exception as e: f5 = []
    bm = ids(db.lexical_search("stories", text=q, k=50, select=["id"]))
    vec = ids(vdb.search("s", query=vdb.encode_query(model=M, query=q.strip('"')), k=50, select=["id"]))
    hyb = [i for i,_ in db.rrf_fuse([bm, vec])]
    fv = [i for i,_ in db.rrf_fuse([f5, vec])] if f5 else vec
    lists = {"fts5": f5[:K], "jammi_bm25": bm[:K], "jammi_vector": vec[:K], "jammi_hybrid": hyb[:K], "fts5+vector_rrf": fv[:K]}
    out.append({"q": q, "kind": kind, "lists": lists})
docs = {i: body[i] for r in out for l in r["lists"].values() for i in l}
json.dump({"results": out, "docs": docs}, open("results/quality.json","w"), indent=1)
print("unique docs to judge:", len(docs))
