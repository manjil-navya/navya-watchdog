import os
import json
import pytz
import base64
import urllib.request
import urllib.error
import smtplib
from datetime import datetime, time
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
STATE_FILE   = "fail_count.txt"
LOG_FILE     = "monitor_log.json"
MAX_FAILURES = 3
NEPAL_TZ     = pytz.timezone('Asia/Kathmandu')

# GitHub config — add these to your .env file:
# GITHUB_REPO  = manjil-navya/navya-watchdog
# GITHUB_TOKEN = github_pat_xxxx
GITHUB_REPO  = os.getenv("GITHUB_REPO", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


# ── Local file helpers ──────────────────────────────────────────────

def get_fail_count():
    if not os.path.exists(STATE_FILE): return 0
    try: return int(open(STATE_FILE).read().strip())
    except: return 0

def update_fail_count(count):
    open(STATE_FILE, "w").write(str(count))

def load_logs():
    if not os.path.exists(LOG_FILE): return []
    try: return json.load(open(LOG_FILE))
    except: return []

def save_logs(logs):
    with open(LOG_FILE, "w") as f:
        json.dump(logs[-500:], f, indent=2)


# ── GitHub push ─────────────────────────────────────────────────────

def github_api(method, path, body=None):
    """Raw GitHub API call. Returns parsed JSON or None."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code}: {e.read().decode()}")
        return None
    except Exception as e:
        print(f"GitHub API error: {e}")
        return None

def get_file_sha(filename):
    """Get current SHA of a file in the repo (needed to update it)."""
    result = github_api("GET", f"contents/{filename}")
    return result.get("sha") if result else None

def push_file_to_github(filename, content_str):
    """Push a file to GitHub repo via API. No git needed."""
    if not GITHUB_REPO or not GITHUB_TOKEN:
        print("GitHub not configured — skipping push (local only)")
        return False

    sha = get_file_sha(filename)
    encoded = base64.b64encode(content_str.encode()).decode()
    now_str = datetime.now(NEPAL_TZ).strftime("%Y-%m-%d %H:%M NPT")

    body = {
        "message": f"chore: monitor update {now_str}",
        "content": encoded,
    }
    if sha:
        body["sha"] = sha  # required for updates, omit for new files

    result = github_api("PUT", f"contents/{filename}", body)
    if result:
        print(f"✓ Pushed {filename} to GitHub")
        return True
    else:
        print(f"✗ Failed to push {filename} to GitHub")
        return False

def sync_to_github(logs, fail_count):
    """Push both log files to GitHub."""
    push_file_to_github("monitor_log.json", json.dumps(logs[-500:], indent=2))
    push_file_to_github("fail_count.txt", str(fail_count))


# ── Email alert ─────────────────────────────────────────────────────

ALERT_COOLDOWN_MINUTES = 60  # Only re-alert once per hour max
_last_alert_sent: datetime | None = None

def send_alert(subject, body):
    global _last_alert_sent

    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASS")
    alert_to   = os.getenv("ALERT_RECEIVER")

    # Guard: check env vars are set
    if not gmail_user or not gmail_pass or not alert_to:
        print(f"⚠ Email not sent — missing env vars: "
              f"GMAIL_USER={'set' if gmail_user else 'MISSING'}, "
              f"GMAIL_APP_PASS={'set' if gmail_pass else 'MISSING'}, "
              f"ALERT_RECEIVER={'set' if alert_to else 'MISSING'}")
        return

    # Throttle: don't send more than once per ALERT_COOLDOWN_MINUTES
    now = datetime.now(NEPAL_TZ)
    if _last_alert_sent:
        minutes_since = (now - _last_alert_sent).total_seconds() / 60
        if minutes_since < ALERT_COOLDOWN_MINUTES:
            print(f"⏳ Alert throttled — last sent {minutes_since:.0f} min ago (cooldown: {ALERT_COOLDOWN_MINUTES} min)")
            return

    msg = MIMEText(body)
    msg['Subject'] = f"🚨 {subject}"
    msg['From']    = gmail_user
    msg['To']      = alert_to
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(gmail_user, gmail_pass)
            s.sendmail(gmail_user, [alert_to], msg.as_string())
        _last_alert_sent = now
        print(f"✓ Email alert sent to {alert_to}")
    except smtplib.SMTPAuthenticationError:
        print("✗ SMTP Auth failed — check GMAIL_APP_PASS is a 16-char App Password, not your Gmail login password")
    except smtplib.SMTPException as e:
        print(f"✗ SMTP Error: {e}")
    except Exception as e:
        print(f"✗ Unexpected email error: {e}")


# ── Logging ──────────────────────────────────────────────────────────

def log_event(logs, event_type, message, details=None):
    entry = {
        "timestamp": datetime.now(NEPAL_TZ).isoformat(),
        "type":      event_type,
        "message":   message,
        "details":   details or {}
    }
    logs.append(entry)
    save_logs(logs)
    print(f"[{event_type.upper()}] {message}")
    return logs


# ── Main check ───────────────────────────────────────────────────────

def check_market():
    now      = datetime.now(NEPAL_TZ)
    now_time = now.time()
    logs     = load_logs()

    if not (time(11, 0) <= now_time <= time(15, 0)):
        msg = f"Outside monitoring hours ({now_time.strftime('%H:%M:%S')}). Market closed."
        logs = log_event(logs, "closed", msg)
        sync_to_github(logs, get_fail_count())
        return

    success      = False
    error_detail = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page    = context.new_page()
        try:
            page.goto("https://navyaadvisors.com/login", wait_until="networkidle")
            page.fill('input[name="email"]',    os.getenv("NAVYA_EMAIL"))
            page.fill('input[name="password"]', os.getenv("NAVYA_PASS"))
            page.click('button[type="submit"]')
            page.wait_for_selector('text="NEPSE"', timeout=45000)
            page.wait_for_timeout(10000)

            if "Live Market" in page.content():
                success = True
            else:
                page.screenshot(path="debug_failure.png")
                error_detail = "Keyword 'Live Market' not found."
        except Exception as e:
            try: page.screenshot(path="debug_error.png")
            except: pass
            error_detail = f"Process Error: {str(e)}"
        finally:
            browser.close()

    current_fails = get_fail_count()

    if success:
        logs = log_event(logs, "success", "Market is confirmed LIVE. Resetting counter.")
        update_fail_count(0)
        sync_to_github(logs, 0)
    else:
        current_fails += 1
        update_fail_count(current_fails)
        msg  = f"Check FAILED ({current_fails}/{MAX_FAILURES}): {error_detail}"
        logs = log_event(logs, "failure", msg)
        sync_to_github(logs, current_fails)

        if current_fails >= MAX_FAILURES:
            send_alert("CRITICAL: Market Feed Down",
                       f"Monitor failed {current_fails} times in a row.\n\nReason: {error_detail}")
            logs = log_event(logs, "alert", "Email alert sent.", {"failures": current_fails})
            sync_to_github(logs, current_fails)


if __name__ == "__main__":
    check_market()