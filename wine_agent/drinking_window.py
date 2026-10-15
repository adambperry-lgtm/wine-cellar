"""Drinking Window Calculation Engine.

Implements enological rules and vintage maturity profiles across world wine regions,
varietals, bottle formats, and quality tiers.
"""

from typing import Optional, Tuple, Dict, Any
from datetime import datetime
from wine_agent.models import WineType, DrinkingStatus, BottleFormat, DrinkingWindow, WineBottle


# Reference year for cellar status calculations (defaults to current year)
CURRENT_YEAR = 2026


# Benchmark aging profiles by category, varietal, and regional classification
# Tuple format: (min_years_to_start, min_years_to_peak, max_years_to_peak, max_years_to_drink, tier_name)
AGING_PROFILES = {
    # BORDEAUX
    "bordeaux_first_growth": (10, 15, 30, 45, "First Growth / Super Second (15-45 yrs)"),
    "bordeaux_left_bank_classified": (8, 12, 24, 35, "Left Bank Grand Cru Classé (12-35 yrs)"),
    "bordeaux_right_bank_premier": (7, 10, 22, 30, "Right Bank Premier Grand Cru / Pomerol (10-30 yrs)"),
    "bordeaux_cru_bourgeois": (4, 6, 12, 18, "Cru Bourgeois / Médoc (6-18 yrs)"),
    "bordeaux_generic": (2, 3, 7, 10, "Bordeaux AOC Standard (3-10 yrs)"),

    # BURGUNDY RED (PINOT NOIR)
    "burgundy_grand_cru_red": (8, 12, 25, 35, "Burgundy Grand Cru Red (12-35 yrs)"),
    "burgundy_premier_cru_red": (5, 8, 16, 24, "Burgundy 1er Cru Red (8-24 yrs)"),
    "burgundy_village_red": (3, 5, 10, 15, "Burgundy Village Red (5-15 yrs)"),
    "burgundy_regional_red": (2, 3, 6, 9, "Bourgogne Rouge (3-9 yrs)"),

    # BURGUNDY WHITE (CHARDONNAY)
    "burgundy_grand_cru_white": (6, 9, 18, 25, "Burgundy Grand Cru White (9-25 yrs)"),
    "burgundy_premier_cru_white": (4, 6, 12, 18, "Burgundy 1er Cru White (6-18 yrs)"),
    "burgundy_village_white": (3, 4, 8, 12, "Burgundy Village White (4-12 yrs)"),
    "chablis_grand_cru": (5, 8, 16, 22, "Chablis Grand Cru (8-22 yrs)"),
    "chablis_premier_cru": (3, 5, 10, 15, "Chablis 1er Cru (5-15 yrs)"),

    # PIEDMONT (NEBBIOLO)
    "barolo_riserva_cru": (10, 14, 28, 40, "Barolo Cru / Riserva (14-40 yrs)"),
    "barolo_standard": (7, 10, 20, 30, "Barolo DOCG (10-30 yrs)"),
    "barbaresco": (6, 9, 18, 28, "Barbaresco DOCG (9-28 yrs)"),
    "nebbiolo_langhe": (2, 4, 8, 12, "Langhe Nebbiolo (4-12 yrs)"),
    "barbera_d_asti": (2, 3, 7, 10, "Barbera d'Asti / d'Alba (3-10 yrs)"),

    # TUSCANY (SANGIOVESE & SUPER TUSCANS)
    "brunello_riserva": (8, 12, 25, 35, "Brunello di Montalcino Riserva (12-35 yrs)"),
    "brunello_annata": (6, 9, 18, 26, "Brunello di Montalcino (9-26 yrs)"),
    "chianti_gran_selezione": (5, 8, 16, 22, "Chianti Classico Gran Selezione (8-22 yrs)"),
    "chianti_riserva": (4, 6, 12, 18, "Chianti Classico Riserva (6-18 yrs)"),
    "chianti_annata": (2, 3, 7, 10, "Chianti Classico Annata (3-10 yrs)"),
    "super_tuscan_premium": (7, 11, 24, 32, "Super Tuscan Icon (e.g. Sassicaia, Tignanello) (11-32 yrs)"),
    "bolgheri_rosso_second": (3, 5, 12, 18, "Bolgheri Rosso / Second Wine (e.g. Guidalberto, Le Serre Nuove) (5-18 yrs)"),

    # RHÔNE VALLEY
    "rhone_hermitage_cote_rotie": (8, 12, 25, 35, "Hermitage / Côte-Rôtie (12-35 yrs)"),
    "rhone_cornas_st_joseph": (5, 7, 15, 22, "Cornas / Saint-Joseph (7-22 yrs)"),
    "chateauneuf_du_pape_prestige": (6, 9, 20, 28, "Châteauneuf-du-Pape Top Cuvée (9-28 yrs)"),
    "chateauneuf_du_pape_standard": (4, 6, 14, 20, "Châteauneuf-du-Pape Standard (6-20 yrs)"),
    "cotes_du_rhone": (2, 3, 6, 9, "Côtes du Rhône (3-9 yrs)"),

    # NAPA VALLEY & CALIFORNIA CABERNET
    "napa_cult_cabernet": (8, 12, 26, 35, "Napa Cult / Mountain Cabernet (12-35 yrs)"),
    "napa_valley_cabernet": (5, 8, 16, 24, "Napa Valley AVA Cabernet (8-24 yrs)"),
    "california_pinot_noir": (3, 5, 10, 15, "Sonoma / Santa Barbara Pinot Noir (5-15 yrs)"),
    "california_chardonnay_oaked": (2, 4, 8, 12, "California Premium Chardonnay (4-12 yrs)"),
    "california_zinfandel": (3, 5, 10, 14, "Old Vine Zinfandel (5-14 yrs)"),

    # SPAIN
    "rioja_gran_reserva": (8, 12, 24, 35, "Rioja Gran Reserva (12-35 yrs)"),
    "rioja_reserva": (5, 7, 14, 20, "Rioja Reserva (7-20 yrs)"),
    "rioja_crianza": (2, 3, 6, 9, "Rioja Crianza (3-9 yrs)"),
    "ribera_del_duero_reserva": (6, 9, 18, 26, "Ribera del Duero Reserva / Gran Reserva (9-26 yrs)"),
    "priorat_classic": (5, 8, 18, 25, "Priorat DOCa (8-25 yrs)"),

    # GERMANY / AUSTRIA (RIESLING)
    "riesling_auslese_sweet": (8, 12, 28, 45, "Riesling Auslese / Beerenauslese (12-45 yrs)"),
    "riesling_spatlese": (5, 8, 20, 30, "Riesling Spätlese (8-30 yrs)"),
    "riesling_kabinett": (3, 5, 12, 20, "Riesling Kabinett (5-20 yrs)"),
    "riesling_trocken_gg": (4, 7, 15, 22, "Grosses Gewächs / Dry Riesling (7-22 yrs)"),

    # AUSTRALIA & NEW ZEALAND
    "australian_icon_shiraz": (8, 12, 25, 35, "Barossa / Grange Icon Shiraz (12-35 yrs)"),
    "australian_shiraz_standard": (4, 6, 12, 18, "Australian Shiraz (6-18 yrs)"),
    "nz_central_otago_pinot": (3, 5, 10, 14, "Central Otago Pinot Noir (5-14 yrs)"),
    "nz_sauvignon_blanc": (1, 1, 3, 5, "Marlborough Sauvignon Blanc (1-4 yrs)"),

    # CHAMPAGNE & SPARKLING
    "champagne_prestige_cuvee": (8, 12, 25, 35, "Prestige Cuvée Champagne (12-35 yrs)"),
    "champagne_vintage": (6, 8, 16, 22, "Vintage Champagne (8-22 yrs)"),
    "champagne_non_vintage": (1, 2, 4, 6, "Non-Vintage Champagne (2-5 yrs post-release)"),
    "prosecco_cava": (1, 1, 2, 4, "Everyday Sparkling (Drink Fresh 1-3 yrs)"),

    # DESSERT & FORTIFIED
    "vintage_port": (15, 22, 45, 65, "Vintage Port (22-65 yrs)"),
    "sauternes_premier_cru": (10, 15, 35, 55, "Sauternes / Barsac 1er Cru (15-55 yrs)"),
    "tawny_port_colheita": (1, 2, 6, 10, "Colheita / Aged Tawny (Drink within 5-10 yrs)"),
    "sweet_tokaji": (8, 12, 30, 45, "Tokaji Aszú 5-6 Puttonyos (12-45 yrs)"),

    # EVERYDAY REDS & WHITES
    "everyday_red": (1, 2, 5, 8, "Approachable Red (2-6 yrs)"),
    "everyday_aromatic_white": (1, 1, 3, 5, "Fresh Aromatic White (1-3 yrs)"),
    "provence_rose": (1, 1, 2, 3, "Provence Rosé (Drink Young 1-2 yrs)"),
    "bandol_rose": (2, 3, 6, 9, "Bandol Mourvèdre Rosé (3-8 yrs)"),
}


