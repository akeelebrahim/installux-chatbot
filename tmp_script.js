
"use strict";
const $ = id => document.getElementById(id);
const chat = $('chat');
let busy = false;
let currentLang = localStorage.getItem('ix_lang') || 'en';
const i18n = {
  en: {
    brand:"INSTALLUX ChatBot", nav_search:"Search", nav_browse:"Browse", nav_history:"History", nav_favorites:"Favorites",
    badge_docs:"Docs", badge_pages:"Pages", ai_offline:"AI offline", answers_by:"Answers by", reindex:"Re-index",
    all_systems:"All systems", figures:"Figures", parts:"Parts",
    hero_title:"Ask about Installux catalogues", hero_sub:"Q&A + image search first — ask in English or Arabic, or upload a photo",
    placeholder:"Ask in English or Arabic — e.g. 5051 / ما هو 560032؟", ask:"Ask", results:"Results", images:"Images", hint:"…or say “show me 3 images”",
    browse_type:"Browse by part type", all_types:"All types", profiles:"Profiles", accessories:"Accessories", drawings:"Drawings & Images",
    recent:"Recent", no_recent:"No recent searches", favorites:"Favorites", no_fav:"No favorites yet",
    welcome:"Ask about the Installux catalogues — <b>COMETE 70TH</b>, <b>GALAXIE 32TH</b> and <b>GALAXIE 45TH</b> (Lift & Slide).<br>Try “glazing bead for 70TH”, “what is 10230A?”, “punching tools rails” or “joint brosse” — now in English or Arabic.",
    welcome_ar:"Try “ما هو 5051؟” or “hinge 560032” — search works in Arabic and English with voice.",
    searching:"Searching the catalogues…", comparing:"Comparing against every drawing…", found:"Found", no_match:"No similar images found."
  },
  ar: {
    brand:"شات بوت إنستالوكس", nav_search:"بحث", nav_browse:"تصفح", nav_history:"السجل", nav_favorites:"المفضلة",
    badge_docs:"مستندات", badge_pages:"صفحات", ai_offline:"الذكاء غير متصل", answers_by:"الإجابة بواسطة", reindex:"إعادة الفهرسة",
    all_systems:"جميع الأنظمة", figures:"رسومات", parts:"قطع",
    hero_title:"اسأل عن كتالوجات إنستالوكس", hero_sub:"الأسئلة والصور أولاً — اسأل بالعربية أو الإنجليزية أو حمّل صورة",
    placeholder:"اسأل بالعربية أو الإنجليزية — مثال: 5051 / ما هو 560032؟", ask:"اسأل", results:"النتائج", images:"صور", hint:"…أو قل “اعرض 3 صور”",
    browse_type:"تصفح حسب النوع", all_types:"الكل", profiles:"مقاطع", accessories:"إكسسوارات", drawings:"رسومات وصور",
    recent:"حديثاً", no_recent:"لا يوجد بحث حديث", favorites:"المفضلة", no_fav:"لا توجد مفضلة",
    welcome:"اسأل عن كتالوجات إنستالوكس — <b>COMETE 70TH</b> و <b>GALAXIE 32TH</b> و <b>GALAXIE 45TH</b>.<br>جرّب “ما هو 5051؟” أو “مفصلة 560032” أو “أدوات الثقب”.",
    welcome_ar:"",
    searching:"جاري البحث في الكتالوجات…", comparing:"جاري مقارنة الصورة…", found:"تم العثور", no_match:"لم يتم العثور على صور مشابهة."
  }
};
function applyLang(lang){
  currentLang=lang; localStorage.setItem('ix_lang',lang);
  document.documentElement.lang=lang; document.body.dir=lang==='ar'?'rtl':'ltr';
  document.querySelectorAll('[data-i18n]').forEach(el=>{ const k=el.getAttribute('data-i18n'); if(i18n[lang][k]) el.innerHTML=i18n[lang][k]; });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{ const k=el.getAttribute('data-i18n-placeholder'); if(i18n[lang][k]) el.placeholder=i18n[lang][k]; });
  $('langToggle').textContent=lang==='ar'?'EN':'عربي';
  // update voice placeholder
  if(lang==='ar') $('q').placeholder="اسأل بالعربية — مثال: ما هو 5051؟";
}
$('langToggle').addEventListener('click',()=> applyLang(currentLang==='en'?'ar':'en'));
applyLang(currentLang);

/* All UI forced to English — but when lang is Arabic, translate French catalogue terms */

/* keep helpers */
const FR_EN = [[/paumelle/gi,'hinge'],[/ouvrant/gi,'sash'],[/dormant/gi,'frame'],[/coulissant/gi,'sliding'],[/levage/gi,'lift'],[/joint\s*brosse/gi,'brush seal'],[/parclose/gi,'glazing bead'],[/batt[ée]e/gi,'leaf'],[/chariot/gi,'roller carriage'],[/poign[ée]e/gi,'handle'],[/serrure/gi,'lock'],[/gâche/gi,'strike plate'],[/partition/gi,'partition'],[/seuil/gi,'threshold'],[/traverse/gi,'crosspiece'],[/montant/gi,'mullion'],[/étanch[ée]it[ée]/gi,'sealing'],[/quincaillerie/gi,'hardware'],[/profil[ée]?/gi,'profile'],[/vitrage/gi,'glazing'],[/d[ée]billard/gi,'sliding'],[/galandage/gi,'pocket'],[/à\s*frappe/gi,'casement']];
const AR_EN = [[/مفصلة/gi,'hinge'],[/باب/gi,'door'],[/نافذة/gi,'window'],[/خرزة/gi,'bead'],[/زجاج/gi,'glazing'],[/مقبض/gi,'handle'],[/قفل/gi,'lock'],[/سكة/gi,'rail'],[/إطار/gi,'frame']];
function toEn(s){ let t=String(s??''); if(currentLang==='en'){FR_EN.forEach(([re,en])=>{t=t.replace(re,en)});} return t; }
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
function escEn(s){ return esc(toEn(s)); }
function looksFrench(t){ return /\b(le|la|les|des|une|est|pour|avec|quelle?|joint|ouvrant|dormant|coulissant|levant)\b/i.test(t); }
function looksArabic(t){ return /[\u0600-\u06FF]/.test(t); }

