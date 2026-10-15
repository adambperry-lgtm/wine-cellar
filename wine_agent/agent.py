"""Sommelier Wine Cellar Agent.

Combines cellar inventory tracking with master sommelier intelligence, pairing logic,
and drinking window optimization.
"""

from typing import List, Dict, Any, Optional
from wine_agent.models import WineBottle, DrinkingStatus, WineType, ConsumptionRecord
from wine_agent.database import WineDatabase
from wine_agent.natural_language import parse_wine_natural_language
from wine_agent.drinking_window import CURRENT_YEAR


FOOD_PAIRING_MATRIX = {
    "steak": ["Cabernet Sauvignon", "Bordeaux", "Super Tuscan", "Syrah", "Nebbiolo", "Barolo", "Brunello"],
    "beef": ["Cabernet Sauvignon", "Bordeaux", "Super Tuscan", "Syrah", "Ribera del Duero"],
    "ribeye": ["Cabernet Sauvignon", "Napa Valley", "Bordeaux", "Barolo", "Shiraz"],
    "lamb": ["Bordeaux", "Rioja", "Rhône", "Syrah", "Brunello", "Cabernet Sauvignon"],
    "duck": ["Pinot Noir", "Burgundy", "Côte-Rôtie", "Barolo", "Nebbiolo"],
    "pork": ["Pinot Noir", "Rioja", "Riesling", "Chardonnay", "Beaujolais"],
    "chicken": ["Chardonnay", "White Burgundy", "Pinot Noir", "Champagne", "Viognier"],
    "fish": ["White Burgundy", "Chardonnay", "Chablis", "Sauvignon Blanc", "Champagne", "Pinot Noir"],
    "salmon": ["Pinot Noir", "Burgundy", "Chardonnay", "Rosé"],
    "oysters": ["Chablis", "Champagne", "Muscadet", "Sauvignon Blanc"],
    "seafood": ["Chablis", "Riesling", "Champagne", "Sauvignon Blanc", "White Burgundy"],
    "pasta": ["Sangiovese", "Chianti", "Brunello", "Barbera", "Nebbiolo", "Pinot Noir"],
    "truffle": ["Barolo", "Barbaresco", "Burgundy", "Nebbiolo", "Brunello"],
    "cheese": ["Port", "Sauternes", "Bordeaux", "Champagne", "Riesling"],
    "spicy": ["Riesling", "Gewürztraminer", "Off-dry", "Champagne"],
    "dessert": ["Sauternes", "Port", "Tokaji", "Late Harvest"]
}


