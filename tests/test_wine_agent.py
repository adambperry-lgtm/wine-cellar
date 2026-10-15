"""Comprehensive unit tests for the Wine Cellar Agent and Drinking Window Engine."""

import unittest
from unittest.mock import patch
import os
import tempfile
from wine_agent.models import WineBottle, WineType, BottleFormat, DrinkingStatus
from wine_agent.drinking_window import calculate_drinking_window, CURRENT_YEAR
from wine_agent.database import WineDatabase
from wine_agent.agent import SommelierAgent
from wine_agent.natural_language import parse_wine_natural_language


class TestDrinkingWindowEngine(unittest.TestCase):
    def test_bordeaux_first_growth_aging(self):
        # 2010 Bordeaux (stellar vintage +5 yrs)
        bottle = WineBottle(
            producer="Château Latour",
            wine_name="Premier Grand Cru Classé",
            vintage=2010,
            region="Bordeaux",
            sub_region="Pauillac",
            varietal="Cabernet Sauvignon",
            wine_type=WineType.RED
        )
        window = calculate_drinking_window(bottle, current_year=2026)
        self.assertEqual(window.status, DrinkingStatus.PEAK)
        self.assertGreaterEqual(window.peak_end, 2040)
        self.assertGreater(window.decant_hours, 0.0)

    def test_young_barolo_hold(self):
        # 2020 Barolo should be held in 2026
        bottle = WineBottle(
            producer="Bartolo Mascarello",
            wine_name="Barolo",
            vintage=2020,
            region="Piedmont",
            varietal="Nebbiolo",
            wine_type=WineType.RED
        )
        window = calculate_drinking_window(bottle, current_year=2026)
        self.assertEqual(window.status, DrinkingStatus.TOO_YOUNG)
        self.assertGreater(window.window_start, 2026)

    def test_format_scaling(self):
        # Half bottle ages faster than Magnum
        b_half = WineBottle(
            producer="Château Margaux",
            vintage=2015,
            region="Bordeaux",
            format=BottleFormat.HALF
        )
        b_mag = WineBottle(
            producer="Château Margaux",
            vintage=2015,
            region="Bordeaux",
            format=BottleFormat.MAGNUM
        )
        w_half = calculate_drinking_window(b_half, current_year=2026)
        w_mag = calculate_drinking_window(b_mag, current_year=2026)
        self.assertLess(w_half.peak_end, w_mag.peak_end)

    def test_champagne_prestige(self):
        bottle = WineBottle(
            producer="Dom Pérignon",
            vintage=2012,
            region="Champagne",
            wine_type=WineType.SPARKLING
        )
        window = calculate_drinking_window(bottle, current_year=2026)
        self.assertEqual(window.status, DrinkingStatus.PEAK)
        self.assertEqual(window.serving_temp_f, 48)