# Regional vintage adjustments: bonus or deduction in aging potential (years added to peak)
VINTAGE_ADJUSTMENTS = {
    # Bordeaux
    ("bordeaux", 2005): +3, ("bordeaux", 2009): +3, ("bordeaux", 2010): +5,
    ("bordeaux", 2015): +3, ("bordeaux", 2016): +4, ("bordeaux", 2018): +2,
    ("bordeaux", 2019): +3, ("bordeaux", 2020): +3, ("bordeaux", 2013): -3,
    ("bordeaux", 2017): -1,

    # Burgundy
    ("burgundy", 2005): +4, ("burgundy", 2010): +3, ("burgundy", 2015): +3,
    ("burgundy", 2016): +2, ("burgundy", 2019): +3, ("burgundy", 2020): +3,
    ("burgundy", 2011): -2, ("burgundy", 2013): -2,

    # Piedmont (Barolo / Barbaresco)
    ("piedmont", 2004): +3, ("piedmont", 2006): +3, ("piedmont", 2010): +5,
    ("piedmont", 2013): +4, ("piedmont", 2016): +5, ("piedmont", 2019): +3,
    ("piedmont", 2014): -2,

    # Tuscany (Brunello / Bolgheri / Chianti)
    ("tuscany", 2010): +4, ("tuscany", 2015): +3, ("tuscany", 2016): +4,
    ("tuscany", 2019): +3, ("tuscany", 2014): -2,

    # Napa Valley
    ("napa", 2012): +2, ("napa", 2013): +4, ("napa", 2016): +3,
    ("napa", 2018): +3, ("napa", 2019): +3, ("napa", 2011): -2,
    ("napa", 2020): -2,  # Smoke taint impacted some producers

    # Champagne
    ("champagne", 2008): +5, ("champagne", 2012): +3, ("champagne", 2013): +2,
    ("champagne", 2015): +2, ("champagne", 2011): -2,

    # Rioja
    ("rioja", 2004): +4, ("rioja", 2005): +3, ("rioja", 2010): +4,
    ("rioja", 2011): +2, ("rioja", 2015): +2, ("rioja", 2013): -2,
}


