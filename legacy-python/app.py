"""
Agent Call Sheet — API mode
Pulls Courted agents (from pipeline / watchlists / saved-searches), matches to
Follow Up Boss contacts, scores by production volume + move signals, and serves
a daily call dashboard at http://localhost:<port>.
"""
import json, re, sys, time, threading, webbrowser
from datetime import date, datetime
from pathlib import Path
import requests
from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).parent.resolve()
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_PATH = DATA_DIR / "last_sync.json"


def load_config():
    if not CONFIG_PATH.exists():
        print(f"\nERROR: {CONFIG_PATH} not found.\n")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("courted_api_key", "").startswith("PASTE_"):
        print("\nERROR: courted_api_key still has placeholder value.\n"); sys.exit(1)
    if cfg.get("fub_api_key", "").startswith("PASTE_"):
        print("\nERROR: fub_api_key still has placeholder value.\n"); sys.exit(1)
    return cfg


CFG = load_config()


class CourtedClient:
    def __init__(self, cfg):
        self.base = cfg["courted_base_url"].rstrip("/")
        scheme = cfg.get("courted_auth_scheme", "Bearer")
        self.headers = {"Authorization": f"{scheme} {cfg['courted_api_key']}", "Accept": "application/json"}

    def _get(self, path_or_url, params=None):
        url = path_or_url if path_or_url.startswith("http") else (self.base + path_or_url)
        # Log the outgoing request (auth header redacted)
        from urllib.parse import urlencode
        full_url = url + (("?" + urlencode(params)) if params else "")
        auth = self.headers.get("Authorization", "")
        scheme = auth.split(" ", 1)[0] if auth else "?"
        if CFG.get("verbose_courted_requests", True):
            print(f"    HTTP GET  {full_url}  [Authorization: {scheme} ****]", flush=True)
        r = requests.get(url, headers=self.headers, params=params, timeout=30)
        if CFG.get("verbose_courted_requests", True):
            print(f"    HTTP {r.status_code} ({len(r.content)} bytes) <- {full_url}", flush=True)
        if r.status_code != 200:
            raise RuntimeError(f"Courted GET {path_or_url} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def health_check(self):
        try:
            r = requests.get(self.base + "/health", headers=self.headers, timeout=8)
            return r.status_code == 200
        except Exception:
            return False

    def _fix_next_url(self, next_url):
        """Courted's API sometimes returns next URLs pointing to internal hosts
        like 'apiserver:80'. Rewrite to use our configured base URL host."""
        if not next_url:
            return None
        try:
            from urllib.parse import urlparse, urlunparse
            n = urlparse(next_url)
            b = urlparse(self.base)
            # If next URL host doesn't match our base host, rewrite it.
            if n.netloc and n.netloc != b.netloc:
                fixed = urlunparse((b.scheme, b.netloc, n.path, n.params, n.query, n.fragment))
                return fixed
        except Exception:
            pass
        return next_url

    def _paginate(self, path, params=None, max_pages=500, page_size=100):
        """Walk DRF-style pagination (count/next/previous/results) with broken-host fix."""
        out = []
        url = path
        first = True
        page = 0
        # Inject a larger page_size on the first request to reduce round-trips.
        initial_params = dict(params or {})
        initial_params.setdefault("limit", page_size)
        initial_params.setdefault("page_size", page_size)
        while url and page < max_pages:
            page += 1
            print(f"    {path} page {page}: requesting...", end="", flush=True)
            t0 = time.time()
            try:
                data = self._get(url, params=initial_params if first else None)
            except Exception as e:
                msg = str(e)
                print(f" FAILED in {time.time()-t0:.1f}s: {msg}", flush=True)
                # Courted's per-session export cap (1000 records, MLS ToS) — return what we have.
                if "export limit" in msg or " 429" in msg or "-> 429" in msg:
                    print(f"    Reached Courted export cap. Continuing with {len(out)} records.", flush=True)
                    return out
                raise
            elapsed = time.time() - t0
            first = False
            if isinstance(data, dict) and "results" in data:
                got = len(data["results"])
                out.extend(data["results"])
                url = self._fix_next_url(data.get("next"))
                total = data.get("count")
                print(f" got {got} ({elapsed:.1f}s){' total='+str(total) if total else ''}, accumulated {len(out)}", flush=True)
            elif isinstance(data, list):
                print(f" got list of {len(data)} ({elapsed:.1f}s)", flush=True)
                out.extend(data)
                url = None
            else:
                print(f" got single object ({elapsed:.1f}s)", flush=True)
                out.append(data)
                url = None
            time.sleep(0.1)
        if page >= max_pages:
            print(f"    Hit max_pages={max_pages}, stopping pagination", flush=True)
        return out

    def list_pipeline_agents(self):
        """Pipeline agents — cached to data/courted_pipeline_cache.json for 24h
        (avoids burning the Courted 1000-records-per-session export cap on every run)."""
        from pathlib import Path as _P
        cache_path = _P(__file__).parent / "data" / "courted_pipeline_cache.json"
        if cache_path.exists():
            try:
                blob = json.loads(cache_path.read_text(encoding="utf-8"))
                age_h = (time.time() - (blob.get("_cached_at") or 0)) / 3600
                if age_h < 24 and blob.get("agents"):
                    print(f"  Courted pipeline: using cache ({len(blob['agents'])} agents, {age_h:.1f}h old). Delete data/courted_pipeline_cache.json to force refresh.", flush=True)
                    return blob["agents"]
            except Exception:
                pass
        agents = self._paginate("/company/pipeline/agents")
        if not agents:
            print(f"  Courted pipeline: got 0 agents — NOT caching (likely hit session quota; try again later or wait 24h)", flush=True)
            return agents
        try:
            # Atomic write: dump to .tmp then rename, so an interrupted process can't truncate the cache.
            tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps({"_cached_at": time.time(), "agents": agents}, default=str), encoding="utf-8")
            tmp_path.replace(cache_path)
            print(f"  Courted pipeline: cached {len(agents)} agents to {cache_path.name}", flush=True)
        except Exception as e:
            print(f"  Courted pipeline: cache write failed: {e}", flush=True)
        return agents

    def list_watchlists(self):
        return self._paginate("/watchlist")

    def list_watchlist_agents(self, watchlist_id):
        return self._paginate(f"/watchlist/{watchlist_id}/agent")

    def list_saved_searches(self):
        return self._paginate("/saved-search")

    def list_saved_search_agents(self, saved_search_id):
        return self._paginate(f"/saved-search/{saved_search_id}/agent")

    def get_agent_by_email(self, email):
        """Look up a single agent by email via /agent?email=X."""
        try:
            data = self._get("/agent", params={"email": str(email)})
            results = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [data])
            target = str(email).lower().strip()
            for r in results:
                if str(r.get("email", "")).lower().strip() == target:
                    return r
            return results[0] if results else None
        except Exception:
            return None

    def list_agents_by_emails(self, emails, cache_path):
        """Fetch full Courted record for each email. Cached for 7 days."""
        cache = {}
        if cache_path.exists():
            try: cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception: cache = {}
        now = time.time()
        TTL = 7 * 24 * 3600  # 7 days
        agents = []
        misses = 0
        hits = 0
        for i, email in enumerate(emails, 1):
            if not email: continue
            key = str(email).lower().strip()
            rec = cache.get(key)
            if rec and isinstance(rec, dict) and (now - (rec.get("_cached_at") or 0)) < TTL:
                hits += 1
                if rec.get("data"): agents.append(rec["data"])
                continue
            # Cache miss — fetch from Courted
            misses += 1
            if misses % 25 == 1 or misses <= 3:
                print(f"    Courted /agent lookup {i}/{len(emails)} for {email} (hits so far: {hits})...", end="", flush=True)
            t0 = time.time()
            agent = self.get_agent_by_email(email)
            elapsed = time.time() - t0
            if misses % 25 == 1 or misses <= 3:
                print(f" {'found' if agent else 'no match'} ({elapsed:.1f}s)", flush=True)
            cache[key] = {"_cached_at": now, "data": agent}
            if agent: agents.append(agent)
            # Periodically save cache so partial runs aren't wasted
            if misses % 50 == 0:
                try: cache_path.write_text(json.dumps(cache), encoding="utf-8")
                except Exception: pass
            time.sleep(0.05)
        try:
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
        except Exception:
            pass
        print(f"    Courted MLS lookup: {hits} cached, {misses} fetched, {len(agents)} matched agents", flush=True)
        return agents

    def fetch_agents(self, fub_people=None):
        """Dispatch to the right list endpoint based on config."""
        source = (CFG.get("courted_source") or "pipeline").lower()
        print(f"  Courted source: {source}")
        if source == "fub_mls" or source == "fub_email":
            if not fub_people:
                raise RuntimeError(f"courted_source={source} but no FUB people provided")
            # Extract email (primary) from each FUB person
            emails = []
            for p in fub_people:
                # FUB contact emails are in p["emails"] as list of {value, type, ...}
                em_list = p.get("emails") or []
                for em in em_list:
                    v = (em.get("value") or "").strip()
                    if v:
                        emails.append(v.lower())
                        break  # one email per contact
            emails = list(dict.fromkeys(emails))  # dedupe, preserve order
            print(f"  Found {len(emails)} unique emails across {len(fub_people)} FUB contacts")
            cache_path = DATA_DIR / "courted_by_email.json"
            return self.list_agents_by_emails(emails, cache_path)
        if source == "pipeline":
            return self.list_pipeline_agents()
        if source == "watchlist":
            wid = CFG.get("courted_watchlist_id")
            if not wid:
                raise RuntimeError("courted_source=watchlist but courted_watchlist_id not set in config.json")
            return self.list_watchlist_agents(wid)
        if source == "watchlists":
            wls = self.list_watchlists()
            print(f"  Found {len(wls)} watchlists")
            seen, combined = set(), []
            for w in wls:
                wid = w.get("id") or w.get("watchlist_id")
                if not wid: continue
                try:
                    for a in self.list_watchlist_agents(wid):
                        cid = a.get("courted_id") or a.get("id")
                        if cid and cid not in seen:
                            seen.add(cid); combined.append(a)
                except Exception as e:
                    print(f"    watchlist {wid} failed: {e}")
            return combined
        if source == "saved_search":
            sid = CFG.get("courted_saved_search_id")
            if not sid:
                raise RuntimeError("courted_source=saved_search but courted_saved_search_id not set in config.json")
            return self.list_saved_search_agents(sid)
        raise RuntimeError(f"Unknown courted_source: {source}")