function md(src){ if(!src) return ''; const lines=esc(src).split('\n'); const inline=t=>t.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[\s(])_([^_]+)_(?=[\s).,;:!?]|$)/g,'$1<em>$2</em>').replace(/`([^`]+)`/g,'<code>$1</code>'); const cells=row=>row.replace(/^\||\|$/g,'').split('|').map(c=>inline(c.trim())); let html='',inList=false; const closeList=()=>{if(inList){html+='</ul>';inList=false}}; for(let i=0;i<lines.length;i++){ const line=lines[i].trim(); if(line.startsWith('|')&& /^\|[\s:|-]+\|$/.test((lines[i+1]||'').trim())){closeList(); const head=cells(line); let body=''; i+=2; for(;i<lines.length&&lines[i].trim().startsWith('|');i++) body+='<tr>'+cells(lines[i].trim()).map(c=>`<td>${c}</td>`).join('')+'</tr>'; i--; html+='<div class="tablewrap"><table><thead><tr>'+head.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+body+'</tbody></table></div>'; continue;} const li=line.match(/^(?:[-*+]|\d+\.)\s+(.*)$/); if(li){if(!inList){html+='<ul>';inList=true} html+='<li>'+inline(li[1])+'</li>'; continue;} closeList(); if(!line) continue; const h=line.match(/^(#{1,4})\s+(.*)$/); if(h){const n=Math.min(h[1].length+1,4); html+=`<h${n}>${inline(h[2])}</h${n}>`;} else if(/^([-*_])\1{2,}$/.test(line)) html+='<hr>'; else html+='<p>'+inline(line)+'</p>'; } closeList(); return html; }

function speak(text){ if(!('speechSynthesis' in window)||!text) return; if(speechSynthesis.speaking){speechSynthesis.cancel(); return;} const u=new SpeechSynthesisUtterance(text.replace(/<[^>]*>/g,'').replace(/\*\*/g,'')); // TTS: Arabic or English or French
  if(looksArabic(text) || currentLang==='ar') u.lang='ar-SA'; else if(looksFrench(text)) u.lang='fr-FR'; else u.lang='en-US';
  const voice=speechSynthesis.getVoices().find(v=>v.lang.startsWith(u.lang.slice(0,2))); if(voice) u.voice=voice; speechSynthesis.speak(u);
}
function stopSpeak(){ if('speechSynthesis' in window) speechSynthesis.cancel(); }

/* sharing helpers kept minimal - copy only */
const absUrl = u => new URL(u, location.href).href;
function openExternal(href){ const w=window.open(href,'_blank','noopener'); if(w) return true; try{const a=document.createElement('a');a.href=href;a.target='_blank';a.rel='noopener';document.body.appendChild(a);a.click();a.remove();return true}catch(e){return false}}
function openMail(href){ try{const a=document.createElement('a');a.href=href;document.body.appendChild(a);a.click();a.remove();return true}catch(e){window.location.href=href;return true}}
function waShare(text){ const url='https://wa.me/?text='+encodeURIComponent(text||''); const ok=openExternal(url); if(!ok){ const div=addMsg(`Pop-up blocked. <a href="${esc(url)}" target="_blank">Click here</a>`, 'bot'); toast('Pop-up blocked'); } }
function emailShare(text,subject){ openMail('mailto:?subject='+encodeURIComponent(subject||'Installux')+'&body='+encodeURIComponent(text||'')); }

async function copyFormatted(text, html){
  const plain=text; const rich=html||plain.replace(/\n/g,'<br>');
  if(navigator.clipboard?.write && typeof ClipboardItem!=='undefined'){
    try{ const item=new ClipboardItem({'text/plain':new Blob([plain],{type:'text/plain'}),'text/html':new Blob([rich],{type:'text/html'})}); await navigator.clipboard.write([item]); toast(currentLang==='ar'?'تم النسخ — منسق لـ Word':'Copied — formatted for Word'); return true}catch(e){}
  }
  return copyText(plain);
}
function copyText(text){ if(navigator.clipboard?.writeText){ return navigator.clipboard.writeText(text).then(()=>{toast(currentLang==='ar'?'تم النسخ':'Copied'); return true},()=>fallbackCopy(text)); } return Promise.resolve(fallbackCopy(text)); }
function fallbackCopy(text){ try{ const ta=document.createElement('textarea'); ta.value=text; ta.style.cssText='position:fixed;top:-1000px;opacity:0'; document.body.appendChild(ta); ta.select(); const ok=document.execCommand('copy'); ta.remove(); toast(ok?(currentLang==='ar'?'تم النسخ':'Copied'):'Could not copy'); return ok;}catch(e){toast('Could not copy'); return false;}}
function downloadUrl(url,name){ const a=document.createElement('a'); a.href=url; a.download=name||(url.split('/').pop()||'image'); document.body.appendChild(a);a.click();a.remove(); }
async function toPngBlob(blob){ if(blob.type==='image/png') return blob; const bmp=await createImageBitmap(blob); const c=document.createElement('canvas'); c.width=bmp.width;c.height=bmp.height; c.getContext('2d').drawImage(bmp,0,0); return new Promise(res=>c.toBlob(res,'image/png')); }
function shareFileName(url,caption){ const fromUrl=(url.split('/').pop()||'image').split('?')[0]; const ext=(fromUrl.match(/\.[a-z0-9]{2,4}$/i)||['.png'])[0]; const stem=(caption||fromUrl.replace(/\.[^.]*$/,'')).replace(/\.(png|jpe?g|gif|webp|bmp|pdf)\b/gi,'').replace(/[^\w.-]+/g,'_').replace(/_+/g,'_').replace(/^[_.]+|[_.]+$/g,'').slice(0,60); return (stem||'installux')+ext; }
async function offerImage(url,name){ if(!url) return 'none'; try{ if(!navigator.clipboard?.write||typeof ClipboardItem==='undefined') throw 0; const png=await toPngBlob(await (await fetch(url)).blob()); await navigator.clipboard.write([new ClipboardItem({'image/png':png})]); return 'clipboard'; }catch(e){ try{downloadUrl(url,shareFileName(url,name)); return 'download';}catch(e2){return 'none'}}}
async function copyImage(url,name){ if(await copyImageServerSide(url)){ toast(currentLang==='ar'?'تم نسخ الصورة — الصق بـ Ctrl+V':'Image copied — paste with Ctrl+V'); return true; } const how=await offerImage(url,name); toast(how==='clipboard'?(currentLang==='ar'?'تم نسخ الصورة':'Image copied'):how==='download'?'Downloaded':'No image'); return how!=='none'; }
const MAX_SHARE_FILES=10; const _fileReady=new Map(); const _pngReady=new Map(); const _filePending=new Set();
async function urlToFile(url,name){ const blob=await (await fetch(url)).blob(); return new File([blob],shareFileName(url,name),{type:blob.type||'image/png'}); }
function primeFile(url,name){ if(!url||_filePending.has(url)) return; if(_fileReady.has(url)&&_pngReady.has(url)) return; _filePending.add(url); fetch(url).then(r=>r.blob()).then(async blob=>{ _fileReady.set(url,new File([blob],shareFileName(url,name),{type:blob.type||'image/png'})); try{_pngReady.set(url,await toPngBlob(blob));}catch(e){}}).catch(()=>{}).finally(()=>_filePending.delete(url)); }
function canShareFiles(files){ return typeof navigator.share==='function' && typeof navigator.canShare==='function' && files.length>0 && navigator.canShare({files}); }
function shareFilesNow(files,text,title){ if(!canShareFiles(files)) return false; try{navigator.share({files,text:text||'',title:title||'Installux'}).catch(()=>{}); return true}catch(e){return false}}
const ATTACH_NOTE={pending:'\n\n(the image is on your clipboard — press Ctrl+V)',clipboard:'\n\n(the image is on your clipboard — press Ctrl+V here)',download:'\n\n(the image was downloaded — attach it from your Downloads folder)',none:''};
async function copyImageServerSide(url){ if(!url||!url.startsWith('/')) return false; try{ const r=await fetch('/api/clipboard-image',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})}); return r.ok && (await r.json()).copied===true;}catch(e){return false}}
async function sendImage(url,caption,channel){ const base=caption||'Installux catalogue image'; if(!url) return; if(await copyImageServerSide(url)){ toast(currentLang==='ar'?'تم نسخ الصورة':'Image copied'); addMsg(currentLang==='ar'?'تم نسخ الصورة — الصق بـ <b>Ctrl+V</b>':'Image copied — press <b>Ctrl+V</b> to paste','bot'); return; } const file=url?_fileReady.get(url):null; if(file&&shareFilesNow([file],base,base.slice(0,78))){ toast('System share opened'); return; } const png=_pngReady.get(url); if(png&&navigator.clipboard?.write&&typeof ClipboardItem!=='undefined'){ try{await navigator.clipboard.write([new ClipboardItem({'image/png':png})]); toast('Image copied'); addMsg('Image copied — press <b>Ctrl+V</b>','bot'); return;}catch(e){}} offerImage(url,caption).then(how=>{ if(how==='none'){toast('No image'); return} addMsg(how==='clipboard'?'Image copied — press <b>Ctrl+V</b>':'Downloaded — attach from Downloads','bot'); });}

function toast(msg){ const t=document.createElement('div'); t.className='warn'; t.textContent=msg; t.style.cssText+='position:fixed;bottom:100px;left:50%;transform:translateX(-50%);z-index:60'; document.body.appendChild(t); setTimeout(()=>t.remove(),1800); }

/* modal */
let zoomLevel=1,pan={x:0,y:0,dragging:false,sx:0,sy:0};
function applyTransform(){ $('modalStage').style.transform=`translate(${pan.x}px, ${pan.y}px) scale(${zoomLevel})`; $('zoomPct').textContent=Math.round(zoomLevel*100)+'%'; }
function setZoom(z){ zoomLevel=Math.min(Math.max(z,0.5),6); if(zoomLevel<=1) pan.x=pan.y=0; applyTransform(); }
function openModal(src,caption,marks){ const layer=$('modalMarks'); layer.innerHTML=(marks||[]).map(([x,y,w,h])=>`<i style="left:${x*100}%;top:${y*100}%;width:${w*100}%;height:${h*100}%"></i>`).join(''); $('modalImg').src=src; $('modalImg').alt=caption||''; $('modalCap').textContent=caption||''; $('modalLink').href=src; $('modalLink').download=(src.split('/').pop()||'image'); pan={x:0,y:0,dragging:false,sx:0,sy:0}; setZoom(1); $('modal').classList.add('open'); }
function closeModal(){ $('modal').classList.remove('open'); stopSpeak(); }
$('modal').addEventListener('click',e=>{if(e.target===$('modal')) closeModal()});
$('modal').addEventListener('wheel',e=>{if(!$('modal').classList.contains('open')) return; e.preventDefault(); setZoom(zoomLevel+(e.deltaY<0?0.2:-0.2));},{passive:false});
document.querySelectorAll('#modal .zoombar button').forEach(b=>{ b.addEventListener('click',e=>{e.stopPropagation(); const v=b.dataset.zoom; if(v==='reset'){pan.x=pan.y=0; setZoom(1);} else setZoom(zoomLevel+parseFloat(v));});});
$('modalStage').addEventListener('mousedown',e=>{if(zoomLevel<=1) return; pan.dragging=true; pan.sx=e.clientX-pan.x; pan.sy=e.clientY-pan.y; $('modalStage').style.cursor='grabbing'; e.preventDefault();});
document.addEventListener('mousemove',e=>{if(!pan.dragging) return; pan.x=e.clientX-pan.sx; pan.y=e.clientY-pan.sy; applyTransform();});
document.addEventListener('mouseup',()=>{if(pan.dragging){pan.dragging=false; $('modalStage').style.cursor='grab';}});
document.addEventListener('keydown',e=>{if(e.key==='Escape') closeModal(); if(!$('modal').classList.contains('open')) return; if(e.key==='+'||e.key==='=') setZoom(zoomLevel+0.25); if(e.key==='-') setZoom(zoomLevel-0.25); if(e.key==='0'){pan.x=pan.y=0; setZoom(1);}});

/* delegation */
function primeFromEvent(e){ const act=e.target.closest('[data-act]'); if(!act) return; const kind=act.dataset.act; if(kind==='copyImg') primeFile(act.dataset.url,act.dataset.caption); else if(kind==='waAll'||kind==='mailAll') bundleUrls().slice(0,MAX_SHARE_FILES).forEach(([u,n])=>primeFile(u,n)); }
chat.addEventListener('pointerover',primeFromEvent); chat.addEventListener('pointerdown',primeFromEvent);
chat.addEventListener('click',e=>{
  const act=e.target.closest('[data-act]');
  if(act){
    e.stopPropagation();
    const text=act.closest('.msg')?.dataset.text||'';
    const url=act.dataset.url||'';
    const caption=act.dataset.caption||'';
    ({speak:()=>speak(text),copy:()=>copyFormatted(bundleText()||text,bundleHtml()),chip:()=>{$('q').value=act.dataset.chip; ask();},copyImg:()=>copyImage(url,caption),copyTxt:()=>copyFormatted(caption+'\n\n'+bundleText(),`<p><b>${esc(caption)}</b></p>`+bundleHtml()),copyAll:()=>copyFormatted(bundleText(),bundleHtml()),zipAll:()=>downloadBundle(),fav:()=>toggleFav(caption,url)}[act.dataset.act]||(()=>{}))();
    return;
  }
  const card=e.target.closest('[data-full]');
  if(card&&card.dataset.full){
    let marks=[]; try{marks=JSON.parse(card.dataset.marks||'[]');}catch{marks=[]}
    openModal(card.dataset.full,card.dataset.caption||'',marks);
  }
});

/* send whole answer - simplified copy only */
let lastResult=null;
function bundleText(){
  const d=lastResult; if(!d) return '';
  const out=[`Installux — ${d.question}`,''];
  if(d.answer) out.push(d.answer.replace(/\*\*/g,'').trim(),'');
  if(d.parts?.length){ out.push('PARTS & ACCESSORIES'); d.parts.forEach(p=>out.push(`  ${p.ref} (${p.kind}) — ${p.designation||'no description'}`)); out.push(''); }
  if(d.parts_without_photo?.length){ out.push('PARTS (no photo)'); d.parts_without_photo.forEach(p=>out.push(`  ${p.ref} (${p.kind}) — ${p.designation||'no description'}`)); out.push(''); }
  if(d.pages?.length){ out.push('SOURCE PAGES — catalogue + page number'); d.pages.forEach(p=>out.push(`  ${p.system} · ${p.filename.split(/[\\/]/).pop()} · p.${p.page_num} (${p.doc_kind})`)); out.push(''); }
  if(d.images?.length){ out.push('DRAWINGS / IMAGES'); d.images.forEach((im,i)=>{ const u=im.doc?`${im.doc} p.${im.page_num}`:(im.system||''); const title=im.ref?`PART ${im.ref}`:(im.filename||`figure ${i+1}`); out.push(`  ${title} — ${u}`);}); out.push(''); }
  out.push(`Generated — ${new Date().toLocaleString()}`); return out.join('\n');
}
function bundleHtml(){
  const d=lastResult; if(!d) return '';
  const e=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  let h=`<html><body style="font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#1e293b;">`;
  h+=`<h2 style="color:#0f172a;border-bottom:2px solid #0091D1;padding-bottom:6px;">Installux — ${e(d.question)}</h2>`;
  if(d.answer) h+=`<div style="margin:12px 0;line-height:1.5;">${md(d.answer)}</div>`;
  const hasParts=(d.parts?.length||0)+(d.parts_without_photo?.length||0);
  if(hasParts){ h+=`<h3>Parts & Accessories — Part Number</h3><table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:10pt;"><tr style="background:#e2e8f0;"><th align="left">Part Number</th><th>Kind</th><th>Designation</th></tr>`; (d.parts||[]).forEach(p=>{h+=`<tr><td><b>${e(p.ref)}</b></td><td>${e(p.kind)}</td><td>${e(p.designation||'—')}</td></tr>`}); (d.parts_without_photo||[]).forEach(p=>{h+=`<tr><td><b>${e(p.ref)}</b></td><td>${e(p.kind)}</td><td>${e(p.designation||'—')} (no photo)</td></tr>`}); h+=`</table>`; }
  if(d.pages?.length){ h+=`<h3>Source Pages — Catalogue & Page Number</h3><table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:10pt;"><tr style="background:#e2e8f0;"><th>Catalogue</th><th>File Number</th><th>Page</th><th>Type</th></tr>`; d.pages.forEach(p=>{const file=e(p.filename.split(/[\\/]/).pop()); h+=`<tr><td>${e(p.system)}</td><td><b>${file}</b></td><td>p.${p.page_num}</td><td>${e(p.doc_kind)}</td></tr>`}); h+=`</table>`; }
  if(d.images?.length){ h+=`<h3>Drawings / Images</h3><table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:10pt;"><tr style="background:#e2e8f0;"><th>Title</th><th>Catalogue / File</th></tr>`; d.images.forEach((im,i)=>{const title=e(im.ref?`PART ${im.ref}`:(im.filename||`figure ${i+1}`)); const cat=e(im.doc?`${im.doc} p.${im.page_num}`:(im.system||'')); h+=`<tr><td><b>${title}</b></td><td>${cat}</td></tr>`}); h+=`</table>`; }
  h+=`<p style="font-size:8pt;color:#94a3b8;margin-top:16px;border-top:1px solid #e2e8f0;padding-top:6px;">Generated — ${e(new Date().toLocaleString())}</p></body></html>`; return h;
}
function bundleUrls(){ const d=lastResult; if(!d) return []; return [...(d.pages||[]).map(p=>['/media/'+p.page_image,`page-${p.page_num}`]), ...(d.images||[]).map((i,n)=>[i.url||i.image_url,`drawing-${n+1}`]), ...(d.parts||[]).filter(p=>p.photo).map(p=>[p.photo,`part-${p.ref}`])]; }
async function downloadBundle(){ if(!lastResult) return; toast(currentLang==='ar'?'جاري إنشاء ZIP…':'Building ZIP…'); const r=await fetch('/api/bundle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:lastResult.question,answer:lastResult.answer||'',max_pages:(lastResult.pages||[]).length||4,max_images:(lastResult.images||[]).length||8})}); if(!r.ok){toast('ZIP failed'); return} const blob=await r.blob(); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=(lastResult.question.replace(/[^\w\u0600-\u06FF]+/g,'-').slice(0,48)||'installux')+'.zip'; document.body.appendChild(a);a.click();a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),10000); }

/* same rule as sendImage */
async function sendEverything(channel){ const text=bundleText(); if(!text) return; const urls=bundleUrls().slice(0,MAX_SHARE_FILES); const files=urls.map(([u])=>_fileReady.get(u)).filter(Boolean); if(files.length===urls.length&&files.length&&shareFilesNow(files,text,`Installux — ${lastResult.question}`.slice(0,78))) return; if(urls.length===1&&await copyImageServerSide(urls[0][0])){ toast(currentLang==='ar'?'تم النسخ':'Image copied'); addMsg(currentLang==='ar'?'تم النسخ — الصق بـ Ctrl+V':'Image copied — press Ctrl+V','bot'); return; } addMsg(currentLang==='ar'?'جاهز للنسخ':'Ready to copy','bot'); if(urls.length) downloadBundle(); }

/* renderers */
function addMsg(html,cls,meta,withActions,rawText){
  const div=document.createElement('div'); div.className='msg '+cls; div.innerHTML=html;
  if(withActions){ div.dataset.text=(rawText||blockText(div)).trim(); div.insertAdjacentHTML('beforeend','<span class="actions"><span data-act="speak" title="Read aloud">🔊</span><span data-act="copy" title="Copy">📋 Copy</span></span>'); }
  if(meta) div.insertAdjacentHTML('beforeend',`<div class="meta">${esc(meta)}</div>`);
  chat.appendChild(div); scrollDown(); return div;
}
function blockText(root){ const BLOCK=/^(P|DIV|LI|H1|H2|H3|H4|TR|BR|HR|UL|OL|TABLE|SECTION)$/; const NL='\n'; let out=''; (function walk(node){ for(const n of node.childNodes){ if(n.nodeType===3){out+=n.nodeValue; continue} if(n.nodeType!==1) continue; if(n.classList&&(n.classList.contains('actions')||n.classList.contains('meta'))) continue; const block=BLOCK.test(n.tagName); if(block&&out&&!out.endsWith(NL)) out+=NL; if(n.tagName==='TD'||n.tagName==='TH') out+=' | '; walk(n); if(block&&!out.endsWith(NL)) out+=NL; } })(root); return out.replace(/\n{3,}/g,NL+NL); }
function addSection(title,innerHTML){ const s=document.createElement('section'); s.innerHTML=`<h3>${esc(title)}</h3>${innerHTML}`; chat.appendChild(s); scrollDown(); return s; }
function scrollDown(){ chat.scrollTop=chat.scrollHeight; }
function cardActs(url,caption){ const ref=(caption.match(/PART\s+([A-Z0-9-]+)/)||[])[1]||caption.slice(0,20); return `<div class="cardacts"><span data-act="copyImg" data-url="${esc(url)}" data-caption="${esc(caption)}" title="Copy">📋 Copy</span><span data-act="fav" data-caption="${esc(caption)}" data-url="${esc(url)}" title="Favorite">⭐</span></div>`; }
const ENTITY_WORDS=new Set(['amp','lt','gt','quot','apos']);
function markTerms(text,terms){ const words=[...new Set((terms||[]).filter(t=>t.length>2&&!ENTITY_WORDS.has(t)))].sort((a,b)=>b.length-a.length).map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')); if(!words.length) return esc(text); return esc(text).replace(new RegExp('('+words.join('|')+')','gi'),'<mark>$1</mark>'); }
function markTermsEn(text,terms){ return markTerms(toEn(text),terms); }
function markBoxes(marks){ return (marks||[]).map(([x,y,w,h])=>`<i style="left:${(x*100).toFixed(3)}%;top:${(y*100).toFixed(3)}%;width:${(w*100).toFixed(3)}%;height:${(h*100).toFixed(3)}%"></i>`).join(''); }
function pageCards(pages,terms){ return `<div class="hits">${pages.map(p=>{const name=p.filename.split(/[\\/]/).pop(); const cap=`${p.system} — ${name} — page ${p.page_num}`; const marks=p.highlights||[]; return `<div class="card" data-full="/media/${esc(p.page_image)}" data-caption="${esc(cap)}" data-marks="${esc(JSON.stringify(marks))}"><span class="shot"><img src="/media/${esc(p.thumb)}" loading="lazy" alt="page ${p.page_num}">${markBoxes(marks)}</span><div class="cmeta"><b>${esc(name)} — p.${p.page_num}</b><span>${esc((p.systems||[p.system]).join(' / '))} · ${esc(p.doc_kind)}</span><span class="snippet">${markTermsEn(p.snippet,terms)}</span><span class="tag">match ${p.score}%</span>${marks.length?`<span class="tag good">${marks.length} highlighted</span>`:''}${p.has_ocr?'<span class="tag">OCR</span>':''}</div>${cardActs('/media/'+p.page_image,cap)}</div>`;}).join('')}</div>`; }
function figureCards(imgs,terms){ return `<div class="imgs">${imgs.map(i=>{const url=i.image_url||i.url; const thumb=i.thumb_url||url; const title=i.kind==='part'&&i.ref?'PART '+i.ref:(i.filename||'figure'); const sub=i.doc?`${i.doc} — p.${i.page_num}`:(i.kind==='part'?'reference part photo':(i.system||'')); const sim=i.inliers!=null?`<span class="tag${i.match?' good':''}">${i.inliers} keypoint matches</span>`:(i.similarity!=null?`<span class="tag${i.match?' good':''}">${i.similarity}% similar</span>`:''); const marks=i.highlights||[]; return `<div class="card" data-full="${esc(url)}" data-caption="${esc(title+' · '+sub)}" data-marks="${esc(JSON.stringify(marks))}"><span class="shot"><img src="${esc(thumb)}" loading="lazy" alt="${esc(title)}">${markBoxes(marks)}</span><div class="cmeta"><b>${markTermsEn(title,terms)}</b><span>${markTermsEn(sub,terms)}</span>${sim}${marks.length?`<span class="tag good">${marks.length} highlighted</span>`:''}</div>${cardActs(url,title+(sub?' · '+sub:''))}</div>`;}).join('')}</div>`; }
function partCards(parts,terms){ return `<div class="imgs">${parts.map(p=>{const caption=`PART ${p.ref}${p.designation?' — '+p.designation:''}`; const tags=`<span class="tag">${esc(p.kind)}</span>`+(p.supplier_ref?`<span class="tag">supplier ${esc(p.supplier_ref)}</span>`:''); if(!p.photo){return `<div class="card nophoto"><div class="cmeta"><b>PART ${markTerms(p.ref,terms)}</b><span class="desc">${p.designation?markTermsEn(p.designation,terms):'<em>no description</em>'}</span>${tags}</div><div class="cardacts"><span data-act="copyTxt" data-caption="${esc(caption)}" title="Copy">📋 Copy</span></div></div>`;} return `<div class="card" data-full="${esc(p.photo)}" data-caption="${esc(caption)}"><img src="${esc(p.photo)}" loading="lazy" alt="part ${esc(p.ref)}"><div class="cmeta"><b>PART ${markTerms(p.ref,terms)}</b><span class="desc">${p.designation?markTermsEn(p.designation,terms):'<em>no description</em>'}</span>${tags}</div>${cardActs(p.photo,caption)}</div>`;}).join('')}</div>`; }
function chipRow(list){ return '<div class="chips">'+list.map(q=>`<span class="chip" data-act="chip" data-chip="${esc(q)}">${esc(q)}</span>`).join('')+'</div>'; }

/* status */
async function loadStatus(){
  try{
    const s=await (await fetch('/api/status')).json();
    $('docCount').textContent=s.indexed_docs.length;
    if($('docCount2')) $('docCount2').textContent=s.indexed_docs.length;
    $('pageCount').textContent=s.total_pages;
    if($('pageCount2')) $('pageCount2').textContent=s.total_pages;
    $('figCount').textContent=s.total_figures||0;
    $('partCount').textContent=s.total_parts||0;
    const badge=$('aiBadge');
    const badge2=$('aiBadge2');
    if(s.reindexing){badge.innerHTML='<span class="dot busy"></span>Indexing…'; if(badge2) badge2.innerHTML='<span class="dot busy"></span>Indexing…';}
    else{ const m=(s.ai_model||'local').split(/[\\/]/).pop(); const html=`<span class="dot ${s.ai_online?'on':'off'}"></span>`+(s.ai_online?'AI online · '+esc(m):'AI offline'); badge.innerHTML=html; if(badge2) badge2.innerHTML=html; }
    $('reindexBtn').disabled=!!s.reindexing; if($('reindexBtn2')) $('reindexBtn2').disabled=!!s.reindexing;
    if(document.activeElement!==$('compute')) $('compute').value=s.compute||'gpu';
    if($('compute2') && document.activeElement!==$('compute2')) $('compute2').value=s.compute||'gpu';
    const sel=$('backend'); const sel2=$('backend2'); const sig=(s.backend_options||[]).map(o=>o.name+o.ready).join('|');
    if(sel.dataset.sig!==sig){ sel.dataset.sig=sig; sel.innerHTML=(s.backend_options||[]).map(o=>`<option value="${esc(o.name)}"${o.ready?'':' disabled'}>${esc(o.label)}${o.ready?'':' — unavailable'}</option>`).join('');}
    if(sel2 && sel2.dataset.sig!==sig){ sel2.dataset.sig=sig; sel2.innerHTML=(s.backend_options||[]).map(o=>`<option value="${esc(o.name)}"${o.ready?'':' disabled'}>${esc(o.label)}${o.ready?'':' — unavailable'}</option>`).join('');}
    if(document.activeElement!==sel) sel.value=s.backend;
    if(sel2 && document.activeElement!==sel2) sel2.value=s.backend;
    $('compute').disabled=false;
    if($('applyCompute2')) $('applyCompute2').disabled = !$('compute2').value;
  }catch(e){}
}

/* actions */
$('reindexBtn').addEventListener('click',async()=>{
  $('reindexBtn').disabled=true;
  const d=await (await fetch('/api/reindex',{method:'POST'})).json();
  if(!d.started){toast(d.message||'Already running'); return}
  addMsg(currentLang==='ar'?'جاري الفهرسة…':'Re-indexing…','bot');
  const poll=setInterval(async()=>{
    const s=await (await fetch('/api/reindex-status')).json();
    if(s.running) return; clearInterval(poll); loadStatus();
    if(s.error) addMsg('Failed: '+esc(s.error),'bot'); else if(s.result) addMsg(`Done — ${s.result.documents} docs, ${s.result.pages} pages`,'bot');
  },2000);
});
$('backend').addEventListener('change',async()=>{
  const name=$('backend').value; const label=$('backend').selectedOptions[0]?.textContent||name;
  $('backend').disabled=true;
  const note=addMsg(`Switching to ${esc(label)}…`,'bot');
  try{ const d=await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backend:name})})).json(); note.remove(); addMsg(esc(d.message||d.error||'done'),'bot');}catch(e){note.remove(); addMsg('Error '+esc(e.message),'bot');} finally{$('backend').disabled=false; loadStatus();}
});
$('applyCompute').addEventListener('click',async()=>{
  const mode=$('compute').value; $('applyCompute').disabled=true;
  const note=addMsg(`Switching to ${mode.toUpperCase()}…`,'bot');
  try{ const d=await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({compute:mode,restart_model:true})})).json(); note.remove(); addMsg(esc(d.message),'bot');}catch(e){note.remove(); addMsg('Error '+esc(e.message),'bot');} finally{$('applyCompute').disabled=false; loadStatus();}
});
$('exportBtn').addEventListener('click',()=>{
  const f=document.createElement('form'); f.method='POST'; f.action='/api/export-images'; document.body.appendChild(f); f.submit(); f.remove();
});
$('imgBtn').addEventListener('click',()=>$('imgUpload').click());
$('imgUpload').addEventListener('change',async ev=>{
  const file=ev.target.files[0]; if(!file) return;
  $('welcome').style.display='none';
  const queryUrl=URL.createObjectURL(file);
  addMsg(`<div>${currentLang==='ar'?'البحث عن':'Find'} <b>${esc(file.name)}</b></div><div class="query-preview"><img src="${esc(queryUrl)}" alt="upload"></div>`,'user');
  addSection(currentLang==='ar'?'صورتك — الأصل':'Your image — original',`<div class="hits"><div class="card query-card" data-full="${esc(queryUrl)}" data-caption="Your upload — ${esc(file.name)}"><img src="${esc(queryUrl)}" alt="upload"><div class="cmeta"><b>${currentLang==='ar'?'صورتك':'Your image'}</b><span>${esc(file.name)} · original</span></div></div></div>`);
  const typing=addMsg(currentLang==='ar'?i18n.ar.comparing:i18n.en.comparing,'bot');
  try{
    const form=new FormData(); form.append('file',file);
    const r=await fetch('/api/find-by-image',{method:'POST',body:form}); const d=await r.json(); typing.remove();
    if(d.error){addMsg(esc(d.error),'bot'); return}
    const results=d.results||[]; if(!results.length){addMsg(currentLang==='ar'?i18n.ar.no_match:i18n.en.no_match,'bot'); return}
    const strong=results.filter(x=>x.match).length; addMsg(strong?`${currentLang==='ar'?i18n.ar.found:i18n.en.found} ${strong}`:'Nearest images:','bot');
    lastResult={question:'Image search: '+file.name,answer:'',pages:[],parts:[],images:results};
    addSection(currentLang==='ar'?'النتائج البصرية':'Visual matches',figureCards(results,[]));
    const bar=document.createElement('div'); bar.className='bulkbar'; bar.innerHTML='<span class="lbl">Copy —</span><button class="ghost" data-act="copyAll">📋 Copy all</button>'; chat.appendChild(bar);
  }catch(e){ typing.remove(); addMsg('Upload failed: '+esc(e.message||e),'bot'); } finally{ev.target.value='';}
});