def _match_profile_key(bottle: WineBottle) -> str:
    """Matches a wine bottle to the most specific enological aging profile."""
    name_str = f"{bottle.producer} {bottle.wine_name} {bottle.sub_region} {bottle.region} {bottle.varietal}".lower()

    # Check for fortified & sweet
    if "vintage port" in name_str or (bottle.wine_type == WineType.FORTIFIED and "vintage" in name_str):
        return "vintage_port"
    if bottle.wine_type == WineType.FORTIFIED and "tawny" in name_str:
        return "tawny_port_colheita"
    if "sauternes" in name_str or "barsac" in name_str or "d'yquem" in name_str or "climens" in name_str:
        return "sauternes_premier_cru"
    if "tokaji" in name_str or "aszú" in name_str:
        return "sweet_tokaji"

    # Sparkling
    if bottle.wine_type == WineType.SPARKLING or "champagne" in name_str:
        if any(icon in name_str for icon in ["dom perignon", "dom pérignon", "cristal", "krug", "comtes de champagne", "belle epoque", "salon", "sir winston churchill"]):
            return "champagne_prestige_cuvee"
        if bottle.vintage is not None:
            return "champagne_vintage"
        if any(p in name_str for p in ["prosecco", "cava"]):
            return "prosecco_cava"
        return "champagne_non_vintage"

    # Rosé
    if bottle.wine_type == WineType.ROSE or "rosé" in name_str or "rose" in name_str:
        if "bandol" in name_str or "tempier" in name_str:
            return "bandol_rose"
        return "provence_rose"

    # Piedmont (Nebbiolo)
    if "barolo" in name_str:
        if any(cru in name_str for cru in ["monfortino", "francia", "cannubi", "brunate", "rocche", "falletto", "riserva", "vigna"]):
            return "barolo_riserva_cru"
        return "barolo_standard"
    if "barbaresco" in name_str:
        return "barbaresco"
    if "nebbiolo" in name_str:
        return "nebbiolo_langhe"
    if "barbera" in name_str:
        return "barbera_d_asti"

    # Tuscany (Sangiovese / Super Tuscan)
    if "brunello" in name_str:
        if "riserva" in name_str or "biondi-santi" in name_str or "soldera" in name_str:
            return "brunello_riserva"
        return "brunello_annata"
    if any(st in name_str for st in ["guidalberto", "le serre nuove", "il bruciato"]):
        return "bolgheri_rosso_second"
    if any(st in name_str for st in ["sassicaia", "ornellaia", "masseto", "tignanello", "solaia", "flaccianello", "redigaffi", "aprile", "super tuscan", "bolgheri"]):
        return "super_tuscan_premium"
    if "primorosso" in name_str or "primo rosso" in name_str:
        return "everyday_red"
    if "chianti" in name_str:
        if "gran selezione" in name_str:
            return "chianti_gran_selezione"
        if "riserva" in name_str:
            return "chianti_riserva"
        return "chianti_annata"

    # Bordeaux
    if "bordeaux" in name_str or any(app in name_str for app in ["pauillac", "margaux", "saint-julien", "saint-estèphe", "pessac-léognan", "graves", "saint-émilion", "pomerol", "médoc"]):
        if any(fg in name_str for fg in ["lafite", "latour", "margaux", "haut-brion", "mouton", "petrus", "le pin", "cheval blanc", "ausone"]):
            return "bordeaux_first_growth"
        if any(app in name_str for app in ["pomerol", "saint-émilion", "st-emilion", "angelus", "pavie", "fleur", "conseillante"]):
            return "bordeaux_right_bank_premier"
        if any(gcc in name_str for gcc in ["grand cru classé", "pontet-canet", "pichon", "montrose", "cos d'estournel", "lynch-bages", "léoville", "leoville", "ducru"]):
            return "bordeaux_left_bank_classified"
        if "cru bourgeois" in name_str or "haut-médoc" in name_str:
            return "bordeaux_cru_bourgeois"
        return "bordeaux_generic"

    # Burgundy (Pinot Noir & Chardonnay)
    if "burgundy" in name_str or "bourgogne" in name_str or any(bg in name_str for bg in ["vosne", "chambolle", "gevrey", "volnay", "pommard", "meursault", "puligny", "chassagne", "chablis", "corton", "romanee", "romanée", "musigny", "chambertin"]):
        is_white = bottle.wine_type == WineType.WHITE or "chardonnay" in name_str or any(w in name_str for w in ["meursault", "puligny", "chassagne", "chablis", "montrachet"])
        if "chablis" in name_str:
            if "grand cru" in name_str or any(gc in name_str for gc in ["les clos", "preuses", "valmur"]):
                return "chablis_grand_cru"
            return "chablis_premier_cru"

        if is_white:
            if "grand cru" in name_str or "montrachet" in name_str or "corton-charlemagne" in name_str:
                return "burgundy_grand_cru_white"
            if "premier cru" in name_str or "1er cru" in name_str:
                return "burgundy_premier_cru_white"
            return "burgundy_village_white"
        else:
            if "grand cru" in name_str or any(gc in name_str for gc in ["chambertin", "musigny", "romanée", "romanee", "clos de vougeot", "richebourg", "la tâche", "tache"]):
                return "burgundy_grand_cru_red"
            if "premier cru" in name_str or "1er cru" in name_str:
                return "burgundy_premier_cru_red"
            if any(vill in name_str for vill in ["gevrey", "vosne", "chambolle", "morey", "nuits", "volnay", "pommard"]):
                return "burgundy_village_red"
            return "burgundy_regional_red"

    # Rhône Valley
    if any(rh in name_str for rh in ["hermitage", "côte-rôtie", "cote-rotie", "guigal", "chave", "chapoutier"]):
        return "rhone_hermitage_cote_rotie"
    if any(rh in name_str for rh in ["cornas", "saint-joseph", "crozes-hermitage"]):
        return "rhone_cornas_st_joseph"
    if "châteauneuf" in name_str or "chateauneuf" in name_str or "rayas" in name_str or "beaucastel" in name_str:
        if any(pc in name_str for pc in ["beaucastel", "rayas", "clos des papes", "hommage", "vieilles vignes"]):
            return "chateauneuf_du_pape_prestige"
        return "chateauneuf_du_pape_standard"
    if "rhône" in name_str or "rhone" in name_str or "gigondas" in name_str:
        return "cotes_du_rhone"

    # Specific California Varietals
    if "zinfandel" in name_str:
        return "california_zinfandel"

    if "pinot noir" in name_str and any(ca in name_str for ca in ["california", "sonoma", "russian river", "santa barbara", "carneros", "napa"]):
        return "california_pinot_noir"

    if "chardonnay" in name_str and any(ca in name_str for ca in ["california", "napa", "sonoma"]):
        return "california_chardonnay_oaked"

    # California & Domestic Rhône Varieties (Syrah, Mourvèdre, Grenache, Petite Sirah)
    if any(rh in name_str for rh in ["mourvèdre", "mourvedre", "syrah", "shiraz", "petite sirah", "grenache"]):
        if any(cult in name_str for cult in ["andremily", "saxum", "sine qua non", "alban"]):
            return "chateauneuf_du_pape_prestige"
        return "rhone_cornas_st_joseph"

    # Napa Valley & California Cabernet / Bordeaux Blends
    if "cabernet" in name_str or "merlot" in name_str or any(ca in name_str for ca in ["napa", "oakville", "rutherford", "howell mountain", "stags leap", "monte bello", "alexander valley", "sonoma", "paso robles", "spring mountain", "columbia valley", "coombsville", "stonestreet", "newton", "arkenstone", "faust"]):
        if any(cult in name_str for cult in ["screaming eagle", "harlan", "colgin", "opus one", "dominus", "monte bello", "dalla valle", "bryant", "promontory", "shafer hillside", "abreu", "9-3-5", "the puzzle", "puzzle", "stonestreet", "g major 7", "g major", "arkenstone", "brinkman block", "brinkman"]):
            return "napa_cult_cabernet"
        return "napa_valley_cabernet"

    # Rioja & Ribera
    if "rioja" in name_str:
        if "gran reserva" in name_str or "viña tondonia" in name_str or "murrieta ygay" in name_str or "la rioja alta" in name_str:
            return "rioja_gran_reserva"
        if "reserva" in name_str:
            return "rioja_reserva"
        return "rioja_crianza"
    if "ribera del duero" in name_str or "vega sicilia" in name_str or "pingus" in name_str:
        return "ribera_del_duero_reserva"
    if "priorat" in name_str:
        return "priorat_classic"

    # Riesling
    if "riesling" in name_str:
        if any(sw in name_str for sw in ["auslese", "beerenauslese", "trockenbeerenauslese", "eiswein"]):
            return "riesling_auslese_sweet"
        if "spätlese" in name_str or "spatlese" in name_str:
            return "riesling_spatlese"
        if "kabinett" in name_str:
            return "riesling_kabinett"
        return "riesling_trocken_gg"

    # Australia / New Zealand
    if "shiraz" in name_str or "syrah" in name_str:
        if any(au in name_str for au in ["grange", "hill of grace", "astralis", "runrig", "torbreck"]):
            return "australian_icon_shiraz"
        return "australian_shiraz_standard"
    if "pinot noir" in name_str and ("central otago" in name_str or "new zealand" in name_str or "oregon" in name_str or "willamette" in name_str):
        return "nz_central_otago_pinot"
    if "sauvignon blanc" in name_str and ("marlborough" in name_str or "new zealand" in name_str):
        return "nz_sauvignon_blanc"

    # General Fallbacks
    if bottle.wine_type == WineType.WHITE:
        return "everyday_aromatic_white"
    return "everyday_red"


