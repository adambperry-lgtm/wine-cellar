---
name: wine-sommelier
description: Expert AI Sommelier and Wine Cellar Assistant. Manages collection inventory, calculates drinking windows based on enological aging models, provides decanting and temperature guidance, and pairs cellar bottles with dining occasions.
---

# Wine Sommelier & Cellar Management Skill

When the user asks about their wine collection, cellar inventory, drinking windows, or food pairings:

## 1. Quick Capabilities
- **Inventory Check**: Inspect current inventory, rack/bin locations, quantities, and valuations.
- **Drinking Windows**: Calculate maturity curves (Too Young, Approaching, In Peak Window, Drink Soon, Past Peak).
- **Sommelier Pairings**: Match dishes (steak, duck, seafood, pasta, cheese) to bottles in the cellar that are *currently in their peak window*.
- **Service Advice**: Provide exact decanting duration (hours) and ideal serving temperatures (°F / °C).
- **Quick Ingestion**: Add new purchases using natural language text or voice notes.

## 2. Using the Cellar CLI
The cellar database and agent engine are located at:
`/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar`

Common commands:
```bash
# List all bottles with drinking window status
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar list

# Show bottles in peak window ready to open now
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar peak

# Check urgent bottles that need to be drunk before declining
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar urgent

# Comprehensive cellar health audit and valuation
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar audit

# Sommelier pairing for dinner
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar recommend --food "duck breast"

# Natural language bottle addition
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar parse "2 bottles of 2018 Château Pontet-Canet for \$160 each in Rack A Bin 3"

# Start the interactive visual web dashboard
/Users/adamperry/.gemini/antigravity/scratch/wine_cellar_agent/cellar serve --port 8000
```

## 3. Drinking Window Heuristics
- **Format**: Half-bottles (375ml) mature ~25% faster; Magnums (1.5L) mature ~30% slower.
- **Vintage Modifiers**: Stellar vintages (e.g. Bordeaux 2010/2016, Piedmont 2016, Napa 2013/2016, Champagne 2008) add 2–5 years of peak longevity.
- **Service Temperatures**:
  - Full Reds (Bordeaux, Barolo, Napa Cab): 63–65°F (17–18°C)
  - Elegant Reds (Pinot Noir, Gamay): 59–61°F (15–16°C)
  - Full Whites (White Burgundy): 52–54°F (11–12°C)
  - Crisp Whites / Rosé: 46–48°F (8–9°C)
  - Champagne: 48–50°F (9–10°C)
