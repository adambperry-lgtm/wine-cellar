"""Google Gemini AI Sommelier Engine for Sommelier Wine Cellar Agent.

Integrates Google Gemini (gemini-2.0-flash / gemini-1.5-flash) to provide
conversational, master-sommelier pairing recommendations grounded directly
in the user's authentic cellar inventory.
"""

import os
import json
import re
import ssl
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from wine_agent.models import WineBottle, WineType, BottleFormat
from wine_agent.drinking_window import calculate_drinking_window


DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"
CANDIDATE_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash"
]
FALLBACK_GEMINI_MODEL = "gemini-flash-latest"
VISION_CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest"
]


def _make_gemini_post_request(url: str, payload: Dict[str, Any], timeout: int = 45) -> Dict[str, Any]:
    """Performs an HTTPS POST request to Gemini API with robust SSL certificate fallback."""
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json", "User-Agent": "Wine-Cellar-Sommelier"},
        method="POST"
    )

    contexts = []
    try:
        contexts.append(ssl.create_default_context())
    except Exception:
        pass
    try:
        contexts.append(ssl._create_unverified_context())
    except Exception:
        pass

    last_exc = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            # HTTP errors (400, 403, 404, 429) come from Google's servers, not SSL failures
            raise
        except Exception as e:
            last_exc = e
            continue

    if last_exc:
        raise last_exc
    raise RuntimeError("Unable to establish connection to Google Gemini API.")


def _is_valid_gemini_key(k: Optional[str]) -> bool:
    """Validates that a string has the structural signature of a Google AI Studio API key."""
    if not k or not isinstance(k, str):
        return False
    clean = k.strip()
    # Google AI Studio keys start with AIzaSy and are ~39 chars.
    # Exclude internal tokens starting with "AQ." which cause 403 policy errors.
    if clean.startswith("AQ.") or len(clean) < 15:
        return False
    return True


