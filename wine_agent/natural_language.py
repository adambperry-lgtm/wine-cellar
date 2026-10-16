"""Natural language processing and wine label OCR parsing for cellar ingestion."""

import re
from typing import Optional, Dict, Any, Tuple, List
from wine_agent.models import WineBottle, WineType, BottleFormat
from wine_agent.drinking_window import calculate_drinking_window


# Known regions, varietals, and styles for contextual entity mapping
KNOWN_REGIONS = {
    # Bordeaux
    "pauillac": ("Bordeaux", "Pauillac", "France", "Cabernet Sauvignon, Merlot", WineType.RED),
    "margaux": ("Bordeaux", "Margaux", "France", "Cabernet Sauvignon, Merlot", WineType.RED),
    "saint-julien": ("Bordeaux", "Saint-Julien", "France", "Cabernet Sauvignon, Merlot", WineType.RED),
    "saint-estèphe": ("Bordeaux", "Saint-Estèphe", "France", "Cabernet Sauvignon, Merlot", WineType.RED),
    "pessac-léognan": ("Bordeaux", "Pessac-Léognan", "France", "Cabernet Sauvignon, Merlot", WineType.RED),
    "saint-émilion": ("Bordeaux", "Saint-Émilion", "France", "Merlot, Cabernet Franc", WineType.RED),
    "pomerol": ("Bordeaux", "Pomerol", "France", "Merlot, Cabernet Franc", WineType.RED),
    "sauternes": ("Bordeaux", "Sauternes", "France", "Sémillon, Sauvignon Blanc", WineType.DESSERT),
    "bordeaux": ("Bordeaux", "", "France", "Bordeaux Blend", WineType.RED),

    # Burgundy
    "burgundy": ("Burgundy", "Côte d'Or", "France", "Pinot Noir", WineType.RED),
    "gevrey-chambertin": ("Burgundy", "Côte de Nuits", "France", "Pinot Noir", WineType.RED),
    "vosne-romanée": ("Burgundy", "Côte de Nuits", "France", "Pinot Noir", WineType.RED),
    "chambolle-musigny": ("Burgundy", "Côte de Nuits", "France", "Pinot Noir", WineType.RED),
    "meursault": ("Burgundy", "Côte de Beaune", "France", "Chardonnay", WineType.WHITE),
    "puligny-montrachet": ("Burgundy", "Côte de Beaune", "France", "Chardonnay", WineType.WHITE),
    "chassagne-montrachet": ("Burgundy", "Côte de Beaune", "France", "Chardonnay", WineType.WHITE),
    "chablis": ("Burgundy", "Chablis", "France", "Chardonnay", WineType.WHITE),
    "beaujolais": ("Burgundy", "Beaujolais", "France", "Gamay", WineType.RED),

    # Rhône & Loire
    "châteauneuf-du-pape": ("Rhône Valley", "Southern Rhône", "France", "GSM Blend", WineType.RED),
    "chateauneuf du pape": ("Rhône Valley", "Southern Rhône", "France", "GSM Blend", WineType.RED),
    "côte-rôtie": ("Rhône Valley", "Northern Rhône", "France", "Syrah", WineType.RED),
    "cote rotie": ("Rhône Valley", "Northern Rhône", "France", "Syrah", WineType.RED),
    "hermitage": ("Rhône Valley", "Northern Rhône", "France", "Syrah", WineType.RED),
    "crozes-hermitage": ("Rhône Valley", "Northern Rhône", "France", "Syrah", WineType.RED),
    "sancerre": ("Loire Valley", "Central Vineyards", "France", "Sauvignon Blanc", WineType.WHITE),
    "pouilly-fumé": ("Loire Valley", "Central Vineyards", "France", "Sauvignon Blanc", WineType.WHITE),

    # Italy
    "barolo": ("Piedmont", "Langhe", "Italy", "Nebbiolo", WineType.RED),
    "barbaresco": ("Piedmont", "Langhe", "Italy", "Nebbiolo", WineType.RED),
    "brunello": ("Tuscany", "Montalcino", "Italy", "Sangiovese Grosso", WineType.RED),
    "chianti": ("Tuscany", "Chianti Classico", "Italy", "Sangiovese", WineType.RED),
    "bolgheri": ("Tuscany", "Bolgheri", "Italy", "Bordeaux Blend", WineType.RED),
    "amarone": ("Veneto", "Valpolicella", "Italy", "Corvina Blend", WineType.RED),

    # California & Pacific NW
    "napa valley": ("California", "Napa Valley", "USA", "Cabernet Sauvignon", WineType.RED),
    "napa": ("California", "Napa Valley", "USA", "Cabernet Sauvignon", WineType.RED),
    "howell mountain": ("California", "Napa Valley / Howell Mountain", "USA", "Cabernet Sauvignon", WineType.RED),
    "oakville": ("California", "Napa Valley / Oakville", "USA", "Cabernet Sauvignon", WineType.RED),
    "rutherford": ("California", "Napa Valley / Rutherford", "USA", "Cabernet Sauvignon", WineType.RED),
    "calistoga": ("California", "Napa Valley / Calistoga", "USA", "Cabernet Sauvignon", WineType.RED),
    "coombsville": ("California", "Napa Valley / Coombsville", "USA", "Cabernet Sauvignon", WineType.RED),
    "st. helena": ("California", "Napa Valley / St. Helena", "USA", "Cabernet Sauvignon", WineType.RED),
    "sonoma": ("California", "Sonoma County", "USA", "Pinot Noir", WineType.RED),
    "russian river": ("California", "Russian River Valley", "USA", "Pinot Noir", WineType.RED),
    "alexander valley": ("California", "Alexander Valley", "USA", "Cabernet Sauvignon", WineType.RED),
    "paso robles": ("California", "Paso Robles", "USA", "Cabernet Sauvignon", WineType.RED),
    "santa cruz": ("California", "Santa Cruz Mountains", "USA", "Cabernet Sauvignon Blend", WineType.RED),
    "willamette": ("Oregon", "Willamette Valley", "USA", "Pinot Noir", WineType.RED),
    "columbia valley": ("Washington", "Columbia Valley", "USA", "Cabernet Sauvignon", WineType.RED),

    # Other Global
    "champagne": ("Champagne", "", "France", "Chardonnay, Pinot Noir", WineType.SPARKLING),
    "rioja": ("Rioja", "Rioja Alta", "Spain", "Tempranillo", WineType.RED),
    "ribera del duero": ("Castilla y León", "Ribera del Duero", "Spain", "Tempranillo / Tinto Fino", WineType.RED),
    "priorat": ("Catalonia", "Priorat", "Spain", "Garnacha, Cariñena", WineType.RED),
    "mosel": ("Mosel", "", "Germany", "Riesling", WineType.WHITE),
    "rheingau": ("Rheingau", "", "Germany", "Riesling", WineType.WHITE),
    "mendoza": ("Mendoza", "Uco Valley", "Argentina", "Malbec", WineType.RED),
    "barossa": ("South Australia", "Barossa Valley", "Australia", "Shiraz", WineType.RED),
    "marlborough": ("Marlborough", "", "New Zealand", "Sauvignon Blanc", WineType.WHITE),
    "port": ("Douro", "", "Portugal", "Touriga Nacional Blend", WineType.FORTIFIED),
}

