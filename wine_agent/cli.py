"""Command-Line Interface for the Sommelier Wine Cellar Agent."""

import argparse
import sys
import json
import os
from wine_agent.database import WineDatabase
from wine_agent.agent import SommelierAgent
from wine_agent.models import WineType, BottleFormat, DrinkingStatus, WineBottle
from wine_agent.drinking_window import CURRENT_YEAR


# ANSI Color formatting
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_WHITE = "\033[37m"


def status_badge(status: DrinkingStatus) -> str:
    if status == DrinkingStatus.PEAK:
        return f"{C_GREEN}[PEAK 🍷]{C_RESET}"
    elif status == DrinkingStatus.EARLY_WINDOW:
        return f"{C_CYAN}[APPROACHING]{C_RESET}"
    elif status == DrinkingStatus.LATE_PEAK:
        return f"{C_YELLOW}[DRINK SOON ⚠️]{C_RESET}"
    elif status == DrinkingStatus.PAST_PEAK:
        return f"{C_RED}[PAST PEAK 🚨]{C_RESET}"
    else:  # TOO_YOUNG
        return f"{C_BLUE}[HOLD ⏳]{C_RESET}"


def print_table(headers: list, rows: list):
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            # Strip ANSI codes for length calculation
            clean_val = val
            for code in [C_RESET, C_BOLD, C_RED, C_GREEN, C_YELLOW, C_BLUE, C_MAGENTA, C_CYAN, C_WHITE]:
                clean_val = clean_val.replace(code, "")
            col_widths[i] = max(col_widths[i], len(clean_val))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))

    print(f"\n{C_BOLD}{header_line}{C_RESET}")
    print(sep_line)
    for r in rows:
        # pad while accounting for ansi
        padded = []
        for i, val in enumerate(r):
            clean_val = val
            for code in [C_RESET, C_BOLD, C_RED, C_GREEN, C_YELLOW, C_BLUE, C_MAGENTA, C_CYAN, C_WHITE]:
                clean_val = clean_val.replace(code, "")
            extra = len(val) - len(clean_val)
            padded.append(val.ljust(col_widths[i] + extra))
        print(" | ".join(padded))
    print()


def cmd_list(agent: SommelierAgent, args):
    status_filter = None
    if args.status:
        for s in DrinkingStatus:
            if args.status.lower() in s.value.lower():
                status_filter = s
                break

    bottles = agent.db.list_bottles(
        status_filter=status_filter,
        wine_type_filter=args.type,
        search_query=args.search
    )

    if not bottles:
        print(f"\n{C_YELLOW}No matching bottles found in cellar.{C_RESET}\n")
        return

    headers = ["ID", "Wine & Vintage", "Type", "Qty", "Window", "Status", "Location", "Decant"]
    rows = []
    for b in bottles:
        dw = b.drinking_window
        win_str = f"{dw.peak_start}-{dw.peak_end}" if dw else "N/A"
        st = status_badge(dw.status) if dw else "N/A"
        loc = f"{b.location_rack} / {b.location_bin}" if b.location_rack or b.location_bin else "-"
        dec = f"{dw.decant_hours}h" if dw and dw.decant_hours > 0 else "None"
        rows.append([
            str(b.id),
            b.display_name[:36],
            b.wine_type.value[:5],
            str(b.quantity),
            win_str,
            st,
            loc[:18],
            dec
        ])

    print(f"\n{C_BOLD}🍷 CELLAR INVENTORY ({len(bottles)} entries | Ref Year: {CURRENT_YEAR}){C_RESET}")
    print_table(headers, rows)


def cmd_peak(agent: SommelierAgent, args):
    bottles = agent.db.list_bottles(status_filter=DrinkingStatus.PEAK)
    if not bottles:
        print(f"\n{C_YELLOW}No bottles currently at peak window.{C_RESET}\n")
        return
    headers = ["ID", "Wine & Vintage", "Qty", "Peak Window", "Decant", "Serving Temp", "Location"]
    rows = []
    for b in bottles:
        dw = b.drinking_window
        rows.append([
            str(b.id),
            b.display_name,
            str(b.quantity),
            f"{dw.peak_start}-{dw.peak_end}",
            f"{dw.decant_hours}h",
            f"{dw.serving_temp_f}°F",
            f"{b.location_rack} {b.location_bin}"
        ])
    print(f"\n{C_GREEN}{C_BOLD}🌟 BOTTLES IN PRIME DRINKING WINDOW (READY NOW){C_RESET}")
    print_table(headers, rows)


