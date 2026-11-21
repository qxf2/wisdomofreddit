"""Build FTS5, Whoosh, Jammi-BM25 over the same stories; report time + size."""
import sys, os, time, shutil, sqlite3, subprocess, json
which, parquet, out = sys.argv[1], sys.argv[2], sys.argv[3]
def du(p): return int(subprocess.check_output(["du","-sk",p]).split()[0])/1024
def load():
    import pyarrow.parquet as pq
    return pq.read_table(parquet).select(["id","body"]).to_pylist()
if which == "fts5":
    rows = json.load(open(parquet))  # json rows when called from whoosh venv
    if os.path.exists(out): os.remove(out)
    con = sqlite3.connect(out); t=time.time()
    con.execute("create virtual table fts using fts5(id UNINDEXED, body, tokenize='porter unicode61')")
    con.executemany("insert into fts(id,body) values(?,?)", [(r["id"], r["body"]) for r in rows]); con.commit()
    print(json.dumps({"engine":"fts5","rows":len(rows),"build_s":time.time()-t,"size_mb":os.path.getsize(out)/2**20}))
elif which == "whoosh":
    rows = json.load(open(parquet))
    from whoosh import index
    from whoosh.fields import Schema, ID, TEXT
    from whoosh.analysis import StemmingAnalyzer
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out); t=time.time()
    ix = index.create_in(out, Schema(id=ID(stored=True), comment=TEXT(stored=True, analyzer=StemmingAnalyzer())), indexname="wor")
    w = ix.writer(limitmb=256)
    for r in rows: w.add_document(id=r["id"], comment=r["body"])
    w.commit()
    print(json.dumps({"engine":"whoosh","rows":len(rows),"build_s":time.time()-t,"size_mb":du(out)}))
elif which == "jammi":
    import jammi, pyarrow.parquet as pq
    shutil.rmtree(out, ignore_errors=True)
    db = jammi.connect("file://"+out); db.add_source("stories", url=parquet, format="parquet")
    before = du(out); t=time.time()
    db.build_lexical_index("stories", columns=["body"], key="id")
    b = time.time()-t; t=time.time(); db.build_lexical_index("stories", columns=["body"], key="id")
    print(json.dumps({"engine":"jammi_bm25","rows":pq.read_metadata(parquet).num_rows,"build_s":b,"rebuild_s":time.time()-t,"size_mb_after_two_builds":du(out)-before}))
