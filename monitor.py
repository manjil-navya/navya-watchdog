import os
import smtplib
import json
import pytz
from datetime import datetime, time
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
STATE_FILE = "fail_count.txt"
LOG_FILE = "monitor_log.json"
MAX_FAILURES = 3 
NEPAL_TZ = pytz.timezone('Asia/Kathmandu')

def get_fail_count():
    if not os.path.exists(STATE_FILE): return 0
    with open(STATE_FILE, "r") as f:
        try: return int(f.read().strip())
        except: return 0

def update_fail_count(count):
    with open(STATE_FILE, "w") as f:
        f.write(str(count))

def log_event(event_type, message, details=None):
    entry = {
        "timestamp": datetime.now(NEPAL_TZ).isoformat(),
        "type": event_type,
        "message": message,
        "details": details or {}
    }
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try: logs = json.load(f)
            except: logs = []
    logs.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(logs[-500:], f)

def send_alert(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = f"🚨 {subject}"
    msg['From'] = os.getenv("GMAIL_USER")
    msg['To'] = os.getenv("ALERT_RECEIVER")
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASS"))
            server.sendmail(msg['From'], [msg['To']], msg.as_string())
        print("Email alert sent.")
    except Exception as e:
        print(f"SMTP Error: {e}")

def check_market():
    now = datetime.now(NEPAL_TZ).time()
    
    # Range check
    if not (time(11, 0) <= now <= time(15, 0)):
        msg = f"Outside monitoring hours ({now.strftime('%H:%M:%S')}). Market closed for the day."
        print(f"[{now}] {msg}")
        log_event("closed", msg)
        return

    success = False
    error_detail = ""

    with sync_playwright() as p:
        # Launching with a slow_mo to simulate human behavior
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        try:
            # 1. Login
            page.goto("https://navyaadvisors.com/login", wait_until="networkidle")
            page.fill('input[name="email"]', os.getenv("NAVYA_EMAIL"))
            page.fill('input[name="password"]', os.getenv("NAVYA_PASS"))
            page.click('button[type="submit"]')
            
            # 2. Wait for the Dashboard to actually load
            # We wait for the 'NEPSE' text which is the main heading
            page.wait_for_selector('text="NEPSE"', timeout=45000)
            
            # 3. EXTRA WAIT (Critical for dynamic sites)
            # This gives the "Live Market" badge time to appear after the API call
            page.wait_for_timeout(10000) 

            # 4. Better Detection Logic
            # We check if the text "Live Market" exists anywhere on the page
            content = page.content()
            if "Live Market" in content:
                success = True
            else:
                # Take a screenshot to see what happened
                page.screenshot(path="debug_failure.png")
                error_detail = "Keyword 'Live Market' not found. See debug_failure.png"

        except Exception as e:
            page.screenshot(path="debug_error.png")
            error_detail = f"Process Error: {str(e)}"
        finally:
            browser.close()

    # --- FAILURE LOGIC ---
    current_fails = get_fail_count()

    if success:
        msg = f"Market is confirmed LIVE. Resetting counter."
        print(f"[{now}] {msg}")
        log_event("success", msg)
        update_fail_count(0)
    else:
        current_fails += 1
        update_fail_count(current_fails)
        msg = f"Check FAILED ({current_fails}/{MAX_FAILURES}): {error_detail}"
        print(f"[{now}] {msg}")
        log_event("failure", msg)

        if current_fails == MAX_FAILURES:
            send_alert("CRITICAL: Market Feed Down", 
                       f"The market monitor failed {MAX_FAILURES} times.\n\nReason: {error_detail}")
            log_event("alert", "Email alert sent", {"failures": current_fails})

if __name__ == "__main__":
    check_market()