class SommelierAgent:
    def __init__(self, db: Optional[WineDatabase] = None):
        self.db = db or WineDatabase()

    def audit_cellar(self, user_id: Optional[int] = 1) -> Dict[str, Any]:
        """Performs a comprehensive cellar audit analyzing maturity, risks, and organization."""
        stats = self.db.get_cellar_stats(user_id=user_id)
        all_bottles = self.db.list_bottles(only_in_stock=True, user_id=user_id)

        urgent_bottles = [
            b for b in all_bottles
            if b.drinking_window and b.drinking_window.status in (DrinkingStatus.LATE_PEAK, DrinkingStatus.PAST_PEAK)
        ]
        urgent_bottles.sort(key=lambda b: (b.drinking_window.window_end if b.drinking_window else 9999))

        peak_bottles = [
            b for b in all_bottles
            if b.drinking_window and b.drinking_window.status == DrinkingStatus.PEAK
        ]

        hold_bottles = [
            b for b in all_bottles
            if b.drinking_window and b.drinking_window.status == DrinkingStatus.TOO_YOUNG
        ]

        # Calculate cellar readiness index (percentage of cellar currently in or approaching prime drinking window)
        total_q = stats["total_bottles"] or 1
        ready_q = stats["ready_to_drink_now"] + stats["status_distribution"].get(DrinkingStatus.EARLY_WINDOW.value, 0)
        readiness_pct = round((ready_q / total_q) * 100, 1)

        recommendations = []
        if urgent_bottles:
            recommendations.append(
                f"🚨 **Drink Soon Alert**: You have {len(urgent_bottles)} bottle(s) in late maturity or past peak. "
                f"Plan to open `{urgent_bottles[0].display_name}` ({urgent_bottles[0].location_rack} / {urgent_bottles[0].location_bin}) within the next 3-6 months before fruit fades."
            )
        if stats["hold_for_future"] > 0:
            recommendations.append(
                f"📦 **Long-Term Storage**: {stats['hold_for_future']} bottle(s) are strictly in aging phase. "
                "Keep them stored at stable 53-57°F (12-14°C) with 65-75% humidity in low-vibration racks."
            )
        if stats["ready_to_drink_now"] > 0:
            recommendations.append(
                f"🍷 **In Prime Window**: {stats['ready_to_drink_now']} bottle(s) are at their absolute peak in {CURRENT_YEAR}. "
                "These are primed for dinner parties and special occasions."
            )

        return {
            "stats": stats,
            "readiness_index_pct": readiness_pct,
            "urgent_bottles": urgent_bottles,
            "peak_bottles": peak_bottles,
            "hold_bottles": hold_bottles,
            "sommelier_recommendations": recommendations,
        }

    def recommend_bottle(
        self,
        food: Optional[str] = None,
        style: Optional[str] = None,
        celebratory: bool = False,
        must_be_peak: bool = True,
        user_id: Optional[int] = 1
    ) -> List[Dict[str, Any]]:
        """Finds the best bottle(s) in the cellar matching dining occasion or mood."""
        bottles = self.db.list_bottles(only_in_stock=True, user_id=user_id)
        scored_candidates = []

        food_targets = []
        if food:
            f_lower = food.lower()
            for key, targets in FOOD_PAIRING_MATRIX.items():
                if key in f_lower:
                    food_targets.extend(targets)

        for b in bottles:
            score = 0
            dw = b.drinking_window
            if not dw:
                continue

            # Status weighting: Highest score for PEAK
            if dw.status == DrinkingStatus.PEAK:
                score += 50
            elif dw.status == DrinkingStatus.EARLY_WINDOW:
                score += 35
            elif dw.status == DrinkingStatus.LATE_PEAK:
                # Urgent to drink, so prioritize if looking for bottles to open
                score += 45
            elif dw.status == DrinkingStatus.PAST_PEAK:
                score += 20
            elif dw.status == DrinkingStatus.TOO_YOUNG:
                if must_be_peak:
                    continue
                score -= 40

            # Food pairing match
            combined_desc = f"{b.producer} {b.wine_name} {b.varietal} {b.region} {b.sub_region}".lower()
            if food_targets:
                matched_target = any(t.lower() in combined_desc for t in food_targets)
                if matched_target:
                    score += 60
                # Also check custom food pairings recorded on bottle
                if any(any(f_kw in p.lower() for f_kw in food.lower().split()) for p in b.food_pairings):
                    score += 70

            # Style match
            if style:
                s_lower = style.lower()
                if s_lower in b.wine_type.value.lower() or s_lower in combined_desc:
                    score += 40

            # Celebratory match (prestige score / value)
            if celebratory:
                if b.critic_score and b.critic_score >= 95:
                    score += 40
                if b.purchase_price and b.purchase_price >= 150:
                    score += 30

            scored_candidates.append((score, b))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        results = []
        for s, b in scored_candidates[:5]:
            results.append({
                "match_score": s,
                "bottle": b,
                "drinking_status": b.drinking_window.status.value if b.drinking_window else "Unknown",
                "decant_advice": f"Decant {b.drinking_window.decant_hours}h" if b.drinking_window and b.drinking_window.decant_hours > 0 else "Pop and pour",
                "serving_temp": f"{b.drinking_window.serving_temp_f}°F ({b.drinking_window.serving_temp_c}°C)" if b.drinking_window else "60°F",
                "rationale": b.drinking_window.rationale if b.drinking_window else ""
            })

        return results

    def recommend_purchases(self, query: str = "") -> Dict[str, Any]:
        """Provides expert cellar acquisition advice to complement the collection and fill dining needs."""
        q_lower = query.lower()

        catalog = [
            {
                "wine_name": "Gran Reserva 904",
                "producer": "La Rioja Alta",
                "vintage_sweet_spot": "2015 or 2016",
                "region": "Rioja, Spain",
                "varietal": "Tempranillo / Graciano",
                "est_price": 85.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 45m",
                "serving_temp": "63°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Wine.com)",
                "match_keywords": ["steak", "ribeye", "beef", "meat", "spanish", "ready", "now", "peak", "mature", "bistecca"],
                "rationale": "Aged 10+ years before release. Silky, resolved tannins, leather, and cedar that melt through ribeye fat without tannins clashing.",
                "cellar_complement": "Complements your young Napa Cabernets by giving you immediate mature complexity without sacrificing bottles that need 5+ more years."
            },
            {
                "wine_name": "Château Léoville Barton (or Pontet-Canet)",
                "producer": "Château Léoville Barton",
                "vintage_sweet_spot": "2014, 2015, or 2016",
                "region": "Saint-Julien / Pauillac, Bordeaux",
                "varietal": "Cabernet Sauvignon Blend",
                "est_price": 135.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 1.5h",
                "serving_temp": "64°F (18°C)",
                "nj_availability": "Available in NJ & ships to NJ (Total Wine NJ, Gary's Wine, Wine.com)",
                "match_keywords": ["steak", "ribeye", "beef", "bordeaux", "cabernet", "ready", "now", "french", "left bank", "collectible"],
                "rationale": "Classic Left Bank gravel structure with graphite, cassis, and savory tobacco. Built for prime beef cuts.",
                "cellar_complement": "Adds Old World classicism and benchmark tertiary Pauillac/Saint-Julien notes to balance California fruit forwardness."
            },
            {
                "wine_name": "Barbaresco Riserva",
                "producer": "Produttori del Barbaresco",
                "vintage_sweet_spot": "2016, 2017, or 2019",
                "region": "Piedmont, Italy",
                "varietal": "Nebbiolo",
                "est_price": 75.0,
                "drinking_status": "Approaching Peak / Peak",
                "decant_advice": "Decant 2h",
                "serving_temp": "63°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Saratoga Wine)",
                "match_keywords": ["steak", "ribeye", "beef", "truffle", "italian", "nebbiolo", "barolo", "barbaresco", "pasta", "risotto"],
                "rationale": "High natural acidity and chalky Nebbiolo tannins slice through heavy ribeye marbling with rose petal and tar aromatics.",
                "cellar_complement": "Supplies noble Italian structure to expand your Italian selection beyond Super Tuscans."
            },
            {
                "wine_name": "Brunello di Montalcino Montosoli",
                "producer": "Altesino",
                "vintage_sweet_spot": "2016 or 2017",
                "region": "Tuscany, Italy",
                "varietal": "Sangiovese Grosso",
                "est_price": 115.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 1.5h",
                "serving_temp": "64°F (18°C)",
                "nj_availability": "Available in NJ & ships to NJ (Total Wine NJ, Gary's Wine, Wine.com)",
                "match_keywords": ["steak", "bistecca", "beef", "italian", "brunello", "tuscany", "pasta", "truffle"],
                "rationale": "Montosoli single-cru elegance. Crushed sour cherry, dried herbs, and noble acidity tailor-made for Bistecca alla Fiorentina.",
                "cellar_complement": "Deepens your Italian cellar depth alongside your Argiano and Casanova di Neri holdings."
            },
            {
                "wine_name": "Lytton Springs (or Geyserville)",
                "producer": "Ridge Vineyards",
                "vintage_sweet_spot": "2019, 2020, or 2021",
                "region": "Dry Creek Valley, California",
                "varietal": "Zinfandel / Petite Sirah Blend",
                "est_price": 52.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 1h",
                "serving_temp": "62°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Ridge DTC to NJ)",
                "match_keywords": ["steak", "ribeye", "bbq", "beef", "daily", "american", "zinfandel", "value", "now", "burger"],
                "rationale": "Deep bramble fruit, black peppercorn, and muscular Petite Sirah backbone. Irresistible with charred ribeye crust.",
                "cellar_complement": "Acts as an accessible cellar-defender bottle that delivers serious pedigree at an everyday price point."
            },
            {
                "wine_name": "Châteauneuf-du-Pape 'Télégramme'",
                "producer": "Domaine du Vieux Télégraphe",
                "vintage_sweet_spot": "2019 or 2020",
                "region": "Southern Rhône, France",
                "varietal": "Grenache / Syrah / Mourvèdre",
                "est_price": 65.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 1h",
                "serving_temp": "62°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Wine.com)",
                "match_keywords": ["lamb", "roast", "beef", "rhone", "grenache", "steak", "duck", "spicy"],
                "rationale": "Pebble-warmed garrigue, ripe dark cherries, and lavender spice that harmonizes beautifully with braised meats and rosemary lamb.",
                "cellar_complement": "Introduces Southern Rhône warmth and fleshy texture to your red cellar roster."
            },
            {
                "wine_name": "Dundee Hills Pinot Noir",
                "producer": "Domaine Drouhin Oregon",
                "vintage_sweet_spot": "2021 or 2022",
                "region": "Willamette Valley, Oregon",
                "varietal": "Pinot Noir",
                "est_price": 48.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Aeration 30m",
                "serving_temp": "58°F (14°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Total Wine NJ)",
                "match_keywords": ["duck", "salmon", "pork", "mushroom", "roast", "pinot", "oregon", "light"],
                "rationale": "French soul, Oregon soil. Bright cranberries, violet, and forest floor that balance duck breast and roasted game.",
                "cellar_complement": "Adds an approachable, peak-ready New World Pinot Noir ready to enjoy without aging delay."
            },
            {
                "wine_name": "Viña Tondonia Reserva",
                "producer": "R. López de Heredia",
                "vintage_sweet_spot": "2011 or 2012",
                "region": "Rioja Alta, Spain",
                "varietal": "Tempranillo / Garnacha",
                "est_price": 62.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 30m",
                "serving_temp": "62°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Saratoga Wine, Wine.com)",
                "match_keywords": ["lamb", "duck", "spanish", "rioja", "mature", "ready", "now", "cheese", "roast"],
                "rationale": "Legendary traditional winemaking with decades of barrel/bottle rest. Dried orange peel, savory umami, and delicate red fruits.",
                "cellar_complement": "Brings unmatched historic European maturity at an extraordinary price tier."
            },
            {
                "wine_name": "Chablis Premier Cru 'Fourchaume'",
                "producer": "Domaine William Fèvre (or Louis Jadot)",
                "vintage_sweet_spot": "2020 or 2022",
                "region": "Chablis, Burgundy",
                "varietal": "Chardonnay",
                "est_price": 60.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Pop and pour",
                "serving_temp": "50°F (10°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Total Wine NJ)",
                "match_keywords": ["fish", "seafood", "oyster", "white", "crisp", "chicken", "summer", "salmon", "raw bar"],
                "rationale": "Kimmeridgian limestone minerality, oyster-shell salinity, and vibrant citrus acidity for seafood and raw bars.",
                "cellar_complement": "Fills a major white wine gap in the cellar, providing premier gastronomic versatility."
            },
            {
                "wine_name": "Riesling Réserve",
                "producer": "Trimbach (or Domaine Weinbach)",
                "vintage_sweet_spot": "2020 or 2021",
                "region": "Alsace, France",
                "varietal": "Riesling",
                "est_price": 36.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Pop and pour",
                "serving_temp": "48°F (9°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Total Wine NJ)",
                "match_keywords": ["fish", "seafood", "pork", "spicy", "asian", "white", "crisp", "thai"],
                "rationale": "Bone-dry, laser-focused lime zest, and stony mineral tension that cuts through pork chops and spiced dishes.",
                "cellar_complement": "Provides high-acid, food-friendly aromatic white power for complex culinary pairings."
            },
            {
                "wine_name": "Santorini Assyrtiko",
                "producer": "Domaine Sigalas (or Argyros)",
                "vintage_sweet_spot": "2022 or 2023",
                "region": "Santorini, Greece",
                "varietal": "Assyrtiko",
                "est_price": 45.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Pop and pour",
                "serving_temp": "50°F (10°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Saratoga Wine, Wine.com)",
                "match_keywords": ["seafood", "fish", "oysters", "grilled", "white", "summer", "mediterranean"],
                "rationale": "Volcanic ash soils produce bracing acidity and saline minerality that complements grilled octopus, branzino, and fresh shellfish.",
                "cellar_complement": "Diversifies cellar whites with one of the wine world's most singular, thrilling indigenous varietals."
            },
            {
                "wine_name": "Brut Réserve Champagne",
                "producer": "Billecart-Salmon (or Charles Heidsieck)",
                "vintage_sweet_spot": "NV (Base 2018/2019)",
                "region": "Champagne, France",
                "varietal": "Pinot Noir / Chardonnay / Meunier",
                "est_price": 68.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Serve chilled",
                "serving_temp": "46°F (8°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Total Wine NJ)",
                "match_keywords": ["celebrat", "sparkling", "champagne", "prestige", "party", "oyster", "appetizer", "toast"],
                "rationale": "Brioche, fine pinpoint bead, and pristine chalky lift. Pairs universally from aperitifs to fried poultry.",
                "cellar_complement": "Ensures you always have world-class celebratory bubbly on hand without having to rush to the store."
            },
            {
                "wine_name": "Collection 244 (or 245) Brut Champagne",
                "producer": "Louis Roederer",
                "vintage_sweet_spot": "NV (Multi-Vintage)",
                "region": "Champagne, France",
                "varietal": "Chardonnay / Pinot Noir",
                "est_price": 75.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Serve chilled",
                "serving_temp": "46°F (8°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Total Wine NJ)",
                "match_keywords": ["celebrat", "sparkling", "champagne", "prestige", "party", "oyster", "toast", "luxury"],
                "rationale": "Perpetual reserve richness with toasted almond, yellow peach, and energetic citrus cut.",
                "cellar_complement": "Supplies house-style luxury sparkling wine with high critic pedigree (94+ pts)."
            },
            {
                "wine_name": "Gigondas",
                "producer": "E. Guigal (or Domaine du Cayron)",
                "vintage_sweet_spot": "2019 or 2020",
                "region": "Southern Rhône, France",
                "varietal": "Grenache / Syrah",
                "est_price": 42.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 45m",
                "serving_temp": "62°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Total Wine NJ)",
                "match_keywords": ["daily", "value", "steak", "bbq", "beef", "burger", "pork", "rhone"],
                "rationale": "Crushed wild blackberries, garrigue herbs, and rustic grip. Exceptional value cellar defender.",
                "cellar_complement": "Shields your top-tier Napa bottles on casual weeknights while providing real Old World pedigree."
            },
            {
                "wine_name": "Malbec 'Paraje Altamira'",
                "producer": "Catena Zapata",
                "vintage_sweet_spot": "2020 or 2021",
                "region": "Uco Valley, Mendoza, Argentina",
                "varietal": "Malbec",
                "est_price": 38.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Decant 45m",
                "serving_temp": "62°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Wine.com)",
                "match_keywords": ["steak", "ribeye", "beef", "bbq", "daily", "value", "meat", "argentina"],
                "rationale": "High-altitude limestone elevation gives floral violets and fresh acidity that cuts right through rich marbled beef.",
                "cellar_complement": "A crowd-pleasing, robust steakhouse wine under $40 for casual grilling."
            },
            {
                "wine_name": "Chianti Classico",
                "producer": "Fèlsina Berardenga (or Castello di Volpaia)",
                "vintage_sweet_spot": "2020 or 2021",
                "region": "Chianti Classico, Tuscany, Italy",
                "varietal": "Sangiovese",
                "est_price": 28.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Aeration 20m",
                "serving_temp": "61°F (16°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Total Wine NJ, Wine.com)",
                "match_keywords": ["pizza", "pasta", "night", "weeknight", "italian", "tomato", "bolognese", "sangiovese", "chianti", "value", "ready", "now"],
                "rationale": "Bright sour cherry, violet, and savory herbs with lively acidity that matches tomato sauce bite-for-bite. The definitive red-sauce wine.",
                "cellar_complement": "A weeknight Italian staple that protects your Brunello and Super Tuscan holdings for special occasions."
            },
            {
                "wine_name": "Barbera d'Alba",
                "producer": "G.D. Vajra (or Vietti 'Tre Vigne')",
                "vintage_sweet_spot": "2021 or 2022",
                "region": "Piedmont, Italy",
                "varietal": "Barbera",
                "est_price": 26.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Pop and pour",
                "serving_temp": "60°F (16°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Buy-Rite, Wine.com)",
                "match_keywords": ["pizza", "pasta", "night", "weeknight", "italian", "tomato", "sausage", "lasagna", "barbera", "piedmont", "value", "ready", "now"],
                "rationale": "Juicy black cherry and plum with naturally high acidity and soft tannins — loves pepperoni, sausage, and baked lasagna.",
                "cellar_complement": "Adds a fruit-forward, low-tannin Piedmont red that drinks perfectly young, unlike Nebbiolo."
            },
            {
                "wine_name": "Etna Rosso",
                "producer": "Tenuta delle Terre Nere (or Benanti)",
                "vintage_sweet_spot": "2021 or 2022",
                "region": "Mount Etna, Sicily, Italy",
                "varietal": "Nerello Mascalese",
                "est_price": 30.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Aeration 15m",
                "serving_temp": "59°F (15°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Wine.com)",
                "match_keywords": ["pizza", "pasta", "night", "weeknight", "italian", "margherita", "mushroom", "sicily", "etna", "value", "ready", "now"],
                "rationale": "Volcanic smoke, wild strawberry, and fine Burgundian tannins. Stunning with Neapolitan Margherita and mushroom pizzas.",
                "cellar_complement": "Introduces one of Italy's most exciting volcanic regions — Pinot-like elegance at an everyday price."
            },
            {
                "wine_name": "Rosso di Montalcino",
                "producer": "Il Poggione (or Col d'Orcia)",
                "vintage_sweet_spot": "2021 or 2022",
                "region": "Montalcino, Tuscany, Italy",
                "varietal": "Sangiovese Grosso",
                "est_price": 32.0,
                "drinking_status": "Prime Peak Window",
                "decant_advice": "Aeration 30m",
                "serving_temp": "62°F (17°C)",
                "nj_availability": "Available in NJ & ships to NJ (Gary's Wine, Total Wine NJ, Wine.com)",
                "match_keywords": ["pizza", "pasta", "night", "weeknight", "italian", "ragu", "meatballs", "bolognese", "sangiovese", "montalcino", "value", "ready", "now"],
                "rationale": "Baby Brunello: same Sangiovese Grosso grapes, released young. Dark cherry, leather, and earth for ragù, meatballs, and pappardelle.",
                "cellar_complement": "Drinks now while your Brunellos age — a preview of Montalcino at a third of the price."
            }
        ]

        scored = []
        for rec in catalog:
            score = 10
            combined = f"{rec['wine_name']} {rec['producer']} {rec['region']} {rec['varietal']} {' '.join(rec['match_keywords'])}".lower()
            if q_lower:
                tokens = q_lower.split()
                for t in tokens:
                    if t in combined:
                        score += 30
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        recs = [s[1] for s in scored]

        # Respect an explicit price range in the query (e.g. "$20-$40", "under $50")
        import re
        price_min, price_max = None, None
        m = re.search(r"\$?\s*(\d{2,4})\s*(?:-|–|to|and)\s*\$?\s*(\d{2,4})", q_lower)
        if m and int(m.group(2)) > int(m.group(1)):
            price_min, price_max = int(m.group(1)), int(m.group(2))
        else:
            u = re.search(r"under\s*\$?\s*(\d{2,4})", q_lower)
            if u:
                price_min, price_max = 0, int(u.group(1))
        if price_max is not None:
            in_budget = [r for r in recs if price_min <= r["est_price"] <= price_max]
            if len(in_budget) >= 2:
                recs = in_budget

        return {
            "query": query,
            "recommendations": recs[:4]
        }

    def add_from_text(self, natural_text: str, user_id: Optional[int] = 1) -> WineBottle:
        """Parses natural language and commits new bottle to database for the user."""
        bottle = parse_wine_natural_language(natural_text)
        bottle.user_id = user_id or 1
        new_id = self.db.add_bottle(bottle, user_id=user_id)
        saved = self.db.get_bottle(new_id, user_id=user_id)
        return saved or bottle

    def add_from_label(self, label_text: str, default_fridge: str = "Basement Fridge", user_id: Optional[int] = 1) -> WineBottle:
        """Parses raw OCR text from a wine label photo and commits new bottle to database for the user."""
        from wine_agent.natural_language import parse_wine_label
        bottle = parse_wine_label(label_text, default_fridge=default_fridge)
        bottle.user_id = user_id or 1
        new_id = self.db.add_bottle(bottle, user_id=user_id)
        saved = self.db.get_bottle(new_id, user_id=user_id)
        return saved or bottle

    def batch_add(self, text: str, default_fridge: str = "Fridge 1", user_id: Optional[int] = 1) -> List[WineBottle]:
        """Parses a multi-line list of bottles and commits them all to the database for the user."""
        from wine_agent.natural_language import parse_batch_wines
        parsed_list = parse_batch_wines(text, default_fridge)
        saved_list = []
        for b in parsed_list:
            b.user_id = user_id or 1
            b_id = self.db.add_bottle(b, user_id=user_id)
            saved = self.db.get_bottle(b_id, user_id=user_id)
            saved_list.append(saved or b)
        return saved_list

    def get_fridge_breakdown(self, user_id: Optional[int] = 1) -> Dict[str, Any]:
        """Groups bottles into intuitive categories: Ready Now vs Needs to Age, organized by fridge."""
        bottles = self.db.list_bottles(only_in_stock=True, user_id=user_id)
        ready_now = []      # In Peak Window
        drink_soon = []     # Late Peak / Drink Soon
        approaching = []    # Approaching peak (can drink with decanting)
        needs_age = []      # Hold (Too young)

        fridges = {}        # "Fridge 1", "Fridge 2", etc.

        for b in bottles:
            dw = b.drinking_window
            fridge = b.location_rack or "Fridge 1"
            fridges.setdefault(fridge, []).append(b)

            if not dw:
                ready_now.append(b)
            elif dw.status == DrinkingStatus.PEAK:
                ready_now.append(b)
            elif dw.status == DrinkingStatus.LATE_PEAK or dw.status == DrinkingStatus.PAST_PEAK:
                drink_soon.append(b)
            elif dw.status == DrinkingStatus.EARLY_WINDOW:
                approaching.append(b)
            else:
                needs_age.append(b)

        return {
            "ready_now": ready_now,
            "drink_soon": drink_soon,
            "approaching": approaching,
            "needs_age": needs_age,
            "fridges": fridges,
            "total_bottles": sum(b.quantity for b in bottles)
        }

    def log_consumption(
        self,
        bottle_id: int,
        count: int = 1,
        rating: Optional[float] = None,
        notes: str = "",
        pairing: str = "",
        aging_curve_stage: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Optional[ConsumptionRecord]:
        """Logs a bottle consumption and updates inventory."""
        return self.db.consume_bottle(bottle_id, count, rating, notes, pairing, aging_curve_stage, user_id=user_id)

    def log_gift(
        self,
        bottle_id: int,
        count: int = 1,
        situation_notes: str = "",
        user_id: Optional[int] = None
    ) -> Optional[ConsumptionRecord]:
        """Logs a bottle gift removal and updates inventory without rating or tasting notes."""
        return self.db.gift_bottle(bottle_id, count, situation_notes, user_id=user_id)