def cmd_approaching(agent: SommelierAgent, args):
    bottles = agent.db.list_bottles(status_filter=DrinkingStatus.EARLY_WINDOW)
    if not bottles:
        print(f"\n{C_YELLOW}No bottles currently approaching peak.{C_RESET}\n")
        return
    headers = ["ID", "Wine & Vintage", "Qty", "Peak Window", "Decant", "Serving Temp", "Location"]
    rows = []
    for b in bottles:
        dw = b.drinking_window
        rows.append([
            str(b.id),
            b.display_name,
            str(b.quantity),
            f"{dw.peak_start}-{dw.peak_end}",
            f"{dw.decant_hours}h",
            f"{dw.serving_temp_f}°F",
            f"{b.location_rack} {b.location_bin}"
        ])
    print(f"\n{C_CYAN}{C_BOLD}🌊 BOTTLES APPROACHING PEAK (EARLY WINDOW / DECANT){C_RESET}")
    print_table(headers, rows)


def cmd_urgent(agent: SommelierAgent, args):
    late = agent.db.list_bottles(status_filter=DrinkingStatus.LATE_PEAK)
    past = agent.db.list_bottles(status_filter=DrinkingStatus.PAST_PEAK)
    all_urgent = late + past
    if not all_urgent:
        print(f"\n{C_GREEN}Good news! No bottles in your cellar are nearing expiration or past peak.{C_RESET}\n")
        return

    headers = ["ID", "Wine & Vintage", "Qty", "Status", "End Year", "Location", "Notes"]
    rows = []
    for b in all_urgent:
        dw = b.drinking_window
        rows.append([
            str(b.id),
            b.display_name,
            str(b.quantity),
            status_badge(dw.status),
            str(dw.window_end),
            f"{b.location_rack} {b.location_bin}",
            b.personal_notes[:35] if b.personal_notes else "Drink soon before tertiary fade"
        ])
    print(f"\n{C_YELLOW}{C_BOLD}⚠️  DRINK SOON / URGENT CONSUMPTION LIST{C_RESET}")
    print_table(headers, rows)


def cmd_hold(agent: SommelierAgent, args):
    young = agent.db.list_bottles(status_filter=DrinkingStatus.TOO_YOUNG)
    if not young:
        print(f"\n{C_YELLOW}No young bottles requiring aging in your cellar.{C_RESET}\n")
        return

    headers = ["ID", "Wine & Vintage", "Qty", "First Approachable", "Peak Start", "Tier", "Location"]
    rows = []
    for b in young:
        dw = b.drinking_window
        rows.append([
            str(b.id),
            b.display_name,
            str(b.quantity),
            str(dw.window_start),
            str(dw.peak_start),
            dw.aging_tier[:30],
            f"{b.location_rack} {b.location_bin}"
        ])
    print(f"\n{C_BLUE}{C_BOLD}⏳ CELLAR HOLD / PATIENCE REQUIRED (AGING){C_RESET}")
    print_table(headers, rows)


