import pathlib
p = pathlib.Path('static/index.html')
t = p.read_text(encoding='utf-8')
# remove old follow-up trial code block
old = """// follow-up refinement — trial all three (chip bar + refine panel + threaded chat), single level, last answer context
function buildRefineChips(){
  if(!lastResult) return [];
  const chips=[];
  const systems=[...new Set((lastResult.pages||[]).map(p=>p.system))].slice(0,2);
  systems.forEach(s=> chips.push(`Filter: ${s}`));
  const kinds=[...new Set((lastResult.parts||[]).map(p=>p.kind))].slice(0,2);
  kinds.forEach(k=> chips.push(`Only ${k}s`));
  (lastResult.parts||[]).slice(0,2).forEach(p=> chips.push(`Related ${p.ref} details`));
  if(lastResult.pages?.[0]) chips.push(`More on ${lastResult.pages[0].system}`);
  return [...new Set(chips)].slice(0,6);
}
function renderRefinePanel(){
  const panel=$('refinePanel');
  const box=$('refineChips');
  if(!panel||!box) return;
  if(!lastResult || (!lastResult.parts?.length && !lastResult.pages?.length)){ panel.style.display='none'; return; }
  const chips=buildRefineChips();
  if(!chips.length){ panel.style.display='none'; return; }
  box.innerHTML=chips.map(c=>`<span class="chip" data-refine="${esc(c)}">${esc(c)}</span>`).join('');
  panel.style.display='block';
  box.querySelectorAll('[data-refine]').forEach(el=>{
    el.addEventListener('click',()=>{
      const q2=el.dataset.refine;
      $('q').value=q2.replace(/^Filter:\\s*|^Only\\s*/,'');
      $('q').focus();
      window.scrollTo({top:0,behavior:'smooth'});
      document.querySelector('.hero')?.scrollIntoView({behavior:'smooth'});
    });
  });
}
document.getElementById('clearRefine')?.addEventListener('click',()=>{ $('refinePanel').style.display='none'; });
document.getElementById('refineChatBtn')?.addEventListener('click',()=>{
  const q=$('q').value.trim();
  if(!q){ toast('Type a follow-up first'); return; }
  // threaded: keep previous question as context in sessionStorage
  try{ sessionStorage.setItem('ix_thread', JSON.stringify({prev: lastResult?.question, q})); }catch{}
  ask();
});"""
# new follow-up: single search box below output, keeps previous results in consideration (one level)
new = """// follow-up: single search box below output, keeps previous results (one level)
function renderFollowUpBox(){
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

if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding='utf-8')
    print("replaced follow-up refine block")
else:
    print("old block not found")

# also remove the follow-up bar in ask that was added after scrollDown
old2 = """    scrollDown();
    refreshHeroChips();
    // follow-up bar in chat (trial all three) + sidebar panel
    try{
      renderRefinePanel();
      const chips=buildRefineChips();
      if(chips.length){
        const sec=document.createElement('section');
        sec.innerHTML=`<h3>Refine — follow-up (single level, last: ${esc((lastResult.question||'').slice(0,40))})</h3><div class="chips">${chips.map(c=>`<span class="chip" data-refine2="${esc(c)}">${esc(c)}</span>`).join('')}</div><div style="font-size:11px;color:#64748B;margin-top:4px">Trial: Chip bar • Sidebar Refine panel • Threaded chat — click copies to search box for editing</div>`;
        chat.appendChild(sec);
        sec.querySelectorAll('[data-refine2]').forEach(el=>{
          el.addEventListener('click',()=>{
            $('q').value=el.dataset.refine2.replace(/^Filter:\\s*|^Only\\s*/,'');
            $('q').focus();
            window.scrollTo({top:0,behavior:'smooth'});
          });
        });
        scrollDown();
      }
    }catch{}"""

new2 = """    scrollDown();
    refreshHeroChips();
    renderFollowUpBox();"""

if old2 in t:
    # need to re-read after first replace
    t = p.read_text(encoding='utf-8')
    t = t.replace(old2, new2)
    p.write_text(t, encoding='utf-8')
    print("replaced ask follow-up bar")
else:
    print("old2 not found")
