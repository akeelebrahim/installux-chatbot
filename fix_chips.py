import pathlib
p = pathlib.Path('static/index.html')
t = p.read_text(encoding='utf-8')
old = """  const popular=["5051 Glazing bead","560032 hinge — 120 KG","Punching tools 70TH","ما هو 5051؟","560017 + A5025","GALAXIE 32TH sliding","420030 glazing bead","Profile 510001","Threshold 510009"];
  let pool=[];
  // 1) last result context (AI related)
  if(lastResult){
    (lastResult.parts||[]).slice(0,2).forEach(p=> pool.push(`${p.ref} ${p.designation.slice(0,22)}`));
    (lastResult.suggestions||[]).slice(0,2).forEach(s=> pool.push(s));
    if(lastResult.question) pool.push(lastResult.question);
  }
  // 2) recent history
  pool.push(...hist.slice(0,4));
  // 3) popular shuffled
  const shuffled=[...popular].sort(()=>Math.random()-0.5);
  pool.push(...shuffled);
  // deduplicate, keep copy-only, max 6
  const seen=new Set(); const out=[];
  for(let s of pool){ s=(s||'').trim(); if(!s||s.length<2) continue; const k=s.toLowerCase(); if(seen.has(k)) continue; seen.add(k); out.push(s); if(out.length>=6) break; }"""
new = """  const popular=["5051","560032","Punching","Door types"];
  let pool=[];
  // 1) last result context (AI related) — short, 4 total random
  if(lastResult){
    (lastResult.parts||[]).slice(0,2).forEach(p=> pool.push(p.ref));
  }
  // 2) recent history (short)
  pool.push(...hist.slice(0,3).map(s=> s.split(' ').slice(0,2).join(' ').slice(0,14)));
  // 3) popular shuffled
  const shuffled=[...popular].sort(()=>Math.random()-0.5);
  pool.push(...shuffled);
  // deduplicate, keep copy-only, max 4 short
  const seen=new Set(); const out=[];
  for(let s of pool){ s=(s||'').trim().slice(0,16); if(!s||s.length<2) continue; const k=s.toLowerCase(); if(seen.has(k)) continue; seen.add(k); out.push(s); if(out.length>=4) break; }"""
if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding='utf-8')
    print("fixed chips js")
else:
    print("not found")
    # debug
    import re
    m=re.search(r"const popular=\[.*?popular", t, re.S)
    print(m.group(0)[:500] if m else "no match")