class FUBClient:
    def __init__(self, cfg):
        self.base = cfg["fub_base_url"].rstrip("/")
        self.auth = (cfg["fub_api_key"], "")
        self.headers = {
            "X-System": cfg.get("fub_system_name", "AgentCallSheet"),
            "X-System-Key": cfg.get("fub_system_key", "agent-call-sheet-local"),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.custom_field_map = {}

    def _request(self, method, url_or_path, **kw):
        url = url_or_path if url_or_path.startswith("http") else (self.base + url_or_path)
        r = requests.request(method, url, auth=self.auth, headers=self.headers, timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"FUB {method} {url_or_path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}

    def _get(self, path, params=None): return self._request("GET", path, params=params)
    def _put(self, path, payload): return self._request("PUT", path, json=payload)
    def _post(self, path, payload): return self._request("POST", path, json=payload)

    def list_people(self, limit=100, max_age_hours=24):
        """Cursor-paginated via _metadata.nextLink. Cached to data/fub_people_cache.json
        for max_age_hours (default 24h) — speeds up subsequent runs from minutes to seconds."""
        from pathlib import Path as _P
        cache = _P(__file__).parent / "data" / "fub_people_cache.json"
        if cache.exists():
            age_h = (time.time() - cache.stat().st_mtime) / 3600
            if age_h < max_age_hours:
                try:
                    data = json.loads(cache.read_text(encoding="utf-8"))
                    print(f"  FUB: using cache ({len(data)} contacts, {age_h:.1f}h old). Delete data/fub_people_cache.json to force refresh.", flush=True)
                    return data
                except Exception:
                    pass
        stage_filter = CFG.get("fub_stage_filter", "Agents")
        params = {"limit": limit, "includeTrash": "false", "sort": "created", "fields": "allFields"}
        if stage_filter:
            params["stage"] = stage_filter
        out, url = [], "/people"
        if stage_filter:
            print(f"  FUB: filtering to stage = {stage_filter!r}", flush=True)
        page = 0
        while url:
            page += 1
            t0 = time.time()
            data = self._get(url, params=params if url == "/people" else None)
            people = data.get("people", [])
            out.extend(people)
            meta = data.get("_metadata") or {}
            next_link = meta.get("nextLink") or meta.get("next")
            total = (meta.get("total") or meta.get("collection") or {}).get("total") if isinstance(meta.get("collection"), dict) else meta.get("total")
            if page % 10 == 0 or page <= 3:
                print(f"    FUB /people page {page}: {len(people)} contacts ({time.time()-t0:.1f}s), accumulated {len(out)}{' / '+str(total) if total else ''}", flush=True)
            if not next_link or not people: break
            url = next_link; params = None; time.sleep(0.05)
        try:
            # Atomic write: smaller subsequent writes won't leave null-byte garbage trailing the file.
            tmp = cache.with_suffix(cache.suffix + ".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(cache)
            print(f"  FUB: cached {len(out)} contacts to {cache.name}", flush=True)
        except Exception as e:
            print(f"  FUB: cache write failed: {e}", flush=True)
        return out

    def list_smartlist_people(self, smartlist_id, limit=100):
        """Fetch all people in a FUB Smart List. Tries multiple FUB API endpoint patterns
        (param name varies by API version). Returns the best-yielding result."""
        attempts = [
            ("smartListId query param", "/people", {"limit": limit, "fields": "allFields", "smartListId": smartlist_id}),
            ("smartlistId query param (lowercase l)", "/people", {"limit": limit, "fields": "allFields", "smartlistId": smartlist_id}),
            ("smart_list_id query param (snake)", "/people", {"limit": limit, "fields": "allFields", "smart_list_id": smartlist_id}),
        ]
        best = []
        for label, url0, params0 in attempts:
            try:
                out = []
                url = url0; params = dict(params0)
                page = 0
                while url:
                    page += 1
                    data = self._get(url, params=params if url == url0 else None)
                    people = data.get("people", [])
                    out.extend(people)
                    meta = data.get("_metadata") or {}
                    next_link = meta.get("nextLink") or meta.get("next")
                    if not next_link or not people: break
                    url = next_link; params = None
                    if page > 50: break
                print(f"    Coops attempt '{label}': {len(out)} people", flush=True)
                if len(out) > len(best):
                    best = out
                # If we got a substantial number, stop trying alternatives
                if len(out) >= 50:
                    break
            except Exception as e:
                print(f"    Coops attempt '{label}' failed: {e}", flush=True)
        return best

    def list_smartlists(self):
        """List all FUB Smart Lists so the user can find the right ID."""
        try:
            data = self._get("/smartLists", params={"limit": 100})
            return data.get("smartLists") or data.get("smartlists") or data.get("data") or []
        except Exception as e:
            print(f"  /smartLists failed: {e}", flush=True)
            return []

    def load_custom_fields(self):
        """Resolve FUB custom field labels to internal keys. Defensive + paginated."""
        from pathlib import Path as _P
        all_fields = []
        next_url = None
        # Try both paths; once one works, paginate it
        for path in ["/customFields", "/customfields"]:
            try:
                data = self._get(path, params={"limit": 100})
                print(f"  FUB: GET {path} -> ok, top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}", flush=True)
                # Save raw response
                try:
                    (_P(__file__).parent / "data" / "fub_customfields_raw.json").write_text(
                        json.dumps(data, indent=2)[:80000], encoding="utf-8")
                except Exception:
                    pass
                while True:
                    fields = (data.get("customFields") or data.get("customfields")
                              or data.get("customField") or data.get("collection")
                              or (data if isinstance(data, list) else []))
                    if not fields and isinstance(data, dict):
                        for v in data.values():
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                fields = v; break
                    all_fields.extend(fields)
                    meta = data.get("_metadata") if isinstance(data, dict) else None
                    next_url = (meta or {}).get("nextLink") or (meta or {}).get("next")
                    if not next_url: break
                    data = self._get(next_url)
                break
            except RuntimeError as e:
                print(f"  FUB: GET {path} -> {e}", flush=True)
                continue
        if not all_fields:
            print("  FUB: no custom fields fetched", flush=True)
            self.custom_field_map = {}
            return
        print(f"  FUB: parsing {len(all_fields)} custom field definitions across all pages", flush=True)
        for f in all_fields:
            label = f.get("label") or f.get("displayName") or f.get("name")
            key = f.get("name") or f.get("key") or f.get("apiName") or f.get("id")
            if label and key:
                self.custom_field_map[label] = key

    def update_person(self, pid, payload): return self._put(f"/people/{pid}", payload)
    def create_person(self, payload): return self._post("/people", payload)
    def add_note(self, pid, body): return self._post("/notes", {"personId": pid, "body": body})
    def log_call(self, pid, outcome="Reached", duration_seconds=300, note="", direction="Outbound"):
        """Log a call event to FUB so it shows on the contact's timeline.
        outcome examples: Reached, Left Message, Bad Number, Busy, No Answer.
        duration_seconds: how long the call lasted (default 5 min).
        note: free-text recap appended to the call."""
        payload = {
            "personId": pid,
            "outcome": outcome,
            "duration": int(duration_seconds),
            "note": note or "",
            "direction": direction,
        }
        return self._post("/calls", payload)


PHONE_RE = re.compile(r"\D+")


def norm_phone(p):
    if not p: return ""
    d = PHONE_RE.sub("", str(p))
    return d[-10:] if len(d) > 10 else d


def index_fub_people(people):
    by_email, by_phone = {}, {}
    for p in people:
        for e in p.get("emails", []) or []:
            v = (e.get("value") or "").lower().strip()
            if v: by_email[v] = p
        for ph in p.get("phones", []) or []:
            v = norm_phone(ph.get("value"))
            if v: by_phone[v] = p
    return by_email, by_phone


def match_fub(agent, by_email, by_phone):
    e = (agent.get("email") or "").lower().strip()
    if e and e in by_email: return by_email[e]
    for k in ("mobile_phone", "phone"):
        n = norm_phone(agent.get(k))
        if n and n in by_phone: return by_phone[n]
    return None


_TODAY_MD_CACHE = {"d": None, "md": None}
def _today_md():
    """Returns today's month-day as 'MM-DD' (recomputed once per day)."""
    today = date.today()
    if _TODAY_MD_CACHE["d"] != today:
        _TODAY_MD_CACHE["d"] = today
        _TODAY_MD_CACHE["md"] = today.strftime("%m-%d")
    return _TODAY_MD_CACHE["md"]

def _matches_today(date_str):
    """Returns True if date_str's month-day matches today, ignoring year."""
    if not date_str: return False
    import re
    s = str(date_str).strip()
    today_md = _today_md()
    # YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"^\d{4}[-/](\d{1,2})[-/](\d{1,2})", s)
    if m: return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}" == today_md
    # MM-DD-YYYY or MM/DD/YYYY
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/]\d{4}", s)
    if m: return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}" == today_md
    # MM-DD or MM/DD
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})$", s)
    if m: return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}" == today_md
    return False

