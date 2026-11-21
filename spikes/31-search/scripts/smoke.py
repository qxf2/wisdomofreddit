import sys, time, shutil, jammi
src, store = sys.argv[1], sys.argv[2]
shutil.rmtree(store, ignore_errors=True)
db = jammi.connect("file://" + store)
M = "sentence-transformers/all-MiniLM-L6-v2"
db.add_source("stories", url=src, format="parquet")
t=time.time(); lt = db.build_lexical_index("stories", columns=["body"], key="id"); print("lex", lt, time.time()-t)
t=time.time(); et = db.generate_embeddings(source="stories", model=M, columns=["body"], key="id"); print("emb", et, time.time()-t)
for q in ['harry potter', '"harry potter"', 'worst job interview ever']:
    lx = db.lexical_search("stories", text=q, k=3)
    print("LEX", q, lx.column_names, [r["id"] for r in lx.to_pylist()])
    v = db.encode_query(model=M, query=q)
    vs = db.search("stories", query=v, k=3)
    print("VEC", q, vs.column_names, [(r.get("id"), r.get("_row_id")) for r in vs.to_pylist()])
print(db.rrf_fuse([["a","b"],["b","c"]]))