/* voice STT + TTS - bilingual */
let recognition=null;
function initVoice(){
  const Rec=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Rec) return;
  $('micBtn').hidden=false;
  $('micBtn').addEventListener('click',()=>{
    if(!recognition){
      recognition=new Rec(); recognition.interimResults=false; recognition.continuous=false;
      recognition.onresult=e=>{ const t=e.results[e.results.length-1][0].transcript.trim(); if(t){$('q').value=t; ask();} };
      recognition.onerror=()=>$('micBtn').classList.remove('rec');
      recognition.onend=()=>$('micBtn').classList.remove('rec');
    }
    recognition.lang = currentLang==='ar' ? 'ar-SA' : (looksArabic($('q').value) ? 'ar-SA' : (looksFrench($('q').value)?'fr-FR':'en-US'));
    try{ recognition.start(); $('micBtn').classList.add('rec'); }catch{}
  });
}

/* header nav — only Search remains */
const navSearch=document.querySelector('nav a[data-i18n="nav_search"]');
if(navSearch) navSearch.addEventListener('click',e=>{e.preventDefault(); document.querySelector('.hero').scrollIntoView({behavior:'smooth',block:'start'}); $('q').focus(); document.querySelectorAll('header nav a').forEach(a=>a.classList.remove('active')); e.target.classList.add('active');});
/* settings dropdown */
$('settingsBtn').addEventListener('click',()=>{ const p=$('settingsPanel'); p.style.display=p.style.display==='none'?'block':'none'; });
document.addEventListener('click',e=>{ if(!e.target.closest('#settingsBtn') && !e.target.closest('#settingsPanel')) $('settingsPanel').style.display='none'; });
/* system pills */
document.querySelectorAll('.pill[data-system]').forEach(b=>{
  b.addEventListener('click',()=>{
    document.querySelectorAll('.pill').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    const sys=b.dataset.system;
    if(sys==='all') $('q').value='';
    else $('q').value = sys + ' ';
    $('q').focus();
  });
});
/* part type filter */
document.querySelectorAll('.side a[data-filter]').forEach(a=>{
  a.addEventListener('click',()=>{
    document.querySelectorAll('.side a[data-filter]').forEach(x=>x.classList.remove('active'));
    a.classList.add('active');
    const f=a.dataset.filter;
    if(f==='all'){ $('q').value=''; $('q').placeholder = currentLang==='ar' ? 'اسأل بالعربية — مثال: ما هو 5051؟' : 'Ask in English or Arabic — e.g. 5051 / ما هو 560032؟'; }
    else { const label = a.textContent.trim(); $('q').value = f + ' '; $('q').placeholder = (currentLang==='ar'?'ابحث في ':'Search only in ') + label; }
    $('q').focus();
    toast((currentLang==='ar'?'فلتر: ':'Filter: ') + a.textContent.trim(), 1200);
  });
});
// add tooltips for clarity
document.querySelectorAll('.side a[data-filter]').forEach(a=>{
  const map={all:'Show all — clear filter',profile:'Search only Profiles',accessory:'Search only Accessories',drawing:'Search only Drawings & Images'};
  a.title = map[a.dataset.filter] || '';
});
// settings sync (panel duplicates header ids)
['backend','compute'].forEach(id=>{
  const a=$(id), b=$(id+'2');
  if(a&&b){
    b.addEventListener('change',()=>{a.value=b.value; a.dispatchEvent(new Event('change'));});
    a.addEventListener('change',()=>{ if(b.value!==a.value) b.value=a.value; });
  }
});
['reindexBtn','exportBtn','applyCompute'].forEach(id=>{
  const b=$(id+'2');
  if(b){
    b.addEventListener('click',()=> $(id).click());
  }
});
// favorites
function getFavs(){ try{ return JSON.parse(localStorage.getItem('ix_fav')||'[]'); }catch{return []} }
function toggleFav(caption,url){
  let favs=getFavs();
  const key=caption||url;
  const idx=favs.findIndex(f=>f.key===key);
  if(idx>=0){ favs.splice(idx,1); toast(currentLang==='ar'?'تمت الإزالة من المفضلة':'Removed from favorites'); }
  else { favs.unshift({key,caption,url,at:Date.now()}); toast(currentLang==='ar'?'تمت الإضافة للمفضلة':'Added to favorites'); }
  localStorage.setItem('ix_fav',JSON.stringify(favs.slice(0,20)));
  renderFavs();
}
function renderFavs(){
  const list=$('favList');
  const favs=getFavs();
  if(!favs.length){ list.innerHTML=`<a style="color:#94A3B8">${currentLang==='ar'?'لا توجد مفضلة':'No favorites yet'}</a>`; return; }
  list.innerHTML=favs.map(f=>`<a data-act="chip" data-chip="${esc(f.caption||f.key)}" title="${esc(f.caption)}">⭐ ${esc((f.caption||'').slice(0,30))}</a>`).join('');
}
// hero chips — outside #chat, so need own handler
document.getElementById('heroChips').addEventListener('click',e=>{
  const chip=e.target.closest('[data-act="chip"]');
  if(chip){ $('q').value=chip.dataset.chip; ask(); }
});
// autocomplete — text prediction based on typed text
let suggestTimer=null;
const suggestBox=$('suggestBox');
$('q').addEventListener('input',()=>{
  const val=$('q').value.trim();
  clearTimeout(suggestTimer);
  if(val.length<2){ suggestBox.style.display='none'; return; }
  suggestTimer=setTimeout(async()=>{
    try{
      const r=await fetch('/api/suggest?q='+encodeURIComponent(val));
      const j=await r.json();
      const list=j.suggestions||[];
      if(!list.length){ suggestBox.style.display='none'; return; }
      suggestBox.innerHTML=list.map(s=>`<div style="padding:8px 12px;cursor:pointer;font-size:13px;border-bottom:1px solid #F1F5F9" data-suggest="${esc(s)}">${esc(s)}</div>`).join('');
      suggestBox.style.display='block';
    }catch{ suggestBox.style.display='none'; }
  },220);
});
suggestBox.addEventListener('click',e=>{
  const el=e.target.closest('[data-suggest]');
  if(el){ $('q').value=el.dataset.suggest; suggestBox.style.display='none'; ask(); }
});
document.addEventListener('click',e=>{
  if(!e.target.closest('#q') && !e.target.closest('#suggestBox')) suggestBox.style.display='none';
});
$('q').addEventListener('keydown',e=>{ if(e.key==='Escape') suggestBox.style.display='none'; });
// delegate fav clicks (added to chat delegation below, but also handle here for side?)
// will be handled in chat click via data-act="fav"