def _format_scaling_factor(fmt: BottleFormat) -> float:
    """Larger formats age slower due to smaller ullage ratio; halves age faster."""
    if fmt == BottleFormat.HALF:
        return 0.75  # 25% faster maturation
    elif fmt == BottleFormat.MAGNUM:
        return 1.30  # 30% longer aging
    elif fmt == BottleFormat.DOUBLE_MAGNUM:
        return 1.45
    elif fmt == BottleFormat.IMPERIAL:
        return 1.60
    return 1.00


def calculate_drinking_window(bottle: WineBottle, current_year: int = CURRENT_YEAR) -> DrinkingWindow:
    """Calculates prime drinking window, serving temp, and decanting guidance."""
    vintage = bottle.vintage if bottle.vintage else (current_year - 2)
    profile_key = _match_profile_key(bottle)
    start_offset, peak_start_offset, peak_end_offset, end_offset, tier_name = AGING_PROFILES[profile_key]

    # Format adjustment
    scale = _format_scaling_factor(bottle.format)
    start_offset = int(round(start_offset * scale))
    peak_start_offset = int(round(peak_start_offset * scale))
    peak_end_offset = int(round(peak_end_offset * scale))
    end_offset = int(round(end_offset * scale))

    # Vintage bonus / penalty
    reg_key = "generic"
    for r in ["bordeaux", "burgundy", "piedmont", "tuscany", "napa", "champagne", "rioja"]:
        if r in bottle.region.lower() or r in bottle.sub_region.lower() or r in bottle.wine_name.lower() or r in bottle.producer.lower():
            reg_key = r
            break

    vintage_adj = VINTAGE_ADJUSTMENTS.get((reg_key, vintage), 0)
    peak_end_offset += vintage_adj
    end_offset += max(0, vintage_adj)

    window_start = vintage + start_offset
    peak_start = vintage + peak_start_offset
    peak_end = vintage + peak_end_offset
    window_end = vintage + end_offset

    # Ensure logical monotonicity
    if peak_start < window_start:
        peak_start = window_start
    if peak_end < peak_start:
        peak_end = peak_start + 2
    if window_end < peak_end:
        window_end = peak_end + 3

    # Calculate current status
    if current_year < window_start:
        status = DrinkingStatus.TOO_YOUNG
        progress = max(0.0, (current_year - vintage) / max(1, (window_start - vintage)) * 25.0)
    elif current_year < peak_start:
        status = DrinkingStatus.EARLY_WINDOW
        progress = 25.0 + ((current_year - window_start) / max(1, (peak_start - window_start))) * 25.0
    elif current_year <= peak_end:
        status = DrinkingStatus.PEAK
        progress = 50.0 + ((current_year - peak_start) / max(1, (peak_end - peak_start))) * 35.0
    elif current_year <= window_end:
        status = DrinkingStatus.LATE_PEAK
        progress = 85.0 + ((current_year - peak_end) / max(1, (window_end - peak_end))) * 15.0
    else:
        status = DrinkingStatus.PAST_PEAK
        over = current_year - window_end
        progress = min(150.0, 100.0 + over * 5.0)

    # Decanting and serving temperatures
    decant_hours, temp_c, temp_f, rationale_text = _compute_sommelier_service_notes(
        bottle, vintage, status, current_year, tier_name, vintage_adj
    )

    return DrinkingWindow(
        window_start=window_start,
        peak_start=peak_start,
        peak_end=peak_end,
        window_end=window_end,
        status=status,
        progress_pct=round(progress, 1),
        rationale=rationale_text,
        decant_hours=decant_hours,
        serving_temp_c=temp_c,
        serving_temp_f=temp_f,
        aging_tier=tier_name,
    )


