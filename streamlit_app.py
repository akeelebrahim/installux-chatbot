"""Streamlit second frontend for Installux ChatBot — modern SaaS facelift.
Keeps FastAPI app.py on 8509, Streamlit runs on 8502 as optional UI.
Run: pip install streamlit requests ; streamlit run streamlit_app.py --server.port 8502
"""
import requests
import streamlit as st

API = "http://127.0.0.1:8509"

st.set_page_config(page_title="Installux ChatBot", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

# --- Modern dark SaaS CSS via unsafe_allow_html ---
st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#0f172a}
[data-testid="stSidebar"]{background:#1e293b; border-right:1px solid #334155}
[data-testid="stHeader"]{background: rgba(15,23,42,0.9)}
h1,h2,h3{color:#e2e8f0 !important}
p, label{color:#cbd5e1}
.stButton>button{border-radius:8px; font-weight:600; border:1px solid #334155}
.stButton>button:hover{border-color:#38bdf8; color:#0f172a; background:#38bdf8}
div[data-testid="stChatMessage"]{border-radius:12px; border:1px solid #334155; background:#1e293b}
[data-testid="stChatMessageAvatar"]{background:#38bdf8}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=15)
def get_status():
    try:
        return requests.get(f"{API}/api/status", timeout=5).json()
    except Exception:
        return None

s = get_status()

# ── Sidebar: decluttered stats + controls ──
with st.sidebar:
    st.title("Installux ChatBot")
    st.caption("COMETE 70TH · GALAXIE 32TH · GALAXIE 45TH")
    st.divider()
    st.subheader("Database")
    c1, c2 = st.columns(2)
    c1.metric("Docs", len(s["indexed_docs"]) if s and s.get("indexed_docs") else 0)
    c2.metric("Pages", s["total_pages"] if s and s.get("total_pages") else 0)
    c3, c4 = st.columns(2)
    c3.metric("Figures", s["total_figures"] if s and s.get("total_figures") is not None else 0)
    c4.metric("Parts", s["total_parts"] if s and s.get("total_parts") is not None else 0)
    st.metric("Photos", s["total_ref_images"] if s and s.get("total_ref_images") is not None else 0)
    st.markdown(f"{'🟢' if s and s.get('ai_online') else '🔴'} **{s['backend_label'] if s else 'AI offline'}**" + (f" · {s.get('ocr_pages',0)} OCR" if s else ""))

    with st.expander("System Controls & Model Selection", expanded=False):
        if s and s.get("backend_options"):
            opts = s["backend_options"]
            names = [o["name"] for o in opts]
            labels = {o["name"]: o["label"] for o in opts}
            cur = s.get("backend") if s.get("backend") in names else names[0]
            sel = st.selectbox("Answers by", names, index=names.index(cur), format_func=lambda n: labels.get(n, n))
            if st.button("Switch model", use_container_width=True):
                with st.spinner("Switching..."):
                    requests.post(f"{API}/api/settings", json={"backend": sel}, timeout=30)
                st.cache_data.clear()
                st.success(f"Switched to {labels.get(sel, sel)}")
                st.rerun()
            comp = st.selectbox("Local on", ["gpu", "cpu"], index=0 if s.get("compute") == "gpu" else 1)
            if st.button("Apply compute", use_container_width=True):
                with st.spinner("Restarting local model..."):
                    requests.post(f"{API}/api/settings", json={"compute": comp, "restart_model": True}, timeout=30)
                st.toast(f"Compute → {comp.upper()}")
        if st.button("Re-index catalogues", use_container_width=True):
            requests.post(f"{API}/api/reindex", timeout=10)
            st.toast("Re-indexing started — check status")
        st.link_button("⬇ Export figures (ZIP)", f"{API}/api/export-images", use_container_width=True)
        st.caption("ZIP downloads all indexed drawings/photos")

# ── Main header (clean, only branding) ──
st.title("Installux ChatBot")
st.caption("Multimodal technical support — vector catalogs · cross-section diagrams · part numbers")

if "msgs" not in st.session_state:
    st.session_state.msgs = []
if "pending" not in st.session_state:
    st.session_state.pending = None

# ── Zero State ──
if not st.session_state.msgs:
    st.markdown("### Welcome")
    st.markdown("Ask in English or French — grounded in the indexed PDFs, not hallucinations.")
    a, b, c = st.columns(3)
    suggestions = [
        ("COMETE 70TH", ["Glazing bead for 70TH", "What is 560032? (hinge weight)", "Punching tools rails 70TH"]),
        ("GALAXIE 32TH", ["Sliding rail drainage 32TH", "Chariot for 32TH", "Joint brosse for 32TH"]),
        ("GALAXIE 45TH", ["Lift & Slide threshold 45TH", "Seal for 45TH", "Profiles starting with 41"]),
    ]
    for col, (title, qs) in zip([a, b, c], suggestions):
        with col:
            with st.container(border=True):
                st.subheader(title)
                for q in qs:
                    if st.button(q, key=f"{title}-{q}", use_container_width=True):
                        st.session_state.pending = q
                        st.rerun()

# ── Chat feed ──
for m in st.session_state.msgs:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        for im in m.get("images", []):
            url = im.get("url") or im.get("image_url") or im.get("thumb_url")
            if url:
                full = url if url.startswith("http") else API + url
                st.image(full, caption=im.get("filename") or im.get("ref") or "", use_container_width=False)
        for p in m.get("pages", []):
            cap = f"{p.get('system','')} — {p.get('filename','').split('/')[-1]} p.{p.get('page_num','')}"
            img = p.get("page_image")
            if img:
                st.image(f"{API}/media/{img}", caption=cap)
                st.caption(p.get("snippet","")[:300])
        for part in m.get("parts", []):
            if part.get("photo"):
                st.image(f"{API}{part['photo']}", caption=f"PART {part['ref']} — {part.get('designation') or 'photo on file'}")
            else:
                st.caption(f"PART {part['ref']} — {part.get('designation') or 'no photo'}")

# ── Unified multimodal input ──
st.divider()
c1, c2, c3 = st.columns([1, 1, 6])
with c1:
    max_pages = st.number_input("Results", 1, 20, 3, key="max_pages")
with c2:
    max_images = st.number_input("Images", 1, 40, 3, key="max_images")
with c3:
    up = st.file_uploader("📷 Image search (catalogue match)", type=["jpg","jpeg","png","webp"], label_visibility="collapsed")

prompt = st.chat_input("Ask a question about the catalogues…")

# handle image upload
if up is not None:
    st.session_state.msgs.append({"role": "user", "content": f"Image search: **{up.name}**"})
    with st.chat_message("user"):
        st.image(up, caption=up.name)
    with st.spinner("Comparing against every drawing and part photo…"):
        try:
            r = requests.post(f"{API}/api/find-by-image", files={"file": (up.name, up.getvalue(), up.type or "image/png")}, timeout=60)
            d = r.json()
            if d.get("error"):
                st.session_state.msgs.append({"role": "assistant", "content": f"⚠️ {d['error']}"})
            elif not d.get("results"):
                st.session_state.msgs.append({"role": "assistant", "content": "No similar images found."})
            else:
                strong = sum(1 for x in d["results"] if x.get("match"))
                hdr = f"Found {strong} confirmed match{'es' if strong!=1 else ''}" if strong else "Nearest images:"
                st.session_state.msgs.append({"role": "assistant", "content": hdr, "images": d["results"]})
        except Exception as e:
            st.session_state.msgs.append({"role": "assistant", "content": f"Upload failed: {e}"})
    st.rerun()

# handle text (including suggestion click)
q = st.session_state.pending or prompt
if q:
    st.session_state.pending = None
    st.session_state.msgs.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.spinner("Searching catalogues…"):
        try:
            r = requests.post(f"{API}/api/ask", json={"question": q, "max_pages": int(max_pages), "max_images": int(max_images)}, timeout=90)
            d = r.json()
            if d.get("error") and not d.get("answer"):
                ans = f"⚠️ {d['error']}"
                st.session_state.msgs.append({"role": "assistant", "content": ans})
            else:
                meta = ""
                if d.get("clarify"):
                    ans = d.get("answer","")
                    if d.get("suggestions"):
                        ans += "\n\n**Pick one:** " + " · ".join(d["suggestions"])
                else:
                    by = d.get("answered_by") or "AI"
                    if d.get("from_cache"):
                        meta = f"\n\n*Reused (cached) · {by}*"
                    elif d.get("ai_used"):
                        meta = f"\n\n*Answered by {by} · grounded in {len(d.get('pages',[]))} page(s)*"
                    ans = (d.get("answer") or "") + meta
                st.session_state.msgs.append({"role": "assistant", "content": ans, "pages": d.get("pages",[]), "images": d.get("images",[] ), "parts": d.get("parts",[])+d.get("parts_without_photo",[])})
        except Exception as e:
            st.session_state.msgs.append({"role": "assistant", "content": f"Request failed: {e}"})
    st.rerun()

st.caption("Backend must be running: `python app.py` on :8509 · Streamlit on :8502 · Copy uses formatted Word tables (Ctrl+C from chat)")
