"""
Agent Call Sheet — CSV mode
===========================
Use this when you don't have API keys yet. Drop a CSV export from Courted into
data/courted_agents.csv, run this script, and you get the same dashboard but
called-status and notes are saved locally instead of writing to Follow Up Boss.

Run with: python csv_mode.py
Or double-click run_csv.bat on Windows.
"""
import csv, json, sys, time, threading, webbrowser
from datetime import date, datetime
from pathlib import Path
from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).parent.resolve()
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CSV_PATH = DATA / "courted_agents.csv"
STATE_PATH = DATA / "local_state.json"

# Default scoring weights (same as the API mode). Edit if you want to tune.
WEIGHTS = {
    "volume_per_million_capped_at": 100,
    "ready_to_move": 50,
    "trouble_at_office": 30,
    "decreasing_sales": 25,
    "fresh_talent": 20,
    "predicted_growth": 15,
    "per_closed_unit": 0.5,
    "called_penalty": 1000,
}
TOP_N = 10
SERVER_PORT = 8765


# ---------- CSV loading ----------

# Map possible CSV column names (case-insensitive) to our internal field names.
# Add aliases here if your Courted export uses different headers.
ALIASES = {
    "first_name": ["first_name", "first name", "firstname"],
    "last_name": ["last_name", "last name", "lastname"],
    "email": ["email", "email_address", "email address"],
    "phone": ["phone", "phone_number", "office_phone"],
    "mobile_phone": ["mobile_phone", "mobile", "cell", "cell_phone"],
    "agent_photo": ["agent_photo", "photo", "photo_url", "image"],
    "courted_id": ["courted_id", "id", "agent_id"],
    "current_office_name": ["current_office_name", "office", "office_name", "brokerage"],
    "current_office_city": ["current_office_city", "office_city", "city"],
    "most_transacted_city": ["most_transacted_city", "primary_city"],
    "ltm_sales_volume": ["ltm_sales_volume", "sales_volume", "ltm_volume", "volume"],
    "ltm_closed_units": ["ltm_closed_units", "closed_units", "deals", "transactions"],
    "active_listings": ["active_listings", "active"],
    "pending_listings": ["pending_listings", "pending"],
    "sales_volume_prediction": ["sales_volume_prediction", "predicted_volume", "forecast"],
    "at_ready_to_move": ["at_ready_to_move", "ready_to_move", "likely_to_move"],
    "at_trouble_at_office": ["at_trouble_at_office", "trouble_at_office", "office_trouble"],
    "at_decreasing_sales": ["at_decreasing_sales", "decreasing_sales", "declining"],
    "at_fresh_talent": ["at_fresh_talent", "fresh_talent", "rising_star"],
}


def _bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("true", "yes", "y", "1", "t")


def _num(v):
    if v is None or v == "":
        return 0
    s = str(v).replace(",", "").replace("$", "").strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return 0


def normalize_row(row):
    """Map a raw CSV row (any header convention) to our internal fields."""
    lc = {k.lower().strip(): v for k, v in row.items() if k}
    out = {}
    for field, aliases in ALIASES.items():
        for a in aliases:
            if a.lower() in lc and lc[a.lower()] not in (None, ""):
                out[field] = lc[a.lower()]
                break
        else:
            out[field] = None

    # Coerce types
    for f in ("ltm_sales_volume", "ltm_closed_units", "active_listings",
              "pending_listings", "sales_volume_prediction"):
        out[f] = _num(out.get(f))
    for f in ("at_ready_to_move", "at_trouble_at_office",
              "at_decreasing_sales", "at_fresh_talent"):
        out[f] = _bool(out.get(f))

    # Stable id fallback
    if not out.get("courted_id"):
        out["courted_id"] = (str(out.get("email") or "") + "|" +
                              str(out.get("first_name") or "") + " " +
                              str(out.get("last_name") or "")).strip()
    return out


def load_csv():
    if not CSV_PATH.exists():
        print(f"\nERROR: {CSV_PATH} not found.")
        print("Drop your Courted CSV export there (any common column names work).\n")
        sys.exit(1)
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [normalize_row(r) for r in reader]
    return rows


# ---------- local state (called + notes) ----------

def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------- scoring + sync ----------

def score_agent(a, called_today):
    s = 0.0
    ltm = a.get("ltm_sales_volume") or 0
    s += min(ltm / 1_000_000, WEIGHTS["volume_per_million_capped_at"])
    if a.get("at_ready_to_move"):
        s += WEIGHTS["ready_to_move"]
    if a.get("at_trouble_at_office"):
        s += WEIGHTS["trouble_at_office"]
    if a.get("at_decreasing_sales"):
        s += WEIGHTS["decreasing_sales"]
    if a.get("at_fresh_talent"):
        s += WEIGHTS["fresh_talent"]
    pred = a.get("sales_volume_prediction") or 0
    if pred and pred > ltm:
        s += WEIGHTS["predicted_growth"]
    s += (a.get("ltm_closed_units") or 0) * WEIGHTS["per_closed_unit"]
    if called_today:
        s -= WEIGHTS["called_penalty"]
    return s


