import sys, json, numpy as np
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
texts = json.load(open(sys.argv[1])); j = np.load(sys.argv[2]); j = j/np.linalg.norm(j,axis=1,keepdims=True)
ntok = [len(m.tokenizer(t)["input_ids"]) for t in texts]
for L in (128, 256, 512):
    m.max_seq_length = L
    v = m.encode(texts, batch_size=32, normalize_embeddings=True); c=(v*j).sum(1)
    print(L, "min %.4f median %.4f" % (c.min(), np.median(c)))
    if L==256:
        bad=[(round(float(c[i]),3), ntok[i]) for i in np.argsort(c)[:6]]; print(" worst (cos,tokens):", bad)
print("tokens: median", int(np.median(ntok)), ">256:", sum(n>256 for n in ntok), ">512:", sum(n>512 for n in ntok))
