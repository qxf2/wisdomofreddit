import sys, time, json
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu"); m.max_seq_length=int(sys.argv[3]) if len(sys.argv)>3 else 256
texts = json.load(open(sys.argv[1]))
print("max_seq_length", m.max_seq_length)
t=time.time(); m.encode(texts, batch_size=32); print(len(texts), "rows st secs", time.time()-t)
import numpy as np
v = m.encode(texts, batch_size=32, normalize_embeddings=True)
j = np.load(sys.argv[2]); j = j/np.linalg.norm(j,axis=1,keepdims=True)
cos = (v*j).sum(1); print("cosine jammi vs st: min %.4f median %.4f" % (cos.min(), np.median(cos)))
