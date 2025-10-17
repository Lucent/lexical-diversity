#!/usr/bin/env python3
import re, spacy, math
from taaled import ld
from collections import Counter

# CONFIG
TEXT_PATH = "../bluesky-tools/lucent.social.txt"
MAX_TOKENS = 10000

# load spaCy large, bump limit
nlp = spacy.load("en_core_web_lg")
nlp.max_length = 10_000_000

# read + tokenize
text = open(TEXT_PATH, "r", encoding="utf-8").read()
text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
doc = nlp(text)
 
# keep: alphabetic, not OOV, not proper nouns, not named entities, content POS only
kept = []
vecs = []
for t in doc:
    if len(kept) >= MAX_TOKENS:
        break
    if t.is_punct or t.text in {"↳",">","+","|"} or t.is_oov:
        continue
    if t.pos_ in {"PROPN","NUM"}:
        continue
    if t.ent_type_ in {"PERSON","ORG","GPE","CARDINAL"}:
        continue
    kept.append(f"{t.lemma_.lower()}_{t.pos_}")
    if t.has_vector:
        vecs.append(t.vector)

# basic freq
lemmas = [k.split("_",1)[0] for k in kept]
freq = Counter(lemmas)

# lexical diversity via TAALED
results = ld.lexdiv(kept)

# hapax ratio & vocab size
V = len(freq)
N = len(kept)
hapax = sum(1 for c in freq.values() if c == 1)
hapax_ratio = hapax / V if V else 0.0
v_per_1k = (V / N) * 1000 if N else 0.0

# simple semantic diversity: avg cosine distance between adjacent kept tokens
def cosine(u, v):
    nu = math.sqrt((u*u).sum()); nv = math.sqrt((v*v).sum())
    if nu == 0 or nv == 0: return 0.0
    return float((u @ v) / (nu * nv))
adj_dists = []
for i in range(1, len(vecs)):
    adj_dists.append(1.0 - cosine(vecs[i-1], vecs[i]))
sem_adj_avg = sum(adj_dists)/len(adj_dists) if adj_dists else 0.0

# compact output
print({
    "n_tokens_kept": N,
    "vocab_size": V,
    "v_per_1k": v_per_1k,
    "hapax_ratio": hapax_ratio,
    "ttr": results.ttr,
    "mtld": results.mtld,
    "hdd": results.hdd,
    "mattr": results.mattr,
    "semantic_adjacent_avg_cosine_distance": sem_adj_avg,
})

for lemma, count in freq.most_common(500):      # change 200 to whatever number you want
    print(f"{lemma}\t{count}")

