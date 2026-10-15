"""Lightweight HTTP REST API and UI Server for Sommelier Wine Cellar Agent."""

import http.server
import socketserver
import json
import urllib.parse
import os
from pathlib import Path
from typing import Any, Optional, Dict
from wine_agent.database import WineDatabase
from wine_agent.agent import SommelierAgent
from wine_agent.models import WineBottle, WineType, BottleFormat


WEB_DIR = Path(__file__).parent.parent / "web"


class WineRequestHandler(http.server.SimpleHTTPRequestHandler):
    agent: SommelierAgent = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/bottles":
            bottles = self.agent.db.list_bottles(only_in_stock=False)
            self._send_json([b.to_dict() for b in bottles])
        elif path == "/api/stats":
            stats = self.agent.audit_cellar()
            # serialize any bottle objects in audit
            serialized = {
                "stats": stats["stats"],
                "readiness_index_pct": stats["readiness_index_pct"],
                "sommelier_recommendations": stats["sommelier_recommendations"],
                "urgent_bottles": [b.to_dict() for b in stats["urgent_bottles"]],
                "peak_bottles": [b.to_dict() for b in stats["peak_bottles"]],
                "hold_bottles": [b.to_dict() for b in stats["hold_bottles"]]
            }
            self._send_json(serialized)
        elif path == "/api/history":
            history = self.agent.db.get_consumption_history()
            self._send_json([r.to_dict() for r in history])
        elif path == "/api/recommend":
            food = params.get("food", [None])[0]
            style = params.get("style", [None])[0]
            celeb = params.get("celebratory", ["false"])[0].lower() == "true"
            recs = self.agent.recommend_bottle(food=food, style=style, celebratory=celeb)
            ser_recs = []
            for r in recs:
                ser_recs.append({
                    "match_score": r["match_score"],
                    "bottle": r["bottle"].to_dict(),
                    "drinking_status": r["drinking_status"],
                    "decant_advice": r["decant_advice"],
                    "serving_temp": r["serving_temp"],
                    "rationale": r["rationale"]
                })
            self._send_json(ser_recs)
        elif path == "/api/public-ratings":
            from wine_agent.critic_ratings import get_public_critic_ratings
            producer = params.get("producer", [""])[0]
            wine = params.get("wine", [""])[0]
            v_raw = params.get("vintage", [None])[0]
            vintage = int(v_raw) if v_raw and v_raw.isdigit() else None
            varietal = params.get("varietal", [""])[0]
            reviews = get_public_critic_ratings(producer, wine, vintage, varietal)
            self._send_json({"producer": producer, "wine": wine, "vintage": vintage, "reviews": reviews})
        elif path == "/api/recommend-purchases":
            query = params.get("query", [""])[0]
            purchases = self.agent.recommend_purchases(query=query)
            self._send_json(purchases)
        elif path == "/api/gemini/status":
            from wine_agent.gemini_sommelier import get_gemini_api_key, DEFAULT_GEMINI_MODEL
            key = get_gemini_api_key()
            self._send_json({
                "configured": bool(key),
                "model": DEFAULT_GEMINI_MODEL,
                "masked_key": f"{key[:4]}...{key[-4:]}" if key and len(key) > 8 else None,
                "api_key": key if key else None
            })
        elif path == "/api/gemini/test-key":
            from wine_agent.gemini_sommelier import validate_gemini_api_key
            key = params.get("key", [None])[0]
            res = validate_gemini_api_key(key)
            self._send_json(res)
        elif path == "/api/export-csv":
            import io
            import csv
            bottles = self.agent.db.list_bottles(only_in_stock=False)
            output = io.StringIO()
            fieldnames = [
                "id", "producer", "wine_name", "vintage", "varietal", "region", "sub_region", "country",
                "wine_type", "format", "quantity", "location_rack", "location_bin",
                "purchase_price", "critic_score", "user_rating", "window_start", "peak_start", "peak_end",
                "window_end", "drinking_status", "decant_hours", "serving_temp_f", "notes"
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for b in bottles:
                dw = b.drinking_window
                writer.writerow({
                    "id": b.id,
                    "producer": b.producer,
                    "wine_name": b.wine_name,
                    "vintage": b.vintage or "NV",
                    "varietal": b.varietal,
                    "region": b.region,
                    "sub_region": b.sub_region or "",
                    "country": b.country,
                    "wine_type": b.wine_type.value if hasattr(b.wine_type, "value") else str(b.wine_type),
                    "format": b.format.value if hasattr(b.format, "value") else str(b.format),
                    "quantity": b.quantity,
                    "location_rack": b.location_rack,
                    "location_bin": b.location_bin,
                    "purchase_price": b.purchase_price or "",
                    "critic_score": b.critic_score or "",
                    "user_rating": b.user_rating or "",
                    "window_start": dw.window_start if dw else "",
                    "peak_start": dw.peak_start if dw else "",
                    "peak_end": dw.peak_end if dw else "",
                    "window_end": dw.window_end if dw else "",
                    "drinking_status": dw.status.value if dw else "",
                    "decant_hours": dw.decant_hours if dw else "",
                    "serving_temp_f": dw.serving_temp_f if dw else "",
                    "notes": b.personal_notes
                })
            csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="wine_cellar_inventory.csv"')
            self.send_header("Content-Length", str(len(csv_bytes)))
            self.end_headers()
            self.wfile.write(csv_bytes)
            return
        elif path == "/" or not path.startswith("/api"):
            # Serve index.html or static files
            if path == "/":
                self.path = "/index.html"
            return super().do_GET()
        else:
            self._send_json({"error": "Not Found"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len)
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            payload = {}

        if path == "/api/parse":
            text = payload.get("text", "")
            if not text:
                self._send_json({"error": "text field is required"}, status=400)
                return
            bottle = self.agent.add_from_text(text)
            self._send_json({"success": True, "bottle": bottle.to_dict()})

        elif path == "/api/scan-label":
            text = payload.get("text", "")
            fridge = payload.get("fridge", "Basement Fridge")
            save_immediately = payload.get("save", False)
            if not text:
                self._send_json({"error": "text recognized from label is required"}, status=400)
                return
            from wine_agent.natural_language import parse_wine_label
            bottle = parse_wine_label(text, default_fridge=fridge)
            if save_immediately:
                b_id = self.agent.db.add_bottle(bottle)
                saved = self.agent.db.get_bottle(b_id)
                self._send_json({"success": True, "bottle": (saved or bottle).to_dict(), "saved": True})
            else:
                self._send_json({"success": True, "bottle": bottle.to_dict(), "saved": False})

        elif path == "/api/bottles":
            # Add direct structured bottle
            try:
                b = WineBottle(
                    producer=payload.get("producer", "Unknown"),
                    wine_name=payload.get("wine_name", ""),
                    vintage=int(payload["vintage"]) if payload.get("vintage") else None,
                    varietal=payload.get("varietal", ""),
                    region=payload.get("region", ""),
                    country=payload.get("country", ""),
                    wine_type=WineType(payload.get("wine_type", "Red")),
                    format=BottleFormat(payload.get("format", "Standard (750ml)")),
                    quantity=int(payload.get("quantity", 1)),
                    location_rack=payload.get("location_rack", ""),
                    location_bin=payload.get("location_bin", ""),
                    purchase_price=float(payload["purchase_price"]) if payload.get("purchase_price") else None,
                    critic_score=int(payload["critic_score"]) if payload.get("critic_score") else None,
                    personal_notes=payload.get("personal_notes", "")
                )
                b_id = self.agent.db.add_bottle(b)
                saved = self.agent.db.get_bottle(b_id)
                self._send_json({"success": True, "bottle": saved.to_dict() if saved else b.to_dict()})
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)

        elif path == "/api/consume":
            b_id = payload.get("bottle_id")
            count = int(payload.get("count", 1))
            rating = float(payload["rating"]) if payload.get("rating") else None
            notes = payload.get("notes", "")
            pairing = payload.get("pairing", "")
            aging_stage = payload.get("aging_curve_stage", "")
            rec = self.agent.log_consumption(b_id, count, rating, notes, pairing, aging_stage)
            if rec:
                self._send_json({"success": True, "record": rec.to_dict()})
            else:
                self._send_json({"error": "Bottle not found"}, status=404)

        elif path == "/api/gift":
            b_id = payload.get("bottle_id")
            count = int(payload.get("count", 1))
            notes = payload.get("notes", "")
            rec = self.agent.log_gift(b_id, count, notes)
            if rec:
                self._send_json({"success": True, "record": rec.to_dict()})
            else:
                self._send_json({"error": "Bottle not found"}, status=404)

        elif path == "/api/batch":
            text = payload.get("text", "")
            default_fridge = payload.get("default_fridge", "Fridge 1")
            if not text:
                self._send_json({"error": "text field is required"}, status=400)
                return
            bottles = self.agent.batch_add(text, default_fridge)
            self._send_json({"success": True, "count": len(bottles), "bottles": [b.to_dict() for b in bottles]})

        elif path == "/api/clear":
            self.agent.db.clear_cellar()
            self._send_json({"success": True, "message": "Cellar cleared"})

        elif path == "/api/enrich-all-ratings":
            from wine_agent.critic_ratings import get_public_critic_ratings
            bottles = self.agent.db.list_bottles(only_in_stock=False)
            enriched_count = 0
            for b in bottles:
                if not b.critic_reviews:
                    revs = get_public_critic_ratings(b.producer, b.wine_name, b.vintage, b.varietal)
                    if revs:
                        b.critic_reviews = revs
                        if not b.critic_score:
                            scores = [x["score"] for x in revs if isinstance(x.get("score"), (int, float))]
                            if scores:
                                b.critic_score = max(scores)
                        self.agent.db.update_bottle(b)
                        enriched_count += 1
            self._send_json({"success": True, "enriched_count": enriched_count})

        elif path == "/api/rename-location":
            old_loc = payload.get("old_location", "").strip()
            new_loc = payload.get("new_location", "").strip()
            if not old_loc or not new_loc:
                self._send_json({"error": "old_location and new_location are required"}, status=400)
                return
            count = self.agent.db.rename_location(old_loc, new_loc)
            self._send_json({"success": True, "updated_count": count})

        elif path == "/api/clear-location":
            loc = payload.get("location", "").strip()
            if not loc:
                self._send_json({"error": "location is required"}, status=400)
                return
            count = self.agent.db.clear_location(loc)
            self._send_json({"success": True, "deleted_count": count})

        elif path in ("/api/delete", "/api/remove"):
            b_id = payload.get("bottle_id") or payload.get("id")
            if not b_id:
                self._send_json({"error": "bottle_id is required"}, status=400)
                return
            success = self.agent.db.delete_bottle(int(b_id))
            self._send_json({"success": success})

        elif path == "/api/seed":
            self.agent.db.seed_sample_collection()
            self._send_json({"success": True, "message": "Seeded collection"})

        elif path == "/api/import-csv":
            csv_content = payload.get("csv_text", "")
            mode = payload.get("mode", "merge")
            if not csv_content:
                self._send_json({"error": "csv_text is required"}, status=400)
                return
            if mode == "replace":
                self.agent.db.clear_cellar()
            import io
            import csv
            reader = csv.DictReader(io.StringIO(csv_content))
            imported_bottles = []
            for row in reader:
                producer = row.get("producer") or row.get("Producer") or row.get("Winery") or "Unknown"
                wine_name = row.get("wine_name") or row.get("Wine") or row.get("Name") or ""
                v_raw = row.get("vintage") or row.get("Vintage") or row.get("Year")
                vintage = int(v_raw) if v_raw and str(v_raw).strip().isdigit() else None
                varietal = row.get("varietal") or row.get("Varietal") or row.get("Grape") or ""
                region = row.get("region") or row.get("Region") or row.get("Appellation") or ""
                sub_region = row.get("sub_region") or row.get("Sub Region") or row.get("Vineyard") or ""
                country = row.get("country") or row.get("Country") or "United States"
                rack = row.get("location_rack") or row.get("Location") or row.get("Fridge") or row.get("Rack") or "Basement Fridge"
                bin_loc = row.get("location_bin") or row.get("Bin") or row.get("Shelf") or ""
                p_raw = row.get("purchase_price") or row.get("Price") or row.get("Cost") or row.get("Valuation")
                price = float(p_raw) if p_raw and str(p_raw).replace(".", "", 1).isdigit() else None
                q_raw = row.get("quantity") or row.get("Quantity") or row.get("Qty") or row.get("Bottles") or "1"
                qty = int(q_raw) if str(q_raw).strip().isdigit() else 1
                notes = row.get("notes") or row.get("Notes") or row.get("personal_notes") or ""
                u_rating_raw = row.get("user_rating") or row.get("Rating") or row.get("rating")
                u_rating = float(u_rating_raw) if u_rating_raw and str(u_rating_raw).replace(".", "", 1).isdigit() else None

                b = WineBottle(
                    producer=producer,
                    wine_name=wine_name,
                    vintage=vintage,
                    varietal=varietal,
                    region=region,
                    sub_region=sub_region,
                    country=country,
                    quantity=qty,
                    location_rack=rack,
                    location_bin=bin_loc,
                    purchase_price=price,
                    user_rating=u_rating,
                    personal_notes=notes
                )
                b_id = self.agent.db.add_bottle(b)
                saved = self.agent.db.get_bottle(b_id)
                imported_bottles.append(saved or b)

            self._send_json({"success": True, "count": len(imported_bottles), "bottles": [b.to_dict() for b in imported_bottles]})

        elif path == "/api/gemini/sommelier":
            from wine_agent.gemini_sommelier import ask_gemini_sommelier, DEFAULT_GEMINI_MODEL
            query = payload.get("query", "").strip()
            api_key = payload.get("api_key")
            model = payload.get("model") or DEFAULT_GEMINI_MODEL
            mode = payload.get("mode", "open")
            history = payload.get("history") or []
            if not query:
                self._send_json({"error": "query parameter is required"}, status=400)
                return
            bottles = self.agent.db.list_bottles(only_in_stock=True)
            result = ask_gemini_sommelier(query, bottles, api_key=api_key, model=model, mode=mode, history=history)
            self._send_json(result)

        elif path == "/api/gemini/save-key":
            from wine_agent.gemini_sommelier import save_gemini_api_key
            key = payload.get("api_key", "").strip()
            if not key:
                self._send_json({"error": "api_key is required"}, status=400)
                return
            saved = save_gemini_api_key(key)
            self._send_json({"success": saved, "message": "Gemini API key saved successfully across cellar configs"})

        elif path == "/api/gemini/test-key":
            from wine_agent.gemini_sommelier import validate_gemini_api_key
            key = payload.get("api_key", "").strip() if payload else None
            res = validate_gemini_api_key(key)
            self._send_json(res)
        else:
            self._send_json({"error": "Not Found"}, status=404)


def run_server(port: int = 8000, db_path: Optional[str] = None):
    # Support Railway / Cloud PORT env var
    env_port = os.environ.get("PORT")
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            pass

    db = WineDatabase(db_path) if db_path else WineDatabase()
    agent = SommelierAgent(db)
    WineRequestHandler.agent = agent

    # Ensure DB has at least sample data if completely empty
    if not agent.db.list_bottles(only_in_stock=False):
        agent.db.seed_sample_collection()

    handler = WineRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"\n🍷 Wine Cellar Sommelier Agent Web UI running on port {port} (http://0.0.0.0:{port})")
        print("Press Ctrl+C to terminate the server.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    run_server(port=port)
