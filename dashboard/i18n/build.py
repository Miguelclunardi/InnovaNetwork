#!/usr/bin/env python3
"""Builds dashboard/app/i18n.js from i18n.tmpl.js + pt.json (the English -> Portuguese dictionary)."""
import json
import os

here = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(here, "pt.json"), encoding="utf-8"))
dic = json.dumps({"exact": d["exact"], "patterns": d["patterns"]}, ensure_ascii=False, separators=(",", ":"))
tmpl = open(os.path.join(here, "i18n.tmpl.js"), encoding="utf-8").read()
assert "/*DICT*/null" in tmpl
out = os.path.join(here, "..", "app", "i18n.js")
open(out, "w", encoding="utf-8").write(tmpl.replace("/*DICT*/null", dic))
print("%s: %d texts, %d patterns" % (os.path.relpath(out), len(d["exact"]), len(d["patterns"])))
