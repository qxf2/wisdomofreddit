import sys, os, time, json, jammi, statistics as st
vdb = jammi.connect("file://" + os.path.abspath(sys.argv[1])); M="sentence-transformers/all-MiniLM-L6-v2"
qs=[l.strip().strip('"') for l in open(sys.argv[2]) if l.strip()]
t=time.time(); vdb.search("s", query=vdb.encode_query(model=M, query="warm up"), k=25); first=time.time()-t
enc=[]; srch=[]
for q in qs:
    t=time.time(); v=vdb.encode_query(model=M, query=q); enc.append((time.time()-t)*1000)
    t=time.time(); vdb.search("s", query=v, k=25, select=["id"]); srch.append((time.time()-t)*1000)
p95=lambda x: sorted(x)[int(.95*len(x))]
print(json.dumps({"first_query_s":first,"encode_ms_median":st.median(enc),"encode_ms_p95":p95(enc),"search_ms_median":st.median(srch),"search_ms_p95":p95(srch)}))