COMMON_PRODUCERS = [
    # User's cellar brands:
    "Hunnicutt", "Hunnicut", "Gargiulo Vineyards", "Gargiulo", "Garguilo Vineyards", "Garguilo",
    "Faust", "Arkenstone", "Pax", "Pax Mahle",
    "Tenuta Villa Pandolfini", "Villa Pandolfini", "Pandolfini",
    # Classic California icons:
    "Caymus", "Silver Oak", "Ridge Vineyards", "Ridge", "Opus One", "Dominus Estate", "Dominus",
    "Harlan Estate", "Screaming Eagle", "Duckhorn",
    "Stags' Leap Winery", "Stags' Leap", "Stags Leap Winery", "Stags Leap",
    "Stag's Leap Wine Cellars", "Stag's Leap",
    "Justin", "Jordan", "The Prisoner", "Belle Glos", "Meiomi", "Austin Hope",
    "Rombauer", "Cakebread", "Far Niente", "Kendall-Jackson", "La Crema",
    "Shafer", "Joseph Phelps", "Heitz Cellar", "Chappellet", "Spottswoode", "Quintessa",
    "Nickel & Nickel", "Pahlmeyer", "Groth", "PlumpJack", "Frank Family",
    # Bordeaux First & Classified Growths:
    "Château Pontet-Canet", "Château Margaux", "Château Latour", "Château Lafite Rothschild",
    "Château Mouton Rothschild", "Château Haut-Brion", "Château Lynch-Bages", "Château Montrose",
    "Château Palmer", "Château Pichon Baron", "Château Pichon Longueville Comtesse de Lalande",
    "Château Cheval Blanc", "Château Ausone", "Petrus", "Château d'Yquem",
    # Burgundy & Rhone:
    "Domaine de la Romanée-Conti", "Domaine Armand Rousseau", "Domaine Leflaive", "Raveneau",
    "E. Guigal", "Château de Beaucastel", "Vieux Télégraphe", "Clos des Papes",
    # Italy:
    "Biondi-Santi", "Giacomo Conterno", "Antinori", "Sassicaia", "Ornellaia", "Tignanello",
    "Gaja", "Fontodi", "Marchesi di Barolo", "Produttori del Barbaresco", "Tenuta San Guido",
    # Spain:
    "La Rioja Alta", "Vega Sicilia", "CVNE", "Marqués de Murrieta", "López de Heredia",
    # Champagne:
    "Dom Pérignon", "Veuve Clicquot", "Krug", "Louis Roederer", "Taittinger", "Billecart-Salmon", "Bollinger",
    "Perrier-Jouët", "Pol Roger", "Ruinart",
    # Global:
    "Penfolds", "Cloudy Bay", "Catena Zapata", "Kim Crawford", "Egon Müller"
]