/* ask */
async function ask(){
  const q=$('q').value.trim(); if(!q||busy) return;
  busy=true; $('askBtn').disabled=true;
  $('welcome').style.display='none';
  addMsg(esc(q),'user'); $('q').value='';
  // history
  try{ let h=JSON.parse(localStorage.getItem('ix_hist')||'[]'); h=[q,...h.filter(x=>x!==q)].slice(0,10); localStorage.setItem('ix_hist',JSON.stringify(h)); renderHistory(); }catch{}
  const typing=addMsg(currentLang==='ar'?i18n.ar.searching:i18n.en.searching,'bot');
  try{
    const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q, max_pages:Math.max(1,+$('maxPages').value||3), max_images:Math.max(1,+$('maxImages').value||3)})});
    const d=await r.json(); lastResult=d; typing.remove();
    if(d.error && !d.answer){addMsg('⚠ '+esc(d.error),'bot'); return}
    if(d.clarify){ addMsg(md(d.answer),'bot'); if(d.suggestions?.length) addMsg('<b>'+(currentLang==='ar'?'اختر':'Pick')+'</b>'+chipRow(d.suggestions),'bot'); }
    else {
      const by=d.answered_by||'AI'; const meta=d.from_cache?`Cached · ${by}`:d.ai_used?`${by} · ${d.pages.length} pages`:'Catalogue evidence';
      addMsg(md(d.answer),'bot',meta,true,d.answer);
    }
    if(d.pages?.length) addSection(currentLang==='ar'?'صفحات':'Pages',pageCards(d.pages,d.terms));
    if(d.parts?.length || d.parts_without_photo?.length){
      const grid=d.parts?.length?partCards(d.parts,d.terms):'';
      const rest=(d.parts_without_photo||[]).map(p=>`<span class="reftag" data-act="chip" data-chip="${esc(p.ref)}">${markTerms(p.ref,d.terms)}<i>${markTermsEn(p.designation||'no description',d.terms)}</i></span>`).join('');
      addSection(currentLang==='ar'?'قطع':'Parts & accessories',grid+(rest?`<div class="reflist"><span class="lbl">${currentLang==='ar'?'بدون صورة:':'Also referenced:'}</span>${rest}</div>`:'')); 
    }
    if(d.images?.length) addSection(currentLang==='ar'?'رسومات':'Drawings & images',figureCards(d.images,d.terms));
    if(d.pages?.length||d.images?.length||d.parts?.length){
      const bar=document.createElement('div'); bar.className='bulkbar';
      bar.innerHTML='<span class="lbl">Copy —</span><button class="ghost" data-act="copyAll">📋 '+(currentLang==='ar'?'نسخ الكل':'Copy all')+'</button><button class="ghost" data-act="zipAll">⬇ ZIP</button>';
      chat.appendChild(bar);
    }
    scrollDown();
  }catch(e){ typing.remove(); addMsg('Request failed: '+esc(e.message||e),'bot'); } finally{ busy=false; $('askBtn').disabled=false; $('q').focus(); }
}
function renderHistory(){
  try{
    const h=JSON.parse(localStorage.getItem('ix_hist')||'[]');
    const c=$('recentList');
    if(!h.length){ c.innerHTML=`<a style="color:#94A3B8">${currentLang==='ar'?'لا يوجد':'No recent'}</a>`; return; }
    c.innerHTML=h.map(q=>`<a data-act="chip" data-chip="${esc(q)}">${esc(q)}</a>`).join('');
  }catch{}
}
$('askBtn').addEventListener('click',ask);
$('q').addEventListener('keydown',e=>{if(e.key==='Enter') ask();});
initVoice(); loadStatus(); setInterval(loadStatus,15000); renderHistory(); renderFavs(); $('q').focus();
