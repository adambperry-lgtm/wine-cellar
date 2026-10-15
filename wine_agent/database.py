"""SQLite Cellar Database and Inventory Management."""

import sqlite3
import json
import csv
import os
import re
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from wine_agent.models import WineBottle, WineType, BottleFormat, DrinkingStatus, DrinkingWindow, ConsumptionRecord
from wine_agent.drinking_window import calculate_drinking_window, CURRENT_YEAR


def get_default_db_path() -> str:
    """Determines the database path with support for environment variables and cloud deployments (e.g. Railway)."""
    # 1. Custom path via environment variable (e.g. Railway volume mount /data/cellar.db)
    if os.environ.get("CELLAR_DB_PATH"):
        return os.environ["CELLAR_DB_PATH"]

    # 2. Local project root cellar.db if present
    project_root = Path(__file__).resolve().parent.parent
    local_db = project_root / "cellar.db"
    if local_db.exists():
        return str(local_db)

    # 3. Standard user scratch location
    scratch_db = Path(os.path.expanduser("~/.gemini/antigravity/scratch/wine_cellar_agent/cellar.db"))
    if scratch_db.exists():
        return str(scratch_db)

    # 4. Fallback to project root cellar.db
    return str(local_db)


DEFAULT_DB_PATH = get_default_db_path()


