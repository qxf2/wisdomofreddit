import sys, time, shutil, jammi
src, store, n = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.rmtree(store, ignore_errors=True)
db = jammi.connect("file://" + store)
db.add_source("s", url=src, format="parquet")
t=time.time(); db.generate_embeddings(source="s", model="sentence-transformers/all-MiniLM-L6-v2", columns=["body"], key="id"); print(n, "rows emb secs", time.time()-t)