def cmd_audit(agent: SommelierAgent, args):
    audit = agent.audit_cellar()
    stats = audit["stats"]

    print(f"\n{C_BOLD}{C_MAGENTA}===================================================={C_RESET}")
    print(f"{C_BOLD}{C_MAGENTA}             🍷 CELLAR SOMMELIER AUDIT REPORT       {C_RESET}")
    print(f"{C_BOLD}{C_MAGENTA}===================================================={C_RESET}")

    print(f"\n📊 {C_BOLD}Overview & Valuation:{C_RESET}")
    print(f"  • Total Bottles in Cellar : {C_BOLD}{stats['total_bottles']}{C_RESET}")
    print(f"  • Distinct Wine Labels    : {stats['total_unique_wines']}")
    print(f"  • Cellar Value (Est.)     : ${stats['estimated_value']:,.2f}")
    print(f"  • Cellar Readiness Index  : {C_GREEN if audit['readiness_index_pct'] > 50 else C_YELLOW}{audit['readiness_index_pct']}%{C_RESET} ready to drink now or approaching")

    print(f"\n📈 {C_BOLD}Drinking Window Breakdown (Reference Year: {CURRENT_YEAR}):{C_RESET}")
    for status_str, count in stats["status_distribution"].items():
        pct = round((count / max(1, stats["total_bottles"])) * 100, 1)
        bar = "█" * int(pct // 5)
        print(f"  • {status_str.ljust(26)} : {str(count).rjust(3)} bottles ({str(pct).rjust(4)}%) | {bar}")

    print(f"\n🌍 {C_BOLD}Top Wine Regions:{C_RESET}")
    for reg, count in stats["top_regions"]:
        print(f"  • {reg.ljust(20)} : {count} bottles")

    print(f"\n💡 {C_BOLD}Sommelier Strategic Recommendations:{C_RESET}")
    for rec in audit["sommelier_recommendations"]:
        print(f"  {rec}")
    print()


def cmd_recommend(agent: SommelierAgent, args):
    recs = agent.recommend_bottle(
        food=args.food,
        style=args.style,
        celebratory=args.celebratory
    )
    if not recs:
        print(f"\n{C_YELLOW}No matching bottles found in your cellar for this occasion.{C_RESET}\n")
        return

    print(f"\n{C_BOLD}{C_GREEN}🍷 SOMMELIER RECOMMENDATIONS FOR TONIGHT{C_RESET}")
    if args.food:
        print(f"   Pairing Target: {C_BOLD}'{args.food}'{C_RESET}")
    print("-" * 60)

    for i, item in enumerate(recs, 1):
        b = item["bottle"]
        dw = b.drinking_window
        print(f"\n{C_BOLD}#{i}. {b.display_name}{C_RESET} ({status_badge(dw.status)})")
        print(f"   • Location    : {b.location_rack} | {b.location_bin}")
        print(f"   • Service     : {item['decant_advice']} | Serve at {item['serving_temp']}")
        print(f"   • Peak Window : {dw.peak_start} - {dw.peak_end} (Tier: {dw.aging_tier})")
        print(f"   • Notes       : {dw.rationale}")
        if b.personal_notes:
            print(f"   • Your Notes  : {b.personal_notes}")
    print()


def cmd_parse(agent: SommelierAgent, args):
    prompt_text = " ".join(args.text)
    bottle = agent.add_from_text(prompt_text)
    dw = bottle.drinking_window
    print(f"\n{C_GREEN}✔ Successfully added to cellar:{C_RESET}")
    print(f"  • Wine       : {C_BOLD}{bottle.display_name}{C_RESET}")
    print(f"  • Region     : {bottle.region} ({bottle.country})")
    print(f"  • Varietal   : {bottle.varietal}")
    print(f"  • Quantity   : {bottle.quantity} ({bottle.format.value})")
    print(f"  • Location   : {bottle.location_rack} / {bottle.location_bin}")
    print(f"  • Price      : ${bottle.purchase_price:.2f}" if bottle.purchase_price else "  • Price      : N/A")
    print(f"  • Window     : {dw.peak_start} - {dw.peak_end} ({status_badge(dw.status)})")
    print(f"  • Service    : Decant {dw.decant_hours}h | Serve at {dw.serving_temp_f}°F")
    print(f"  • Rationale  : {dw.rationale}\n")


def cmd_scan(agent: SommelierAgent, args):
    """Parses raw text from a wine label photo and commits to cellar."""
    raw_text = ""
    if args.text:
        text_arg = " ".join(args.text)
        if os.path.exists(text_arg):
            with open(text_arg, "r", encoding="utf-8") as f:
                raw_text = f.read()
        else:
            raw_text = text_arg
    else:
        print(f"\n{C_BOLD}📸 WINE LABEL SCANNER{C_RESET}")
        print("Paste the OCR text from your wine bottle label (or Ctrl+D when finished):\n")
        try:
            raw_text = sys.stdin.read()
        except KeyboardInterrupt:
            print("\nScan cancelled.")
            return

    if not raw_text.strip():
        print(f"{C_YELLOW}No label text provided.{C_RESET}")
        return

    fridge = args.fridge or "Basement Fridge"
    bottle = agent.add_from_label(raw_text, default_fridge=fridge)
    dw = bottle.drinking_window
    print(f"\n{C_GREEN}✔ Wine label recognized and added to {bottle.location_rack}!{C_RESET}")
    print(f"  • Wine       : {C_BOLD}{bottle.display_name}{C_RESET}")
    print(f"  • Producer   : {bottle.producer}")
    print(f"  • Vintage    : {bottle.vintage or 'Non-Vintage'}")
    print(f"  • Varietal   : {bottle.varietal} ({bottle.wine_type.value})")
    print(f"  • Region     : {bottle.region} {f'({bottle.sub_region})' if bottle.sub_region else ''}")
    print(f"  • Location   : {bottle.location_rack} / {bottle.location_bin}")
    print(f"  • Status     : {status_badge(dw.status)}")
    print(f"  • Peak Window: {dw.peak_start} - {dw.peak_end} (Window: {dw.window_start}-{dw.window_end})")
    print(f"  • Service    : Decant {dw.decant_hours}h | Serve at {dw.serving_temp_f}°F")
    print(f"  • Notes      : {bottle.personal_notes}\n")


def cmd_drink(agent: SommelierAgent, args):
    bottle = agent.db.get_bottle(args.id)
    if not bottle:
        print(f"{C_RED}Bottle ID {args.id} not found.{C_RESET}")
        return

    dw = bottle.drinking_window
    curve_stage = f"{dw.status.value} (Peak: {dw.peak_start}–{dw.peak_end})" if dw else "Standard Aging Window"
    print(f"\nOpening {C_BOLD}{bottle.display_name}{C_RESET} (Qty remaining: {bottle.quantity}).")
    print(f"Aging curve position at opening: {C_GREEN}{curve_stage}{C_RESET}")
    rating_str = input("Your rating (1–5 stars, or score / empty): ").strip()
    rating = float(rating_str) if rating_str else None
    tasting_notes = input("Tasting notes / impressions: ").strip()
    pairing_notes = input("Food paired with: ").strip()

    rec = agent.log_consumption(
        bottle_id=args.id,
        count=args.count,
        rating=rating,
        tasting_notes=tasting_notes,
        pairing_notes=pairing_notes,
        aging_curve_stage=curve_stage
    )
    if rec:
        print(f"\n{C_GREEN}✔ Bottle recorded in consumption history! Remaining in cellar: {max(0, bottle.quantity - args.count)}{C_RESET}\n")


def cmd_gift(agent: SommelierAgent, args):
    """Removes a bottle as a gift without prompting for score or tasting impressions."""
    bottle = agent.db.get_bottle(args.id)
    if not bottle:
        print(f"{C_RED}Bottle ID {args.id} not found.{C_RESET}")
        return

    if bottle.quantity < args.count:
        print(f"{C_RED}Requested {args.count} bottle(s), but only {bottle.quantity} available in cellar.{C_RESET}")
        return

    notes = args.notes or ""
    if not notes and not args.force:
        print(f"\n{C_BOLD}🎁 Gift Wine Bottle: {bottle.display_name}{C_RESET}")
        print(f"Current Stock: {bottle.quantity} btl in {bottle.location_rack or 'Cellar'}")
        notes = input("Enter gift situation / recipient notes (e.g. 'Birthday gift for Dave'): ").strip()

    rec = agent.log_gift(args.id, args.count, notes)
    if rec:
        remaining = max(0, bottle.quantity - args.count)
        print(f"\n{C_GREEN}✔ Successfully gifted {args.count} bottle(s) of '{bottle.display_name}'! Remaining in cellar: {remaining}{C_RESET}")
        if notes:
            print(f"  Situation Notes: \"{notes}\"")
        print()


def cmd_history(agent: SommelierAgent, args):
    """Displays consumption & gift history, aging curve status when opened, star ratings, and tasting notes."""
    records = agent.db.get_consumption_history()
    if not records:
        print(f"\n{C_YELLOW}No cellar events or bottles logged yet.{C_RESET}")
        print("Use './cellar drink <ID>' to log opened bottles or './cellar gift <ID>' to gift bottles.\n")
        return

    print(f"\n{C_BOLD}📖 CELLAR ACTIVITY & TASTING LOG ({len(records)} entries){C_RESET}\n")
    for r in records:
        if r.action_type == "gift":
            print(f"  • {C_YELLOW}🎁 GIFTED ({r.bottles_consumed} btl){C_RESET} : {C_BOLD}{r.wine_display_name}{C_RESET} | Date: {r.date_opened}")
            if r.tasting_notes:
                print(f"    Situation: \"{r.tasting_notes}\"")
        else:
            stars = f"★ {r.rating}/5" if r.rating else "Unrated"
            curve = f" | Curve: {r.aging_curve_stage}" if r.aging_curve_stage else ""
            print(f"  • 🥂 {C_BOLD}{r.wine_display_name}{C_RESET} | Date: {r.date_opened} | {C_YELLOW}{stars}{C_RESET}{curve}")
            if r.tasting_notes:
                print(f"    Notes: \"{r.tasting_notes}\"")
            if r.pairing_notes:
                print(f"    Food : {r.pairing_notes}")
        print()


def cmd_delete(agent: SommelierAgent, args):
    bottle = agent.db.get_bottle(args.id)
    if not bottle:
        print(f"{C_RED}Bottle ID {args.id} not found.{C_RESET}")
        return
    if not args.force:
        confirm = input(f"Are you sure you want to delete '{bottle.display_name}' (ID: {bottle.id}) from cellar? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
    success = agent.db.delete_bottle(args.id)
    if success:
        print(f"\n{C_GREEN}✔ Successfully deleted '{bottle.display_name}' (ID: {args.id}) from your cellar.{C_RESET}\n")
    else:
        print(f"{C_RED}Failed to delete bottle ID {args.id}.{C_RESET}")


def cmd_seed(agent: SommelierAgent, args):
    existing = agent.db.list_bottles(only_in_stock=False)
    if existing and not args.force:
        print(f"{C_YELLOW}Cellar already contains {len(existing)} bottles. Use --force to seed additional samples.{C_RESET}")
        return
    agent.db.seed_sample_collection()
    print(f"{C_GREEN}✔ Successfully seeded 12 premier benchmark wines (Bordeaux, Barolo, Burgundy, Napa, Champagne, Rioja, Mosel, Yquem)!{C_RESET}")


def cmd_batch(agent: SommelierAgent, args):
    print(f"\n{C_BOLD}📝 BATCH WINE INTAKE (BASEMENT & UPSTAIRS FRIDGES){C_RESET}")
    print(f"Paste your bottle list below (e.g., with headers 'Basement Fridge:' or 'Upstairs Fridge:').")
    print(f"When finished, press {C_BOLD}Ctrl+D{C_RESET} (or Ctrl+Z on Windows) on a new line to process:\n")
    try:
        content = sys.stdin.read()
    except KeyboardInterrupt:
        print("\nBatch intake cancelled.")
        return

    if not content.strip():
        print(f"{C_YELLOW}No text provided.{C_RESET}")
        return

    added = agent.batch_add(content, default_fridge=args.fridge or "Basement Fridge")
    print(f"\n{C_GREEN}✔ Processed and added {len(added)} bottle(s) to your collection!{C_RESET}")
    for b in added:
        dw = b.drinking_window
        st = status_badge(dw.status) if dw else ""
        print(f"  • {b.quantity}x {C_BOLD}{b.display_name}{C_RESET} | {b.location_rack} ({b.location_bin}) | {st}")
    print()


def cmd_fridges(agent: SommelierAgent, args):
    breakdown = agent.get_fridge_breakdown()
    print(f"\n{C_BOLD}🧊 YOUR WINE FRIDGES (Total: {breakdown['total_bottles']} bottles | Ref: {CURRENT_YEAR}){C_RESET}")
    print("=" * 65)

    if not breakdown["fridges"]:
        print(f"\n{C_YELLOW}No bottles currently in your fridges. Use 'cellar batch' or 'cellar parse' to add some.{C_RESET}\n")
        return

    for fridge_name, bottles in sorted(breakdown["fridges"].items()):
        print(f"\n{C_BOLD}{C_MAGENTA}📍 {fridge_name.upper()} ({sum(b.quantity for b in bottles)} bottles):{C_RESET}")
        print("-" * 65)

        # Separate into Ready to Drink vs Keep Aging
        ready = [b for b in bottles if b.drinking_window and b.drinking_window.status in (DrinkingStatus.PEAK, DrinkingStatus.LATE_PEAK, DrinkingStatus.PAST_PEAK)]
        aging = [b for b in bottles if b.drinking_window and b.drinking_window.status in (DrinkingStatus.TOO_YOUNG, DrinkingStatus.EARLY_WINDOW)]

        if ready:
            print(f"  {C_GREEN}{C_BOLD}🍷 READY TO DRINK NOW / TONIGHT:{C_RESET}")
            for b in ready:
                dw = b.drinking_window
                loc = f"[{b.location_bin}]" if b.location_bin and b.location_bin != "Unassigned" else ""
                urgency = f"{C_YELLOW}(Drink Soon!){C_RESET}" if dw.status == DrinkingStatus.LATE_PEAK else ""
                print(f"    • {b.quantity}x {C_BOLD}{b.display_name}{C_RESET} {loc} {urgency}")
                print(f"      Decant: {dw.decant_hours}h | Serve: {dw.serving_temp_f}°F | Peak: {dw.peak_start}-{dw.peak_end}")

        if aging:
            print(f"\n  {C_BLUE}{C_BOLD}⏳ LEAVE IN FRIDGE (KEEP AGING):{C_RESET}")
            for b in aging:
                dw = b.drinking_window
                loc = f"[{b.location_bin}]" if b.location_bin and b.location_bin != "Unassigned" else ""
                print(f"    • {b.quantity}x {b.display_name} {loc} -> First prime window starts in {C_BOLD}{dw.peak_start}{C_RESET}")

        print()


def cmd_clear(agent: SommelierAgent, args):
    if not args.force:
        confirm = input(f"{C_RED}Are you sure you want to clear all bottles from your cellar? (y/N): {C_RESET}").strip().lower()
        if confirm != 'y':
            print("Operation aborted.")
            return
    agent.db.clear_cellar()
    print(f"\n{C_GREEN}✔ Cellar cleared! Database is fresh and ready for your bottles.{C_RESET}\n")


def cmd_serve(agent: SommelierAgent, args):
    from wine_agent.server import run_server
    port = args.port
    env_port = os.environ.get("PORT")
    if env_port and args.port == 8000:
        try:
            port = int(env_port)
        except ValueError:
            pass
    run_server(port=port, db_path=agent.db.db_path)


def cmd_publish(agent: SommelierAgent, args):
    from wine_agent.github_sync import publish_to_github
    print(f"\n{C_BOLD}Publishing latest wine cellar application to GitHub Pages...{C_RESET}")
    msg = getattr(args, "message", None) or "Update wine cellar web application"
    res = publish_to_github(commit_message=msg)
    if res.get("success"):
        print(f"{C_GREEN}✔ Successfully published to GitHub!{C_RESET}")
        print(f"  Repository: {C_BOLD}{res.get('repo')}{C_RESET} (branch: {res.get('branch')})")
        print(f"  Commit:     {res.get('commit_sha')[:7]}")
        print(f"  Live URL:   {C_CYAN}{C_BOLD}{res.get('pages_url')}{C_RESET}\n")
    else:
        print(f"{C_RED}✖ Publish failed: {res.get('error')}{C_RESET}\n")


def cmd_ask(agent: SommelierAgent, args):
    from wine_agent.gemini_sommelier import ask_gemini_sommelier, get_gemini_api_key
    key = getattr(args, "key", None) or get_gemini_api_key()
    mode = "buy" if (getattr(args, "buy", False) or args.command in ("buy", "acquire")) else "open"

    if not key:
        print(f"\n{C_YELLOW}⚠ No Gemini API Key found.{C_RESET}")
        print("Set GEMINI_API_KEY environment variable or pass --key YOUR_KEY.")
        if mode == "buy":
            print("Consulting built-in Master Sommelier acquisition advisor...\n")
            recs_obj = agent.recommend_purchases(args.query)
            print(f"{C_BOLD}Recommended Wines to Purchase ({args.query}):{C_RESET}\n")
            for r in recs_obj["recommendations"]:
                print(f"  • {C_GREEN}{C_BOLD}{r['producer']} {r['wine_name']}{C_RESET} ({r['vintage_sweet_spot']}) - est. ${r['est_price']:.0f}")
                print(f"    Region: {r['region']} | Varietal: {r['varietal']}")
                print(f"    Pairing:    {r['rationale']}")
                print(f"    Cellar fit: {r['cellar_complement']}\n")
        else:
            print("Falling back to built-in Master Sommelier pairing engine...\n")
            setattr(args, "food", args.query)
            setattr(args, "style", None)
            setattr(args, "celebratory", False)
            cmd_recommend(agent, args)
        return

    label = "Cellar Acquisition Advisor" if mode == "buy" else "Private Sommelier"
    print(f"\n{C_BOLD}Consulting Google Gemini AI ({label} - {args.model})...{C_RESET}\n")
    bottles = agent.db.list_bottles(only_in_stock=True)
    res = ask_gemini_sommelier(args.query, bottles, api_key=key, model=args.model, mode=mode)
    if res.get("success"):
        print(f"{C_GREEN}{C_BOLD}🍷 Sommelier Advice:{C_RESET}\n")
        print(res.get("advice"))
        print()
    else:
        print(f"{C_RED}✖ Gemini Error: {res.get('error')}{C_RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Sommelier Wine Cellar Agent & Drinking Window Assistant")
    parser.add_argument("--db", type=str, default=None, help="Custom path to SQLite database")
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="List bottles in cellar")
    p_list.add_argument("--status", type=str, help="Filter by status (peak, young, urgent)")
    p_list.add_argument("--type", type=str, help="Filter by wine type (red, white, sparkling)")
    p_list.add_argument("--search", type=str, help="Search producer, varietal, rack")

    # peak / approaching / urgent / hold / audit
    subparsers.add_parser("peak", help="Show bottles ready to drink at prime peak")
    subparsers.add_parser("approaching", help="Show bottles approaching peak maturity (early window / decant)")
    subparsers.add_parser("urgent", help="Show bottles in late peak or past peak")
    subparsers.add_parser("hold", help="Show young bottles that should remain aging")
    subparsers.add_parser("audit", help="Run full cellar health and maturity audit")

    # recommend
    p_rec = subparsers.add_parser("recommend", help="Get sommelier recommendation for tonight")
    p_rec.add_argument("--food", type=str, help="Food to pair with (e.g. ribeye, duck, oysters)")
    p_rec.add_argument("--style", type=str, help="Desired style (e.g. bold red, crisp white)")
    p_rec.add_argument("--celebratory", action="store_true", help="Select top-rated or prestige bottles")

    # parse / add
    p_parse = subparsers.add_parser("parse", help="Add bottle using natural language sentence")
    p_parse.add_argument("text", nargs="+", help="Natural language description of bottle(s)")

    # drink
    p_drink = subparsers.add_parser("drink", help="Mark bottle as consumed with tasting notes")
    p_drink.add_argument("id", type=int, help="Bottle ID")
    p_drink.add_argument("--count", type=int, default=1, help="Quantity consumed")

    # gift
    p_gift = subparsers.add_parser("gift", help="Gift bottle (remove from cellar without opening or rating)")
    p_gift.add_argument("id", type=int, help="Bottle ID")
    p_gift.add_argument("--count", type=int, default=1, help="Quantity to gift")
    p_gift.add_argument("--notes", type=str, default="", help="Situation or recipient notes")
    p_gift.add_argument("--force", "-f", action="store_true", help="Skip interactive prompts")

    # delete / remove
    p_del = subparsers.add_parser("delete", aliases=["remove", "rm"], help="Delete a bottle from cellar by ID")
    p_del.add_argument("id", type=int, help="Bottle ID to delete")
    p_del.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # seed
    p_seed = subparsers.add_parser("seed", help="Seed cellar with representative sommelier collection")
    p_seed.add_argument("--force", action="store_true", help="Force seeding even if DB is not empty")

    # export / import
    p_exp = subparsers.add_parser("export", help="Export cellar to CSV")
    p_exp.add_argument("--csv", type=str, required=True, help="Path for CSV export")

    p_imp = subparsers.add_parser("import", help="Import cellar from CSV")
    p_imp.add_argument("--csv", type=str, required=True, help="Path for CSV import")

    # batch / quick-add
    p_batch = subparsers.add_parser("batch", help="Batch paste multiple bottles for Basement/Upstairs fridge entry")
    p_batch.add_argument("--fridge", type=str, default="Basement Fridge", help="Default fridge (e.g. 'Basement Fridge' or 'Upstairs Fridge')")

    # scan / label OCR
    p_scan = subparsers.add_parser("scan", help="Parse wine label text from OCR and add to fridge")
    p_scan.add_argument("text", nargs="*", type=str, help="Raw OCR label text or path to text file")
    p_scan.add_argument("--fridge", type=str, default="Basement Fridge", help="Target fridge (Basement Fridge or Upstairs Fridge)")

    # fridges
    subparsers.add_parser("fridges", help="View collection organized by Basement Fridge / Upstairs Fridge (Ready vs Aging)")

    # clear
    p_clear = subparsers.add_parser("clear", help="Clear all bottles to start with an empty cellar")
    p_clear.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    # history / log
    subparsers.add_parser("history", help="View tasting history, notes, and star ratings of opened bottles")
    subparsers.add_parser("log", help="Alias for history")

    # serve
    p_serve = subparsers.add_parser("serve", help="Start local web dashboard")
    p_serve.add_argument("--port", type=int, default=8000, help="Web server port (default: 8000)")

    # publish / sync-github
    p_pub = subparsers.add_parser("publish", help="Publish latest web app to GitHub Pages")
    p_pub.add_argument("-m", "--message", type=str, default="Update wine cellar web application", help="Commit message")
    subparsers.add_parser("sync-github", help="Alias for publish")

    # ask / gemini
    p_ask = subparsers.add_parser("ask", help="Ask Google Gemini AI Sommelier for recommendations grounded in your cellar")
    p_ask.add_argument("query", type=str, help="Question or meal description (e.g. 'What pairs with ribeye tonight?')")
    p_ask.add_argument("--key", type=str, default=None, help="Gemini API Key")
    p_ask.add_argument("--model", type=str, default="gemini-flash-latest", help="Gemini model name")
    subparsers.add_parser("gemini", help="Alias for ask")

    # buy / acquire
    p_buy = subparsers.add_parser("buy", help="Ask what wines to purchase to complement your cellar or dining needs")
    p_buy.add_argument("query", type=str, help="Purchase goal (e.g. 'ready to drink with ribeye', 'age-worthy Barolo under $100')")
    p_buy.add_argument("--key", type=str, default=None, help="Gemini API Key")
    p_buy.add_argument("--model", type=str, default="gemini-flash-latest", help="Gemini model name")
    subparsers.add_parser("acquire", help="Alias for buy")

    args = parser.parse_args()
    db = WineDatabase(args.db) if args.db else WineDatabase()
    agent = SommelierAgent(db)

    if args.command == "list":
        cmd_list(agent, args)
    elif args.command == "peak":
        cmd_peak(agent, args)
    elif args.command == "approaching":
        cmd_approaching(agent, args)
    elif args.command == "urgent":
        cmd_urgent(agent, args)
    elif args.command == "hold":
        cmd_hold(agent, args)
    elif args.command == "audit":
        cmd_audit(agent, args)
    elif args.command == "recommend":
        cmd_recommend(agent, args)
    elif args.command == "parse":
        cmd_parse(agent, args)
    elif args.command == "scan":
        cmd_scan(agent, args)
    elif args.command == "batch":
        cmd_batch(agent, args)
    elif args.command == "fridges":
        cmd_fridges(agent, args)
    elif args.command == "clear":
        cmd_clear(agent, args)
    elif args.command == "drink":
        cmd_drink(agent, args)
    elif args.command == "gift":
        cmd_gift(agent, args)
    elif args.command in ("history", "log"):
        cmd_history(agent, args)
    elif args.command in ("delete", "remove", "rm"):
        cmd_delete(agent, args)
    elif args.command == "seed":
        cmd_seed(agent, args)
    elif args.command == "export":
        agent.db.export_csv(args.csv)
        print(f"{C_GREEN}Exported cellar to {args.csv}{C_RESET}")
    elif args.command == "import":
        cnt = agent.db.import_csv(args.csv)
        print(f"{C_GREEN}Imported {cnt} bottles from {args.csv}{C_RESET}")
    elif args.command == "serve":
        cmd_serve(agent, args)
    elif args.command in ("publish", "sync-github"):
        cmd_publish(agent, args)
    elif args.command in ("ask", "gemini", "buy", "acquire"):
        cmd_ask(agent, args)
    else:
        # Default action: run fridges overview
        cmd_fridges(agent, args)


if __name__ == "__main__":
    main()
