import spacy
nlp = spacy.load("en_core_web_lg")
doc = nlp("|")

t = doc[0]
print("text\tis_punct\tpos_\ttag_\tis_oov\tent_type_")
print(t.text, "\t", t.is_punct, "\t", t.pos_, t.tag_, t.is_oov, t.ent_type_)

