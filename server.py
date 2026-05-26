from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import json, os, pytz, urllib.request
from datetime import datetime, time
from pathlib import Path

app = FastAPI()

NEPAL_TZ = pytz.timezone('Asia/Kathmandu')

BASE_DIR   = Path(__file__).parent.resolve()
LOG_FILE   = BASE_DIR / "monitor_log.json"
STATE_FILE = BASE_DIR / "fail_count.txt"
HTML_FILE  = BASE_DIR / "index.html"

# Set these as environment variables on Railway:
#   GITHUB_REPO  = "youruser/navya-watchdog"   (e.g. "manjil/navya-watchdog")
#   GITHUB_TOKEN = "ghp_xxxx"  (a fine-grained read-only PAT)
GITHUB_REPO  = os.getenv("GITHUB_REPO", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def fetch_from_github(filename):
    if not GITHUB_REPO:
        return None
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}"
    req = urllib.request.Request(url)
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode()
    except Exception as e:
        print(f"GitHub fetch failed for {filename}: {e}")
        return None


def load_logs():
    if GITHUB_REPO:
        raw = fetch_from_github("monitor_log.json")
        if raw:
            try:
                return json.loads(raw)
            except Exception as e:
                print(f"Log parse error: {e}")
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except:
            pass
    return []


def load_fail_count():
    if GITHUB_REPO:
        raw = fetch_from_github("fail_count.txt")
        if raw is not None:
            try:
                return int(raw.strip())
            except:
                return 0
    if STATE_FILE.exists():
        try:
            return int(STATE_FILE.read_text().strip())
        except:
            pass
    return 0


@app.get("/api/status")
def get_status():
    logs       = load_logs()
    fail_count = load_fail_count()
    latest     = logs[-1] if logs else {}

    now        = datetime.now(NEPAL_TZ)
    now_time   = now.time()
    is_trading = time(11, 0) <= now_time <= time(15, 0)
    is_after   = now_time > time(15, 0)

    ltype = latest.get("type", "")
    if is_after and ltype in ("success", "closed"):
        status, label = "closed", "Market Closed"
    elif ltype == "success":
        status, label = "live", "Live"
    elif ltype == "failure" and fail_count >= 3:
        status, label = "down", "Down"
    elif ltype == "failure":
        status, label = "warning", "Issue"
    elif ltype == "alert":
        status, label = "alert", "Alert"
    elif ltype == "closed":
        status, label = "closed", "Market Closed"
    else:
        status = "warning" if is_trading else "closed"
        label  = "Checking..." if is_trading else "Market Closed"

    total     = len(logs)
    successes = sum(1 for l in logs if l.get("type") == "success")
    failures  = sum(1 for l in logs if l.get("type") in ("failure", "alert"))
    uptime    = round(successes / total * 100, 2) if total > 0 else 100.0
    recent    = list(reversed(logs[-200:]))

    return JSONResponse({
        "status":           status,
        "status_label":     label,
        "fail_count":       fail_count,
        "is_trading_hours": is_trading,
        "is_after_market":  is_after,
        "current_time":     now.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime":           uptime,
        "total_events":     total,
        "total_successes":  successes,
        "total_failures":   failures,
        "latest":           latest,
        "logs":             recent,
        "chart_logs":       logs[-30:],
    })


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_FILE.read_text()