VARIETAL_DETECTION = [
    (r"\bcabernet\s+sauvignon\b", "Cabernet Sauvignon", WineType.RED),
    (r"\bcabernet\s+franc\b", "Cabernet Franc", WineType.RED),
    (r"\bcabernet\b", "Cabernet Sauvignon", WineType.RED),
    (r"\bpinot\s+noir\b", "Pinot Noir", WineType.RED),
    (r"\bnebbiolo\b", "Nebbiolo", WineType.RED),
    (r"\bsangiovese\b", "Sangiovese", WineType.RED),
    (r"\bsyrah\b", "Syrah", WineType.RED),
    (r"\bshiraz\b", "Shiraz", WineType.RED),
    (r"\bzinfandel\b", "Zinfandel", WineType.RED),
    (r"\bmerlot\b", "Merlot", WineType.RED),
    (r"\btempranillo\b", "Tempranillo", WineType.RED),
    (r"\bmalbec\b", "Malbec", WineType.RED),
    (r"\bgrenache\b|\bgarnacha\b", "Grenache", WineType.RED),
    (r"\bpetite\s+sirah\b", "Petite Sirah", WineType.RED),
    (r"\bgamay\b", "Gamay", WineType.RED),
    (r"\bchardonnay\b", "Chardonnay", WineType.WHITE),
    (r"\bsauvignon\s+blanc\b", "Sauvignon Blanc", WineType.WHITE),
    (r"\briesling\b", "Riesling", WineType.WHITE),
    (r"\bpinot\s+grigio\b|\bpinot\s+gris\b", "Pinot Grigio", WineType.WHITE),
    (r"\bchenin\s+blanc\b", "Chenin Blanc", WineType.WHITE),
    (r"\bviognier\b", "Viognier", WineType.WHITE),
    (r"\bchampagne\b|\bprosecco\b|\bcava\b|\bcrémant\b|\bsparkling\b", "Sparkling Blend", WineType.SPARKLING),
    (r"\brosé\b|\brose\b", "Rosé Blend", WineType.ROSE),
]