STATE = {"agents": [], "last_sync": None, "errors": []}


def run_sync():
    print("Loading CSV...")
    try:
        agents = load_csv()
    except SystemExit:
        raise
    except Exception as e:
        STATE["errors"] = [f"CSV load failed: {e}"]
        STATE["agents"] = []
        return
    local = load_state()
    today = date.today().isoformat()
    enriched = []
    for a in agents:
        st = local.get(a["courted_id"], {})
        called_today = (st.get("last_called_date") == today)
        a["_called_today"] = called_today
        a["_score"] = score_agent(a, called_today)
        a["_note"] = st.get("note", "")
        enriched.append(a)
    enriched.sort(key=lambda x: x["_score"], reverse=True)
    STATE["agents"] = enriched
    STATE["last_sync"] = datetime.now().isoformat(timespec="seconds")
    STATE["errors"] = []
    print(f"  Loaded {len(enriched)} agents from CSV. Top score: {enriched[0]['_score'] if enriched else 0:.1f}")


# ---------- Flask ----------

app = Flask(__name__, template_folder=str(ROOT / "templates"))


def public_agent(a, rank):
    return {
        "rank": rank,
        "courted_id": a.get("courted_id"),
        "first_name": a.get("first_name") or "",
        "last_name": a.get("last_name") or "",
        "email": a.get("email") or "",
        "phone": a.get("mobile_phone") or a.get("phone") or "",
        "office": a.get("current_office_name") or "",
        "city": a.get("most_transacted_city") or a.get("current_office_city") or "",
        "photo": a.get("agent_photo") or "",
        "ltm_sales_volume": a.get("ltm_sales_volume") or 0,
        "ltm_closed_units": a.get("ltm_closed_units") or 0,
        "active_listings": a.get("active_listings") or 0,
        "pending_listings": a.get("pending_listings") or 0,
        "ready_to_move": bool(a.get("at_ready_to_move")),
        "trouble_at_office": bool(a.get("at_trouble_at_office")),
        "decreasing_sales": bool(a.get("at_decreasing_sales")),
        "fresh_talent": bool(a.get("at_fresh_talent")),
        "predicted_growth": bool((a.get("sales_volume_prediction") or 0) > (a.get("ltm_sales_volume") or 0)),
        "called": bool(a.get("_called_today")),
        "in_fub": True,  # CSV mode hides "Not in FUB" warnings
        "score": round(a.get("_score") or 0, 1),
    }


@app.route("/")
def index():
    return render_template("dashboard.html", top_n=TOP_N, dry_run=False)


@app.route("/api/agents")
def api_agents():
    n = int(request.args.get("n", TOP_N))
    show_all = request.args.get("all") == "1"
    agents = STATE["agents"] if show_all else STATE["agents"][:n]
    return jsonify({
        "last_sync": STATE["last_sync"],
        "errors": STATE["errors"],
        "dry_run": False,
        "total": len(STATE["agents"]),
        "agents": [public_agent(a, i + 1) for i, a in enumerate(agents)],
    })


@app.route("/api/called/<courted_id>", methods=["POST"])
def api_called(courted_id):
    body = request.get_json(silent=True) or {}
    called = bool(body.get("called", True))
    state = load_state()
    rec = state.setdefault(courted_id, {})
    if called:
        rec["last_called_date"] = date.today().isoformat()
        rec["last_called_at"] = datetime.now().isoformat(timespec="seconds")
    else:
        rec.pop("last_called_date", None)
        rec.pop("last_called_at", None)
    save_state(state)
    a = next((x for x in STATE["agents"] if x.get("courted_id") == courted_id), None)
    if a:
        a["_called_today"] = called
        a["_score"] = score_agent(a, called)
        STATE["agents"].sort(key=lambda x: x["_score"], reverse=True)
    return jsonify({"ok": True})


@app.route("/api/note/<courted_id>", methods=["POST"])
def api_note(courted_id):
    body = request.get_json(silent=True) or {}
    note = (body.get("note") or "").strip()
    if not note:
        return jsonify({"ok": False, "error": "empty note"})
    state = load_state()
    rec = state.setdefault(courted_id, {})
    stamp = datetime.now().isoformat(timespec="minutes")
    existing = rec.get("note", "")
    rec["note"] = (existing + "\n\n" if existing else "") + f"[{stamp}] {note}"
    save_state(state)
    return jsonify({"ok": True})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    run_sync()
    return jsonify({"ok": True, "last_sync": STATE["last_sync"]})


@app.route("/api/push-photos", methods=["POST"])
def api_push_photos():
    return jsonify({"ok": False, "error": "Photo push to FUB requires API mode. Switch to app.py once you have your API keys."})


def open_browser_when_ready(url):
    time.sleep(1.0)
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    run_sync()
    url = f"http://localhost:{SERVER_PORT}/"
    print(f"\nDashboard: {url}")
    print(f"State saved to: {STATE_PATH}")
    print("Press Ctrl+C to stop.\n")
    threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    app.run(host="127.0.0.1", port=SERVER_PORT, debug=False)