def _compute_sommelier_service_notes(
    bottle: WineBottle, vintage: int, status: DrinkingStatus, current_year: int, tier_name: str, vintage_adj: int
) -> Tuple[float, int, int, str]:
    """Generates precise sommelier decanting times, serving temps, and analytical rationale."""
    age = current_year - vintage

    # Temperature defaults by wine style
    if bottle.wine_type == WineType.SPARKLING:
        temp_c, temp_f = 9, 48
    elif bottle.wine_type == WineType.WHITE:
        if "oaked" in tier_name.lower() or "burgundy" in tier_name.lower() or "grand cru" in tier_name.lower():
            temp_c, temp_f = 12, 54
        else:
            temp_c, temp_f = 8, 46
    elif bottle.wine_type == WineType.ROSE:
        temp_c, temp_f = 10, 50
    elif bottle.wine_type == WineType.DESSERT:
        temp_c, temp_f = 11, 52
    elif bottle.wine_type == WineType.FORTIFIED:
        temp_c, temp_f = 16, 61
    else:
        # Reds
        if "pinot" in tier_name.lower() or "gamay" in tier_name.lower():
            temp_c, temp_f = 15, 59
        else:
            temp_c, temp_f = 17, 63

    # Decanting time
    decant_hours = 0.0
    if bottle.wine_type == WineType.RED:
        if status == DrinkingStatus.TOO_YOUNG or status == DrinkingStatus.EARLY_WINDOW:
            if any(k in tier_name.lower() for k in ["barolo", "bordeaux", "napa", "syrah", "hermitage"]):
                decant_hours = 2.5
            else:
                decant_hours = 1.5
        elif status == DrinkingStatus.PEAK:
            if age > 15:
                decant_hours = 0.75  # Gentle decant for sediment
            else:
                decant_hours = 1.0
        elif status == DrinkingStatus.LATE_PEAK or status == DrinkingStatus.PAST_PEAK:
            decant_hours = 0.25  # Only decant off sediment immediately prior to pouring to preserve fleeting tertiary aromas
    elif bottle.wine_type == WineType.WHITE:
        if "grand cru" in tier_name.lower() and (status == DrinkingStatus.TOO_YOUNG or status == DrinkingStatus.EARLY_WINDOW):
            decant_hours = 1.0
        else:
            decant_hours = 0.0
    elif bottle.wine_type == WineType.FORTIFIED and "vintage port" in tier_name.lower():
        decant_hours = 2.0

    # Analytical explanation
    status_desc = {
        DrinkingStatus.TOO_YOUNG: f"Currently {age} years old. Primary tannins and brisk acidity dominate; hold to allow tertiary complexities (leather, forest floor, dried fruit) to integrate.",
        DrinkingStatus.EARLY_WINDOW: f"Entering drinkability at {age} years old. Tannins are softening but structured. Decanting {decant_hours}h recommended if opened now.",
        DrinkingStatus.PEAK: f"In prime maturity sweet spot at {age} years old. Perfect equilibrium between youthful fruit expression and secondary savory nuances.",
        DrinkingStatus.LATE_PEAK: f"At late stage of maturity ({age} years old). Fruit intensity is gently yielding to tertiary cedar, tobacco, and earth. Best enjoyed over the next 1-2 years.",
        DrinkingStatus.PAST_PEAK: f"Beyond primary and secondary window ({age} years old). May show elevated oxidation or faded fruit. Open promptly for an educational mature tasting."
    }[status]

    vintage_note = ""
    if vintage_adj > 0:
        vintage_note = f" The {vintage} vintage was celebrated for structured longevity (+{vintage_adj} yrs added)."
    elif vintage_adj < 0:
        vintage_note = f" The {vintage} vintage favored earlier approachability ({vintage_adj} yrs adjusted)."

    format_note = ""
    if bottle.format == BottleFormat.HALF:
        format_note = " Half-bottle accelerates maturation rate by ~25%."
    elif bottle.format in (BottleFormat.MAGNUM, BottleFormat.DOUBLE_MAGNUM, BottleFormat.IMPERIAL):
        format_note = f" {bottle.format.value} preserves youthful vibrance and extends peak window."

    rationale = f"{tier_name}. {status_desc}{vintage_note}{format_note}"
    return decant_hours, temp_c, temp_f, rationale
