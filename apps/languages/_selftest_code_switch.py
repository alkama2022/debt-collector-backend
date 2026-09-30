"""
Standalone checks for code_switch.py — run without Django:

    .venv/Scripts/python.exe backend/apps/languages/_selftest_code_switch.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import code_switch  # noqa: E402

# Mirror of the router's keyword tables so this file stays Django-free.
KEYWORDS = {
    "ha": ["ina kwana", "sannu", "yaya", "nagode", "na gode", "don allah",
           "bashi", "biya", "biyan", "kuɗi", "kudi", "ina gida", "zan"],
    "yo": ["bawo", "mo le san", "o dabo", "e kaaro", "e kaasan", "e ku owuro",
           "e ku isan", "owo", "gbese", "jowo", "ejowo", "se alafia", "ẹ ranti"],
    "ig": ["kedu", "ndewo", "daalu", "biko", "ego", "igbo", "kedu ka", "imeela",
           "ugwo", "ikwu ugwo", "gini", "ewo", "ndi", "kwụọ"],
    "pcm": ["i go pay", "i go", "how far", "abeg", "o de pay", "dey", "na wa",
            "you don", "i dey", "no dey", "make i", "wetin", "shey", "pidgin",
            "una", "japa", "small small", "small time"],
    "en": ["hello", "please", "balance", "invoice", "payment", "pay", "the",
           "i will", "thanks", "dear", "good morning"],
}

CASES = [
    # (text, expect_primary, expect_switched, label)
    ("Ina kwana? Zan biya gobe.", "ha", False, "pure Hausa (S6)"),
    ("Mo ti san pe mo ni gbese, emi yoo san owo naa ni Friday.", "yo", False, "pure Yoruba (S6)"),
    ("I go pay am tomorrow.", "pcm", False, "Pidgin (S6)"),
    ("I understand the balance, but wallahi I need small time.", "en", True,
     "S27 code-switch: English + Pidgin, wallahi must not flip it"),
    ("Sannu! Ina kwana? Zan biya gobe.", "ha", False, "Hausa greeting + body"),
    ("Hello, I will pay the invoice on Friday. Abeg send the link.", "en", True,
     "English body + Pidgin request"),
    ("Please pay your balance today.", "en", False, "plain English"),
    ("Kedu ka ị mere? Ihe ncheta sitere na ABC School.", "ig", False, "Igbo"),
    ("", "en", False, "empty falls back"),
    ("Ok", "en", False, "neutral token"),
]

fails = 0
for text, want_primary, want_switch, label in CASES:
    r = code_switch.detect_code_switch(text, KEYWORDS, default_language="en")
    ok = (r.primary == want_primary) and (r.is_code_switched == want_switch)
    if not ok:
        fails += 1
    status = "PASS" if ok else "FAIL"
    print(
        "%s | %-46s primary=%-4s switch=%-5s conf=%.2f secondary=%s"
        % (status, label, r.primary, r.is_code_switched, float(r.confidence), r.secondary)
    )
    if not ok:
        print("      expected primary=%s switch=%s" % (want_primary, want_switch))
        for s in r.segments:
            print("        seg[%s score=%d] %r" % (s.language, s.score, s.text))

print("")
print("%d/%d passed" % (len(CASES) - fails, len(CASES)))
sys.exit(1 if fails else 0)
