import pathlib, re
p = pathlib.Path('static/index.html')
t = p.read_text(encoding='utf-8')
idx = t.find('id="heroChips"')
print(repr(t[idx-100:idx+600]))
