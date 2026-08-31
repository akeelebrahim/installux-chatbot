# Installux-ChatBot French Translation & Server Startup

## French Translation Capability

The AI client uses OpenRouter with Claude Sonnet 5, which automatically translates French to English in answers. The system is designed to:

1. **Accept questions in any language** (French, English, etc.)
2. **Translate answers to English** before outputting
3. **Preserve technical terms** (part numbers, reference codes, dimensions) untranslated

### Test: French Question → English Answer

**Question (French):** "porte coulissante avec charniere 560032"  
**Expected Answer (English):** "Sliding door with hinge 560032: The maximum leaf weight for hinge 560032 on a 900 × 2000 mm door is 120 KG. ..."

**Mechanism:** The LLM (Claude Sonnet 5) receives the question in French, processes it against the indexed catalogue data (which is in English), and outputs the answer in English while preserving all part numbers and technical terms.

### Example Output Format

When asked a French question like "Quelle est la charge maximale pour la charniere 560032 sur une porte 900x2000mm?":

```
Answer: 120 KG

The maximum leaf weight for hinge 560032 on a 900 × 2000 mm door is 120 KG. This is found on page 5 of the COMETE 70TH catalogue, which shows the weight and dimension limits chart for three-leaf hinges reference 560032.

The chart displays weight capacities of 120 kg, 110 kg, 90 kg, and 70 kg across different leaf height and width combinations, with an unusable region marked for extreme dimensions.

Source: Page 5, COMETE 70TH catalogue - "MAX. WEIGHT, KG PER LEAF WITH 2 x THREE-LEAF HINGES REF. 560032"
```

## Server Startup Instructions (Port 8509)

To run the Installux-ChatBot on port 8509:

### Option 1: Using PowerShell (recommended)

```powershell
PowerShell -command "Start-Process python -ArgumentList 'C:\Users\PC\AppData\Local\Temp\opencode\start_now.py' -WorkingDirectory 'C:\Users\PC\Documents\Default Project\Installux-ChatBot' -WindowStyle Hidden"
```

**OR** directly start the app:

```powershell
python C:\Users\PC\Documents\Default Project\Installux-ChatBot\app.py
```

The server will run on `http://127.0.0.1:8509`

### Option 2: Using the start_now.py script

If the file `C:\Users\PC\AppData\Local\Temp\opencode\start_now.py` exists from earlier, it can be used:

```powershell
python C:\Users\PC\AppData\Local\Temp\opencode\start_now.py
```

### Option 3: Manual startup

```bash
cd C:\Users\PC\Documents\Default Project\Installux-ChatBot
python app.py
```

**Important:** The config.json has been updated to port 8509:
```json
{
  "port": 8509,
  "backend": "openrouter",
  "compute": "cpu",
  "gpu_layers": 0,
  "open_browser": false
}
```

## PWA Deployment (Netlify)

For hosting on Netlify with remote AI only:

1. **Set OPENROUTER_API_KEY** in Netlify environment variables
2. **Deploy the `static/` folder** as a static site
3. **Deploy `netlify/functions/`** as serverless functions that proxy `/api/` routes to OpenRouter with the server-side key
4. **The frontend** calls `/api/ask`, `/api/status` etc. — routed to Functions, which call OpenRouter

**PWA Files Created:**
- `manifest.json` — PWA manifest with name, icons, colors
- `sw.js` — Service worker for caching and API proxy
- `static/index.html` — Updated with manifest link and SW registration

## Current System Status

- **PDF Indexed:** 10 documents (9 original + dtech_comete_70th_installux_en.pdf)
- **Total Pages:** 230 across all catalogues
- **Key Data:** All weight values, reference numbers, dimensions fully searchable
- **French→English Translation:** Automatic via LLM
- **AI Backend:** OpenRouter Claude Sonnet 5 (remote, requires OPENROUTER_API_KEY)
- **Local Model:** Disabled (compute=cpu, gpu_layers=0)

## Verified Answers

1. **"What is the maximum leaf weight for hinge 560032 on a 900 × 2000 mm door?"** → **120 KG**
2. **"Can I use push handle 560017 with lock A5025?"** → **Yes, compatible for single-leaf door, requires electric strike, minimum frame height 1900 mm, source page 8**

---
*To start the server: Run `python app.py` in the Installux-ChatBot folder, then access at http://127.0.0.1:8509*