def get_gemini_api_key() -> Optional[str]:
    """Retrieves Gemini API key from environment, project config, or user profile."""
    # 1. Environment variables
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if _is_valid_gemini_key(key):
        return key.strip()

    # 2. Local project config file (.gemini_key)
    base_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    key_file = os.path.join(base_dir, ".gemini_key")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if _is_valid_gemini_key(k):
                    return k
        except Exception:
            pass

    # 3. Global user configuration (~/.gemini/config/gemini_key.txt)
    user_gemini_file = os.path.expanduser("~/.gemini/config/gemini_key.txt")
    if os.path.exists(user_gemini_file):
        try:
            with open(user_gemini_file, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if _is_valid_gemini_key(k):
                    return k
        except Exception:
            pass

    # 4. User home directory ~/.gemini_key
    home_key_file = os.path.expanduser("~/.gemini_key")
    if os.path.exists(home_key_file):
        try:
            with open(home_key_file, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if _is_valid_gemini_key(k):
                    return k
        except Exception:
            pass

    # 5. Antigravity MCP config (~/.gemini/config/mcp_config.json)
    mcp_path = os.path.expanduser("~/.gemini/config/mcp_config.json")
    if os.path.exists(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", {})
            for srv in servers.values():
                env = srv.get("env", {})
                gk = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
                if _is_valid_gemini_key(gk):
                    return gk.strip()
        except Exception:
            pass

    return None


def save_gemini_api_key(api_key: str) -> bool:
    """Persists the Gemini API key across project root and user configuration directories."""
    cleaned = api_key.strip()
    if not cleaned:
        return False

    success = False
    base_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    # 1. Save in project root (.gemini_key)
    try:
        key_file = os.path.join(base_dir, ".gemini_key")
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(cleaned)
        success = True
    except Exception:
        pass

    # 2. Save in ~/.gemini/config/gemini_key.txt
    try:
        user_config_dir = os.path.expanduser("~/.gemini/config")
        os.makedirs(user_config_dir, exist_ok=True)
        with open(os.path.join(user_config_dir, "gemini_key.txt"), "w", encoding="utf-8") as f:
            f.write(cleaned)
        success = True
    except Exception:
        pass

    # 3. Save in ~/.gemini_key
    try:
        home_key_file = os.path.expanduser("~/.gemini_key")
        with open(home_key_file, "w", encoding="utf-8") as f:
            f.write(cleaned)
        success = True
    except Exception:
        pass

    return success


def format_cellar_context(bottles: List[WineBottle]) -> str:
    """Formats active cellar bottles into a structured text prompt for Gemini."""
    lines = []
    in_stock = [b for b in bottles if (b.quantity or 0) > 0]
    
    for b in in_stock:
        dw = b.drinking_window
        status_str = dw.status.value if dw else "Unknown"
        decant_str = f"{dw.decant_hours}h decant" if dw and dw.decant_hours > 0 else "gentle aeration"
        temp_str = f"{dw.serving_temp_f}°F" if dw and dw.serving_temp_f else "60°F"
        score_str = f", Critic: {b.critic_score} pts" if b.critic_score else ""
        price_str = f", Paid: ${b.purchase_price:.0f}" if b.purchase_price else ""
        notes_str = f", Notes: {b.personal_notes}" if b.personal_notes else ""
        loc_str = f"Location: {b.location_rack or 'Cellar'}"
        if b.location_bin:
            loc_str += f" / {b.location_bin}"

        line = (
            f"- [ID {b.id}] {b.vintage or 'NV'} {b.producer} '{b.wine_name or ''}' ({b.varietal}, {b.region}) | "
            f"Qty: {b.quantity} | Status: {status_str} | {decant_str} | Serve at: {temp_str} | "
            f"{loc_str}{score_str}{price_str}{notes_str}"
        )
        lines.append(line)

    return "\n".join(lines)


def call_gemini_api(prompt: str, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> str:
    """Calls Google Generative Language API via standard HTTPS POST with model fallback cascade."""
    candidate_list = [model] + [m for m in CANDIDATE_MODELS if m != model]
    last_error = None

    for current_model in candidate_list:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 1200
            }
        }

        try:
            data = _make_gemini_post_request(url, payload, timeout=45)
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return "No response generated by Gemini."
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_msg)
                msg = err_json.get("error", {}).get("message", err_msg)
            except Exception:
                msg = err_msg
            last_error = f"Google Gemini API error ({e.code}) on {current_model}: {msg}"
            if e.code in (404, 503, 429):
                continue
            raise RuntimeError(last_error)
        except Exception as e:
            last_error = f"Failed to communicate with Gemini API on {current_model}: {e}"
            continue

    raise RuntimeError(last_error or "Unable to reach Gemini API.")


def validate_gemini_api_key(api_key: Optional[str] = None) -> Dict[str, Any]:
    """Tests connectivity to Google Gemini API with the specified key across candidate models."""
    resolved = api_key.strip() if api_key else get_gemini_api_key()
    if not resolved:
        return {"valid": False, "error": "No Gemini API key provided. Obtain a free key from https://aistudio.google.com/app/apikey."}

    last_err = ""
    for current_model in CANDIDATE_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={resolved}"
        payload = {
            "contents": [{"parts": [{"text": "Hello"}]}],
            "generationConfig": {"maxOutputTokens": 5}
        }
        try:
            data = _make_gemini_post_request(url, payload, timeout=10)
            if data.get("candidates"):
                return {"valid": True, "model": current_model, "message": f"Connected to Google Gemini ({current_model})."}
            return {"valid": True, "model": current_model, "message": f"Connected to Gemini API ({current_model})."}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_msg)
                msg = err_json.get("error", {}).get("message", err_msg)
            except Exception:
                msg = err_msg
            last_err = f"Google Gemini API error ({e.code}) on {current_model}: {msg}"
            if e.code in (404, 503, 429):
                continue
            return {"valid": False, "status_code": e.code, "error": last_err}
        except Exception as e:
            last_err = f"Connection error: {str(e)}"
            continue

    return {"valid": False, "error": last_err or "Unable to find an active Gemini model for this key."}