def score_agent(agent, weights, called_today):
    s = 0.0
    ltm = agent.get("ltm_sales_volume") or 0
    s += min(ltm / 1_000_000, weights.get("volume_per_million_capped_at", 100))
    if agent.get("at_ready_to_move"): s += weights.get("ready_to_move", 50)
    if agent.get("at_trouble_at_office"): s += weights.get("trouble_at_office", 30)
    if agent.get("at_decreasing_sales"): s += weights.get("decreasing_sales", 25)
    if agent.get("at_fresh_talent"): s += weights.get("fresh_talent", 20)
    pred = agent.get("sales_volume_prediction") or 0
    if pred and pred > ltm: s += weights.get("predicted_growth", 15)
    s += (agent.get("ltm_closed_units") or 0) * weights.get("per_closed_unit", 0.5)
    # Birthday / anniversary boost — float these to the top on their special day.
    # Set 'prioritize_celebrations: false' (or 0) in config to disable; without a match
    # there's no bonus and the standard ranking applies automatically.
    if weights.get("prioritize_celebrations", True):
        if _matches_today(agent.get("_birthday")):
            s += weights.get("birthday_today", 200)
            agent["_birthday_today"] = True
        if _matches_today(agent.get("_anniversary")):
            s += weights.get("anniversary_today", 150)
            agent["_anniversary_today"] = True
    if called_today: s -= weights.get("called_penalty", 1000)
    return s


STATE = {"agents": [], "last_sync": None, "errors": []}
OVERRIDES_PATH = DATA_DIR / "agent_overrides.json"
SKIPPED_PATH = DATA_DIR / "skipped.json"
BUCKETS_PATH = DATA_DIR / "buckets.json"
BUCKET_NAMES = ("warm", "nurture", "hot")
# Special tabs (filters that aren't user-managed buckets, but share the bucket-tab UI)
SPECIAL_TABS = ("coops", "birthday", "anniversary")
COOPS_SMARTLIST_ID = 21
COOPS_PER_DAY = 10
COOPS_CACHE_PATH = DATA_DIR / "coops_cache.json"

