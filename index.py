#!/usr/bin/env python3
import spacy
from taaled import ld

# load the large spaCy model
nlp = spacy.load("en_core_web_lg")
nlp.max_length = 10_000_000

# sample text (replace with file read if you like)
text = open("../bluesky-tools/lucent.social.txt").read()

# tokenize and lemmatize
doc = nlp(text)
tokens = [f"{t.lemma_}_{t.pos_}" for t in doc if t.is_alpha]

print(tokens)  # expect ['this_PRON', 'be_AUX', 'a_DET', 'quick_ADJ', 'test_NOUN']

# compute lexical diversity metrics
results = ld.lexdiv(tokens)
print({
    "n_tokens": len(tokens),
    "ttr": results.ttr,
    "mtld": results.mtld,
    "hdd": results.hdd,
    "mattr": results.mattr,
})
