# 🍷 Sommelier Wine Cellar Agent & Drinking Window Assistant

An intelligent, master-sommelier-grade agent and cellar management platform built to organize your wine collection, track bin locations, and identify precise drinking windows for every bottle.

---

## 🌟 Key Capabilities

1. **Enological Drinking Window Engine**:
   - Analyzes grape varietals, regional classifications (Bordeaux Cru Classé, Burgundy Grand/Premier Cru, Barolo Riserva, Napa Cult, Rioja Gran Reserva, Vintage Port, etc.), and producer prestige.
   - **Maturity Status Tiers**:
     - ⏳ `Hold (Too Young)`: High tannins and brisk acidity; aging required for tertiary complexity.
     - 🌊 `Approaching Peak`: Entering drinkability; decanting 1.5–2.5h recommended.
     - 🍷 `In Peak Window`: Ideal equilibrium of fruit, acid, and resolved tannins.
     - ⚠️ `Drink Soon (Late Peak)`: Tertiary earth and leather dominant; fruit tapering. Prioritize opening!
     - 🚨 `Past Peak (Decline)`: Past prime; open promptly.
   - **Format Scaling**: Automatically adjusts aging duration based on bottle format (Half-bottles mature ~25% faster; Magnums age ~30% slower).
   - **Vintage Scoring Adjustments**: Accounts for landmark age-worthy vintages (e.g., Bordeaux 2010/2016, Barolo 2016, Napa 2013/2016, Champagne 2008) by extending peak windows.

2. **Sommelier Service Guidance**:
   - Calculates exact **decanting times** (from gentle aeration off sediment to 3-hour decants for young Barolo).
   - Recommends optimal **serving temperatures** in °F and °C.
   - Explains the specific structure and tasting profile of each wine.

3. **Natural Language & Voice Ingestion**:
   - Add bottles in plain English (spoken or typed):
     > *"Bought 2 bottles of 2018 Château Pontet-Canet Pauillac for $160 each in Rack A Bin 3"*
   - The NLP parser extracts producer, wine name, vintage, varietal, region, country, format, quantity, price, rack, and bin automatically!

4. **📸 AI Wine Label Scanner (OCR + Sommelier Intelligence)**:
   - Drag-and-drop or photograph wine bottle labels directly in the web dashboard (or via CLI).
   - In-browser optical character recognition (OCR) strips regulatory boilerplate and extracts producer, vintage, cuvée, varietal, and region.
   - Automatically computes drinking windows, serving temperatures, and decant times.
   - Pre-assigns directly to **Basement Fridge** or **Upstairs Fridge** with 1 click.

5. **Sommelier Pairing & Recommendation Engine**:
   - Ask: *"What should I open tonight with prime ribeye steak?"* or *"Give me something celebratory with duck breast."*
   - Matches culinary flavour profiles with bottles in your cellar that are *currently in their peak window*.

6. **Interactive Web Dashboard & Visual Timeline**:
   - Maturation curve Gantt chart showing where every bottle sits relative to the current year (**2026 NOW indicator**).
   - Instant filtering, search, consumption logger, and cellar valuation statistics.

7. **Full Import & Export Support**:
   - Import and export CSV spreadsheets (compatible with CellarTracker exports).

---

## 🚀 Quick Start

### 1. View Current Cellar Inventory
```bash
cd /Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent
./cellar list
```

### 2. View Bottles Ready to Drink Now (Peak Window)
```bash
./cellar peak
```

### 3. Check Urgent Bottles to Drink Soon
```bash
./cellar urgent
```

### 4. Run a Cellar Health & Valuation Audit
```bash
./cellar audit
```

### 5. Ask Sommelier for Dinner Pairings Tonight
```bash
./cellar recommend --food "ribeye steak"
./cellar recommend --food "roast duck"
./cellar recommend --food "fresh oysters"
```

### 6. Add Bottles with Voice or Natural Language
```bash
./cellar parse "I bought 2 bottles of 2018 Château Pontet-Canet Pauillac for \$160 each in Basement Fridge Shelf 1"
```

### 7. Scan Wine Label from Photo or Text
```bash
./cellar scan "HUNNICUTT 2024 CABERNET SAUVIGNON NAPA VALLEY" --fridge "Basement Fridge"
```

### 8. Mark a Bottle as Opened / Consumed
```bash
./cellar drink <bottle_id>
```

### 9. Deploy to Railway Cloud

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https%3A%2F%2Fgithub.com%2Fadambperry-lgtm%2Fwine-cellar)

Deploy the complete backend server, database, and interactive dashboard to [Railway](https://railway.app):

#### Option A: Connect via GitHub (Automatic CI/CD)
1. Go to [Railway Dashboard](https://railway.app/dashboard) and click **New Project** → **Deploy from GitHub repo**.
2. Select your repository: `adambperry-lgtm/wine-cellar`.
3. Railway automatically detects the included `railway.json`, `Dockerfile`, and `Procfile`.
4. Under **Variables**, add:
   - `GEMINI_API_KEY`: *(Optional)* Your Google Gemini API Key.
   - `CELLAR_DB_PATH`: *(Optional)* `/data/cellar.db` if using an attached persistent volume.

#### Option B: Deploy via Railway CLI
```bash
# Authenticate CLI
railway login

# Initialize project and deploy
railway link  # or railway init
railway up
```

---

## 📁 Project Architecture

```
wine_cellar_agent/
├── cellar                              # Main executable CLI script
├── cellar.db                           # Persistent SQLite database
├── wine_agent/
│   ├── __init__.py                     # Package init
│   ├── models.py                       # WineBottle, DrinkingWindow, and status enums
│   ├── drinking_window.py              # Enological maturity calculation engine
│   ├── database.py                     # SQLite CRUD, stats, CSV import/export
│   ├── natural_language.py             # NLP receipt/voice text entity extractor
│   ├── agent.py                        # Sommelier pairing logic and cellar health auditor
│   ├── cli.py                          # ANSI formatted command line tool
│   └── server.py                       # Lightweight HTTP REST backend
├── web/
│   └── index.html                      # Interactive web dashboard with aging timeline
├── tests/
│   └── test_wine_agent.py              # Automated unit tests
└── .agents/
    └── skills/
        └── wine-sommelier/
            └── SKILL.md                # Antigravity skill definition
```

---

## 📊 Drinking Window Timeline Structure

Each bottle is evaluated on a continuous maturation curve:

```
[Vintage] ===== Youth / Hold ===== [Window Start] --- Approach --- [Peak Start] ====== PRIME PEAK ====== [Peak End] --- Late Peak --- [Window End] >>> Decline
```
- **Hold (Too Young)**: Primary fruit and tannins dominate; tertiary development has not begun.
- **Approaching Peak**: Beginning to open up; aeration or decanting helps express aromatics.
- **In Peak Window**: Harmony between acidity, tannin resolution, and secondary/tertiary balance.
- **Late Peak**: Fading primary fruit; savory notes (leather, tobacco, forest floor) dominate. Drink within 1–2 years.
- **Past Peak**: Acidity or oxidation overtakes fruit. Open immediately.