def load_overrides():
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_overrides(o):
    try:
        OVERRIDES_PATH.write_text(json.dumps(o, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_skipped():
    """Returns {date_iso: [courted_id, ...]}."""
    if not SKIPPED_PATH.exists():
        return {}
    try:
        return json.loads(SKIPPED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_skipped(s):
    try:
        SKIPPED_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_skipped_today():
    today = date.today().isoformat()
    return set((load_skipped().get(today) or []))

def set_skipped(courted_id, skip=True):
    today = date.today().isoformat()
    blob = load_skipped()
    day_list = list(blob.get(today) or [])
    alt_ids = _alt_ids_for(courted_id)
    # Remove all alternate IDs first, then add back only if skipping
    day_list = [x for x in day_list if x not in alt_ids]
    if skip:
        day_list.append(courted_id)
    blob[today] = day_list
    save_skipped(blob)
    return day_list

def load_buckets():
    """Returns {bucket_name: [courted_id, ...]}. Persistent (not per-day)."""
    if not BUCKETS_PATH.exists():
        return {b: [] for b in BUCKET_NAMES}
    try:
        data = json.loads(BUCKETS_PATH.read_text(encoding="utf-8"))
        for b in BUCKET_NAMES:
            data.setdefault(b, [])
        return data
    except Exception:
        return {b: [] for b in BUCKET_NAMES}

def save_buckets(b):
    try:
        BUCKETS_PATH.write_text(json.dumps(b, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_bucket_for(courted_id):
    """Returns the bucket name if assigned, else None."""
    blob = load_buckets()
    for name in BUCKET_NAMES:
        if courted_id in (blob.get(name) or []):
            return name
    return None

def _fub_person_to_agent_stub(p, cf_map):
    """Convert a FUB person record into the agent-shape used by the dashboard.
    Reads transaction data from FUB custom fields (customClosedDeals, customLTMSalesVolume)."""
    def _cf(label):
        if not label: return None
        if label in cf_map: return cf_map[label]
        t = label.strip().lower()
        for lbl, k in cf_map.items():
            if lbl.strip().lower() == t: return k
        return None
    photo_key = _cf("Photo URL")
    bday_key = _cf("Birthday")
    anni_key = _cf("customSREGAniversary") or "customSREGAniversary"
    closed_key = _cf("Closed Deals")
    volume_key = _cf("LTM Sales Volume")
    office_key = _cf("Office Name")
    emails = p.get("emails") or []; phones = p.get("phones") or []
    em = (emails[0] or {}).get("value", "") if emails else ""
    ph = (phones[0] or {}).get("value", "") if phones else ""
    closed_units = 0
    if closed_key and p.get(closed_key) is not None:
        try: closed_units = int(float(p.get(closed_key)))
        except (ValueError, TypeError): closed_units = 0
    volume = 0
    if volume_key and p.get(volume_key) is not None:
        try: volume = float(p.get(volume_key))
        except (ValueError, TypeError): volume = 0
    return {
        "courted_id": f"fub-{p.get('id')}",
        "first_name": p.get("firstName") or "",
        "last_name": p.get("lastName") or "",
        "email": em, "phone": ph,
        "agent_photo": (p.get(photo_key) if photo_key else "") or "",
        "current_office_name": (p.get(office_key) if office_key else "") or p.get("assignedLenderName") or "",
        "ltm_sales_volume": volume,
        "ltm_closed_units": closed_units,
        "_fub_id": p.get("id"),
        "_called_today": False, "_tags": list(p.get("tags") or []),
        "_birthday": (p.get(bday_key) if bday_key else None) or p.get("birthday") or None,
        "_anniversary": p.get("customSREGAniversary") or p.get("customSREGAnniversary") or None,
        "_score": 0, "_top_15_percent": False,
    }


# In-memory cache for the SREG pool, keyed by (FUB cache mtime, STATE last_sync) so we
# rebuild when EITHER the FUB data changes OR a Courted sync brings new production data.
_SREG_POOL_CACHE = {"key": None, "pool": []}

def get_sreg_agents_from_fub():
    """Returns all FUB people tagged 'SREG', 'SREG##', or 'Signature Real Estate Group', in agent-shape,
    enriched with Courted production data where the email or phone matches a Courted record.
    Cached in memory; rebuilds when FUB data or Courted state changes."""
    cache_path = DATA_DIR / "fub_people_cache.json"
    if not cache_path.exists():
        return []
    try:
        mtime = cache_path.stat().st_mtime
    except Exception:
        mtime = None
    cache_key = (mtime, STATE.get("last_sync"))
    if _SREG_POOL_CACHE["key"] == cache_key:
        return _SREG_POOL_CACHE["pool"]
    try:
        people = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  SREG pool: FUB cache read failed: {e}", flush=True)
        return _SREG_POOL_CACHE["pool"]
    # Load custom field map (cached on disk after each sync)
    cf_map = {}
    cfm_path = DATA_DIR / "fub_custom_fields.json"
    if cfm_path.exists():
        try: cf_map = json.loads(cfm_path.read_text(encoding="utf-8"))
        except Exception: cf_map = {}
    sreg = []
    for p in people:
        tags_lc = [str(t).lower().strip() for t in (p.get("tags") or [])]
        # Match any SREG sub-brand: "SREG", "SREG02", "Signature Real Estate Group",
        # "Signature Edge Farm", "Signature ..." — anything starting with signature or sreg.
        if any(t.startswith("signature") or t.startswith("sreg") for t in tags_lc):
            sreg.append(_fub_person_to_agent_stub(p, cf_map))
    # Enrich each SREG agent with Courted production data (LTM volume, closed units, signals,
    # office name, etc.) by matching on email. SREG agents that aren't in today's Courted
    # pipeline keep whatever data came from FUB's custom fields.
    by_email_courted = {}
    by_phone_courted = {}
    for a in STATE.get("agents", []):
        em = (a.get("email") or "").lower().strip()
        if em and em not in by_email_courted: by_email_courted[em] = a
        for k in ("mobile_phone", "phone"):
            ph = norm_phone(a.get(k))
            if ph and ph not in by_phone_courted: by_phone_courted[ph] = a
    courted_fields = ("ltm_sales_volume", "ltm_closed_units", "ltm_closed_units_buy_side",
                     "ltm_closed_units_list_side", "ltm_avg_sale_price", "ltm_est_gci",
                     "prev_ltm_sales_volume", "prev_ltm_closed_units", "prev_ltm_avg_sale_price",
                     "sales_volume_prediction", "active_listings", "pending_listings",
                     "agent_tenure", "time_at_current_office", "office_rank", "office_roster_count",
                     "current_office_name", "brand_name", "mls_id", "member_mls_id",
                     "courted_mls_id", "at_ready_to_move", "at_trouble_at_office",
                     "at_decreasing_sales", "at_fresh_talent", "most_transacted_city",
                     "current_office_city", "current_office_state", "agent_photo")
    enriched = 0
    for stub in sreg:
        em = (stub.get("email") or "").lower().strip()
        ph = norm_phone(stub.get("phone"))
        c = (by_email_courted.get(em) if em else None) or (by_phone_courted.get(ph) if ph else None)
        if c:
            for k in courted_fields:
                v = c.get(k)
                if v not in (None, "", 0) or k in ("at_ready_to_move", "at_trouble_at_office", "at_decreasing_sales", "at_fresh_talent"):
                    stub[k] = v
            enriched += 1
    print(f"  SREG pool: built {len(sreg)} agents from {len(people)} FUB contacts; {enriched} enriched with Courted data", flush=True)
    _SREG_POOL_CACHE["key"] = cache_key
    _SREG_POOL_CACHE["pool"] = sreg
    return sreg


def get_coops_for_today():
    """Returns up to 10 coops agents (FUB Smart List 21) for today.
    Pulls the full smartlist once per day, then deterministically samples 10 using
    today's date as the random seed so the same 10 show all day.
    Each returned record is in agent-shape (matching public_agent output keys)."""
    today_iso = date.today().isoformat()
    # Try cache first
    if COOPS_CACHE_PATH.exists():
        try:
            blob = json.loads(COOPS_CACHE_PATH.read_text(encoding="utf-8"))
            if blob.get("date") == today_iso and isinstance(blob.get("agents"), list):
                return blob["agents"]
        except Exception:
            pass
    # Fetch fresh smartlist
    try:
        fub = FUBClient(CFG)
        fub.load_custom_fields()
        # Enumerate available smartlists so the user can verify the ID is right
        lists = fub.list_smartlists()
        if lists:
            print(f"  Coops: FUB has {len(lists)} smart lists. Looking for id={COOPS_SMARTLIST_ID}...", flush=True)
            for sl in lists[:30]:
                marker = " <-- TARGET" if str(sl.get("id")) == str(COOPS_SMARTLIST_ID) else ""
                print(f"    [{sl.get('id')}] {sl.get('name')!r}{marker}", flush=True)
        people = fub.list_smartlist_people(COOPS_SMARTLIST_ID)
        print(f"  Coops: fetched {len(people)} people from FUB Smart List {COOPS_SMARTLIST_ID}", flush=True)
    except Exception as e:
        print(f"  Coops: fetch failed: {e}", flush=True)
        return []
    if not people:
        return []
    # Deterministic rotation: show 10 per day, cycling through the full smartlist.
    # Order by FUB id for stability, then slice based on days since a fixed epoch.
    ordered = sorted(people, key=lambda p: p.get("id") or 0)
    import datetime as _dt
    day_idx = (date.today() - _dt.date(2026, 1, 1)).days
    total = len(ordered)
    start = (day_idx * COOPS_PER_DAY) % total
    if start + COOPS_PER_DAY <= total:
        sample = ordered[start:start + COOPS_PER_DAY]
    else:
        # Wrap around to the beginning of the list
        sample = ordered[start:] + ordered[:(start + COOPS_PER_DAY) - total]
    print(f"  Coops: showing day-{day_idx} window [{start}:{start + COOPS_PER_DAY}] of {total} smartlist members", flush=True)
    # Convert FUB people to agent-shape stubs
    cf_map = fub.custom_field_map or {}
    def _cf(label):
        if not label: return None
        if label in cf_map: return cf_map[label]
        t = label.strip().lower()
        for lbl, k in cf_map.items():
            if lbl.strip().lower() == t: return k
        return None
    photo_key = _cf(CFG.get("fub_custom_fields", {}).get("photo_url"))
    bday_key = _cf(CFG.get("fub_custom_fields", {}).get("birthday"))
    anni_key = _cf(CFG.get("fub_custom_fields", {}).get("anniversary"))
    out = []
    for p in sample:
        emails = p.get("emails") or []; phones = p.get("phones") or []
        em = (emails[0] or {}).get("value", "") if emails else ""
        ph = (phones[0] or {}).get("value", "") if phones else ""
        out.append({
            "courted_id": f"fub-{p.get('id')}",
            "first_name": p.get("firstName") or "",
            "last_name": p.get("lastName") or "",
            "email": em, "phone": ph,
            "agent_photo": (p.get(photo_key) if photo_key else "") or "",
            "current_office_name": p.get("assignedLenderName") or "",
            "ltm_sales_volume": 0, "ltm_closed_units": 0,
            "_fub_id": p.get("id"),
            "_called_today": False, "_tags": list(p.get("tags") or []),
            "_birthday": (p.get(bday_key) if bday_key else None) or p.get("birthday") or None,
            "_anniversary": (p.get(anni_key) if anni_key else None) or p.get("customSREGAniversary") or p.get("customSREGAnniversary") or None,
            "_score": 0, "_top_15_percent": False,
        })
    try:
        COOPS_CACHE_PATH.write_text(json.dumps({"date": today_iso, "agents": out}, default=str), encoding="utf-8")
    except Exception:
        pass
    return out


def _alt_ids_for(courted_id):
    """Returns the full set of IDs this agent might be saved under (handles legacy fub-NNN format)."""
    ids = {courted_id}
    try:
        a = next((x for x in STATE.get("agents", []) if x.get("courted_id") == courted_id), None)
        if a and a.get("_fub_id"):
            ids.add(f"fub-{a['_fub_id']}")
    except Exception:
        pass
    return ids

def set_bucket(courted_id, bucket):
    """Assigns courted_id to a bucket (or None to remove). Removes from any other bucket first."""
    blob = load_buckets()
    alt_ids = _alt_ids_for(courted_id)
    for name in BUCKET_NAMES:
        blob[name] = [x for x in (blob.get(name) or []) if x not in alt_ids]
    if bucket in BUCKET_NAMES:
        blob[bucket].append(courted_id)
    save_buckets(blob)
    return blob



def run_sync():
    print("Starting sync...", flush=True)
    errors = []
    courted = CourtedClient(CFG)
    if courted.health_check():
        print("  Courted /health: ok", flush=True)
    else:
        print("  Courted /health: failed (continuing anyway)", flush=True)

    # Pull FUB first — needed by fub_mls mode AND by all modes for matching/enrichment
    fub = FUBClient(CFG)
    people = []
    def _atomic_write_json(path, obj, indent=2):
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(obj, indent=indent, default=str), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass
    try:
        fub.load_custom_fields()
        _atomic_write_json(DATA_DIR / "fub_custom_fields.json", fub.custom_field_map)
        print(f"  FUB: loaded {len(fub.custom_field_map)} custom field mappings", flush=True)
        people = fub.list_people()
        print(f"  FUB: pulled {len(people)} people", flush=True)
        if people:
            _atomic_write_json(DATA_DIR / "sample_fub_person.json", people[0])
    except Exception as e:
        errors.append(f"FUB pull failed: {e}")

    # Share the custom-field map with the Courted client (so fub_mls mode can resolve labels)
    courted.custom_field_map = fub.custom_field_map

    try:
        agents_raw = courted.fetch_agents(fub_people=people)
        print(f"  Courted: pulled {len(agents_raw)} agents", flush=True)
        # CSV fallback: if Courted returned 0 (rate limited / quota exhausted),
        # try loading from data/courted_agents.csv (same file csv_mode.py uses).
        if not agents_raw:
            csv_path = DATA_DIR / "courted_agents.csv"
            if csv_path.exists():
                import csv
                def _bool(v):
                    return str(v).strip().lower() in ("true", "yes", "y", "1", "t")
                def _num(v):
                    if v in (None, ""): return 0
                    s = str(v).replace(",", "").replace("$", "").strip()
                    try: return float(s) if "." in s else int(s)
                    except: return 0
                with open(csv_path, encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.DictReader(f))
                # Coerce common fields
                for r in rows:
                    for k in ("ltm_sales_volume","ltm_closed_units","ltm_closed_units_buy_side","ltm_closed_units_list_side","ltm_avg_sale_price","ltm_est_gci","prev_ltm_sales_volume","prev_ltm_closed_units","prev_ltm_avg_sale_price","sales_volume_prediction","active_listings","pending_listings","agent_tenure","time_at_current_office","office_rank","office_roster_count"):
                        if k in r: r[k] = _num(r[k])
                    for k in ("at_ready_to_move","at_trouble_at_office","at_decreasing_sales","at_fresh_talent"):
                        if k in r: r[k] = _bool(r[k])
                agents_raw = rows
                print(f"  CSV fallback: loaded {len(agents_raw)} agents from data/courted_agents.csv", flush=True)
            else:
                print(f"  CSV fallback: data/courted_agents.csv not found — falling back to FUB people", flush=True)
        # FUB fallback: if still empty AND we have cached FUB people, build agents from them.
        # No production data (LTM volume etc), but you get the call list with names/photos/contact info.
        if not agents_raw and people:
            print(f"  FUB fallback: building agent list from {len(people)} cached FUB people", flush=True)
            # Resolve photo_url + courted_id custom field keys
            cf_map = fub.custom_field_map or {}
            def _cf_key(label):
                if not label: return None
                if label in cf_map: return cf_map[label]
                t = label.strip().lower()
                for lbl, k in cf_map.items():
                    if lbl.strip().lower() == t: return k
                return None
            photo_key = _cf_key(CFG.get("fub_custom_fields", {}).get("photo_url"))
            cid_key = _cf_key(CFG.get("fub_custom_fields", {}).get("courted_id"))
            rows = []
            for p in people:
                emails = p.get("emails") or []
                phones = p.get("phones") or []
                email = (emails[0] or {}).get("value", "") if emails else ""
                phone = (phones[0] or {}).get("value", "") if phones else ""
                rows.append({
                    "courted_id": (p.get(cid_key) if cid_key else "") or f"fub-{p.get('id')}",
                    "first_name": p.get("firstName") or "",
                    "last_name": p.get("lastName") or "",
                    "email": email,
                    "phone": phone,
                    "agent_photo": (p.get(photo_key) if photo_key else "") or "",
                    "agent_office_name": p.get("assignedLenderName") or "",
                    "ltm_sales_volume": 0, "ltm_closed_units": 0,
                    "at_ready_to_move": False, "at_trouble_at_office": False,
                    "at_decreasing_sales": False, "at_fresh_talent": False,
                })
            agents_raw = rows
            print(f"  FUB fallback: built {len(agents_raw)} agent records from FUB cache", flush=True)
        if agents_raw:
            all_keys = sorted(list(agents_raw[0].keys()))
            print(f"  First agent has {len(all_keys)} fields: {all_keys}", flush=True)
            try:
                sample_path = DATA_DIR / "sample_agent.json"
                sample_path.write_text(json.dumps(agents_raw[0], indent=2, default=str), encoding="utf-8")
                # Summarize which production fields actually have non-zero values
                production_fields = ["ltm_sales_volume","ltm_closed_units","ltm_closed_units_buy_side","ltm_closed_units_list_side","ltm_avg_sale_price","ltm_est_gci","prev_ltm_sales_volume","prev_ltm_closed_units","prev_ltm_avg_sale_price","sales_volume_prediction","agent_tenure","time_at_current_office","office_rank","office_roster_count","active_listings","pending_listings"]
                summary = {f: agents_raw[0].get(f) for f in production_fields}
                non_zero = {k: v for k, v in summary.items() if v not in (None, 0, "", 0.0)}
                print(f"  Production fields with values on agent 1: {non_zero or '(none — pipeline endpoint returns thin records)'}", flush=True)
            except Exception as e:
                print(f"  Could not write sample: {e}", flush=True)
    except Exception as e:
        errors.append(f"Courted pull failed: {e}")
        agents_raw = []

    by_email, by_phone = index_fub_people(people)
    overrides = load_overrides()
    print(f"  Local overrides loaded for {len(overrides)} agents (from data/agent_overrides.json)", flush=True)
    today = date.today().isoformat()
    weights = CFG.get("scoring_weights", {})
    tag_today = CFG.get("fub_called_tag_template", "called-{date}").format(date=today)
    # Resolve birthday + anniversary custom field keys (case-insensitive, with whitespace trim).
    # Also accept the configured value AS the direct field key if no label match found.
    def _resolve_key(label):
        if not label: return None
        if label in fub.custom_field_map:
            return fub.custom_field_map[label]
        target = label.strip().lower()
        for lbl, k in fub.custom_field_map.items():
            if lbl.strip().lower() == target:
                return k
        # Also check if any internal key matches the configured value
        for k in fub.custom_field_map.values():
            if k.lower() == target:
                return k
        # Last resort: assume the config value IS the field key, even if not in map
        return label
    bday_label = CFG.get("fub_custom_fields", {}).get("birthday")
    bday_key = _resolve_key(bday_label)
    anni_label = CFG.get("fub_custom_fields", {}).get("anniversary")
    anni_key = _resolve_key(anni_label)
    print(f"  FUB custom fields resolved: birthday={bday_label!r} -> {bday_key!r}, anniversary={anni_label!r} -> {anni_key!r}", flush=True)
    if not bday_key or not anni_key:
        # Show what labels DO exist so user can see exact spelling
        labels = sorted(fub.custom_field_map.keys())[:30]
        print(f"  Available FUB custom field labels (first 30): {labels}", flush=True)
    enriched = []
    for a in agents_raw:
        m = match_fub(a, by_email, by_phone)
        called_today = False
        fub_id = None
        birthday = None
        anniversary = None
        tags = []
        if m:
            fub_id = m.get("id")
            tags = list(m.get("tags") or [])
            called_today = tag_today in tags
            # Try the custom field first (per user config); fall back to FUB built-in birthday
            if bday_key:
                birthday = m.get(bday_key) or None
            if not birthday:
                birthday = m.get("birthday") or None
            if anni_key:
                anniversary = m.get(anni_key) or None
            # FUB data quirk: the SREG anniversary field is defined as 'customSREGAnniversary'
            # but actual person records store it under the misspelled key 'customSREGAniversary'
            # (missing one 'n'). Try both, prefer whichever has a value.
            if not anniversary:
                anniversary = m.get("customSREGAniversary") or m.get("customSREGAnniversary") or None
        a["_fub_id"] = fub_id
        a["_called_today"] = called_today
        a["_birthday"] = birthday
        a["_anniversary"] = anniversary
        a["_tags"] = tags
        # Apply local overrides (user-entered dates take precedence)
        ov = overrides.get(a.get("courted_id"), {}) if overrides else {}
        if ov.get("birthday"): a["_birthday"] = ov["birthday"]
        if ov.get("anniversary"): a["_anniversary"] = ov["anniversary"]
        a["_score"] = score_agent(a, weights, called_today)
        enriched.append(a)
    # Compute the 85th-percentile threshold of LTM sales volume — top 15% of the pulled market
    volumes = sorted([(a.get("ltm_sales_volume") or 0) for a in enriched if (a.get("ltm_sales_volume") or 0) > 0], reverse=True)
    top15_threshold = 0
    if volumes:
        cutoff_index = max(0, int(len(volumes) * 0.15) - 1)
        top15_threshold = volumes[cutoff_index]
        print(f"  Top-15% threshold: ${top15_threshold:,.0f} (over {len(volumes)} producers; {cutoff_index+1} agents qualify)", flush=True)
    for a in enriched:
        vol = a.get("ltm_sales_volume") or 0
        a["_top_15_percent"] = bool(vol and top15_threshold and vol >= top15_threshold)

    # Add stubs for any agents that are bucketed under legacy fub-NNN IDs but not present in the
    # current pull (so they remain visible in their Warm/Nurture/Hot tab).
    try:
        buckets_blob = load_buckets()
        bucketed_fub_ids = set()
        for bname in BUCKET_NAMES:
            for cid in (buckets_blob.get(bname) or []):
                if isinstance(cid, str) and cid.startswith("fub-"):
                    try: bucketed_fub_ids.add(int(cid[4:]))
                    except ValueError: pass
        existing_fub_ids = {a.get("_fub_id") for a in enriched if a.get("_fub_id")}
        missing = bucketed_fub_ids - existing_fub_ids
        if missing and people:
            cf_map = fub.custom_field_map or {}
            def _cf(label):
                if not label: return None
                if label in cf_map: return cf_map[label]
                t = label.strip().lower()
                for lbl, k in cf_map.items():
                    if lbl.strip().lower() == t: return k
                return None
            photo_key = _cf(CFG.get("fub_custom_fields", {}).get("photo_url"))
            bday_key = _cf(CFG.get("fub_custom_fields", {}).get("birthday"))
            anni_key = _cf(CFG.get("fub_custom_fields", {}).get("anniversary"))
            added = 0
            for p in people:
                if p.get("id") in missing:
                    emails = p.get("emails") or []; phones = p.get("phones") or []
                    em = (emails[0] or {}).get("value", "") if emails else ""
                    ph = (phones[0] or {}).get("value", "") if phones else ""
                    stub = {
                        "courted_id": f"fub-{p.get('id')}",
                        "first_name": p.get("firstName") or "",
                        "last_name": p.get("lastName") or "",
                        "email": em, "phone": ph,
                        "agent_photo": (p.get(photo_key) if photo_key else "") or "",
                        "current_office_name": p.get("assignedLenderName") or "",
                        "ltm_sales_volume": 0, "ltm_closed_units": 0,
                        "_fub_id": p.get("id"),
                        "_called_today": False, "_tags": list(p.get("tags") or []),
                        "_birthday": (p.get(bday_key) if bday_key else None) or p.get("birthday") or None,
                        "_anniversary": (p.get(anni_key) if anni_key else None) or p.get("customSREGAniversary") or p.get("customSREGAnniversary") or None,
                        "_score": 0, "_top_15_percent": False,
                    }
                    enriched.append(stub); added += 1
            if added:
                print(f"  Added {added} bucketed-agent stubs from FUB cache (legacy bucket IDs)", flush=True)
    except Exception as e:
        print(f"  Bucket stub build failed: {e}", flush=True)

    # Tell the user how many celebrants matched today (so it's obvious when birthday/anniversary
    # priority is or isn't doing anything to the ranking).
    bday_today = sum(1 for a in enriched if a.get("_birthday_today"))
    anni_today = sum(1 for a in enriched if a.get("_anniversary_today"))
    if bday_today or anni_today:
        print(f"  Celebrants today: {bday_today} birthday, {anni_today} anniversary — boosted to top of list", flush=True)
    else:
        print(f"  No birthdays or anniversaries today — using standard ranking", flush=True)

    enriched.sort(key=lambda x: x["_score"], reverse=True)
    # Guard: if this sync returned far fewer agents than we already had, keep the old data.
    # Protects against partial Courted pulls (e.g., 1000-record session cap returning a tiny slice).
    prev_count = len(STATE.get("agents") or [])
    if prev_count >= 50 and len(enriched) < max(10, prev_count // 4):
        msg = f"new sync returned only {len(enriched)} agents vs {prev_count} previously — keeping previous data"
        print(f"  {msg}", flush=True)
        errors.append(msg)
    else:
        STATE["agents"] = enriched
    STATE["last_sync"] = datetime.now().isoformat(timespec="seconds")
    STATE["errors"] = errors

    # Diagnostic: scan matched FUB contacts for ANY populated birthday/anniversary-like field
    # (across native + every custom field), so we can see if the data exists anywhere.
    matched_people = []
    for a in enriched:
        if a.get("_fub_id"):
            cid = a.get("courted_id")
            for p in people:
                if p.get("id") == a["_fub_id"]:
                    matched_people.append(p); break
    if matched_people:
        # Build reverse map: internal key -> label
        key_to_label = {v: k for k, v in fub.custom_field_map.items()}
        bday_keys = [k for k, lbl in key_to_label.items() if "birthday" in lbl.lower() or "bday" in lbl.lower()]
        anni_keys = [k for k, lbl in key_to_label.items() if "anniv" in lbl.lower()]
        native_bday_count = sum(1 for p in matched_people if p.get("birthday"))
        print(f"  Scan of {len(matched_people)} matched FUB contacts:", flush=True)
        print(f"    - native 'birthday' field populated: {native_bday_count}", flush=True)
        for k in bday_keys:
            n = sum(1 for p in matched_people if p.get(k))
            print(f"    - custom '{key_to_label[k]}' populated: {n}", flush=True)
        for k in anni_keys:
            n = sum(1 for p in matched_people if p.get(k))
            print(f"    - custom '{key_to_label[k]}' populated: {n}", flush=True)
        # Also count the typoed key (where FUB actually stores SREG anniversary data)
        typoed_anni_count = sum(1 for p in matched_people if p.get("customSREGAniversary"))
        print(f"    - custom 'customSREGAniversary' (typoed key — actual data location): {typoed_anni_count}", flush=True)
        # Show an example of one matched contact that has ANY date-like value, with its keys
        for p in matched_people:
            populated = []
            if p.get("birthday"): populated.append(("birthday (native)", p.get("birthday")))
            for k in bday_keys + anni_keys:
                if p.get(k): populated.append((key_to_label[k], p.get(k)))
            if populated:
                print(f"    Example contact id={p.get('id')} ({p.get('firstName','?')} {p.get('lastName','?')}):", flush=True)
                for label, val in populated:
                    print(f"      {label}: {val}", flush=True)
                break
        else:
            print(f"    No matched contact has any date-like field populated in FUB.", flush=True)

    # Diagnostic: top 5 ranked agents with key stats
    print("  Top 5 by score:", flush=True)
    for i, a in enumerate(enriched[:5], 1):
        name = f"{a.get('first_name','?')} {a.get('last_name','?')}"
        off = a.get('current_office_name', '?')
        vol = a.get('ltm_sales_volume') or 0
        units = a.get('ltm_closed_units') or 0
        prev_vol = a.get('prev_ltm_sales_volume') or 0
        sigs = []
        if a.get('at_ready_to_move'): sigs.append('ready')
        if a.get('at_trouble_at_office'): sigs.append('trouble')
        if a.get('at_decreasing_sales'): sigs.append('decreasing')
        if a.get('at_fresh_talent'): sigs.append('fresh')
        sigs_str = ','.join(sigs) or '-'
        print(f"    #{i} score={a['_score']:.1f}  {name:<25}  vol=${vol:>13,.0f}  prev=${prev_vol:>13,.0f}  units={units:>3}  [{sigs_str}]  @{off}", flush=True)
    # Count agents with non-zero LTM volume
    have_vol = sum(1 for a in enriched if (a.get('ltm_sales_volume') or 0) > 0)
    print(f"  {have_vol} of {len(enriched)} agents have non-zero LTM sales volume", flush=True)
    try:
        # Atomic write so an interrupted process can't truncate this file (it's read at startup).
        tmp_cache = CACHE_PATH.with_suffix(CACHE_PATH.suffix + ".tmp")
        with open(tmp_cache, "w", encoding="utf-8") as f:
            json.dump({"last_sync": STATE["last_sync"], "agents": enriched[:200]}, f, indent=2, default=str)
        tmp_cache.replace(CACHE_PATH)
    except Exception:
        pass
    top = enriched[0]["_score"] if enriched else 0
    print(f"  Done. {len(enriched)} agents ranked. Top score: {top:.1f}", flush=True)
    if errors:
        print("  Errors:")
        for e in errors: print(f"    - {e}")


def _create_fub_from_courted(fub, agent):
    payload = {
        "firstName": agent.get("first_name") or "",
        "lastName": agent.get("last_name") or "",
        "stage": "Lead", "source": "Courted",
        "emails": [{"value": agent["email"]}] if agent.get("email") else [],
        "phones": [{"value": p} for p in [agent.get("mobile_phone"), agent.get("phone")] if p],
    }
    cf = CFG.get("fub_custom_fields", {})
    cid = cf.get("courted_id"); pf = cf.get("photo_url")
    if cid and cid in fub.custom_field_map:
        payload[fub.custom_field_map[cid]] = agent.get("courted_id")
    if pf and pf in fub.custom_field_map and agent.get("agent_photo"):
        payload[fub.custom_field_map[pf]] = agent["agent_photo"]
    return fub.create_person(payload).get("id")


def fub_mark_called(courted_id, called):
    if CFG.get("dry_run"): return {"ok": True, "dry_run": True}
    a = next((x for x in STATE["agents"] if x.get("courted_id") == courted_id), None)
    if not a: return {"ok": False, "error": "agent not in current sync"}
    fub = FUBClient(CFG); fub.load_custom_fields()
    fub_id = a.get("_fub_id")
    if not fub_id:
        if not CFG.get("auto_create_in_fub"):
            return {"ok": False, "error": "agent not in FUB. Set auto_create_in_fub=true or add them in FUB manually."}
        try:
            fub_id = _create_fub_from_courted(fub, a); a["_fub_id"] = fub_id
        except Exception as e:
            return {"ok": False, "error": f"auto-create failed: {e}"}
    today = date.today().isoformat()
    tag = CFG.get("fub_called_tag_template", "called-{date}").format(date=today)
    try:
        person = fub._get(f"/people/{fub_id}")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    tags = list(person.get("tags") or [])
    if called and tag not in tags: tags.append(tag)
    elif not called and tag in tags: tags = [t for t in tags if t != tag]
    payload = {"tags": tags}
    lc = CFG.get("fub_custom_fields", {}).get("last_called")
    if lc and lc in fub.custom_field_map:
        payload[fub.custom_field_map[lc]] = datetime.now().isoformat() if called else None
    try:
        fub.update_person(fub_id, payload)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    a["_called_today"] = called
    a["_score"] = score_agent(a, CFG.get("scoring_weights", {}), called)
    STATE["agents"].sort(key=lambda x: x["_score"], reverse=True)
    return {"ok": True}


def fub_add_note(courted_id, body):
    if CFG.get("dry_run"): return {"ok": True, "dry_run": True}
    if not body or not body.strip(): return {"ok": False, "error": "empty note"}
    a = next((x for x in STATE["agents"] if x.get("courted_id") == courted_id), None)
    if not a or not a.get("_fub_id"): return {"ok": False, "error": "agent not in FUB"}
    try:
        FUBClient(CFG).add_note(a["_fub_id"], body.strip())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def fub_log_call(courted_id, outcome="Reached", duration_seconds=300, note=""):
    """Log a call event to FUB so it shows in the agent's activity timeline."""
    if CFG.get("dry_run"): return {"ok": True, "dry_run": True}
    a = next((x for x in STATE["agents"] if x.get("courted_id") == courted_id), None)
    if not a or not a.get("_fub_id"): return {"ok": False, "error": "agent not in FUB"}
    try:
        FUBClient(CFG).log_call(a["_fub_id"], outcome=outcome, duration_seconds=duration_seconds, note=note)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def fub_push_photo_urls():
    if CFG.get("dry_run"): return {"ok": True, "dry_run": True, "updated": 0}
    fub = FUBClient(CFG); fub.load_custom_fields()
    label = CFG.get("fub_custom_fields", {}).get("photo_url")
    key = fub.custom_field_map.get(label)
    if not key:
        return {"ok": False, "error": f"FUB custom field '{label}' not found. Create it in FUB Admin > Custom Fields."}
    n = 0
    for a in STATE["agents"]:
        if not a.get("_fub_id") or not a.get("agent_photo"): continue
        try:
            fub.update_person(a["_fub_id"], {key: a["agent_photo"]}); n += 1; time.sleep(0.1)
        except Exception:
            continue
    return {"ok": True, "updated": n}


app = Flask(__name__, template_folder=str(ROOT / "templates"))


def public_agent(a, rank):
    cid = a.get("courted_id") or a.get("id")
    mls = a.get("mls_id") or ""
    # Courted's web URL uses the combo "courted_id_MLS" (e.g., "7aa61d6c..._GLVAR").
    # Prefer the explicit combo field if present; otherwise build it from courted_id + mls_id.
    courted_mls_id = a.get("courted_mls_id") or (f"{cid}_{mls}" if cid and mls else cid or "")
    fub_id = a.get("_fub_id")
    fub_url_tmpl = CFG.get("fub_web_url", "https://app.followupboss.com/2/people/view/{id}")
    courted_url_tmpl = CFG.get("courted_web_url", "https://brokerage.courted.io/candidates/agent_{courted_mls_id}")
    fub_url = fub_url_tmpl.format(id=fub_id) if fub_id else ""
    courted_url = ""
    if courted_mls_id:
        try:
            courted_url = courted_url_tmpl.format(courted_id=cid or "", courted_mls_id=courted_mls_id, mls_id=mls)
        except Exception:
            courted_url = ""
    return {
        "rank": rank,
        "courted_id": cid,
        "first_name": a.get("first_name") or "",
        "last_name": a.get("last_name") or "",
        "email": a.get("email") or "",
        "phone": a.get("mobile_phone") or a.get("phone") or "",
        "office": a.get("current_office_name") or "",
        "city": a.get("most_transacted_city") or a.get("current_office_city") or "",
        "state": a.get("current_office_state") or "",
        "photo": a.get("agent_photo") or "",
        "ltm_sales_volume": a.get("ltm_sales_volume") or 0,
        "ltm_closed_units": a.get("ltm_closed_units") or 0,
        "ltm_closed_units_buy": a.get("ltm_closed_units_buy_side") or 0,
        "ltm_closed_units_list": a.get("ltm_closed_units_list_side") or 0,
        "ltm_avg_sale_price": a.get("ltm_avg_sale_price") or 0,
        "ltm_est_gci": a.get("ltm_est_gci") or 0,
        "prev_ltm_sales_volume": a.get("prev_ltm_sales_volume") or 0,
        "prev_ltm_closed_units": a.get("prev_ltm_closed_units") or 0,
        "prev_ltm_avg_sale_price": a.get("prev_ltm_avg_sale_price") or 0,
        "sales_volume_prediction": a.get("sales_volume_prediction") or 0,
        "active_listings": a.get("active_listings") or 0,
        "pending_listings": a.get("pending_listings") or 0,
        "agent_tenure": a.get("agent_tenure") or 0,
        "time_at_current_office": a.get("time_at_current_office") or 0,
        "office_rank": a.get("office_rank") or 0,
        "office_roster_count": a.get("office_roster_count") or 0,
        "ready_to_move": bool(a.get("at_ready_to_move")),
        "trouble_at_office": bool(a.get("at_trouble_at_office")),
        "decreasing_sales": bool(a.get("at_decreasing_sales")),
        "fresh_talent": bool(a.get("at_fresh_talent")),
        "predicted_growth": bool((a.get("sales_volume_prediction") or 0) > (a.get("ltm_sales_volume") or 0)),
        "top_15_percent": bool(a.get("_top_15_percent")),
        "called": bool(a.get("_called_today")),
        "in_fub": bool(fub_id),
        "birthday": a.get("_birthday") or "",
        "anniversary": a.get("_anniversary") or "",
        "fub_url": fub_url,
        "courted_url": courted_url,
        "tags": a.get("_tags") or [],
        "score": round(a.get("_score") or 0, 1),
        "bucket": a.get("_bucket") or "",
        "skipped": bool(a.get("_skipped")),
        "birthday_today": bool(a.get("_birthday_today")),
        "anniversary_today": bool(a.get("_anniversary_today")),
        "group": a.get("_group") or "",
    }


@app.route("/")
def index():
    return render_template("dashboard.html", top_n=CFG.get("top_n", 10), dry_run=CFG.get("dry_run", True))


@app.route("/api/agents")
def api_agents():
    n = int(request.args.get("n", CFG.get("top_n", 10)))
    show_all = request.args.get("all") == "1"
    source = (CFG.get("courted_source") or "pipeline").lower()
    visible = STATE["agents"] if show_all else STATE["agents"][:max(n * 3, 30)]
    # Lazy enrichment: fetch Courted data only for visible stubs (fub_email/fub_mls modes)
    if source in ("fub_email", "fub_mls"):
        courted = CourtedClient(CFG)
        cache_path = DATA_DIR / "courted_by_email.json"
        cache = {}
        if cache_path.exists():
            try: cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception: cache = {}
        fetched_any = False
        for a in visible:
            if not a.get("_lazy"): continue
            email = a.get("email")
            if not email: continue
            rec = cache.get(email)
            if rec is None or not isinstance(rec, dict):
                fetched = courted.get_agent_by_email(email)
                cache[email] = {"_cached_at": time.time(), "data": fetched}
                fetched_any = True
            else:
                fetched = rec.get("data")
            if fetched:
                for k, v in fetched.items():
                    if k not in a or not a[k]:
                        a[k] = v
            a["_lazy"] = False
            fid = a.get("_fub_id_hint")
            if fid:
                a["_fub_id"] = fid
            a["_score"] = score_agent(a, CFG.get("scoring_weights", {}), bool(a.get("_called_today")))
        if fetched_any:
            try: cache_path.write_text(json.dumps(cache), encoding="utf-8")
            except Exception: pass
            STATE["agents"].sort(key=lambda x: x.get("_score") or 0, reverse=True)
    # Skipped agents are DEMOTED (pushed to the bottom of the list), not hidden.
    # They auto-reset at midnight (per-day skip list), so tomorrow they rank normally again.
    skipped = get_skipped_today()
    # Build lookup: id -> bucket name
    buckets_blob = load_buckets()
    bucket_of = {}
    for bname in BUCKET_NAMES:
        for cid in (buckets_blob.get(bname) or []):
            bucket_of[cid] = bname
    def _agent_ids(a):
        """All identifiers an agent might be saved under in buckets/skipped (handles cross-source ID drift)."""
        ids = []
        if a.get("courted_id"): ids.append(a["courted_id"])
        if a.get("_fub_id"): ids.append(f"fub-{a['_fub_id']}")
        return ids
    def _bucket_for(a):
        for aid in _agent_ids(a):
            if aid in bucket_of: return bucket_of[aid]
        return None
    def _is_skipped(a):
        return any(aid in skipped for aid in _agent_ids(a))
    bucket_filter = (request.args.get("bucket") or "").strip().lower()
    pool_active, pool_skipped = [], []

    # Coops tab: served from FUB Smart List 21 (10/day, deterministic), bypasses the main pool entirely.
    if bucket_filter == "coops":
        coops_agents = get_coops_for_today()
        for a in coops_agents:
            a["_bucket"] = _bucket_for(a)
            a["_skipped"] = _is_skipped(a)
        pool_active = coops_agents
    elif not bucket_filter:
        # Top ten tab: pool is SREG agents from FUB only (their own agents, for management).
        # Brokerage chips (Green Valley / Utah / Southwest / Northwest) sub-filter this set on the frontend.
        sreg_pool = get_sreg_agents_from_fub()
        skipped_blank = 0
        for a in sreg_pool:
            # Skip records that have neither tags nor an office name (incomplete entries).
            has_tags = bool(a.get("_tags"))
            has_office = bool((a.get("current_office_name") or "").strip())
            if not has_tags and not has_office:
                skipped_blank += 1
                continue
            b = _bucket_for(a)
            # Hide bucketed from the main view; skipped go to bottom
            if b: continue
            a["_bucket"] = b
            a["_skipped"] = _is_skipped(a)
            (pool_skipped if a["_skipped"] else pool_active).append(a)
        print(f"  Top ten: pool of {len(pool_active)} SREG agents (from FUB)" + (f", {skipped_blank} blank records skipped" if skipped_blank else ""), flush=True)
    else:
        for a in STATE["agents"]:
            # Top ten tab shows all agents (with or without FUB match), so birthday/anniversary
            # display "NA" gracefully but the agent still appears. Other tabs require FUB match
            # so writes like "Mark called" / "Save note" can actually go through.
            if bucket_filter and not a.get("_fub_id"):
                continue
            cid = a.get("courted_id")
            b = _bucket_for(a)
            if bucket_filter in BUCKET_NAMES:
                # Showing a specific Warm/Nurture/Hot bucket
                if b != bucket_filter: continue
            elif bucket_filter == "birthday":
                if not a.get("_birthday_today"): continue
            elif bucket_filter == "anniversary":
                if not a.get("_anniversary_today"): continue
            else:
                # Default Call list view: hide already-bucketed agents
                if b: continue
            a["_bucket"] = b
            a["_skipped"] = _is_skipped(a)
            (pool_skipped if a["_skipped"] else pool_active).append(a)
    # Top ten tab — daily rotation through the SREG pool. Each day shows 5 from the top
    # (most transactions, advancing through the list) and 5 from the bottom (least), so over
    # time you cycle through every SREG agent. With ~15K agents, full coverage takes ~1,500 days.
    if not bucket_filter and pool_active:
        # Clear any stale _group flags from previous calls
        for a in pool_active: a.pop("_group", None)
        # Stable sort: by closed deals desc, then by name (ensures deterministic rotation)
        sorted_pool = sorted(
            pool_active,
            key=lambda a: (-(a.get("ltm_closed_units") or 0), (a.get("first_name") or "") + (a.get("last_name") or ""))
        )
        total = len(sorted_pool)
        # Day index seeded from a fixed epoch so the same window shows all day, advances tomorrow
        import datetime as _dt
        day_idx = (date.today() - _dt.date(2026, 1, 1)).days
        # Rotation length: how many days to fully traverse the list at 10/day. Cycles back to start.
        rotation_len = max(1, (total + 9) // 10)
        cycle_idx = day_idx % rotation_len
        # 5 from the top side, advancing forward each day
        top_start = cycle_idx * 5
        top_5 = sorted_pool[top_start : top_start + 5]
        # 5 from the bottom side, advancing inward each day
        bottom_end = total - cycle_idx * 5
        bottom_start = max(top_start + 5, bottom_end - 5)  # prevent overlap with top half
        bottom_5 = sorted_pool[bottom_start : bottom_end]
        for a in top_5: a["_group"] = "most"
        for a in bottom_5: a["_group"] = "least"
        combined = top_5 + bottom_5
        if combined:
            # Per-agent Courted enrichment: for the 10 agents we're about to display,
            # fetch their production data from Courted by email. Cached per-email so we
            # don't re-fetch the same agent every page load.
            try:
                courted_client = CourtedClient(CFG)
                lookup_cache_path = DATA_DIR / "courted_by_email.json"
                lookup_cache = {}
                if lookup_cache_path.exists():
                    try: lookup_cache = json.loads(lookup_cache_path.read_text(encoding="utf-8"))
                    except Exception: lookup_cache = {}
                now_ts = time.time()
                CACHE_TTL_DAYS = 7
                enriched_live = 0
                for stub in combined:
                    # Skip if already has Courted data (matched from pipeline cache)
                    if stub.get("ltm_closed_units") or stub.get("ltm_sales_volume") or stub.get("agent_tenure"):
                        continue
                    email = (stub.get("email") or "").lower().strip()
                    if not email: continue
                    rec = lookup_cache.get(email)
                    if rec and isinstance(rec, dict) and (now_ts - (rec.get("_cached_at") or 0)) < CACHE_TTL_DAYS * 86400:
                        data = rec.get("data")
                    else:
                        try:
                            data = courted_client.get_agent_by_email(email)
                        except Exception:
                            data = None
                        lookup_cache[email] = {"_cached_at": now_ts, "data": data}
                    if data and isinstance(data, dict):
                        # Copy production fields from Courted record
                        for k in ("ltm_sales_volume", "ltm_closed_units", "ltm_closed_units_buy_side",
                                  "ltm_closed_units_list_side", "ltm_avg_sale_price", "ltm_est_gci",
                                  "prev_ltm_sales_volume", "prev_ltm_closed_units", "prev_ltm_avg_sale_price",
                                  "sales_volume_prediction", "active_listings", "pending_listings",
                                  "agent_tenure", "time_at_current_office", "office_rank", "office_roster_count",
                                  "current_office_name", "brand_name", "mls_id", "member_mls_id",
                                  "courted_mls_id", "at_ready_to_move", "at_trouble_at_office",
                                  "at_decreasing_sales", "at_fresh_talent", "agent_photo"):
                            v = data.get(k)
                            if v not in (None, "", 0):
                                stub[k] = v
                        enriched_live += 1
                try: lookup_cache_path.write_text(json.dumps(lookup_cache, default=str), encoding="utf-8")
                except Exception: pass
                if enriched_live:
                    print(f"  Top ten: live-enriched {enriched_live} agents from Courted by email lookup", flush=True)
            except Exception as e:
                print(f"  Top ten: Courted enrichment failed: {e}", flush=True)
            pool_active = combined
            print(f"  Top ten: day-{day_idx} window — top[{top_start}:{top_start+5}] + bottom[{bottom_start}:{bottom_end}] of {total} SREG agents (rotation day {cycle_idx+1}/{rotation_len})", flush=True)
        else:
            print(f"  Top-ten rotation produced no agents from pool of {len(pool_active)} — keeping original ordering", flush=True)
    # Skipped agents sink to the bottom (but still appear once you've worked through the rest).
    pool = pool_active + pool_skipped
    agents = pool if show_all else pool[:n]
    # Counts for special tabs (so the UI can show "Birthday 2" / "Coops 10" etc.)
    bday_count = sum(1 for a in STATE["agents"] if a.get("_fub_id") and a.get("_birthday_today"))
    anni_count = sum(1 for a in STATE["agents"] if a.get("_fub_id") and a.get("_anniversary_today"))
    # Coops count: if already cached for today, use that length; else show 0 until first fetch.
    coops_count = 0
    try:
        if COOPS_CACHE_PATH.exists():
            blob = json.loads(COOPS_CACHE_PATH.read_text(encoding="utf-8"))
            if blob.get("date") == date.today().isoformat():
                coops_count = len(blob.get("agents") or [])
    except Exception:
        pass
    return jsonify({
        "last_sync": STATE["last_sync"], "errors": STATE["errors"],
        "dry_run": CFG.get("dry_run", True), "total": len(pool),
        "skipped_today": sorted(skipped),
        "buckets_counts": {b: len(buckets_blob.get(b) or []) for b in BUCKET_NAMES},
        "special_counts": {"coops": coops_count, "birthday": bday_count, "anniversary": anni_count},
        "agents": [public_agent(a, i + 1) for i, a in enumerate(agents)],
    })


@app.route("/api/called/<courted_id>", methods=["POST"])
def api_called(courted_id):
    b = request.get_json(silent=True) or {}
    return jsonify(fub_mark_called(courted_id, bool(b.get("called", True))))


@app.route("/api/skip/<courted_id>", methods=["POST"])
def api_skip(courted_id):
    """Skip an agent for today (auto-resets at midnight). Body: {skip: true|false}."""
    b = request.get_json(silent=True) or {}
    skip = bool(b.get("skip", True))
    day_list = set_skipped(courted_id, skip)
    return jsonify({"ok": True, "skipped": skip, "count_today": len(day_list)})


@app.route("/api/bucket/<courted_id>", methods=["POST"])
def api_bucket(courted_id):
    """Move an agent to a bucket ('warm' | 'nurture' | 'hot') or remove with null/empty."""
    b = request.get_json(silent=True) or {}
    bucket = (b.get("bucket") or "").strip().lower()
    if bucket and bucket not in BUCKET_NAMES:
        return jsonify({"ok": False, "error": f"unknown bucket '{bucket}'. Use one of: {list(BUCKET_NAMES)}"}), 400
    blob = set_bucket(courted_id, bucket or None)
    return jsonify({"ok": True, "bucket": bucket or None,
                    "counts": {n: len(blob.get(n) or []) for n in BUCKET_NAMES}})


@app.route("/api/note/<courted_id>", methods=["POST"])
def api_note(courted_id):
    b = request.get_json(silent=True) or {}
    return jsonify(fub_add_note(courted_id, b.get("note", "")))


@app.route("/api/log-call/<courted_id>", methods=["POST"])
def api_log_call(courted_id):
    """Log a call activity to FUB so it appears on the contact's timeline.
    Body: {outcome, duration_seconds, note}"""
    b = request.get_json(silent=True) or {}
    outcome = (b.get("outcome") or "Reached").strip()
    duration = int(b.get("duration_seconds") or 300)
    note = b.get("note") or ""
    return jsonify(fub_log_call(courted_id, outcome=outcome, duration_seconds=duration, note=note))


@app.route("/api/dates/<courted_id>", methods=["POST"])
def api_dates(courted_id):
    """Save user-entered birthday/anniversary to a local overrides file. Updates in-memory state."""
    body = request.get_json(silent=True) or {}
    overrides = load_overrides()
    rec = overrides.setdefault(courted_id, {})
    if "birthday" in body:
        rec["birthday"] = (body.get("birthday") or "").strip() or None
        if rec["birthday"] is None: rec.pop("birthday", None)
    if "anniversary" in body:
        rec["anniversary"] = (body.get("anniversary") or "").strip() or None
        if rec["anniversary"] is None: rec.pop("anniversary", None)
    if not rec:
        overrides.pop(courted_id, None)
    save_overrides(overrides)
    # Update in-memory record so dashboard sees the new values without re-sync
    a = next((x for x in STATE["agents"] if x.get("courted_id") == courted_id), None)
    if a:
        a["_birthday"] = rec.get("birthday")
        a["_anniversary"] = rec.get("anniversary")
    return jsonify({"ok": True})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    run_sync()
    return jsonify({"ok": True, "last_sync": STATE["last_sync"]})


@app.route("/api/debug/<courted_id>")
def api_debug(courted_id):
    """Returns the agent record + the matched FUB person record so we can verify
    whether birthday/anniversary are actually present in FUB for this person."""
    a = next((x for x in STATE["agents"] if x.get("courted_id") == courted_id), None)
    if not a:
        return jsonify({"error": f"agent {courted_id} not in STATE"}), 404
    out = {
        "agent_summary": {
            "courted_id": a.get("courted_id"),
            "name": f"{a.get('first_name','')} {a.get('last_name','')}".strip(),
            "email": a.get("email"),
            "phone": a.get("phone") or a.get("mobile_phone"),
            "_fub_id": a.get("_fub_id"),
            "_birthday": a.get("_birthday"),
            "_anniversary": a.get("_anniversary"),
            "_birthday_today": a.get("_birthday_today"),
            "_anniversary_today": a.get("_anniversary_today"),
        },
        "matched_fub_person": None,
    }
    fub_id = a.get("_fub_id")
    if fub_id:
        # Find this person in the FUB cache
        try:
            cache_path = DATA_DIR / "fub_people_cache.json"
            if cache_path.exists():
                people = json.loads(cache_path.read_text(encoding="utf-8"))
                m = next((p for p in people if p.get("id") == fub_id), None)
                if m:
                    # Show every key that looks date-related
                    date_keys = {k: v for k, v in m.items() if v and ("birthday" in k.lower() or "anniv" in k.lower() or "bday" in k.lower())}
                    out["matched_fub_person"] = {
                        "id": m.get("id"),
                        "firstName": m.get("firstName"),
                        "lastName": m.get("lastName"),
                        "stage": m.get("stage"),
                        "native_birthday": m.get("birthday"),
                        "customBirthday": m.get("customBirthday"),
                        "customSREGAniversary_typo": m.get("customSREGAniversary"),
                        "customSREGAnniversary_correct": m.get("customSREGAnniversary"),
                        "all_date_related_fields": date_keys,
                    }
        except Exception as e:
            out["fub_cache_error"] = str(e)
    return jsonify(out)


@app.route("/api/push-photos", methods=["POST"])
def api_push_photos():
    return jsonify(fub_push_photo_urls())


def open_browser_when_ready(url):
    time.sleep(1.0)
    try: webbrowser.open(url)
    except Exception: pass


if __name__ == "__main__":
    # Pre-load the last good snapshot into STATE so the dashboard isn't empty if today's sync
    # returns a partial/empty result (Courted rate-limit etc.).
    try:
        if CACHE_PATH.exists():
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if cached.get("agents"):
                STATE["agents"] = cached["agents"]
                STATE["last_sync"] = cached.get("last_sync")
                print(f"Pre-loaded {len(STATE['agents'])} agents from {CACHE_PATH.name} (last sync: {STATE['last_sync']})", flush=True)
    except Exception as e:
        print(f"Could not pre-load {CACHE_PATH.name}: {e}", flush=True)
    run_sync()
    port = int(CFG.get("server_port", 8765))
    url = f"http://localhost:{port}/"
    print(f"\nDashboard: {url}\nPress Ctrl+C to stop.\n")
    threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False)
