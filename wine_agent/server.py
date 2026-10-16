"""Lightweight HTTP REST API and UI Server for Sommelier Wine Cellar Agent."""

import http.server
import socketserver
import json
import urllib.parse
import os
from pathlib import Path
from typing import Any, Optional, Dict, List
from wine_agent.database import WineDatabase
from wine_agent.agent import SommelierAgent
from wine_agent.models import WineBottle, WineType, BottleFormat, UserProfile


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _get_authenticated_user_strict(self) -> Optional[UserProfile]:
        """Extracts strictly authenticated user from session token without falling back to default."""
        token = None
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        if not token and "Cookie" in self.headers:
            cookie_header = self.headers.get("Cookie", "")
            for part in cookie_header.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    if k == "cellar_session":
                        token = v
                        break

        if token:
            return self.agent.db.get_user_from_session(token)
        return None

    def _get_current_user(self, params: Optional[Dict[str, List[str]]] = None) -> UserProfile:
        """Extracts current authenticated user, defaulting to User 1 (Cellar Master) if unauthenticated."""
        token = None
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        if not token and "Cookie" in self.headers:
            cookie_header = self.headers.get("Cookie", "")
            for part in cookie_header.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    if k == "cellar_session":
                        token = v
                        break

        if not token and params and "auth_token" in params:
            token = params["auth_token"][0]

        if token:
            user = self.agent.db.get_user_from_session(token)
            if user:
                return user

        # Fallback to User 1 (Cellar Master) for backward compatibility
        default_user = self.agent.db.get_user_by_id(1)
        if default_user:
            return default_user
        # If DB was just initialized and user 1 lookup failed
        users = self.agent.db.list_users()
        return users[0] if users else UserProfile(id=1, email="cellarmaster@cellar.local", name="Cellar Master")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # ==================== Auth Routes ====================
        if path == "/api/auth/me":
            strict_user = self._get_authenticated_user_strict()
            effective_user = strict_user or self.agent.db.get_user_by_id(1)
            self._send_json({
                "authenticated": strict_user is not None,
                "user": effective_user.to_dict() if effective_user else None
            })
            return

        elif path == "/api/auth/users":
            users = self.agent.db.list_users()
            self._send_json([u.to_dict() for u in users])
            return

        elif path == "/api/admin/activity":
            report = self.agent.db.get_admin_activity_report()
            self._send_json(report)
            return

        # ==================== Cellar API Routes ====================
        current_user = self._get_current_user(params)

        if path == "/api/bottles":
            bottles = self.agent.db.list_bottles(only_in_stock=False, user_id=current_user.id)
            self._send_json([b.to_dict() for b in bottles])

        elif path == "/api/stats":
            stats = self.agent.audit_cellar(user_id=current_user.id)
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
            history = self.agent.db.get_consumption_history(user_id=current_user.id)
            self._send_json([r.to_dict() for r in history])

        elif path == "/api/storage-locations":
            locations = self.agent.db.get_storage_locations(user_id=current_user.id)
            self._send_json({"locations": locations})

        elif path == "/api/recommend":
            food = params.get("food", [None])[0]
            style = params.get("style", [None])[0]
            celeb = params.get("celebratory", ["false"])[0].lower() == "true"
            recs = self.agent.recommend_bottle(food=food, style=style, celebratory=celeb, user_id=current_user.id)
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
            bottles = self.agent.db.list_bottles(only_in_stock=False, user_id=current_user.id)
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
            self.send_header("Content-Disposition", f'attachment; filename="cellar_inventory_{current_user.name.lower().replace(" ", "_")}.csv"')
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

        # ==================== Authentication Endpoints ====================
        if path == "/api/auth/register":
            email = payload.get("email", "").strip()
            password = payload.get("password", "")
            name = payload.get("name", "").strip()
            if not email or "@" not in email:
                self._send_json({"error": "A valid email address is required"}, status=400)
                return
            if not password or len(password) < 6:
                self._send_json({"error": "Password must be at least 6 characters long"}, status=400)
                return
            if self.agent.db.get_user_by_email(email):
                self._send_json({"error": "An account with this email address already exists"}, status=400)
                return
            user = self.agent.db.create_user(email=email, password=password, name=name)
            if not user:
                self._send_json({"error": "Failed to create account"}, status=500)
                return
            token = self.agent.db.create_session(user.id)
            self._send_json({
                "success": True,
                "token": token,
                "user": user.to_dict(),
                "message": f"Welcome to your private wine cellar, {user.name}!"
            })
            return

        elif path == "/api/auth/login":
            email = payload.get("email", "").strip()
            password = payload.get("password", "")
            if not email or not password:
                self._send_json({"error": "Email and password are required"}, status=400)
                return
            user = self.agent.db.authenticate_user(email, password)
            if not user:
                self._send_json({"error": "Invalid email or password"}, status=401)
                return
            token = self.agent.db.create_session(user.id)
            self._send_json({
                "success": True,
                "token": token,
                "user": user.to_dict(),
                "message": f"Welcome back, {user.name}!"
            })
            return

        elif path == "/api/auth/google":
            credential = payload.get("credential") or payload.get("id_token") or payload.get("token")
            if not credential:
                demo_email = payload.get("email", "sommelier.demo@gmail.com")
                demo_name = payload.get("name", "Google Sommelier")
                credential = f"demo:{demo_email}:{demo_name}"
            user = self.agent.db.authenticate_or_create_google_user(credential)
            if not user:
                self._send_json({"error": "Failed to verify Google Identity credential"}, status=401)
                return
            token = self.agent.db.create_session(user.id)
            self._send_json({
                "success": True,
                "token": token,
                "user": user.to_dict(),
                "message": f"Signed in with Google as {user.name}!"
            })
            return

        elif path == "/api/auth/logout":
            token = None
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
            if token:
                self.agent.db.delete_session(token)
            self._send_json({"success": True, "message": "Logged out successfully"})
            return

        elif path == "/api/auth/switch":
            target_id = payload.get("user_id")
            if not target_id:
                self._send_json({"error": "user_id is required"}, status=400)
                return
            user = self.agent.db.get_user_by_id(int(target_id))
            if not user:
                self._send_json({"error": "User account not found"}, status=404)
                return
            token = self.agent.db.create_session(user.id)
            self._send_json({
                "success": True,
                "token": token,
                "user": user.to_dict(),
                "message": f"Switched active account to {user.name}"
            })
            return

        # ==================== User-Scoped Cellar Actions ====================
        current_user = self._get_current_user()

        if path == "/api/parse":
            text = payload.get("text", "")
            if not text:
                self._send_json({"error": "text field is required"}, status=400)
                return
            bottle = self.agent.add_from_text(text, user_id=current_user.id)
            self._send_json({"success": True, "bottle": bottle.to_dict()})

        elif path == "/api/scan-label":
            image_data = payload.get("image_data") or payload.get("image_base64")
            text = payload.get("text", "")
            fridge = payload.get("fridge", "Basement Fridge")
            save_immediately = payload.get("save", False)
            api_key = payload.get("api_key")

            bottle = None
            method = "ocr"

            # 1. Attempt Gemini Multimodal Vision if an image was provided
            if image_data:
                from wine_agent.gemini_sommelier import analyze_wine_label_image
                vision_res = analyze_wine_label_image(image_data, api_key=api_key, default_fridge=fridge)
                if vision_res.get("success") and vision_res.get("bottle"):
                    bottle = vision_res["bottle"]
                    method = "gemini_vision"
                elif not text:
                    # Vision analysis failed and no fallback OCR text was provided
                    self._send_json({
                        "error": vision_res.get("error", "Unable to parse wine label image via Gemini Vision."),
                        "vision_error": vision_res.get("error")
                    }, status=400)
                    return

            # 2. Text / OCR fallback
            if not bottle:
                if not text:
                    self._send_json({"error": "Neither image data nor recognized text was provided."}, status=400)
                    return
                from wine_agent.natural_language import parse_wine_label
                bottle = parse_wine_label(text, default_fridge=fridge)
                method = "ocr"

            bottle.user_id = current_user.id
            if save_immediately:
                b_id = self.agent.db.add_bottle(bottle, user_id=current_user.id)
                saved = self.agent.db.get_bottle(b_id, user_id=current_user.id)
                self._send_json({"success": True, "bottle": (saved or bottle).to_dict(), "method": method, "saved": True})
            else:
                self._send_json({"success": True, "bottle": bottle.to_dict(), "method": method, "saved": False})

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
                    personal_notes=payload.get("personal_notes", ""),
                    user_id=current_user.id
                )
                b_id = self.agent.db.add_bottle(b, user_id=current_user.id)
                saved = self.agent.db.get_bottle(b_id, user_id=current_user.id)
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
            rec = self.agent.log_consumption(b_id, count, rating, notes, pairing, aging_stage, user_id=current_user.id)
            if rec:
                self._send_json({"success": True, "record": rec.to_dict()})
            else:
                self._send_json({"error": "Bottle not found"}, status=404)

        elif path == "/api/gift":
            b_id = payload.get("bottle_id")
            count = int(payload.get("count", 1))
            notes = payload.get("notes", "")
            rec = self.agent.log_gift(b_id, count, notes, user_id=current_user.id)
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
            bottles = self.agent.batch_add(text, default_fridge, user_id=current_user.id)
            self._send_json({"success": True, "count": len(bottles), "bottles": [b.to_dict() for b in bottles]})

        elif path == "/api/clear":
            self.agent.db.clear_cellar(user_id=current_user.id)
            self._send_json({"success": True, "message": f"Cellar cleared for {current_user.name}"})

        elif path == "/api/enrich-all-ratings":
            from wine_agent.critic_ratings import get_public_critic_ratings
            bottles = self.agent.db.list_bottles(only_in_stock=False, user_id=current_user.id)
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
                        self.agent.db.update_bottle(b, user_id=current_user.id)
                        enriched_count += 1
            self._send_json({"success": True, "enriched_count": enriched_count})

        elif path == "/api/storage-locations":
            locs = payload.get("locations", [])
            updated = self.agent.db.set_storage_locations(user_id=current_user.id, locations=locs)
            self._send_json({"success": True, "locations": updated})

        elif path == "/api/storage-locations/add":
            name = payload.get("name", "").strip()
            if not name:
                self._send_json({"error": "name is required"}, status=400)
                return
            updated = self.agent.db.add_storage_location(user_id=current_user.id, name=name)
            self._send_json({"success": True, "locations": updated})

        elif path == "/api/storage-locations/delete":
            name = payload.get("name", "").strip()
            reassign_to = payload.get("reassign_to", "Unassigned").strip()
            if not name:
                self._send_json({"error": "name is required"}, status=400)
                return
            updated = self.agent.db.delete_storage_location(user_id=current_user.id, name=name, reassign_to=reassign_to)
            self._send_json({"success": True, "locations": updated})

        elif path == "/api/storage-locations/rename":
            old_name = payload.get("old_name", "").strip()
            new_name = payload.get("new_name", "").strip()
            if not old_name or not new_name:
                self._send_json({"error": "old_name and new_name are required"}, status=400)
                return
            updated = self.agent.db.rename_storage_location(user_id=current_user.id, old_name=old_name, new_name=new_name)
            self._send_json({"success": True, "locations": updated})

        elif path == "/api/rename-location":
            old_loc = payload.get("old_location", "").strip()
            new_loc = payload.get("new_location", "").strip()
            if not old_loc or not new_loc:
                self._send_json({"error": "old_location and new_location are required"}, status=400)
                return
            self.agent.db.rename_storage_location(user_id=current_user.id, old_name=old_loc, new_name=new_loc)
            count = self.agent.db.rename_location(old_loc, new_loc, user_id=current_user.id)
            self._send_json({"success": True, "updated_count": count})

        elif path == "/api/clear-location":
            loc = payload.get("location", "").strip()
            if not loc:
                self._send_json({"error": "location is required"}, status=400)
                return
            count = self.agent.db.clear_location(loc, user_id=current_user.id)
            self._send_json({"success": True, "deleted_count": count})

        elif path in ("/api/delete", "/api/remove"):
            b_id = payload.get("bottle_id") or payload.get("id")
            if not b_id:
                self._send_json({"error": "bottle_id is required"}, status=400)
                return
            success = self.agent.db.delete_bottle(int(b_id), user_id=current_user.id)
            self._send_json({"success": success})

        elif path == "/api/seed":
            self.agent.db.seed_sample_collection(user_id=current_user.id)
            self._send_json({"success": True, "message": f"Seeded collection for {current_user.name}"})

        elif path == "/api/import-csv":
            csv_content = payload.get("csv_text", "")
            mode = payload.get("mode", "merge")
            if not csv_content:
                self._send_json({"error": "csv_text is required"}, status=400)
                return
            if mode == "replace":
                self.agent.db.clear_cellar(user_id=current_user.id)
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
                    personal_notes=notes,
                    user_id=current_user.id
                )
                b_id = self.agent.db.add_bottle(b, user_id=current_user.id)
                saved = self.agent.db.get_bottle(b_id, user_id=current_user.id)
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
            bottles = self.agent.db.list_bottles(only_in_stock=True, user_id=current_user.id)
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

    # Ensure DB has at least sample data for User 1 if completely empty
    if not agent.db.list_bottles(only_in_stock=False, user_id=1):
        agent.db.seed_sample_collection(user_id=1)

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