class WineDatabase:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_default_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bottles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    producer TEXT NOT NULL,
                    wine_name TEXT,
                    vintage INTEGER,
                    varietal TEXT,
                    region TEXT,
                    sub_region TEXT,
                    country TEXT,
                    wine_type TEXT NOT NULL,
                    format TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    location_rack TEXT,
                    location_bin TEXT,
                    purchase_date TEXT,
                    purchase_price REAL,
                    market_value REAL,
                    critic_score INTEGER,
                    user_rating REAL,
                    personal_notes TEXT,
                    food_pairings TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consumption_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bottle_id INTEGER NOT NULL,
                    wine_display_name TEXT NOT NULL,
                    date_opened TEXT NOT NULL,
                    rating REAL,
                    tasting_notes TEXT,
                    pairing_notes TEXT,
                    bottles_consumed INTEGER NOT NULL DEFAULT 1,
                    aging_curve_stage TEXT
                )
            """)
            try:
                conn.execute("ALTER TABLE consumption_log ADD COLUMN aging_curve_stage TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE consumption_log ADD COLUMN action_type TEXT DEFAULT 'opened'")
            except Exception:
                pass
            for col in ["window_start", "peak_start", "peak_end", "window_end"]:
                try:
                    conn.execute(f"ALTER TABLE bottles ADD COLUMN {col} INTEGER")
                except Exception:
                    pass
            try:
                conn.execute("ALTER TABLE bottles ADD COLUMN critic_reviews TEXT")
            except Exception:
                pass
            conn.commit()

    def add_bottle(self, bottle: WineBottle) -> int:
        """Adds a wine bottle to inventory and returns its ID."""
        pairings_json = json.dumps(bottle.food_pairings if bottle.food_pairings else [])
        wine_type_val = bottle.wine_type.value if isinstance(bottle.wine_type, WineType) else bottle.wine_type
        format_val = bottle.format.value if isinstance(bottle.format, BottleFormat) else bottle.format
        reviews_json = json.dumps(bottle.critic_reviews if bottle.critic_reviews else [])

        dw = bottle.drinking_window
        w_start = dw.window_start if dw else None
        p_start = dw.peak_start if dw else None
        p_end = dw.peak_end if dw else None
        w_end = dw.window_end if dw else None

        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO bottles (
                    producer, wine_name, vintage, varietal, region, sub_region,
                    country, wine_type, format, quantity, location_rack, location_bin,
                    purchase_date, purchase_price, market_value, critic_score,
                    user_rating, personal_notes, food_pairings, created_at,
                    window_start, peak_start, peak_end, window_end, critic_reviews
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bottle.producer, bottle.wine_name, bottle.vintage, bottle.varietal,
                bottle.region, bottle.sub_region, bottle.country, wine_type_val,
                format_val, bottle.quantity, bottle.location_rack, bottle.location_bin,
                bottle.purchase_date, bottle.purchase_price, bottle.market_value,
                bottle.critic_score, bottle.user_rating, bottle.personal_notes,
                pairings_json, bottle.created_at,
                w_start, p_start, p_end, w_end, reviews_json
            ))
            conn.commit()
            return cursor.lastrowid

    def update_bottle(self, bottle: WineBottle) -> bool:
        """Updates an existing bottle in the inventory."""
        if not bottle.id:
            return False
        pairings_json = json.dumps(bottle.food_pairings if bottle.food_pairings else [])
        wine_type_val = bottle.wine_type.value if isinstance(bottle.wine_type, WineType) else bottle.wine_type
        format_val = bottle.format.value if isinstance(bottle.format, BottleFormat) else bottle.format
        reviews_json = json.dumps(bottle.critic_reviews if bottle.critic_reviews else [])

        with self._get_conn() as conn:
            cursor = conn.execute("""
                UPDATE bottles SET
                    producer = ?, wine_name = ?, vintage = ?, varietal = ?,
                    region = ?, sub_region = ?, country = ?, wine_type = ?,
                    format = ?, quantity = ?, location_rack = ?, location_bin = ?,
                    purchase_date = ?, purchase_price = ?, market_value = ?,
                    critic_score = ?, user_rating = ?, personal_notes = ?,
                    food_pairings = ?, critic_reviews = ?
                WHERE id = ?
            """, (
                bottle.producer, bottle.wine_name, bottle.vintage, bottle.varietal,
                bottle.region, bottle.sub_region, bottle.country, wine_type_val,
                format_val, bottle.quantity, bottle.location_rack, bottle.location_bin,
                bottle.purchase_date, bottle.purchase_price, bottle.market_value,
                bottle.critic_score, bottle.user_rating, bottle.personal_notes,
                pairings_json, reviews_json, bottle.id
            ))
            conn.commit()
            return cursor.rowcount > 0

    def delete_bottle(self, bottle_id: int) -> bool:
        """Deletes a bottle record."""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM bottles WHERE id = ?", (bottle_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_cellar(self):
        """Removes all bottles and logs to start fresh."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM bottles")
            conn.execute("DELETE FROM consumption_log")
            conn.commit()

    def rename_location(self, old_location: str, new_location: str) -> int:
        """Renames a storage location/rack across all bottles."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE bottles SET location_rack = ? WHERE LOWER(location_rack) = LOWER(?)",
                (new_location, old_location)
            )
            conn.commit()
            return cursor.rowcount

    def clear_location(self, location: str) -> int:
        """Deletes all bottles in a specific storage location."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM bottles WHERE LOWER(location_rack) = LOWER(?)",
                (location,)
            )
            conn.commit()
            return cursor.rowcount

    def get_bottle(self, bottle_id: int) -> Optional[WineBottle]:
        """Retrieves a single bottle by ID with computed drinking window."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM bottles WHERE id = ?", (bottle_id,)).fetchone()
            if not row:
                return None
            return self._row_to_bottle(row)

    def list_bottles(
        self,
        status_filter: Optional[DrinkingStatus] = None,
        wine_type_filter: Optional[str] = None,
        search_query: Optional[str] = None,
        only_in_stock: bool = True
    ) -> List[WineBottle]:
        """Lists bottles with optional filtering and computed drinking windows."""
        sql = "SELECT * FROM bottles WHERE 1=1"
        params = []

        if only_in_stock:
            sql += " AND quantity > 0"

        if wine_type_filter:
            sql += " AND LOWER(wine_type) = LOWER(?)"
            params.append(wine_type_filter)

        if search_query:
            term = f"%{search_query.strip()}%"
            sql += " AND (producer LIKE ? OR wine_name LIKE ? OR varietal LIKE ? OR region LIKE ? OR location_rack LIKE ? OR location_bin LIKE ?)"
            params.extend([term, term, term, term, term, term])

        sql += " ORDER BY vintage ASC, producer ASC"

        bottles = []
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            for r in rows:
                b = self._row_to_bottle(r)
                if status_filter and b.drinking_window and b.drinking_window.status != status_filter:
                    continue
                bottles.append(b)

        return bottles

    def consume_bottle(
        self,
        bottle_id: int,
        count: int = 1,
        rating: Optional[float] = None,
        tasting_notes: str = "",
        pairing_notes: str = "",
        aging_curve_stage: Optional[str] = None
    ) -> Optional[ConsumptionRecord]:
        """Marks bottle(s) as consumed, decrements inventory, and logs tasting notes and aging curve status."""
        bottle = self.get_bottle(bottle_id)
        if not bottle:
            return None

        dw = bottle.drinking_window
        if not aging_curve_stage:
            if dw:
                aging_curve_stage = f"{dw.status.value} (Peak: {dw.peak_start}–{dw.peak_end})"
            else:
                aging_curve_stage = "Standard Aging Window"

        new_qty = max(0, bottle.quantity - count)
        with self._get_conn() as conn:
            if rating is not None:
                conn.execute("UPDATE bottles SET quantity = ?, user_rating = ? WHERE id = ?", (new_qty, rating, bottle_id))
            else:
                conn.execute("UPDATE bottles SET quantity = ? WHERE id = ?", (new_qty, bottle_id))
            cursor = conn.execute("""
                INSERT INTO consumption_log (
                    bottle_id, wine_display_name, date_opened, rating,
                    tasting_notes, pairing_notes, bottles_consumed, aging_curve_stage, action_type
                ) VALUES (?, ?, date('now'), ?, ?, ?, ?, ?, 'opened')
            """, (
                bottle_id, bottle.display_name, rating,
                tasting_notes, pairing_notes, count, aging_curve_stage
            ))
            conn.commit()
            log_id = cursor.lastrowid

        return ConsumptionRecord(
            id=log_id,
            bottle_id=bottle_id,
            wine_display_name=bottle.display_name,
            rating=rating,
            tasting_notes=tasting_notes,
            pairing_notes=pairing_notes,
            bottles_consumed=count,
            aging_curve_stage=aging_curve_stage,
            action_type="opened"
        )

    def gift_bottle(
        self,
        bottle_id: int,
        count: int = 1,
        situation_notes: str = ""
    ) -> Optional[ConsumptionRecord]:
        """Marks bottle(s) as gifted, decrements inventory, and logs gift situation notes without rating or tasting impressions."""
        bottle = self.get_bottle(bottle_id)
        if not bottle:
            return None

        dw = bottle.drinking_window
        stage = f"{dw.status.value} (Peak: {dw.peak_start}–{dw.peak_end})" if dw else "Standard Aging Window"

        new_qty = max(0, bottle.quantity - count)
        with self._get_conn() as conn:
            conn.execute("UPDATE bottles SET quantity = ? WHERE id = ?", (new_qty, bottle_id))
            cursor = conn.execute("""
                INSERT INTO consumption_log (
                    bottle_id, wine_display_name, date_opened, rating,
                    tasting_notes, pairing_notes, bottles_consumed, aging_curve_stage, action_type
                ) VALUES (?, ?, date('now'), NULL, ?, '', ?, ?, 'gift')
            """, (
                bottle_id, bottle.display_name,
                situation_notes, count, stage
            ))
            conn.commit()
            log_id = cursor.lastrowid

        return ConsumptionRecord(
            id=log_id,
            bottle_id=bottle_id,
            wine_display_name=bottle.display_name,
            rating=None,
            tasting_notes=situation_notes,
            pairing_notes="",
            bottles_consumed=count,
            aging_curve_stage=stage,
            action_type="gift"
        )

    def get_consumption_history(self) -> List[ConsumptionRecord]:
        """Returns recent bottle consumption history."""
        records = []
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM consumption_log ORDER BY id DESC").fetchall()
            for r in rows:
                stage = ""
                try:
                    stage = r["aging_curve_stage"] or ""
                except (IndexError, KeyError):
                    stage = ""
                action = "opened"
                try:
                    action = r["action_type"] or "opened"
                except (IndexError, KeyError):
                    action = "opened"
                records.append(ConsumptionRecord(
                    id=r["id"],
                    bottle_id=r["bottle_id"],
                    wine_display_name=r["wine_display_name"],
                    date_opened=r["date_opened"],
                    rating=r["rating"],
                    tasting_notes=r["tasting_notes"] or "",
                    pairing_notes=r["pairing_notes"] or "",
                    bottles_consumed=r["bottles_consumed"],
                    aging_curve_stage=stage,
                    action_type=action
                ))
        return records

    def get_cellar_stats(self) -> Dict[str, Any]:
        """Computes comprehensive cellar metrics and drinking readiness."""
        bottles = self.list_bottles(only_in_stock=True)
        total_bottles = sum(b.quantity for b in bottles)
        total_unique = len(bottles)
        total_value = sum((b.purchase_price or b.market_value or 0.0) * b.quantity for b in bottles)

        status_counts = {
            DrinkingStatus.TOO_YOUNG.value: 0,
            DrinkingStatus.EARLY_WINDOW.value: 0,
            DrinkingStatus.PEAK.value: 0,
            DrinkingStatus.LATE_PEAK.value: 0,
            DrinkingStatus.PAST_PEAK.value: 0,
        }
        type_counts = {}
        region_counts = {}

        for b in bottles:
            if b.drinking_window:
                st = b.drinking_window.status.value
                status_counts[st] = status_counts.get(st, 0) + b.quantity

            wt = b.wine_type.value if isinstance(b.wine_type, WineType) else b.wine_type
            type_counts[wt] = type_counts.get(wt, 0) + b.quantity

            reg = b.region or "Unknown"
            region_counts[reg] = region_counts.get(reg, 0) + b.quantity

        return {
            "total_bottles": total_bottles,
            "total_unique_wines": total_unique,
            "estimated_value": round(total_value, 2),
            "status_distribution": status_counts,
            "type_distribution": type_counts,
            "top_regions": sorted(region_counts.items(), key=lambda x: x[1], reverse=True)[:6],
            "ready_to_drink_now": status_counts.get(DrinkingStatus.PEAK.value, 0),
            "drink_urgently": status_counts.get(DrinkingStatus.LATE_PEAK.value, 0) + status_counts.get(DrinkingStatus.PAST_PEAK.value, 0),
            "hold_for_future": status_counts.get(DrinkingStatus.TOO_YOUNG.value, 0)
        }

    def _row_to_bottle(self, r: sqlite3.Row) -> WineBottle:
        try:
            pairings = json.loads(r["food_pairings"]) if r["food_pairings"] else []
        except Exception:
            pairings = []

        try:
            w_type = WineType(r["wine_type"])
        except Exception:
            w_type = WineType.RED

        try:
            b_format = BottleFormat(r["format"])
        except Exception:
            b_format = BottleFormat.STANDARD

        bottle = WineBottle(
            id=r["id"],
            producer=r["producer"],
            wine_name=r["wine_name"] or "",
            vintage=r["vintage"],
            varietal=r["varietal"] or "",
            region=r["region"] or "",
            sub_region=r["sub_region"] or "",
            country=r["country"] or "",
            wine_type=w_type,
            format=b_format,
            quantity=r["quantity"],
            location_rack=r["location_rack"] or "",
            location_bin=r["location_bin"] or "",
            purchase_date=r["purchase_date"],
            purchase_price=r["purchase_price"],
            market_value=r["market_value"],
            critic_score=r["critic_score"],
            user_rating=r["user_rating"],
            personal_notes=r["personal_notes"] or "",
            food_pairings=pairings,
            created_at=r["created_at"]
        )

        has_custom_dw = False
        try:
            p_start = r["peak_start"]
            p_end = r["peak_end"]
            if p_start and p_end:
                w_start = r["window_start"] or (p_start - 2)
                w_end = r["window_end"] or (p_end + 5)
                st = DrinkingStatus.PEAK
                if CURRENT_YEAR < p_start:
                    st = DrinkingStatus.EARLY_WINDOW if (p_start - CURRENT_YEAR <= 2) else DrinkingStatus.TOO_YOUNG
                elif CURRENT_YEAR <= p_end:
                    st = DrinkingStatus.PEAK
                elif CURRENT_YEAR <= w_end:
                    st = DrinkingStatus.LATE_PEAK
                else:
                    st = DrinkingStatus.PAST_PEAK
                progress = max(0.0, min(100.0, round(((CURRENT_YEAR - w_start) / max(1, w_end - w_start)) * 100.0, 1)))
                bottle.drinking_window = DrinkingWindow(
                    window_start=w_start,
                    peak_start=p_start,
                    peak_end=p_end,
                    window_end=w_end,
                    status=st,
                    progress_pct=progress,
                    decant_hours=1.5 if w_type == WineType.RED else 0.5,
                    serving_temp_f=64 if w_type == WineType.RED else 48,
                    serving_temp_c=18 if w_type == WineType.RED else 9,
                    aging_tier=f"{bottle.varietal or 'Cellar'} Window",
                    rationale=f"Imported / stored window (Peak: {p_start}–{p_end})."
                )
                has_custom_dw = True
        except Exception:
            pass

        if not has_custom_dw:
            bottle.drinking_window = calculate_drinking_window(bottle, CURRENT_YEAR)

        critic_revs = []
        try:
            if "critic_reviews" in r.keys() and r["critic_reviews"]:
                critic_revs = json.loads(r["critic_reviews"])
        except Exception:
            critic_revs = []

        if not critic_revs:
            from wine_agent.critic_ratings import get_public_critic_ratings
            critic_revs = get_public_critic_ratings(bottle.producer, bottle.wine_name, bottle.vintage, bottle.varietal)

        bottle.critic_reviews = critic_revs
        if not bottle.critic_score and critic_revs:
            scores = [x["score"] for x in critic_revs if isinstance(x.get("score"), (int, float))]
            if scores:
                bottle.critic_score = max(scores)

        return bottle

    def export_csv(self, file_path: str):
        """Exports the entire cellar to a CSV spreadsheet."""
        bottles = self.list_bottles(only_in_stock=False)
        fieldnames = [
            "id", "producer", "wine_name", "vintage", "varietal", "region", "sub_region", "country",
            "wine_type", "format", "quantity", "location_rack", "location_bin",
            "purchase_price", "critic_score", "user_rating", "window_start", "peak_start", "peak_end",
            "window_end", "drinking_status", "decant_hours", "serving_temp_f", "notes"
        ]
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
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

    def import_csv(self, file_path: str) -> int:
        """Imports bottles from standard or CellarTracker CSV formats with full column mapping."""
        count = 0
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for raw_row in reader:
                # Normalize keys by removing whitespace, underscores, hyphens, and lowercasing
                row = {}
                for k, v in raw_row.items():
                    if k is not None:
                        clean_k = re.sub(r'[\s_\-]+', '', k.strip().lower())
                        row[clean_k] = (v or "").strip()

                def get_field(*aliases):
                    for a in aliases:
                        clean_a = re.sub(r'[\s_\-]+', '', a.lower())
                        if clean_a in row and row[clean_a]:
                            return row[clean_a]
                    return ""

                producer = get_field("producer", "winery", "maker", "brand", "estate") or "Unknown Producer"
                wine_name = get_field("wine_name", "wine", "name", "cuvee", "designation", "label")

                # Vintage extraction (supports '2018', 'NV', or dates)
                vint_raw = get_field("vintage", "year", "vint")
                vint_match = re.search(r'\b(19\d\d|20\d\d)\b', vint_raw)
                vintage = int(vint_match.group(1)) if vint_match else None

                varietal = get_field("varietal", "mastervarietal", "variety", "grape", "blend")
                region = get_field("region", "appellation", "area")
                sub_region = get_field("sub_region", "subregion", "vineyard", "ava")
                country = get_field("country") or "United States"

                # Bottle format / size normalization
                format_raw = get_field("format", "size", "bottlesize").lower()
                b_format = BottleFormat.STANDARD
                if "1.5" in format_raw or "1500" in format_raw or "magnum" in format_raw:
                    b_format = BottleFormat.MAGNUM
                elif "375" in format_raw or "half" in format_raw or "demi" in format_raw:
                    b_format = BottleFormat.HALF
                elif "3.0" in format_raw or "3l" in format_raw or "double" in format_raw:
                    b_format = BottleFormat.DOUBLE_MAGNUM
                elif "6.0" in format_raw or "6l" in format_raw or "imperial" in format_raw:
                    b_format = BottleFormat.IMPERIAL

                # Wine type / color normalization
                type_raw = get_field("wine_type", "type", "color").lower()
                w_type = WineType.RED
                if any(x in type_raw for x in ["white", "chardonnay", "sauvignon blanc", "riesling", "pinot grigio"]):
                    w_type = WineType.WHITE
                elif any(x in type_raw for x in ["sparkling", "champagne", "prosecco", "cava"]):
                    w_type = WineType.SPARKLING
                elif any(x in type_raw for x in ["rose", "rosé", "pink"]):
                    w_type = WineType.ROSE
                elif any(x in type_raw for x in ["dessert", "sweet", "sauternes", "port", "tokaji"]):
                    w_type = WineType.DESSERT
                elif "fortified" in type_raw:
                    w_type = WineType.FORTIFIED

                # Quantity (CellarTracker individual bottle rows have 1 or blank; skip 0 consumed rows)
                qty_raw = get_field("quantity", "qty", "count", "bottles", "bottlecount")
                if qty_raw:
                    try:
                        digits = re.sub(r'[^\d]', '', qty_raw)
                        qty = int(digits) if digits else 1
                    except Exception:
                        qty = 1
                else:
                    qty = 1

                if qty <= 0:
                    continue  # Skip consumed or pending 0-bottle records

                # Storage location & bin
                rack = get_field("location_rack", "location", "fridge", "rack", "storage", "storagelocation") or "Basement Fridge"
                bin_loc = get_field("location_bin", "bin", "shelf", "row", "binlocation")

                # Purchase price / valuation (strip currency signs $, €, £)
                price_raw = get_field("purchase_price", "price", "cost", "valuation", "paid", "value")
                price = None
                if price_raw:
                    clean_p = re.sub(r'[^0-9.]', '', price_raw)
                    try:
                        price = float(clean_p)
                    except Exception:
                        price = None

                # Scores & ratings (CT community score, critic score, user stars)
                critic_raw = get_field("critic_score", "score", "ct", "communityscore", "points")
                critic_score = None
                if critic_raw:
                    try:
                        critic_score = int(float(re.sub(r'[^0-9.]', '', critic_raw)))
                    except Exception:
                        critic_score = None

                rating_raw = get_field("user_rating", "rating", "myrating", "userscore", "stars", "mystars")
                user_rating = None
                if rating_raw:
                    try:
                        user_rating = float(re.sub(r'[^0-9.]', '', rating_raw))
                    except Exception:
                        user_rating = None

                # Notes & CellarTracker identifiers (iWine, Barcode)
                notes_parts = []
                base_notes = get_field("notes", "mynotes", "privatenotes", "tastingnotes", "comments", "personalnotes")
                if base_notes:
                    notes_parts.append(base_notes)

                iwine = get_field("iwine", "iwineid", "wineid")
                if iwine and f"iWine: {iwine}" not in base_notes:
                    notes_parts.append(f"[CT iWine: {iwine}]")

                barcode = get_field("barcode")
                if barcode and f"Barcode: {barcode}" not in base_notes:
                    notes_parts.append(f"[Barcode: {barcode}]")

                personal_notes = " | ".join(notes_parts)

                bottle = WineBottle(
                    producer=producer,
                    wine_name=wine_name,
                    vintage=vintage,
                    varietal=varietal,
                    region=region,
                    sub_region=sub_region,
                    country=country,
                    wine_type=w_type,
                    format=b_format,
                    quantity=qty,
                    location_rack=rack,
                    location_bin=bin_loc,
                    purchase_price=price,
                    critic_score=critic_score,
                    user_rating=user_rating,
                    personal_notes=personal_notes
                )

                # Drinking window if provided by CellarTracker (BeginConsume / EndConsume)
                begin_raw = get_field("beginconsume", "peakstart", "windowstart", "drinkfrom", "consume")
                end_raw = get_field("endconsume", "peakend", "windowend", "drinkby")
                if begin_raw or end_raw:
                    b_match = re.search(r'\b(19\d\d|20\d\d)\b', begin_raw)
                    e_match = re.search(r'\b(19\d\d|20\d\d)\b', end_raw)
                    if b_match and e_match:
                        p_start = int(b_match.group(1))
                        p_end = int(e_match.group(1))
                        w_start = p_start - 2
                        w_end = p_end + 5
                        st = DrinkingStatus.PEAK
                        if CURRENT_YEAR < p_start:
                            st = DrinkingStatus.EARLY_WINDOW if (p_start - CURRENT_YEAR <= 2) else DrinkingStatus.TOO_YOUNG
                        elif CURRENT_YEAR <= p_end:
                            st = DrinkingStatus.PEAK
                        elif CURRENT_YEAR <= w_end:
                            st = DrinkingStatus.LATE_PEAK
                        else:
                            st = DrinkingStatus.PAST_PEAK

                        progress = max(0.0, min(100.0, round(((CURRENT_YEAR - w_start) / max(1, w_end - w_start)) * 100.0, 1)))
                        bottle.drinking_window = DrinkingWindow(
                            window_start=w_start,
                            peak_start=p_start,
                            peak_end=p_end,
                            window_end=w_end,
                            status=st,
                            progress_pct=progress,
                            decant_hours=1.5 if w_type == WineType.RED else 0.5,
                            serving_temp_f=64 if w_type == WineType.RED else 48,
                            serving_temp_c=18 if w_type == WineType.RED else 9,
                            aging_tier=f"{varietal or 'CellarTracker'} Window",
                            rationale=f"Imported from CellarTracker window (Peak: {p_start}–{p_end})."
                        )

                self.add_bottle(bottle)
                count += 1
        return count

    def seed_sample_collection(self):
        """Populates cellar with an authentic, prestigious sommelier collection."""
        samples = [
            # 1. PEAK: Legendary 2010 Bordeaux
            WineBottle(
                producer="Château Pontet-Canet",
                wine_name="Grand Cru Classé",
                vintage=2010,
                varietal="Cabernet Sauvignon, Merlot",
                region="Bordeaux",
                sub_region="Pauillac",
                country="France",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=3,
                location_rack="Rack A",
                location_bin="Row 1, Bin 1-3",
                purchase_date="2014-05-12",
                purchase_price=195.0,
                market_value=320.0,
                critic_score=100,
                personal_notes="Purchased en primeur. Iconic 100-pt vintage showing graphite, cassis, and seamlessly melted tannins.",
                food_pairings=["Prime Ribeye", "Roast Lamb with Rosemary", "Aged Comté"]
            ),
            # 2. PEAK: Mature Brunello
            WineBottle(
                producer="Biondi-Santi",
                wine_name="Tenuta Greppo Brunello di Montalcino Annata",
                vintage=2012,
                varietal="Sangiovese Grosso",
                region="Tuscany",
                sub_region="Montalcino",
                country="Italy",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=2,
                location_rack="Rack A",
                location_bin="Row 2, Bin 4-5",
                purchase_date="2018-09-20",
                purchase_price=175.0,
                market_value=240.0,
                critic_score=95,
                personal_notes="High acid, aristocratic Sangiovese. Sour cherry, crushed rose petal, dried orange peel.",
                food_pairings=["Bistecca alla Fiorentina", "Wild Boar Pappardelle", "Truffle Risotto"]
            ),
            # 3. PEAK: Mature Northern Rhône Syrah
            WineBottle(
                producer="E. Guigal",
                wine_name="Château d'Ampuis Côte-Rôtie",
                vintage=2011,
                varietal="Syrah, Viognier",
                region="Rhône Valley",
                sub_region="Côte-Rôtie",
                country="France",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=2,
                location_rack="Rack A",
                location_bin="Row 3, Bin 1-2",
                purchase_date="2016-03-10",
                purchase_price=140.0,
                market_value=190.0,
                critic_score=94,
                personal_notes="Deep smoky bacon fat, violets, and black olive tapenade. Perfectly mature now.",
                food_pairings=["Roast Duck Breast", "Braised Venison", "Grilled Lamb Chops"]
            ),
            # 4. LATE PEAK (DRINK SOON): 2004 Rioja Gran Reserva
            WineBottle(
                producer="La Rioja Alta",
                wine_name="Gran Reserva 904",
                vintage=2004,
                varietal="Tempranillo, Graciano",
                region="Rioja",
                sub_region="Rioja Alta",
                country="Spain",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=1,
                location_rack="Rack B",
                location_bin="Row 1, Bin 6 (Drink Soon)",
                purchase_date="2015-11-04",
                purchase_price=75.0,
                market_value=150.0,
                critic_score=96,
                personal_notes="Silky American oak vanilla, dried dill, cigar box, and leather. In its glorious late maturity.",
                food_pairings=["Suckling Pig", "Mushroom Risotto", "Manchego Cheese"]
            ),
            # 5. LATE PEAK (DRINK SOON): 2013 Chablis 1er Cru
            WineBottle(
                producer="Domaine François Raveneau",
                wine_name="Chablis 1er Cru Montée de Tonnerre",
                vintage=2013,
                varietal="Chardonnay",
                region="Burgundy",
                sub_region="Chablis",
                country="France",
                wine_type=WineType.WHITE,
                format=BottleFormat.STANDARD,
                quantity=1,
                location_rack="Rack B",
                location_bin="Row 2, Bin 1",
                purchase_date="2017-04-18",
                purchase_price=160.0,
                market_value=350.0,
                critic_score=95,
                personal_notes="Oyster shell, wet stone, lemon oil, flint. Ready to drink to catch precision before oxidation.",
                food_pairings=["Fresh Oysters", "Pan-Seared Scallops", "Poached Turbot"]
            ),
            # 6. TOO YOUNG (HOLD): 2019 Ridge Monte Bello
            WineBottle(
                producer="Ridge Vineyards",
                wine_name="Monte Bello Cabernet Sauvignon",
                vintage=2019,
                varietal="Cabernet Sauvignon Blend",
                region="California",
                sub_region="Santa Cruz Mountains",
                country="USA",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=4,
                location_rack="Rack C",
                location_bin="Deep Cellar 1-4",
                purchase_date="2022-10-01",
                purchase_price=225.0,
                market_value=275.0,
                critic_score=98,
                personal_notes="Monumental structure, mountain acidity, firm mineral core. Needs until 2031 to reveal its magic.",
                food_pairings=["Cellar Hold - Future Prime Rib Roast"]
            ),
            # 7. TOO YOUNG (HOLD): 2016 Giacomo Conterno Barolo
            WineBottle(
                producer="Giacomo Conterno",
                wine_name="Barolo Francia",
                vintage=2016,
                varietal="Nebbiolo",
                region="Piedmont",
                sub_region="Serralunga d'Alba",
                country="Italy",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=2,
                location_rack="Rack C",
                location_bin="Deep Cellar 5-6",
                purchase_date="2021-06-15",
                purchase_price=280.0,
                market_value=420.0,
                critic_score=99,
                personal_notes="Legendary 2016 vintage. Fierce Serralunga tannins, immense depth. Do not open before 2030.",
                food_pairings=["Cellar Hold - Future Braised Beef Cheek in Barolo"]
            ),
            # 8. TOO YOUNG (HOLD): 2020 Domaine Armand Rousseau
            WineBottle(
                producer="Domaine Armand Rousseau",
                wine_name="Gevrey-Chambertin 1er Cru Clos Saint-Jacques",
                vintage=2020,
                varietal="Pinot Noir",
                region="Burgundy",
                sub_region="Côte de Nuits",
                country="France",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=1,
                location_rack="Rack C",
                location_bin="Lockbox 1",
                purchase_date="2023-02-14",
                purchase_price=850.0,
                market_value=1200.0,
                critic_score=98,
                personal_notes="Grand Cru quality in all but name. Intense red cherries, incense, mineral backbone. Sleep until 2028-2040.",
                food_pairings=["Cellar Hold - Future Roasted Squab / Chanterelles"]
            ),
            # 9. APPROACHING PEAK: 2016 Dominus Estate
            WineBottle(
                producer="Dominus Estate",
                wine_name="Christian Moueix Napa Valley",
                vintage=2016,
                varietal="Cabernet Sauvignon, Cabernet Franc, Petit Verdot",
                region="California",
                sub_region="Napa Valley / Yountville",
                country="USA",
                wine_type=WineType.RED,
                format=BottleFormat.STANDARD,
                quantity=2,
                location_rack="Rack A",
                location_bin="Row 4, Bin 1-2",
                purchase_date="2019-11-20",
                purchase_price=260.0,
                market_value=360.0,
                critic_score=100,
                personal_notes="Christian Moueix masterpiece. Bordeaux elegance meets Napa power. Approaching prime; 2.5hr decant recommended if opened now.",
                food_pairings=["Dry-Aged Tomahawk Steak", "Roasted Venison Loin"]
            ),
            # 10. PEAK: 2012 Dom Pérignon Vintage
            WineBottle(
                producer="Dom Pérignon",
                wine_name="Vintage Brut Champagne",
                vintage=2012,
                varietal="Chardonnay, Pinot Noir",
                region="Champagne",
                sub_region="Épernay",
                country="France",
                wine_type=WineType.SPARKLING,
                format=BottleFormat.STANDARD,
                quantity=3,
                location_rack="Sparkling Fridge",
                location_bin="Shelf 1",
                purchase_date="2021-12-05",
                purchase_price=220.0,
                market_value=270.0,
                critic_score=97,
                personal_notes="Toasted brioche, smoky salinity, apricot, and razor precision. At the apex of its vintage window.",
                food_pairings=["Caviar on Blinis", "Butter-Poached Lobster", "Fried Chicken"]
            ),
            # 11. PEAK: 2015 Egon Müller Scharzhofberger Kabinett
            WineBottle(
                producer="Egon Müller",
                wine_name="Scharzhofberger Riesling Kabinett",
                vintage=2015,
                varietal="Riesling",
                region="Mosel",
                sub_region="Saar",
                country="Germany",
                wine_type=WineType.WHITE,
                format=BottleFormat.STANDARD,
                quantity=2,
                location_rack="Rack B",
                location_bin="Row 3, Bin 3-4",
                purchase_date="2017-08-10",
                purchase_price=120.0,
                market_value=210.0,
                critic_score=96,
                personal_notes="Electrifying Saar acidity balancing residual sweetness. White peach, lime blossom, slate minerality.",
                food_pairings=["Spicy Thai Crab Salad", "Peking Duck", "Sushi & Sashimi"]
            ),
            # 12. PEAK: 2001 Château d'Yquem
            WineBottle(
                producer="Château d'Yquem",
                wine_name="Premier Cru Supérieur Sauternes",
                vintage=2001,
                varietal="Sémillon, Sauvignon Blanc",
                region="Bordeaux",
                sub_region="Sauternes",
                country="France",
                wine_type=WineType.DESSERT,
                format=BottleFormat.HALF,
                quantity=2,
                location_rack="Rack B",
                location_bin="Half Bottle Bin 1",
                purchase_date="2010-01-20",
                purchase_price=290.0,
                market_value=550.0,
                critic_score=100,
                personal_notes="The legendary 100-pt Yquem. Honeycomb, dried apricots, saffron, endless finish. Drinking immortal nectar.",
                food_pairings=["Pan-Seared Foie Gras", "Roquefort Blue Cheese", "Crème Brûlée"]
            )
        ]

        for s in samples:
            self.add_bottle(s)