def parse_wine_natural_language(text: str) -> WineBottle:
    """Parses free-form wine text (e.g. from receipt, notes, or spoken input) into a structured WineBottle."""
    raw = text.strip()

    # 1. Extract Quantity
    qty = 1
    # Check for prefix 'x' like 'x 6' or 'x6'
    m_x_prefix = re.search(r'\bx\s*(\d+)\b', raw, re.IGNORECASE)
    if m_x_prefix:
        qty = int(m_x_prefix.group(1))
    else:
        # Check for number followed by x or bottle/btl, ensuring number is not a 4-digit vintage
        qty_match = re.search(r'\b(?!(?:19\d\d|20\d\d)\b)(\d+)\s*(?:x|bottles?|btls?|btl)\b', raw, re.IGNORECASE)
        if qty_match:
            qty = int(qty_match.group(1))
        elif re.search(r'\b(?:a|one)\s+bottle\b', raw, re.IGNORECASE):
            qty = 1

    # 2. Extract Vintage
    vintage = None
    if re.search(r'\b(?:NV|non[- ]vintage)\b', raw, re.IGNORECASE):
        vintage = None
    else:
        v_match = re.search(r'\b(19\d\d|20[0-2]\d)\b', raw)
        if v_match:
            vintage = int(v_match.group(1))

    # 3. Extract Price
    price = None
    price_match = re.search(r'\$\s*([0-9]+(?:\.[0-9]{2})?)|\b([0-9]+(?:\.[0-9]{2})?)\s*(?:dollars?|usd)\b', raw, re.IGNORECASE)
    if price_match:
        val_str = price_match.group(1) or price_match.group(2)
        try:
            price = float(val_str)
        except ValueError:
            price = None

    # 4. Extract Bottle Format
    b_format = BottleFormat.STANDARD
    if re.search(r'\b(?:magnum|1\.5l|1500ml)\b', raw, re.IGNORECASE):
        b_format = BottleFormat.MAGNUM
    elif re.search(r'\b(?:half[- ]bottle|demi|375ml)\b', raw, re.IGNORECASE):
        b_format = BottleFormat.HALF
    elif re.search(r'\b(?:double[- ]magnum|jeroboam|3l)\b', raw, re.IGNORECASE):
        b_format = BottleFormat.DOUBLE_MAGNUM

    # 5. Extract Rack and Bin Location
    rack = ""
    bin_loc = ""
    if re.search(r'\b(?:basement|downstairs)\b', raw, re.IGNORECASE):
        rack = "Basement Fridge"
    elif re.search(r'\b(?:upstairs|kitchen)\b', raw, re.IGNORECASE):
        rack = "Upstairs Fridge"

    loc_match = re.search(r'(?:in|at|rack)\s+([A-Za-z0-9\s\-]+?)(?:,\s*|\s+)(?:bin|shelf|row)\s+([A-Za-z0-9\s\-]+)', raw, re.IGNORECASE)
    if loc_match:
        if not rack:
            r_clean = re.sub(r'(?i)\brack\b', '', loc_match.group(1)).strip()
            rack = f"Rack {r_clean}" if r_clean else loc_match.group(1).strip()
        b_clean = re.sub(r'(?i)\b(?:bin|shelf|row)\b', '', loc_match.group(2)).strip()
        prefix = "Shelf" if "shelf" in raw.lower() else "Bin"
        bin_loc = f"{prefix} {b_clean}" if b_clean else loc_match.group(2).strip()
    else:
        rack_single = re.search(r'\brack\s+([A-Za-z0-9\-]+)\b', raw, re.IGNORECASE)
        shelf_single = re.search(r'\bshelf\s+([A-Za-z0-9\-]+)\b', raw, re.IGNORECASE)
        bin_single = re.search(r'\bbin\s+([A-Za-z0-9\-]+)\b', raw, re.IGNORECASE)
        if rack_single and not rack:
            rack = f"Rack {rack_single.group(1).strip()}"
        if shelf_single:
            bin_loc = f"Shelf {shelf_single.group(1).strip()}"
        elif bin_single:
            bin_loc = f"Bin {bin_single.group(1).strip()}"

    if not rack:
        rack = "Basement Fridge"

    # 6. Clean Text of extracted metadata to isolate Wine Name & Producer
    clean_text = raw
    clean_text = re.sub(r'^(?:i\s+bought|i\s+have|add|just\s+picked\s+up|purchased|got)\s+', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bx\s*\d+\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?!(?:19\d\d|20\d\d)\b)\d+\s*(?:x|bottles?|btls?|btl)\s*(?:of)?\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?:a|one)\s+bottle\s*(?:of)?\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?:for|at)?\s*\$\s*[0-9]+(?:\.[0-9]{2})?\s*(?:each|per bottle|a piece)?\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b[0-9]+(?:\.[0-9]{2})?\s*(?:dollars?|usd)\s*(?:each|per bottle)?\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\$\s*[0-9]+(?:\.[0-9]{2})?', '', clean_text)
    clean_text = re.sub(r'(?:in|at|rack)\s+[A-Za-z0-9\s\-]+?(?:bin|shelf|row)\s+[A-Za-z0-9\s\-]+', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?:in|at)\s+(?:rack|bin|shelf)\s+[A-Za-z0-9\-]+\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?:rack|bin|shelf)\s+[A-Za-z0-9\-]+\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?:magnum|half[- ]bottle|375ml|1\.5l)\b', '', clean_text, flags=re.IGNORECASE)
    if vintage:
        clean_text = re.sub(rf'\b{vintage}\b', '', clean_text)
    clean_text = re.sub(r'\b(?:each|for|of|in|at)\b', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip(' ,.;')

    # 7. Identify Region, Varietal, Country, WineType
    region = ""
    sub_region = ""
    country = ""
    varietal = ""
    wine_type = WineType.RED

    lowered = raw.lower()
    for reg_key, (r, sr, c, var, wt) in KNOWN_REGIONS.items():
        if reg_key in lowered:
            region = r
            sub_region = sr
            country = c
            varietal = var
            wine_type = wt
            break

    # If varietal was not set by region, check explicit grape names
    for pattern, v_name, wt in VARIETAL_DETECTION:
        if re.search(pattern, lowered):
            varietal = v_name
            wine_type = wt
            break

    # Specific producer/wine enrichments
    if any(k in lowered for k in ["pandolfini", "primorosso", "selve"]):
        producer = "Tenuta Villa Pandolfini"
        wine_name = "Primorosso (Podere Le Selve)"
        region = "Tuscany"
        sub_region = "Lastra a Signa / Colli Fiorentini"
        country = "Italy"
        varietal = "Sangiovese Blend"
        wine_type = WineType.RED
        if price is None:
            price = 28.00
    elif any(k in lowered for k in ["hunnicutt", "hunnicut"]):
        producer = "Hunnicutt"
        region = "California"
        sub_region = "Napa Valley / Rutherford"
        country = "USA"
        wine_type = WineType.RED
        if "brinkman" in lowered:
            wine_name = "Brinkman Block Cabernet Sauvignon"
            varietal = "Cabernet Sauvignon"
            if price is None:
                price = 165.00
        else:
            wine_name = clean_text
            for cp in ["Hunnicutt", "Hunnicut"]:
                wine_name = re.sub(re.escape(cp), '', wine_name, flags=re.IGNORECASE).strip(' ,-')
    else:
        # 8. Determine Producer vs Wine Name
        producer = clean_text
        wine_name = ""
        for cp in COMMON_PRODUCERS:
            if cp.lower() in clean_text.lower():
                producer = cp
                rem = re.sub(re.escape(cp), '', clean_text, flags=re.IGNORECASE).strip(' ,-')
                if rem:
                    wine_name = rem
                break

        if not wine_name and producer:
            parts = re.split(r'[,–-]', producer, maxsplit=1)
            if len(parts) == 2:
                producer = parts[0].strip()
                wine_name = parts[1].strip()

    bottle = WineBottle(
        producer=producer or "Unknown Producer",
        wine_name=wine_name,
        vintage=vintage,
        varietal=varietal or "Blend",
        region=region or "Global",
        sub_region=sub_region,
        country=country or "",
        wine_type=wine_type,
        format=b_format,
        quantity=qty,
        location_rack=rack or "Basement Fridge",
        location_bin=bin_loc or "Unassigned",
        purchase_price=price,
        personal_notes=f"Quick added: '{text}'"
    )
    bottle.drinking_window = calculate_drinking_window(bottle)
    return bottle


def parse_wine_label(label_text: str, default_fridge: str = "Basement Fridge") -> WineBottle:
    """Parses raw text extracted from a wine bottle label photo via OCR.

    Cleans regulatory boilerplate, recognizes vintages, varietals, producers,
    and returns a structured WineBottle with its calculated drinking window.
    """
    raw_lines = [l.strip() for l in label_text.splitlines() if l.strip()]
    if not raw_lines:
        return parse_wine_natural_language(label_text)

    # 1. Filter out common OCR noise and regulatory lines
    noise_regexes = [
        r'(?i)government\s+warning.*',
        r'(?i)contains\s+sulfites.*',
        r'(?i)contient\s+des\s+sulfites.*',
        r'(?i)enth[aä]lt\s+sulfite.*',
        r'(?i)alc\.?\s*\d+(\.\d+)?\s*%.*',
        r'(?i)\d+(\.\d+)?\s*%\s*alc.*',
        r'(?i)\b\d+(\.\d+)?\s*%\s*vol\b',
        r'(?i)produced\s+(?:and|&)\s+bottled.*',
        r'(?i)vinted\s+(?:and|&)\s+bottled.*',
        r'(?i)estate\s+bottled\b',
        r'(?i)mis\s+en\s+bouteille.*',
        r'(?i)appellation\s+.*contr[oô]l[eé]e',
        r'(?i)protecting\s+nature.*',
        r'(?i)product\s+of\s+.*',
        r'(?i)produit\s+de\s+.*',
        r'(?i)imported\s+by.*',
        r'(?i)drink\s+responsibly.*',
        r'(?i)pregnancy\s+warning.*',
        r'(?i)750\s*ml|1\.5\s*l|375\s*ml|1500\s*ml|75\s*cl',
    ]

    cleaned_lines = []
    sku_found = None
    detected_format = BottleFormat.STANDARD

    full_lower = label_text.lower()
    if "1.5l" in full_lower or "magnum" in full_lower or "1500ml" in full_lower:
        detected_format = BottleFormat.MAGNUM
    elif "375ml" in full_lower or "half-bottle" in full_lower:
        detected_format = BottleFormat.HALF

    for line in raw_lines:
        # Check for SKU codes (e.g. DRH23C79, DRH24C7, DRH24ZN7)
        sku_m = re.match(r'^(DRH[0-9A-Za-z]+|SKU:?\s*[0-9A-Za-z]+|LOT:?\s*[0-9A-Za-z]+)$', line, re.I)
        if sku_m:
            sku_found = sku_m.group(1)
            continue

        skip = False
        for nr in noise_regexes:
            if re.search(nr, line):
                skip = True
                break

        # Skip lines that are mostly punctuation, slashes, bars, or OCR noise
        alnum = re.findall(r'[a-zA-Z0-9]', line)
        if len(line) >= 3 and len(alnum) / max(len(line), 1) < 0.35:
            skip = True

        if not skip and len(line) >= 2:
            cleaned_lines.append(line)

    joined_text = " ".join(cleaned_lines) if cleaned_lines else label_text

    # 2. Extract Vintage
    vintage = None
    if re.search(r'\b(?:NV|non[- ]vintage|sans\s+ann[eé]e)\b', joined_text, re.IGNORECASE):
        vintage = None
    else:
        v_match = re.search(r'\b(19\d\d|20[0-2]\d)\b', joined_text)
        if v_match:
            vintage = int(v_match.group(1))

    # 3. Detect Region & Country
    region = ""
    sub_region = ""
    country = ""
    varietal = ""
    producer = ""
    wine_type = WineType.RED

    for reg_key, (r, sr, c, var, wt) in KNOWN_REGIONS.items():
        if reg_key in joined_text.lower():
            region = r
            sub_region = sr
            country = c
            varietal = var
            wine_type = wt
            break

    # 4. Detect Varietal
    for pattern, v_name, wt in VARIETAL_DETECTION:
        if re.search(pattern, joined_text, re.IGNORECASE):
            varietal = v_name
            wine_type = wt
            break

    # Specific Hunnicutt wine naming intelligence
    is_hunnicutt = "hunnicutt" in joined_text.lower()
    if is_hunnicutt and "9-3-5" in joined_text:
        varietal = "Cabernet Sauvignon Blend"
        wine_type = WineType.RED

    # Stags' Leap Winery & Petite Sirah intelligence
    is_stags_leap = any(s in joined_text.lower() for s in ["stags leap", "stags' leap", "stag's leap", "1893"])
    if is_stags_leap:
        producer = "Stags' Leap Winery"
        if any(p in joined_text.lower() for p in ["petite", "sirah", "syrah"]):
            varietal = "Petite Sirah"
            wine_type = WineType.RED
        if not region:
            region = "Napa Valley, California"

    # 5. Determine Producer
    if not producer:
        for cp in COMMON_PRODUCERS:
            if cp.lower() in joined_text.lower():
                producer = cp
                break

    # Fallback to top non-noise line if producer not matched
    if not producer and cleaned_lines:
        for line in cleaned_lines:
            l_clean = re.sub(r'[^a-zA-Z0-9\s\'-]', '', line).strip()
            letters = re.findall(r'[a-zA-Z]', l_clean)
            # Require at least 4 letters and genuine word structure to avoid OCR noise
            if len(letters) < 4:
                continue
            l_lower = l_clean.lower()
            if vintage and str(vintage) == line.strip():
                continue
            if varietal and varietal.lower() == l_lower:
                continue
            if region and region.lower() == l_lower:
                continue
            producer = l_clean
            break

    if not producer:
        producer = "Unidentified Wine"

    # 6. Determine Wine Name / Cuvée
    wine_name_candidates = []
    for line in cleaned_lines:
        l_clean = line
        if producer.lower() in l_clean.lower():
            l_clean = re.sub(re.escape(producer), '', l_clean, flags=re.IGNORECASE).strip()
        if vintage:
            l_clean = re.sub(rf'\b{vintage}\b', '', l_clean).strip()
        if region and region.lower() in l_clean.lower():
            l_clean = re.sub(re.escape(region), '', l_clean, flags=re.IGNORECASE).strip()
        if sub_region and sub_region.lower() in l_clean.lower():
            l_clean = re.sub(re.escape(sub_region), '', l_clean, flags=re.IGNORECASE).strip()

        l_clean = l_clean.strip(' ,-•')
        if l_clean and len(l_clean) > 2 and l_clean.lower() != varietal.lower():
            wine_name_candidates.append(l_clean)

    wine_name = " ".join(wine_name_candidates[:2]).strip()
    if not wine_name:
        wine_name = varietal or "Reserve"

    # 7. Check Fridge Placement
    fridge = default_fridge
    if re.search(r'\b(?:basement|downstairs)\b', joined_text, re.IGNORECASE):
        fridge = "Basement Fridge"
    elif re.search(r'\b(?:upstairs|kitchen)\b', joined_text, re.IGNORECASE):
        fridge = "Upstairs Fridge"

    notes = "Added via Label Scanner"
    if sku_found:
        notes += f" (SKU: {sku_found})"

    bottle = WineBottle(
        producer=producer,
        wine_name=wine_name,
        vintage=vintage,
        varietal=varietal or "Blend",
        region=region or "Cellar Selection",
        sub_region=sub_region,
        country=country or ("USA" if "napa" in joined_text.lower() or "california" in joined_text.lower() else ""),
        wine_type=wine_type,
        format=detected_format,
        quantity=1,
        location_rack=fridge,
        location_bin="Shelf 1",
        purchase_price=None,
        personal_notes=notes
    )
    bottle.drinking_window = calculate_drinking_window(bottle)
    return bottle


def parse_batch_wines(text: str, default_fridge: str = "Basement Fridge") -> list:
    """Parses multi-line text blocks with fridge headers and bullet points."""
    lines = text.strip().splitlines()
    bottles = []
    current_fridge = default_fridge
    current_shelf = ""

    for line in lines:
        cleaned = line.strip().lstrip("-*•>").strip()
        if not cleaned:
            continue

        if re.search(r'^(?:wine\s*)?basement(?:\s*fridge)?\s*[:\-]?\s*$', cleaned, re.IGNORECASE):
            current_fridge = "Basement Fridge"
            continue
        if re.search(r'^(?:wine\s*)?upstairs(?:\s*fridge)?\s*[:\-]?\s*$', cleaned, re.IGNORECASE):
            current_fridge = "Upstairs Fridge"
            continue

        header_match = re.match(r'^(?:wine\s*)?(fridge\s*[0-9A-Za-z]+|cellar|cooler)\s*[:\-]?\s*(.*)$', cleaned, re.IGNORECASE)
        shelf_match = re.match(r'^(?:shelf|row|bin)\s*([0-9A-Za-z]+)\s*[:\-]?\s*(.*)$', cleaned, re.IGNORECASE)

        if header_match and not header_match.group(2).strip():
            current_fridge = header_match.group(1).title()
            continue
        if shelf_match and not shelf_match.group(2).strip():
            current_shelf = f"Shelf {shelf_match.group(1)}"
            continue

        bottle = parse_wine_natural_language(cleaned)
        if bottle.location_rack == "Basement Fridge" and current_fridge != "Basement Fridge":
            bottle.location_rack = current_fridge
        if bottle.location_bin == "Unassigned" and current_shelf:
            bottle.location_bin = current_shelf

        bottles.append(bottle)

    return bottles