def analyze_wine_label_image(
    image_base64: str,
    mime_type: str = "image/jpeg",
    api_key: Optional[str] = None,
    default_fridge: str = "Basement Fridge",
    model: Optional[str] = None
) -> Dict[str, Any]:
    """Analyzes a wine bottle label photo using Google Gemini Multimodal Vision API.

    Extracts structured wine attributes (producer, cuvée, vintage, varietal, region,
    country, wine type, format, notes) and computes the authentic drinking window.
    """
    resolved_key = (api_key or get_gemini_api_key() or "").strip()
    if not resolved_key:
        return {
            "success": False,
            "error": "Gemini API key is required for AI Vision label scanning. Please enter your free key in Sommelier settings."
        }

    # Clean data URL prefix if present (e.g. data:image/jpeg;base64,...)
    clean_data = image_base64.strip()
    if "base64," in clean_data:
        header, clean_data = clean_data.split("base64,", 1)
        if "image/png" in header:
            mime_type = "image/png"
        elif "image/webp" in header:
            mime_type = "image/webp"
        elif "image/jpeg" in header or "image/jpg" in header:
            mime_type = "image/jpeg"

    prompt = (
        "You are a Master Sommelier and world-class wine bottle label recognition engine.\n"
        "Analyze this wine bottle label photo with maximum enological accuracy.\n"
        "Extract and return ONLY a valid, raw JSON object (without markdown code blocks, backticks, or extra commentary) with these exact keys:\n"
        "- producer: The winery, château, domaine, or estate name (e.g. \"Château Margaux\", \"Caymus Vineyards\", \"Hunnicutt\", \"Penfolds\", \"Domaine Dujac\")\n"
        "- wine_name: Cuvée name, vineyard designation, or specific wine name (e.g. \"Special Selection\", \"9-3-5\", \"Brut Reserve\", \"Grange\", \"Estate Cabernet Sauvignon\"). If the label does not specify a separate cuvée name, use the varietal or leave empty.\n"
        "- vintage: The 4-digit vintage year as an integer (e.g. 2019). Set to null for Non-Vintage (NV) wines or Champagnes without a year.\n"
        "- varietal: Primary grape varietal or blend name (e.g. \"Cabernet Sauvignon\", \"Bordeaux Blend\", \"Pinot Noir\", \"Nebbiolo\", \"Chardonnay\", \"Tempranillo\", \"Syrah/Shiraz\", \"Champagne Blend\")\n"
        "- region: The official wine region and appellation (e.g. \"Rutherford, Napa Valley, California\", \"Margaux, Bordeaux\", \"Barolo, Piedmont\", \"Rioja Alta\").\n"
        "- country: Country of origin (e.g. \"United States\", \"France\", \"Italy\", \"Spain\", \"Germany\", \"Australia\", \"New Zealand\", \"Argentina\", \"Chile\").\n"
        "- wine_type: Exactly one of: \"Red\", \"White\", \"Sparkling\", \"Rosé\", \"Dessert / Sweet\", \"Fortified\".\n"
        "- format: Exactly one of: \"Standard (750ml)\", \"Magnum (1.5L)\", \"Half (375ml)\", \"Double Magnum (3.0L)\".\n"
        "- alcohol_pct: Alcohol by volume percentage as a float (e.g. 14.5), or null if not clearly readable.\n"
        "- critic_score: Any visible score points on label (e.g. 95) or null.\n"
        "- personal_notes: A brief 1-2 sentence sommelier appraisal noting the producer pedigree, terroir, and drinking profile."
    )

    candidate_list = [model] + [m for m in VISION_CANDIDATE_MODELS if m != model] if model else VISION_CANDIDATE_MODELS
    last_err = None

    for current_model in candidate_list:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={resolved_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": clean_data
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json"
            }
        }

        try:
            resp_json = _make_gemini_post_request(url, payload, timeout=35)
            candidates = resp_json.get("candidates", [])
            if not candidates:
                last_err = f"No output returned by model {current_model}"
                continue

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                last_err = f"Empty content parts from model {current_model}"
                continue

            text_out = parts[0].get("text", "").strip()

            # Strip potential markdown fences if returned
            text_out = re.sub(r"^```(?:json)?\s*", "", text_out, flags=re.IGNORECASE)
            text_out = re.sub(r"\s*```$", "", text_out)

            parsed = json.loads(text_out)

            # Extract fields with safe defaults
            producer = str(parsed.get("producer") or "Unknown Producer").strip()
            wine_name = str(parsed.get("wine_name") or "").strip()
            vintage_raw = parsed.get("vintage")
            vintage = None
            if vintage_raw is not None:
                try:
                    v_int = int(vintage_raw)
                    if 1900 <= v_int <= 2035:
                        vintage = v_int
                except (ValueError, TypeError):
                    pass

            varietal = str(parsed.get("varietal") or "Cabernet Sauvignon").strip()
            region = str(parsed.get("region") or "").strip()
            country = str(parsed.get("country") or "").strip()

            # Map wine type enum safely
            wt_str = str(parsed.get("wine_type") or "Red").strip()
            wt_map = {
                "Red": WineType.RED,
                "White": WineType.WHITE,
                "Sparkling": WineType.SPARKLING,
                "Rosé": WineType.ROSE,
                "Rose": WineType.ROSE,
                "Dessert / Sweet": WineType.DESSERT,
                "Dessert": WineType.DESSERT,
                "Sweet": WineType.DESSERT,
                "Fortified": WineType.FORTIFIED
            }
            wine_type = wt_map.get(wt_str, WineType.RED)

            # Map bottle format safely
            fmt_str = str(parsed.get("format") or "Standard (750ml)").strip()
            fmt_map = {
                "Half (375ml)": BottleFormat.HALF,
                "Standard (750ml)": BottleFormat.STANDARD,
                "Magnum (1.5L)": BottleFormat.MAGNUM,
                "Double Magnum (3.0L)": BottleFormat.DOUBLE_MAGNUM
            }
            bottle_fmt = fmt_map.get(fmt_str, BottleFormat.STANDARD)

            alc_pct = None
            if parsed.get("alcohol_pct"):
                try:
                    alc_pct = float(parsed["alcohol_pct"])
                except (ValueError, TypeError):
                    pass

            critic_score = None
            if parsed.get("critic_score"):
                try:
                    critic_score = int(parsed["critic_score"])
                except (ValueError, TypeError):
                    pass

            notes = str(parsed.get("personal_notes") or "").strip()
            if alc_pct:
                notes = f"{notes} (Alc: {alc_pct}% vol.)".strip()

            bottle = WineBottle(
                producer=producer,
                wine_name=wine_name,
                vintage=vintage,
                varietal=varietal,
                region=region,
                country=country,
                wine_type=wine_type,
                format=bottle_fmt,
                quantity=1,
                location_rack=default_fridge,
                location_bin="Shelf 1",
                critic_score=critic_score,
                personal_notes=notes or "Scanned via Gemini AI Vision"
            )
            bottle.drinking_window = calculate_drinking_window(bottle)

            return {
                "success": True,
                "bottle": bottle,
                "raw_json": parsed,
                "model": current_model
            }

        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_msg)
                msg = err_json.get("error", {}).get("message", err_msg)
            except Exception:
                msg = err_msg
            last_err = f"Gemini API error ({e.code}) on {current_model}: {msg}"
            if e.code in (404, 503, 429):
                continue
            break
        except Exception as e:
            last_err = f"Gemini Vision call failed on {current_model}: {str(e)}"
            continue

    return {
        "success": False,
        "error": last_err or "Unable to recognize bottle details from image via Gemini Vision."
    }


