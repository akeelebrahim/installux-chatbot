import pathlib
p = pathlib.Path('static/index.html')
t = p.read_text(encoding='utf-8')
old = """      <span class="chip" data-act="chip" data-chip="5051">5051 Glazing bead</span>
      <span class="chip" data-act="chip" data-chip="What is hinge 560032 max weight 900x2000?">560032 — 120 KG</span>
      <span class="chip" data-act="chip" data-chip="Punching tools 70TH">Punching tools 70TH</span>
      <span class="chip" data-act="chip" data-chip="ما هو 5051؟" dir="rtl">ما هو 5051؟</span>"""
new = """      <span class="chip" data-act="chip" data-chip="5051">5051</span>
      <span class="chip" data-act="chip" data-chip="560032">560032</span>
      <span class="chip" data-act="chip" data-chip="Punching">Punching</span>
      <span class="chip" data-act="chip" data-chip="Door types">Door types</span>"""
if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding='utf-8')
    print("fixed static chips")
else:
    print("not found static")
