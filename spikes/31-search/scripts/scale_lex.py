import sys, os, time, shutil, json, jammi, pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
mult = int(sys.argv[1]); base = pq.read_table("data/stories.parquet")
src = f"data/stories_x{mult}.parquet"
if not os.path.exists(src):
    parts = [base.set_column(0, "id", pc.binary_join_element_wise(base.column("id"), pa.scalar(f"_{i}"), "")) for i in range(mult)]
    pq.write_table(pa.concat_tables(parts), src)
store = os.path.abspath(f"idx/jammi_lex_x{mult}"); shutil.rmtree(store, ignore_errors=True)
db = jammi.connect("file://" + store); db.add_source("s", url=os.path.abspath(src), format="parquet")
r = {"rows": pq.read_metadata(src).num_rows}
t=time.time(); db.build_lexical_index("s", columns=["body"], key="id"); r["build_s"]=time.time()-t
t=time.time(); db.lexical_search("s", text="dentist", k=25); r["first_query_s"]=time.time()-t
ts=[]
for q in ["dentist here","night shift nurse","harry potter","worst job interview","my grandmother"]:
    t=time.time(); db.lexical_search("s", text=q, k=25, select=["id"]); ts.append((time.time()-t)*1000)
r["query_ms"]=[round(x) for x in ts]
print(json.dumps(r))
