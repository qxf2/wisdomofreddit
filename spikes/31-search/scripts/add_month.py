"""Can Jammi add new rows incrementally? Source = a parquet file we grow; then refresh."""
import sys, os, time, shutil, json, jammi, pyarrow.parquet as pq, pyarrow as pa
base_n, add_n, store = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
M = "sentence-transformers/all-MiniLM-L6-v2"
full = pq.read_table("data/stories.parquet")
shutil.rmtree(store, ignore_errors=True); os.makedirs(store)
src = os.path.join(store, "src.parquet"); pq.write_table(full.slice(0, base_n), src)
db = jammi.connect("file://" + os.path.join(store, "db"))
db.add_source("s", url=src, format="parquet")
t=time.time(); et = db.generate_embeddings(source="s", model=M, columns=["body"], key="id"); base_s=time.time()-t
db.build_lexical_index("s", columns=["body"], key="id")
new = full.slice(base_n, add_n); probe = new.column("id")[0].as_py(); probe_text = new.column("body")[0].as_py()
pq.write_table(full.slice(0, base_n + add_n), src)   # "a new month arrives"
r = {"base_rows": base_n, "base_embed_s": base_s, "added_rows": add_n}
try:
    t=time.time(); rep = db.refresh_embeddings(et); r["refresh_s"]=time.time()-t; r["refresh_report"]=rep
except Exception as e: r["refresh_error"]=repr(e)[:400]
t=time.time(); db.build_lexical_index("s", columns=["body"], key="id"); r["lexical_rebuild_s"]=time.time()-t
v = db.search("s", row_key=probe, k=3) if False else db.search("s", query=db.encode_query(model=M, query=probe_text), k=3)
r["new_row_found_by_vector"] = probe in v.column("id").to_pylist()
lx = db.lexical_search("s", text=" ".join(probe_text.split()[:30]), k=5)
r["new_row_found_by_bm25"] = probe in lx.column("id").to_pylist()
print(json.dumps(r, default=str, indent=1))
