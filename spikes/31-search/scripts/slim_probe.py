import os, time, json, jammi, numpy as np
store = os.path.abspath("idx/vec_slim_x1/db"); db = jammi.connect("file://" + store)
V = np.random.default_rng(0).standard_normal((50,384)).astype(np.float32)
def T(f):
    f(); ts=[]
    for i in range(5):
        t=time.time(); f(); ts.append((time.time()-t)*1000)
    return round(min(ts)), round(max(ts))
print("slim source, ann     ", T(lambda: db.search("s", query=V[1].tolist(), k=25, select=["id"])))
print("slim source, exact   ", T(lambda: db.search("s", query=V[1].tolist(), k=25, select=["id"], exact=True)))
