"""Vector-search latency vs corpus size, using imported vectors (random or real)."""
import sys, os, time, shutil, json, numpy as np, jammi, pyarrow as pa, pyarrow.parquet as pq
src, vecs, store = os.path.abspath(sys.argv[1]), sys.argv[2], os.path.abspath(sys.argv[3])
ids = pq.read_table(src, columns=["id"]).column("id").to_pylist()
V = np.load(vecs) if vecs != "random" else np.random.default_rng(0).standard_normal((len(ids),384)).astype(np.float32)
V = np.tile(V, (len(ids)//len(V),1)) if len(V) < len(ids) else V
shutil.rmtree(store, ignore_errors=True); os.makedirs(store)
vp = os.path.join(store, "vectors.parquet")
pq.write_table(pa.table({"_row_id": ids, "vector": pa.FixedSizeListArray.from_arrays(pa.array(V.ravel()), 384)}), vp)
db = jammi.connect("file://" + os.path.join(store, "db")); db.add_source("s", url=src, format="parquet")
r = {"rows": len(ids)}
t=time.time(); db.import_embeddings(source="s", model="sentence-transformers/all-MiniLM-L6-v2", vectors_url=vp, key="id", text_columns=["body"], dimensions=384); r["import_s"]=time.time()-t
q = V[7].tolist()
t=time.time(); db.search("s", query=q, k=25); r["first_query_s"]=time.time()-t
ts=[]
for i in range(5):
    t=time.time(); db.search("s", query=V[100+i].tolist(), k=25, select=["id"]); ts.append((time.time()-t)*1000)
r["query_ms"]=[round(x) for x in ts]
os.makedirs("results", exist_ok=True)
r["disk_mb"] = round(sum(os.path.getsize(os.path.join(d,f)) for d,_,fs in os.walk(os.path.join(store,"db")) for f in fs)/2**20,1)
print(json.dumps(r))
