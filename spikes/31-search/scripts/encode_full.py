import sys, json, time, numpy as np
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu"); m.max_seq_length = 512
rows = json.load(open(sys.argv[1])); texts=[r["body"] for r in rows]
# sort by length so batches pad less; restore order after
order = np.argsort([len(t) for t in texts]); out = np.zeros((len(texts),384), dtype=np.float32)
t0=time.time(); B=2000
for s in range(0, len(texts), B):
    idx = order[s:s+B]; out[idx] = m.encode([texts[i] for i in idx], batch_size=32)
    print(f"{s+len(idx)}/{len(texts)} {time.time()-t0:.0f}s", flush=True)
np.save(sys.argv[2], out); print("DONE", time.time()-t0, flush=True)