class TestWineDatabaseAndAgent(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_cellar.db")
        self.db = WineDatabase(self.db_path)
        self.agent = SommelierAgent(self.db)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_add_and_list_bottle(self):
        b = WineBottle(
            producer="Ridge Vineyards",
            wine_name="Monte Bello",
            vintage=2019,
            region="California",
            quantity=2,
            location_rack="Rack 1",
            location_bin="Bin A"
        )
        b_id = self.db.add_bottle(b)
        self.assertIsNotNone(b_id)

        retrieved = self.db.get_bottle(b_id)
        self.assertEqual(retrieved.producer, "Ridge Vineyards")
        self.assertEqual(retrieved.quantity, 2)
        self.assertIsNotNone(retrieved.drinking_window)

    def test_consume_bottle(self):
        b = WineBottle(producer="Penfolds", wine_name="Grange", vintage=2012, quantity=2)
        b_id = self.db.add_bottle(b)
        rec = self.db.consume_bottle(b_id, count=1, rating=98, tasting_notes="Sublime blackberry")
        self.assertIsNotNone(rec)

        updated = self.db.get_bottle(b_id)
        self.assertEqual(updated.quantity, 1)

    def test_nlp_parsing(self):
        text = "I bought 3 bottles of 2016 Giacomo Conterno Barolo Francia for $280 each in Rack C Bin 4"
        parsed = parse_wine_natural_language(text)
        self.assertEqual(parsed.quantity, 3)
        self.assertEqual(parsed.vintage, 2016)
        self.assertEqual(parsed.purchase_price, 280.0)
        self.assertEqual(parsed.location_rack, "Rack C")
        self.assertEqual(parsed.location_bin, "Bin 4")
        self.assertIn("Giacomo Conterno", parsed.producer)

    def test_food_pairing_recommendation(self):
        self.db.seed_sample_collection()
        recs = self.agent.recommend_bottle(food="prime ribeye steak")
        self.assertGreater(len(recs), 0)
        top = recs[0]["bottle"]
        self.assertEqual(top.wine_type, WineType.RED)

    def test_label_scanner_hunnicutt_cabernet(self):
        label_text = """
        HUNNICUTT
        2024
        CABERNET SAUVIGNON
        NAPA VALLEY
        ALC. 14.8% BY VOL. 750 ML
        PRODUCED AND BOTTLED BY HUNNICUTT WINES
        ST. HELENA, CALIFORNIA
        CONTAINS SULFITES
        """
        bottle = self.agent.add_from_label(label_text, default_fridge="Basement Fridge")
        self.assertEqual(bottle.producer, "Hunnicutt")
        self.assertEqual(bottle.vintage, 2024)
        self.assertEqual(bottle.varietal, "Cabernet Sauvignon")
        self.assertEqual(bottle.location_rack, "Basement Fridge")
        self.assertEqual(bottle.wine_type, WineType.RED)
        self.assertIsNotNone(bottle.drinking_window)
        self.assertEqual(bottle.drinking_window.status, DrinkingStatus.TOO_YOUNG)
        self.assertEqual(bottle.drinking_window.peak_start, 2032)
        self.assertEqual(bottle.drinking_window.peak_end, 2040)

    def test_label_scanner_hunnicutt_935_sku(self):
        label_text = """
        HUNNICUTT
        2023 9-3-5
        PROPRIETARY RED
        NAPA VALLEY
        DRH23C79
        14.5% ALC / VOL
        """
        bottle = self.agent.add_from_label(label_text, default_fridge="Basement Fridge")
        self.assertEqual(bottle.producer, "Hunnicutt")
        self.assertEqual(bottle.vintage, 2023)
        self.assertIn("DRH23C79", bottle.personal_notes)
        self.assertEqual(bottle.drinking_window.status, DrinkingStatus.TOO_YOUNG)

    def test_gift_bottle_removes_from_inventory_without_rating(self):
        bottle_id = self.db.add_bottle(WineBottle(
            producer="Caymus",
            wine_name="Special Selection",
            vintage=2018,
            varietal="Cabernet Sauvignon",
            region="Napa Valley",
            quantity=2
        ))
        # Gift 1 bottle
        rec = self.agent.log_gift(bottle_id, count=1, situation_notes="40th Birthday gift for Dave")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.action_type, "gift")
        self.assertIsNone(rec.rating)
        self.assertEqual(rec.tasting_notes, "40th Birthday gift for Dave")
        self.assertEqual(rec.bottles_consumed, 1)

        # Inventory decremented to 1
        updated = self.db.get_bottle(bottle_id)
        self.assertEqual(updated.quantity, 1)

        # History includes gift record
        history = self.db.get_consumption_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].action_type, "gift")
        self.assertIsNone(history[0].rating)

    def test_export_and_import_csv(self):
        b1 = WineBottle(
            producer="Domaine de la Romanée-Conti",
            wine_name="La Tâche",
            vintage=2015,
            varietal="Pinot Noir",
            region="Burgundy",
            sub_region="Vosne-Romanée",
            country="France",
            quantity=2,
            location_rack="Basement Fridge",
            purchase_price=4500.0,
            critic_score=99,
            user_rating=5.0,
            personal_notes="Anniversary bottle"
        )
        self.db.add_bottle(b1)

        csv_path = os.path.join(self.tmp_dir.name, "cellar_export.csv")
        self.db.export_csv(csv_path)

        # Verify file exists and starts with UTF-8 BOM
        with open(csv_path, "rb") as f:
            content_bytes = f.read()
            self.assertTrue(content_bytes.startswith(b"\xef\xbb\xbf"))

        # Import into a second fresh database
        db2_path = os.path.join(self.tmp_dir.name, "fresh_cellar.db")
        db2 = WineDatabase(db2_path)
        imported_count = db2.import_csv(csv_path)
        self.assertEqual(imported_count, 1)

        bottles = db2.list_bottles()
        self.assertEqual(len(bottles), 1)
        self.assertEqual(bottles[0].producer, "Domaine de la Romanée-Conti")
        self.assertEqual(bottles[0].wine_name, "La Tâche")
        self.assertEqual(bottles[0].vintage, 2015)
        self.assertEqual(bottles[0].sub_region, "Vosne-Romanée")
        self.assertEqual(bottles[0].quantity, 2)
        self.assertEqual(bottles[0].location_rack, "Basement Fridge")
        self.assertEqual(bottles[0].purchase_price, 4500.0)
        self.assertEqual(bottles[0].user_rating, 5.0)

    def test_import_csv_aliases(self):
        csv_path = os.path.join(self.tmp_dir.name, "aliases.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("Winery,Wine,Year,Grape,Appellation,Vineyard,Bottles,Fridge,Price,Rating,Notes\n")
            f.write("Silver Oak,Alexander Valley,2016,Cabernet Sauvignon,California,Alexander Valley,3,Upstairs Fridge,95,4.5,Delicious\n")

        db_alias_path = os.path.join(self.tmp_dir.name, "alias_cellar.db")
        db_alias = WineDatabase(db_alias_path)
        count = db_alias.import_csv(csv_path)
        self.assertEqual(count, 1)

        b = db_alias.list_bottles()[0]
        self.assertEqual(b.producer, "Silver Oak")
        self.assertEqual(b.wine_name, "Alexander Valley")
        self.assertEqual(b.vintage, 2016)
        self.assertEqual(b.varietal, "Cabernet Sauvignon")
        self.assertEqual(b.region, "California")
        self.assertEqual(b.sub_region, "Alexander Valley")
        self.assertEqual(b.quantity, 3)
        self.assertEqual(b.location_rack, "Upstairs Fridge")
        self.assertEqual(b.purchase_price, 95.0)
        self.assertEqual(b.user_rating, 4.5)
        self.assertEqual(b.personal_notes, "Delicious")

    def test_prepare_distribution_files(self):
        from wine_agent.github_sync import prepare_distribution_files, get_github_token
        clean_html = prepare_distribution_files()
        self.assertIn("const FALLBACK_BOTTLES = [];", clean_html)
        self.assertIn("tabCsvBtn", clean_html)
        self.assertIn("exportCellarDatabase", clean_html)

        # Test token resolution via environment
        old_env = os.environ.get("GITHUB_TOKEN")
        try:
            os.environ["GITHUB_TOKEN"] = "test_ghp_mock_token"
            self.assertEqual(get_github_token(), "test_ghp_mock_token")
        finally:
            if old_env is not None:
                os.environ["GITHUB_TOKEN"] = old_env
            else:
                os.environ.pop("GITHUB_TOKEN", None)

    def test_import_cellartracker_csv(self):
        ct_csv = os.path.join(self.tmp_dir.name, "cellartracker_export.csv")
        with open(ct_csv, "w", encoding="utf-8") as f:
            f.write("iWine,Barcode,Producer,Wine,Vintage,WineType,MasterVarietal,Country,Region,SubRegion,Appellation,Vineyard,Size,Quantity,Location,Bin,Price,Valuation,BeginConsume,EndConsume,Score,MyRating,MyNotes\n")
            f.write('1492011,1001,Château Pontet-Canet,Grand Cru Classé,2010,Red,Cabernet Sauvignon,France,Bordeaux,Pauillac,Pauillac,Pauillac,750ml,2,Basement Fridge,Bin 4,"$195.00","$320.00",2022,2039,97,5.0,"Bought en primeur"\n')
            f.write('2849102,1002,Dominus Estate,Christian Moueix,2016,Red,Bordeaux Blend,United States,California,Napa Valley,Napa Valley,,1.5L,1,Upstairs Fridge,Rack A,"$350.00","$420.00",2028,2045,98,,Collector Magnum\n')
            f.write('9999999,1003,Consumed Wine,Old Vintage,1995,Red,Cabernet,United States,California,,,,750ml,0,Cellar,,$50,$50,2005,2015,90,,Consumed\n')

        ct_db_path = os.path.join(self.tmp_dir.name, "ct_cellar.db")
        ct_db = WineDatabase(ct_db_path)
        imported = ct_db.import_csv(ct_csv)

        # 2 active bottles imported; 0-quantity consumed bottle skipped
        self.assertEqual(imported, 2)

        bottles = ct_db.list_bottles()
        self.assertEqual(len(bottles), 2)

        # First bottle verification (Pontet-Canet)
        b1 = [b for b in bottles if "Pontet-Canet" in b.producer][0]
        self.assertEqual(b1.producer, "Château Pontet-Canet")
        self.assertEqual(b1.wine_name, "Grand Cru Classé")
        self.assertEqual(b1.vintage, 2010)
        self.assertEqual(b1.wine_type, WineType.RED)
        self.assertEqual(b1.format, BottleFormat.STANDARD)
        self.assertEqual(b1.quantity, 2)
        self.assertEqual(b1.location_rack, "Basement Fridge")
        self.assertEqual(b1.location_bin, "Bin 4")
        self.assertEqual(b1.purchase_price, 195.0)
        self.assertEqual(b1.critic_score, 97)
        self.assertEqual(b1.user_rating, 5.0)
        self.assertIn("[CT iWine: 1492011]", b1.personal_notes)
        self.assertIn("Bought en primeur", b1.personal_notes)
        self.assertIsNotNone(b1.drinking_window)
        self.assertEqual(b1.drinking_window.peak_start, 2022)
        self.assertEqual(b1.drinking_window.peak_end, 2039)
        self.assertEqual(b1.drinking_window.status, DrinkingStatus.PEAK)

        # Second bottle verification (Dominus Magnum)
        b2 = [b for b in bottles if "Dominus" in b.producer][0]
        self.assertEqual(b2.producer, "Dominus Estate")
        self.assertEqual(b2.format, BottleFormat.MAGNUM)
        self.assertEqual(b2.quantity, 1)
        self.assertEqual(b2.location_rack, "Upstairs Fridge")
        self.assertEqual(b2.purchase_price, 350.0)
        self.assertEqual(b2.critic_score, 98)
        self.assertIn("[CT iWine: 2849102]", b2.personal_notes)
        self.assertEqual(b2.drinking_window.peak_start, 2028)
        self.assertEqual(b2.drinking_window.peak_end, 2045)
        self.assertEqual(b2.drinking_window.status, DrinkingStatus.EARLY_WINDOW)

    def test_critic_ratings_lookup_and_persistence(self):
        from wine_agent.critic_ratings import get_public_critic_ratings, enrich_bottle_ratings

        # 1. Test Registry Lookup for James Suckling and others
        reviews = get_public_critic_ratings(producer="Tenuta San Guido", wine_name="Guidalberto", vintage=2022)
        self.assertGreaterEqual(len(reviews), 2)
        js_reviews = [r for r in reviews if r.get("code") == "JS"]
        self.assertEqual(len(js_reviews), 1)
        self.assertEqual(js_reviews[0]["score"], 94)
        self.assertEqual(js_reviews[0]["source"], "James Suckling")
        self.assertIn("James Suckling", js_reviews[0]["reviewer"])
        self.assertIn("currant", js_reviews[0]["review"].lower())

        # 2. Test Bottle Enrichment
        b = WineBottle(
            producer="Faust",
            wine_name="The Pact Cabernet Sauvignon",
            vintage=2022,
            region="Napa Valley",
            sub_region="Coombsville",
            varietal="Cabernet Sauvignon",
            quantity=1
        )
        enrich_bottle_ratings(b)
        self.assertTrue(len(b.critic_reviews) > 0)
        self.assertEqual(b.critic_score, 95)  # Max score (JS 95)

        # 3. Test Database Persistence
        b_id = self.db.add_bottle(b)
        retrieved = self.db.get_bottle(b_id)
        self.assertEqual(len(retrieved.critic_reviews), len(b.critic_reviews))
        self.assertEqual(retrieved.critic_score, 95)
        critics_found = {r["code"] for r in retrieved.critic_reviews}
        self.assertIn("JS", critics_found)
        self.assertIn("JD", critics_found)

    def test_gemini_sommelier_context_and_api(self):
        from wine_agent.gemini_sommelier import format_cellar_context, ask_gemini_sommelier
        from unittest.mock import patch

        b1 = WineBottle(
            id=1,
            producer="Faust",
            wine_name="The Pact",
            vintage=2022,
            varietal="Cabernet Sauvignon",
            region="Napa Valley",
            quantity=2,
            location_rack="Basement Fridge",
            location_bin="Shelf 2",
            critic_score=95
        )
        b2 = WineBottle(
            id=2,
            producer="Goldeneye",
            wine_name="Pinot Noir",
            vintage=2022,
            varietal="Pinot Noir",
            region="Anderson Valley",
            quantity=0  # Out of stock
        )

        # 1. Format context (should only include in-stock bottles)
        context = format_cellar_context([b1, b2])
        self.assertIn("Faust", context)
        self.assertIn("The Pact", context)
        self.assertIn("Basement Fridge", context)
        self.assertNotIn("Goldeneye", context)  # Out of stock excluded

        # 2. Test missing key error handling
        with patch("wine_agent.gemini_sommelier.get_gemini_api_key", return_value=None):
            res_no_key = ask_gemini_sommelier("What to drink with ribeye?", [b1], api_key=None)
            self.assertFalse(res_no_key.get("success"))
            self.assertIn("Gemini API key is required", res_no_key["error"])

        # 3. Test mock API call
        with patch("wine_agent.gemini_sommelier.call_gemini_api", return_value="**2022 Faust The Pact** pairs gorgeously with ribeye."):
            res_mock = ask_gemini_sommelier("What to drink with steak?", [b1], api_key="test_fake_key")
            self.assertTrue(res_mock["success"])
            self.assertIn("Faust The Pact", res_mock["advice"])
            self.assertEqual(res_mock["source"], "gemini")

        # 4. Test buy mode in Gemini sommelier
        with patch("wine_agent.gemini_sommelier.call_gemini_api") as mock_api:
            mock_api.return_value = "### Acquisition Recommendations\n\n1. **2015 La Rioja Alta Gran Reserva 904** - ready for ribeye."
            res_buy = ask_gemini_sommelier("Buy wine ready for ribeye", [b1], api_key="test_fake_key", mode="buy")
            self.assertTrue(res_buy["success"])
            self.assertEqual(res_buy["mode"], "buy")
            self.assertIn("history", res_buy)
            self.assertEqual(len(res_buy["history"]), 2)
            prompt_used = mock_api.call_args[0][0]
            self.assertIn("acquisition advisor", prompt_used.lower())
            self.assertIn("PURCHASE", prompt_used)

        # 5. Test multi-turn follow-up history in Gemini sommelier
        with patch("wine_agent.gemini_sommelier.call_gemini_api") as mock_api:
            mock_api.return_value = "### Alternative Feedback & Options under $50\n\n1. **2019 Viña Tondonia Reserva** or **Produttori del Barbaresco**."
            prior_history = [
                {"role": "user", "content": "Buy wine ready for ribeye"},
                {"role": "assistant", "content": "1. 2015 La Rioja Alta Gran Reserva 904 ($85)"}
            ]
            res_followup = ask_gemini_sommelier(
                "Can you suggest alternatives under $50, or what do you think of 2018 Faust?",
                [b1],
                api_key="test_fake_key",
                mode="buy",
                history=prior_history
            )
            self.assertTrue(res_followup["success"])
            self.assertEqual(len(res_followup["history"]), 4)
            self.assertEqual(res_followup["history"][-1]["role"], "assistant")
            self.assertIn("Alternative Feedback", res_followup["advice"])
            prompt_used = mock_api.call_args[0][0]
            self.assertIn("CONVERSATION TRANSCRIPT SO FAR", prompt_used)
            self.assertIn("2015 La Rioja Alta", prompt_used)
            self.assertIn("DIRECT EVALUATION & FEEDBACK", prompt_used)
            self.assertIn("NEW CRITERIA & DIRECTIONS", prompt_used)

    def test_recommend_purchases_classic(self):
        # Ribeye query
        ribeye_recs = self.agent.recommend_purchases("ribeye")
        self.assertIn("recommendations", ribeye_recs)
        self.assertGreater(len(ribeye_recs["recommendations"]), 0)
        top_rec = ribeye_recs["recommendations"][0]
        self.assertIn("wine_name", top_rec)
        self.assertIn("producer", top_rec)
        self.assertIn("vintage_sweet_spot", top_rec)
        self.assertIn("cellar_complement", top_rec)

        # Seafood query
        seafood_recs = self.agent.recommend_purchases("seafood oysters")
        seafood_names = [r["wine_name"] for r in seafood_recs["recommendations"]]
        self.assertTrue(any("Chablis" in name for name in seafood_names))

    def test_gemini_key_persistence(self):
        from wine_agent.gemini_sommelier import save_gemini_api_key, get_gemini_api_key
        # Preserve original key if present
        original_key = get_gemini_api_key()
        try:
            test_key = "AIzaSyFakeTestKeyForCellarSommelier123"
            saved = save_gemini_api_key(test_key)
            self.assertTrue(saved)
            retrieved = get_gemini_api_key()
            self.assertEqual(retrieved, test_key)
        finally:
            if original_key:
                save_gemini_api_key(original_key)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
                key_file = os.path.join(base_dir, ".gemini_key")
                if os.path.exists(key_file):
                    os.remove(key_file)

    def test_validate_gemini_api_key(self):
        from wine_agent.gemini_sommelier import validate_gemini_api_key
        # Test with no key provided
        res_empty = validate_gemini_api_key("")
        self.assertFalse(res_empty["valid"])
        self.assertIn("error", res_empty)

        # Test mock successful validation
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}'
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            res_valid = validate_gemini_api_key("fake_valid_key")
            self.assertTrue(res_valid["valid"])
            self.assertIn("gemini-flash-lite-latest", res_valid["model"])

    def test_critic_source_url(self):
        from wine_agent.critic_ratings import get_public_critic_ratings, get_critic_source_url
        revs = get_public_critic_ratings("Stonestreet", "Estate Cabernet Sauvignon", 2018)
        self.assertGreater(len(revs), 0)
        for r in revs:
            self.assertIn("source_url", r)
            self.assertTrue(r["source_url"].startswith("http"))
            self.assertIn("Stonestreet", r["source_url"])

    def test_railway_cloud_deployment_configs(self):
        import json
        base_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        
        # 1. Procfile check
        procfile_path = os.path.join(base_dir, "Procfile")
        self.assertTrue(os.path.exists(procfile_path))
        with open(procfile_path, "r", encoding="utf-8") as f:
            proc_content = f.read()
            self.assertIn("web: python3 -m wine_agent.server", proc_content)

        # 2. railway.json check
        railway_json_path = os.path.join(base_dir, "railway.json")
        self.assertTrue(os.path.exists(railway_json_path))
        with open(railway_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn("deploy", data)
            self.assertEqual(data["deploy"].get("healthcheckPath"), "/api/bottles")

        # 3. Dockerfile check
        dockerfile_path = os.path.join(base_dir, "Dockerfile")
        self.assertTrue(os.path.exists(dockerfile_path))
        with open(dockerfile_path, "r", encoding="utf-8") as f:
            docker_content = f.read()
            self.assertIn("EXPOSE 8000", docker_content)
            self.assertIn("wine_agent.server", docker_content)

        # 4. CELLAR_DB_PATH resolution test
        from wine_agent.database import get_default_db_path
        old_custom = os.environ.get("CELLAR_DB_PATH")
        try:
            os.environ["CELLAR_DB_PATH"] = "/tmp/test_railway_cellar.db"
            self.assertEqual(get_default_db_path(), "/tmp/test_railway_cellar.db")
        finally:
            if old_custom:
                os.environ["CELLAR_DB_PATH"] = old_custom
            else:
                os.environ.pop("CELLAR_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()