def format_history_transcript(history: Optional[List[Dict[str, str]]]) -> str:
    """Formats past conversation turns into a clean sommelier dialogue transcript."""
    if not history:
        return ""
    lines = []
    for turn in history:
        role = turn.get("role", "user")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        speaker = "Collector" if role in ("user", "collector") else "Master Sommelier"
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


def ask_gemini_sommelier(
    query: str,
    bottles: List[WineBottle],
    api_key: Optional[str] = None,
    model: str = DEFAULT_GEMINI_MODEL,
    mode: str = "open",
    history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """Generates an intelligent sommelier recommendation grounded in the cellar inventory.
    
    Supports multi-turn interactive conversations:
    - User can provide follow-up directions (price caps, alternate regions/grapes, styles).
    - User can ask for feedback on specific alternative choices or retail bottles found.

    Modes:
    - 'open': Recommends what bottles to pull and open from current inventory.
    - 'buy': Recommends what new wines to purchase to complement the cellar or fulfill immediate dining needs.
    """
    resolved_key = api_key or get_gemini_api_key()
    if not resolved_key:
        return {
            "success": False,
            "error": "Gemini API key is required. Please set GEMINI_API_KEY or provide a key in settings.",
            "source": "gemini",
            "history": history or []
        }

    cellar_text = format_cellar_context(bottles)
    if not cellar_text:
        return {
            "success": False,
            "error": "Your cellar is currently empty. Add bottles before asking for recommendations.",
            "source": "gemini",
            "history": history or []
        }

    has_history = bool(history and len(history) > 0)
    history_transcript = format_history_transcript(history)

    if mode in ("buy", "acquire", "purchase"):
        if has_history:
            system_prompt = f"""You are a Master Sommelier acting as the interactive private cellar acquisition advisor for a wine collector located in New Jersey (NJ).
The collector is having an ongoing conversation with you regarding wines to PURCHASE to complement their collection or dining needs.

COLLECTOR'S CURRENT CELLAR INVENTORY:
{cellar_text}

CONVERSATION TRANSCRIPT SO FAR:
{history_transcript}

COLLECTOR'S LATEST FOLLOW-UP DIRECTIONS / ALTERNATIVE INQUIRY:
"{query}"

INSTRUCTIONS FOR MASTER SOMMELIER:
1. DIRECT EVALUATION & FEEDBACK:
   - If the collector is asking for feedback on specific alternative bottles they found (e.g. at a local store, online, or in a retail flyer), thoroughly evaluate each bottle:
     * Appraise the producer's reputation, vintage pedigree, flavor profile, and drinking window.
     * Compare it directly against your earlier recommendations and the dining/cellar goal.
     * Deliver a clear verdict: "Top Pick / Buy Now", "Solid Alternative", or "Skip / Pass" with precise enological reasoning.
2. NEW CRITERIA & DIRECTIONS:
   - If the collector is providing follow-up directions (e.g. adjust price tier such as "<$50", change region like Barolo/Brunello/Rioja, request white or sparkling alternatives, or adjust style):
     * Recommend 2 to 3 SPECIFIC real-world benchmark alternative wines to PURCHASE fulfilling their revised criteria.
3. NJ RETAIL & SHIPPING REQUIREMENT:
   - Every wine recommended or endorsed must be available at retail in New Jersey (NJ) or shippable to NJ addresses (e.g. distributed through top NJ merchants such as Gary's Wine, Buy-Rite, Total Wine NJ, Wine Library, Saratoga Wine, Wine.com, or direct winery DTC shipping to NJ).
   - For any newly recommended purchases, include:
     * **Wine & Producer**: Specific estate and cuvée
     * **Target Vintage(s)**: Current drinking sweet spot
     * **Est. Price**: Estimated market price
     * **NJ Availability**: Confirmed retail / shipping to NJ
     * **Sommelier Critique & Comparison**: How it fits the dining plan and cellar
     * **Service Guidance**: Decant time and serving temperature
     * **Where to Buy Link**: [🔍 Search Retailers (Ship to NJ)](https://www.google.com/search?q=buy+PRODUCER+WINE+wine+ship+to+NJ)
4. TONE & FORMAT:
   - Use an authoritative, engaging, polished Master Sommelier tone. Use clean Markdown headings, bold text, and bullet points. Be punchy, conversational, and directly answer their latest question.
"""
        else:
            system_prompt = f"""You are a Master Sommelier acting as the private cellar acquisition advisor for a wine collector located in New Jersey (NJ).
The collector wants recommendations for wines to PURCHASE to complement their current collection.

COLLECTOR'S CURRENT CELLAR INVENTORY:
{cellar_text}

USER'S ACQUISITION REQUEST:
"{query}"

INSTRUCTIONS:
1. Provide a brief 1-2 sentence Master Sommelier assessment of the collector's current cellar profile (e.g. noting varietal strengths, current maturity stages, or readiness gaps).
2. Recommend 3 SPECIFIC real-world benchmark wines to PURCHASE that fulfill the user's request and complement their collection.
   CRITICAL REQUIREMENT: Every recommended wine must be widely available to purchase at retail in New Jersey (NJ) or legally shippable to a New Jersey address (e.g. distributed through top NJ fine wine merchants such as Gary's Wine, Buy-Rite, Total Wine NJ, Wine Library, Saratoga Wine, Wine.com, or direct winery DTC shipping to NJ). Do not recommend obscure allocations that cannot be shipped to NJ.
3. For each recommended purchase, clearly specify:
   - **Wine & Producer**: Specific estate and cuvée (e.g. *La Rioja Alta Gran Reserva 904*, *Château Léoville Barton*, *Produttori del Barbaresco*)
   - **Target Vintage(s) to Seek Out**: Specific vintage(s) currently drinking at their prime peak right now
   - **Price Tier / Est. Market Price**: Estimated retail price (e.g. ~$45, ~$85, ~$140)
   - **NJ Availability**: Confirmed retail / shipping availability in New Jersey
   - **Why It Complements the Cellar & Dining Goal**: Explain how its tannins, acidity, and flavor profile meet the dining need (e.g. pairing with ribeye) and how it fits alongside what they already own.
   - **Service Guidance**: Decant duration and ideal serving temperature once acquired.
   - **Where to Buy**: Provide a direct Google search link formatted as: [🔍 Search Retailers (Ship to NJ)](https://www.google.com/search?q=buy+PRODUCER+WINE+wine+ship+to+NJ)
4. Conclude with 1-2 practical buying tips for collectors purchasing in New Jersey (e.g. benchmark retail vintages or regional sweet spots).
5. Format with polished Markdown headings, bold text, and bullet points in an inspiring, authoritative sommelier tone. Be punchy and concise.
"""
    else:
        if has_history:
            system_prompt = f"""You are a Master Sommelier acting as the private cellar sommelier for a private collector.
Your recommendations MUST be grounded strictly in the collector's actual cellar bottles listed below.
Do NOT invent bottles that are not in this cellar list.

CURRENT CELLAR INVENTORY:
{cellar_text}

CONVERSATION TRANSCRIPT SO FAR:
{history_transcript}

COLLECTOR'S LATEST FOLLOW-UP QUESTION / DIRECTION:
"{query}"

INSTRUCTIONS:
1. Respond directly to the collector's follow-up or critique regarding what to open from their cellar.
2. If they ask for alternatives, different styles, different price points, or have questions about decanting/pairing, evaluate bottles strictly from their cellar inventory.
3. For any recommended bottle, specify full name, vintage, cellar location, pairing harmony, and service guidance (decant duration and temperature).
4. Use a polished, master sommelier tone with clean Markdown.
"""
        else:
            system_prompt = f"""You are a Master Sommelier acting as the private cellar sommelier for a private collector.
Your recommendations MUST be grounded strictly in the collector's actual cellar bottles listed below.
Do NOT invent bottles that are not in this cellar list.

CURRENT CELLAR INVENTORY:
{cellar_text}

INSTRUCTIONS:
1. Recommend 1 to 3 specific bottles from the cellar that best suit the collector's query: "{query}".
2. PRIORITIZE bottles whose Drinking Status is "In Peak Window" or "Approaching Peak" or "Drink Soon (Late Peak)". If a wine is "Hold (Too Young)", explain why it should be held unless the user specifically wants to open a youthful powerhouse.
3. For each recommended bottle, specify:
   - Full Name & Vintage
   - Storage location (e.g. Basement Fridge Shelf 1)
   - Why its acid, tannins, and flavor profile harmonize with the food/occasion
   - Service guidance: Exact decanting duration and ideal serving temperature
4. Use a polished, evocative, master sommelier tone. Format with clear Markdown headings and bullet points.

USER QUERY:
"{query}"
"""

    try:
        answer = call_gemini_api(system_prompt, resolved_key, model=model)
        new_history = [dict(h) for h in (history or [])]
        new_history.append({"role": "user", "content": query})
        new_history.append({"role": "assistant", "content": answer})
        return {
            "success": True,
            "advice": answer,
            "model": model,
            "mode": mode,
            "source": "gemini",
            "history": new_history
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "source": "gemini",
            "history": history or []
        }
