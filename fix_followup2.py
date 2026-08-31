import pathlib
p = pathlib.Path('static/index.html')
t = p.read_text(encoding='utf-8')
# patch renderFollowUpBox to enforce one level only
old = """function renderFollowUpBox(){
  // remove old box if any
  const old=document.getElementById('followUpWrap');
  if(old) old.remove();
  if(!lastResult) return;
  const wrap=document.createElement('section');
  wrap.id='followUpWrap';
  wrap.innerHTML=`<h3>${currentLang==='ar'?'تضييق النتائج':'Refine these results'}</h3>
    <div style="display:flex;gap:8px;margin-top:6px">
      <input id="followUpInput" placeholder="${currentLang==='ar'?'كلمة إضافية للتصفية...':'Additional keywords to refine…'}" style="flex:1;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;font-size:13px">
      <button class="btn primary" id="followUpBtn">${currentLang==='ar'?'تضييق':'Refine'}</button>
    </div>
    <div style="font-size:11px;color:#64748B;margin-top:6px">${currentLang==='ar'?'سيتم البحث مع مراعاة النتائج السابقة (مستوى واحد)':'Search will consider previous results (one level follow-up)'}</div>`;
  chat.appendChild(wrap);
  const inp=wrap.querySelector('#followUpInput');
  const btn=wrap.querySelector('#followUpBtn');
  const doRefine=()=>{
    const extra=(inp.value||'').trim();
    if(!extra){ toast(currentLang==='ar'?'أدخل كلمة للتصفية':'Enter a keyword to refine'); return; }
    const prevQ=lastResult.question||'';
    // keep previous results in consideration: combine previous question + refine keywords
    // also pass previous pages/parts as context via sessionStorage for backend to use if needed
    try{ sessionStorage.setItem('ix_followup', JSON.stringify({prevQ, extra, prevPages:(lastResult.pages||[]).map(p=>p.page_id), prevParts:(lastResult.parts||[]).map(p=>p.ref)})); }catch{}
    // one level only: hide this box after use, run new search with combined query
    const combined = `${prevQ} ${extra}`.trim();
    $('q').value = combined;
    wrap.remove();
    ask();
  };
  btn.addEventListener('click', doRefine);
  inp.addEventListener('keydown', e=>{ if(e.key==='Enter') doRefine(); });
  inp.focus();
  scrollDown();
}"""
new = """function renderFollowUpBox(){
  // one level only: if last search was already a follow-up, don't show again
  try{
    const done=sessionStorage.getItem('ix_followup_done');
    const isFollowUp = lastResult && lastResult.question && sessionStorage.getItem('ix_followup');
    if(done==='1' && isFollowUp){
      // clear flag after showing once
      sessionStorage.removeItem('ix_followup_done');
      return;
    }
  }catch{}
  // remove old box if any
  const old=document.getElementById('followUpWrap');
  if(old) old.remove();
  if(!lastResult) return;
  const wrap=document.createElement('section');
  wrap.id='followUpWrap';
  wrap.innerHTML=`<h3>${currentLang==='ar'?'تضييق النتائج':'Refine these results'}</h3>
    <div style="display:flex;gap:8px;margin-top:6px">
      <input id="followUpInput" placeholder="${currentLang==='ar'?'كلمة إضافية للتصفية...':'Additional keywords to refine…'}" style="flex:1;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;font-size:13px">
      <button class="btn primary" id="followUpBtn">${currentLang==='ar'?'تضييق':'Refine'}</button>
    </div>
    <div style="font-size:11px;color:#64748B;margin-top:6px">${currentLang==='ar'?'سيتم البحث مع مراعاة النتائج السابقة (مستوى واحد)':'Search will consider previous results (one level follow-up)'}</div>`;
  chat.appendChild(wrap);
  const inp=wrap.querySelector('#followUpInput');
  const btn=wrap.querySelector('#followUpBtn');
  const doRefine=()=>{
    const extra=(inp.value||'').trim();
    if(!extra){ toast(currentLang==='ar'?'أدخل كلمة للتصفية':'Enter a keyword to refine'); return; }
    const prevQ=lastResult.question||'';
    try{ sessionStorage.setItem('ix_followup', JSON.stringify({prevQ, extra, prevPages:(lastResult.pages||[]).map(p=>p.page_id), prevParts:(lastResult.parts||[]).map(p=>p.ref)})); sessionStorage.setItem('ix_followup_done','1'); }catch{}
    const combined = `${prevQ} ${extra}`.trim();
    $('q').value = combined;
    wrap.remove();
    ask();
  };
  btn.addEventListener('click', doRefine);
  inp.addEventListener('keydown', e=>{ if(e.key==='Enter') doRefine(); });
  inp.focus();
  scrollDown();
}"""
if old in t:
    t=t.replace(old,new)
    p.write_text(t,encoding='utf-8')
    print("patched follow-up one level")
else:
    print("not found")
# also clear flag on new main search (non-follow-up)
# patch ask to clear follow-up flag when it's a fresh search not via follow-up box
old2 = "  // history — up to 15\n  try{ let h=JSON.parse(localStorage.getItem('ix_hist')||'[]'); h=[q,...h.filter(x=>x!==q)].slice(0,15); localStorage.setItem('ix_hist',JSON.stringify(h)); renderHistory(); }catch{}"
new2 = "  // history — up to 15\n  try{ let h=JSON.parse(localStorage.getItem('ix_hist')||'[]'); h=[q,...h.filter(x=>x!==q)].slice(0,15); localStorage.setItem('ix_hist',JSON.stringify(h)); renderHistory(); }catch{}\n  // if this is a fresh main search (not via follow-up box), clear one-level flag so next follow-up can show\n  try{ const isFollowUp = sessionStorage.getItem('ix_followup') && q.includes(JSON.parse(sessionStorage.getItem('ix_followup')).prevQ||''); if(!isFollowUp) sessionStorage.removeItem('ix_followup_done'); }catch{}"
t=p.read_text(encoding='utf-8')
if old2 in t:
    t=t.replace(old2,new2)
    p.write_text(t,encoding='utf-8')
    print("patched ask history")
else:
    print("ask history not found")
