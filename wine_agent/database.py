"""SQLite Cellar Database and Inventory Management."""

import sqlite3
import json
import csv
import os
import re
import hashlib
import secrets
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from wine_agent.models import WineBottle, WineType, BottleFormat, DrinkingStatus, DrinkingWindow, ConsumptionRecord, UserProfile
from wine_agent.drinking_window import calculate_drinking_window, CURRENT_YEAR


def hash_password(password: str) -> str:
    """Hashes a password with PBKDF2-HMAC-SHA256 and a random 16-byte salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"pbkdf2:sha256:100000${salt}${key.hex()}"


def verify_password(stored_hash: str, password: str) -> bool:
    """Verifies a password against a PBKDF2-HMAC-SHA256 hash."""
    if not stored_hash or "$" not in stored_hash:
        return False
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False
        method, salt, key_hex = parts
        iters = int(method.split(":")[2])
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iters)
        return secrets.compare_digest(new_key.hex(), key_hex)
    except Exception:
        return False


def verify_google_id_token(id_token: str) -> Optional[Dict[str, Any]]:
    """Verifies Google ID token against Google OAuth endpoint or mock demo token."""
    if not id_token:
        return None
    token_str = str(id_token).strip()

    # Fast support for demo accounts / testing / offline environments
    if token_str.startswith("demo:") or token_str.startswith("mock:"):
        parts = token_str.split(":", 2)
        email = parts[1] if len(parts) > 1 else "sommelier.demo@gmail.com"
        name = parts[2] if len(parts) > 2 else email.split("@")[0].title()
        return {
            "sub": f"google_{hashlib.md5(email.encode()).hexdigest()[:12]}",
            "email": email,
            "name": name,
            "picture": f"https://api.dicebear.com/7.x/bottts/svg?seed={urllib.parse.quote(email)}"
        }

    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(token_str)}"
        req = urllib.request.Request(url, headers={"User-Agent": "WineCellarAgent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                if "email" in data:
                    return {
                        "sub": data.get("sub"),
                        "email": data.get("email"),
                        "name": data.get("name") or data.get("email", "").split("@")[0].title(),
                        "picture": data.get("picture", "")
                    }
    except Exception:
        pass
    return None


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
            # Users and Accounts
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT,
                    password_hash TEXT,
                    google_id TEXT UNIQUE,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            # Core Inventory and History
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

            # Migrations for user isolation & drinking window columns
            try:
                conn.execute("ALTER TABLE bottles ADD COLUMN user_id INTEGER DEFAULT 1")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE consumption_log ADD COLUMN user_id INTEGER DEFAULT 1")
            except Exception:
                pass
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

            # Ensure default User 1 (Cellar Master) exists for backward compatibility and authentic collection
            conn.execute("""
                INSERT OR IGNORE INTO users (id, email, name, password_hash, created_at, avatar_url)
                VALUES (1, 'cellarmaster@cellar.local', 'Cellar Master', ?, ?, 'https://api.dicebear.com/7.x/bottts/svg?seed=cellarmaster')
            """, (hash_password("cellarmaster"), datetime.now().isoformat()))

            # Ensure all pre-existing bottles belong to User 1
            conn.execute("UPDATE bottles SET user_id = 1 WHERE user_id IS NULL OR user_id = 0")
            conn.execute("UPDATE consumption_log SET user_id = 1 WHERE user_id IS NULL OR user_id = 0")

            conn.commit()

    # ==================== Multi-User & Auth Management ====================

    def create_user(
        self,
        email: str,
        password: Optional[str] = None,
        name: str = "",
        google_id: Optional[str] = None,
        avatar_url: str = ""
    ) -> Optional[UserProfile]:
        """Creates a new user profile with optional password or Google linking."""
        clean_email = email.strip().lower()
        if not clean_email:
            return None
        pw_hash = hash_password(password) if password else None
        clean_name = name.strip() or clean_email.split("@")[0].title()
        if not avatar_url:
            avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={urllib.parse.quote(clean_email)}"
        now = datetime.now().isoformat()
        try:
            with self._get_conn() as conn:
                cur = conn.execute("""
                    INSERT INTO users (email, name, password_hash, google_id, avatar_url, created_at, last_login)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (clean_email, clean_name, pw_hash, google_id, avatar_url, now, now))
                conn.commit()
                return UserProfile(
                    id=cur.lastrowid,
                    email=clean_email,
                    name=clean_name,
                    avatar_url=avatar_url,
                    created_at=now,
                    google_id=google_id
                )
        except sqlite3.IntegrityError:
            return None

    def authenticate_user(self, email: str, password: str) -> Optional[UserProfile]:
        """Authenticates user with email and password."""
        clean_email = email.strip().lower()
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (clean_email,)).fetchone()
            if not row or not row["password_hash"]:
                return None
            if verify_password(row["password_hash"], password):
                conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (row["id"],))
                conn.commit()
                return self._row_to_user(row)
        return None

    def authenticate_or_create_google_user(self, id_token: str) -> Optional[UserProfile]:
        """Authenticates a user via verified Google ID token, creating an account if first time."""
        info = verify_google_id_token(id_token)
        if not info:
            return None
        sub = info["sub"]
        email = info["email"].strip().lower()
        name = info.get("name") or email.split("@")[0].title()
        picture = info.get("picture") or f"https://api.dicebear.com/7.x/bottts/svg?seed={urllib.parse.quote(email)}"

        with self._get_conn() as conn:
            # Check by Google ID
            row = conn.execute("SELECT * FROM users WHERE google_id = ?", (sub,)).fetchone()
            if row:
                conn.execute("""
                    UPDATE users SET last_login = datetime('now'),
                    avatar_url = COALESCE(NULLIF(avatar_url, ''), ?)
                    WHERE id = ?
                """, (picture, row["id"]))
                conn.commit()
                return self._row_to_user(row)

            # Check by matching email address
            row = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
            if row:
                conn.execute("""
                    UPDATE users SET google_id = ?, last_login = datetime('now'),
                    avatar_url = COALESCE(NULLIF(avatar_url, ''), ?)
                    WHERE id = ?
                """, (sub, picture, row["id"]))
                conn.commit()
                updated = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                return self._row_to_user(updated)

        # Create new user for first-time Google sign-in
        return self.create_user(email=email, name=name, google_id=sub, avatar_url=picture)

    def create_session(self, user_id: int, days: int = 30) -> str:
        """Generates a secure cryptographic session token valid for 30 days."""
        token = secrets.token_hex(32)
        now = datetime.now()
        expires = now + timedelta(days=days)
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO user_sessions (token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, (token, user_id, now.isoformat(), expires.isoformat()))
            conn.commit()
        return token

    def get_user_from_session(self, token: str) -> Optional[UserProfile]:
        """Retrieves user profile associated with an active session token."""
        if not token:
            return None
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT u.* FROM users u
                JOIN user_sessions s ON u.id = s.user_id
                WHERE s.token = ? AND s.expires_at > datetime('now')
            """, (token,)).fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    def delete_session(self, token: str) -> bool:
        """Deletes session token on logout."""
        if not token:
            return False
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
            return cur.rowcount > 0

    def list_users(self) -> List[UserProfile]:
        """Lists all registered cellar users."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
            return [self._row_to_user(r) for r in rows]

    def get_user_by_id(self, user_id: int) -> Optional[UserProfile]:
        """Retrieves user profile by ID."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._row_to_user(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[UserProfile]:
        """Retrieves user profile by email."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email.strip().lower(),)).fetchone()
            return self._row_to_user(row) if row else None

    def _row_to_user(self, r: sqlite3.Row) -> UserProfile:
        return UserProfile(
            id=r["id"],
            email=r["email"],
            name=r["name"] or r["email"].split("@")[0].title(),
            avatar_url=r["avatar_url"] or f"https://api.dicebear.com/7.x/bottts/svg?seed={urllib.parse.quote(r['email'])}",
            created_at=r["created_at"] or "",
            google_id=r["google_id"]
        )

    # ==================== Bottle & Inventory Management ====================

    def add_bottle(self, bottle: WineBottle, user_id: Optional[int] = None) -> int:
        """Adds a wine bottle to inventory for a specific user and returns its ID."""
        pairings_json = json.dumps(bottle.food_pairings if bottle.food_pairings else [])
        wine_type_val = bottle.wine_type.value if isinstance(bottle.wine_type, WineType) else bottle.wine_type
        format_val = bottle.format.value if isinstance(bottle.format, BottleFormat) else bottle.format
        reviews_json = json.dumps(bottle.critic_reviews if bottle.critic_reviews else [])

        uid = user_id if user_id is not None else (bottle.user_id if bottle.user_id is not None else 1)
        bottle.user_id = uid

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
                    window_start, peak_start, peak_end, window_end, critic_reviews, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bottle.producer, bottle.wine_name, bottle.vintage, bottle.varietal,
                bottle.region, bottle.sub_region, bottle.country, wine_type_val,
                format_val, bottle.quantity, bottle.location_rack, bottle.location_bin,
                bottle.purchase_date, bottle.purchase_price, bottle.market_value,
                bottle.critic_score, bottle.user_rating, bottle.personal_notes,
                pairings_json, bottle.created_at,
                w_start, p_start, p_end, w_end, reviews_json, uid
            ))
            conn.commit()
            return cursor.lastrowid

    def update_bottle(self, bottle: WineBottle, user_id: Optional[int] = None) -> bool:
        """Updates an existing bottle in the inventory for the owner."""
        if not bottle.id:
            return False
        pairings_json = json.dumps(bottle.food_pairings if bottle.food_pairings else [])
        wine_type_val = bottle.wine_type.value if isinstance(bottle.wine_type, WineType) else bottle.wine_type
        format_val = bottle.format.value if isinstance(bottle.format, BottleFormat) else bottle.format
        reviews_json = json.dumps(bottle.critic_reviews if bottle.critic_reviews else [])

        uid = user_id if user_id is not None else bottle.user_id

        with self._get_conn() as conn:
            if uid is not None:
                cursor = conn.execute("""
                    UPDATE bottles SET
                        producer = ?, wine_name = ?, vintage = ?, varietal = ?,
                        region = ?, sub_region = ?, country = ?, wine_type = ?,
                        format = ?, quantity = ?, location_rack = ?, location_bin = ?,
                        purchase_date = ?, purchase_price = ?, market_value = ?,
                        critic_score = ?, user_rating = ?, personal_notes = ?,
                        food_pairings = ?, critic_reviews = ?
                    WHERE id = ? AND (user_id = ? OR (user_id IS NULL AND ? = 1))
                """, (
                    bottle.producer, bottle.wine_name, bottle.vintage, bottle.varietal,
                    bottle.region, bottle.sub_region, bottle.country, wine_type_val,
                    format_val, bottle.quantity, bottle.location_rack, bottle.location_bin,
                    bottle.purchase_date, bottle.purchase_price, bottle.market_value,
                    bottle.critic_score, bottle.user_rating, bottle.personal_notes,
                    pairings_json, reviews_json, bottle.id, uid, uid
                ))
            else:
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

    def delete_bottle(self, bottle_id: int, user_id: Optional[int] = None) -> bool:
        """Deletes a bottle record belonging to the user."""
        with self._get_conn() as conn:
            if user_id is not None:
                cursor = conn.execute(
                    "DELETE FROM bottles WHERE id = ? AND (user_id = ? OR (user_id IS NULL AND ? = 1))",
                    (bottle_id, user_id, user_id)
                )
            else:
                cursor = conn.execute("DELETE FROM bottles WHERE id = ?", (bottle_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_cellar(self, user_id: Optional[int] = 1):
        """Removes all bottles and logs for a specific user to start fresh."""
        with self._get_conn() as conn:
            if user_id is not None:
                conn.execute("DELETE FROM bottles WHERE user_id = ? OR (user_id IS NULL AND ? = 1)", (user_id, user_id))
                conn.execute("DELETE FROM consumption_log WHERE user_id = ? OR (user_id IS NULL AND ? = 1)", (user_id, user_id))
            else:
                conn.execute("DELETE FROM bottles")
                conn.execute("DELETE FROM consumption_log")
            conn.commit()

    def rename_location(self, old_location: str, new_location: str, user_id: Optional[int] = 1) -> int:
        """Renames a storage location/rack across bottles for the user."""
        with self._get_conn() as conn:
            if user_id is not None:
                cursor = conn.execute(
                    "UPDATE bottles SET location_rack = ? WHERE LOWER(location_rack) = LOWER(?) AND (user_id = ? OR (user_id IS NULL AND ? = 1))",
                    (new_location, old_location, user_id, user_id)
                )
            else:
                cursor = conn.execute(
                    "UPDATE bottles SET location_rack = ? WHERE LOWER(location_rack) = LOWER(?)",
                    (new_location, old_location)
                )
            conn.commit()
            return cursor.rowcount

    def clear_location(self, location: str, user_id: Optional[int] = 1) -> int:
        """Deletes all bottles in a specific storage location for the user."""
        with self._get_conn() as conn:
            if user_id is not None:
                cursor = conn.execute(
                    "DELETE FROM bottles WHERE LOWER(location_rack) = LOWER(?) AND (user_id = ? OR (user_id IS NULL AND ? = 1))",
                    (location, user_id, user_id)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM bottles WHERE LOWER(location_rack) = LOWER(?)",
                    (location,)
                )
            conn.commit()
            return cursor.rowcount

    def get_bottle(self, bottle_id: int, user_id: Optional[int] = None) -> Optional[WineBottle]:
        """Retrieves a single bottle by ID with computed drinking window."""
        with self._get_conn() as conn:
            if user_id is not None:
                row = conn.execute(
                    "SELECT * FROM bottles WHERE id = ? AND (user_id = ? OR (user_id IS NULL AND ? = 1))",
                    (bottle_id, user_id, user_id)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM bottles WHERE id = ?", (bottle_id,)).fetchone()
            if not row:
                return None
            return self._row_to_bottle(row)

    def list_bottles(
        self,
        status_filter: Optional[DrinkingStatus] = None,
        wine_type_filter: Optional[str] = None,
        search_query: Optional[str] = None,
        only_in_stock: bool = True,
        user_id: Optional[int] = 1
    ) -> List[WineBottle]:
        """Lists bottles with optional filtering and computed drinking windows scoped to user."""
        sql = "SELECT * FROM bottles WHERE 1=1"
        params = []

        if user_id is not None:
            sql += " AND (user_id = ? OR (user_id IS NULL AND ? = 1))"
            params.extend([user_id, user_id])

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
        aging_curve_stage: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Optional[ConsumptionRecord]:
        """Marks bottle(s) as consumed, decrements inventory, and logs tasting notes and aging curve status."""
        bottle = self.get_bottle(bottle_id, user_id=user_id)
        if not bottle:
            return None

        uid = user_id if user_id is not None else (bottle.user_id if bottle.user_id is not None else 1)
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
                    tasting_notes, pairing_notes, bottles_consumed, aging_curve_stage, action_type, user_id
                ) VALUES (?, ?, date('now'), ?, ?, ?, ?, ?, 'opened', ?)
            """, (
                bottle_id, bottle.display_name, rating,
                tasting_notes, pairing_notes, count, aging_curve_stage, uid
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
            action_type="opened",
            user_id=uid
        )

    def gift_bottle(
        self,
        bottle_id: int,
        count: int = 1,
        situation_notes: str = "",
        user_id: Optional[int] = None
    ) -> Optional[ConsumptionRecord]:
        """Marks bottle(s) as gifted, decrements inventory, and logs gift situation notes."""
        bottle = self.get_bottle(bottle_id, user_id=user_id)
        if not bottle:
            return None

        uid = user_id if user_id is not None else (bottle.user_id if bottle.user_id is not None else 1)
        dw = bottle.drinking_window
        stage = f"{dw.status.value} (Peak: {dw.peak_start}–{dw.peak_end})" if dw else "Standard Aging Window"

        new_qty = max(0, bottle.quantity - count)
        with self._get_conn() as conn:
            conn.execute("UPDATE bottles SET quantity = ? WHERE id = ?", (new_qty, bottle_id))
            cursor = conn.execute("""
                INSERT INTO consumption_log (
                    bottle_id, wine_display_name, date_opened, rating,
                    tasting_notes, pairing_notes, bottles_consumed, aging_curve_stage, action_type, user_id
                ) VALUES (?, ?, date('now'), NULL, ?, '', ?, ?, 'gift', ?)
            """, (
                bottle_id, bottle.display_name,
                situation_notes, count, stage, uid
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
            action_type="gift",
            user_id=uid
        )

    def get_consumption_history(self, user_id: Optional[int] = 1) -> List[ConsumptionRecord]:
        """Returns recent bottle consumption history scoped to the user."""
        records = []
        with self._get_conn() as conn:
            if user_id is not None:
                rows = conn.execute(
                    "SELECT * FROM consumption_log WHERE user_id = ? OR (user_id IS NULL AND ? = 1) ORDER BY id DESC",
                    (user_id, user_id)
                ).fetchall()
            else:
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
                uid = 1
                try:
                    if "user_id" in r.keys() and r["user_id"]:
                        uid = r["user_id"]
                except Exception:
                    uid = 1
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
                    action_type=action,
                    user_id=uid
                ))
        return records

    def get_cellar_stats(self, user_id: Optional[int] = 1) -> Dict[str, Any]:
        """Computes comprehensive cellar metrics and drinking readiness for the user's cellar."""
        bottles = self.list_bottles(only_in_stock=True, user_id=user_id)
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

        uid = 1
        try:
            if "user_id" in r.keys() and r["user_id"]:
                uid = r["user_id"]
        except Exception:
            uid = 1

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
            created_at=r["created_at"],
            user_id=uid
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

    def export_csv(self, file_path: str, user_id: Optional[int] = 1):
        """Exports the user's cellar to a CSV spreadsheet."""
        bottles = self.list_bottles(only_in_stock=False, user_id=user_id)
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

    def import_csv(self, file_path: str, user_id: Optional[int] = 1) -> int:
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

                bottle.user_id = user_id or 1
                self.add_bottle(bottle, user_id=user_id)
                count += 1
        return count

    def seed_sample_collection(self, user_id: Optional[int] = 1):
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
            s.user_id = user_id or 1
            self.add_bottle(s, user_id=user_id)
