#!/usr/bin/env python3
"""
my_ld.py — reusable lexical diversity analyzer
"""

import re, spacy, sys
from collections import Counter
from taaled import ld
from ftfy import fix_text

MAX_TOKENS = 1_000_000

nlp = spacy.load("en_core_web_lg")
nlp.max_length = 10_000_000

def preprocess_text(text):
	text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
	text = fix_text(text, normalization="NFKC")
	doc = nlp(text)
	kept = []
	for t in doc:
		if len(kept) >= MAX_TOKENS:
			break
		if t.is_punct or t.text in {"↳",">","+","|","$"} or t.is_oov:
			continue
		if t.pos_ in {"PROPN","NUM"} or t.ent_type_ in {"PERSON","ORG","GPE","CARDINAL"}:
			continue
		kept.append(f"{t.lemma_}_{t.pos_}")
	return kept

def compute_lexdiv(tokens):
	"""Return the full lexical-diversity suite with our tuned TAALD settings."""
	return ld.lexdiv(tokens)

def main():
	if len(sys.argv) < 2:
		print("usage: python3 my_ld.py textfile.txt [limit_tokens]")
		sys.exit(1)
	path = sys.argv[1]
	limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

	text = open(path, "r", encoding="utf-8").read()
	tokens = preprocess_text(text)
	if limit and len(tokens) > limit:
		tokens = tokens[:limit]
	lexdiv = compute_lexdiv(tokens)
	for key, value in lexdiv.__dict__.items():
		print(f"{key}: {value}")

if __name__ == "__main__":
	main()
