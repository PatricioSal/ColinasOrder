from playwright.sync_api import sync_playwright
import time
import hashlib

PROFILE_DIR = "whatsapp_profile"

def fingerprint(sender, text):
    return hashlib.sha1(f"{sender}|{text}".encode("utf-8")).hexdigest()

def process_message(sender, text):
    print(f"NEW MESSAGE from {sender}: {text}")

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False
    )
    page = browser.new_page()
    page.goto("https://web.whatsapp.com/")

    input("Log into WhatsApp Web and open your target group, then press Enter...")

    last_seen = None

    try:
        while True:
            messages = page.locator("div[role='row']")
            count = messages.count()

            if count > 0:
                last = messages.nth(count - 1)
                text = last.inner_text().strip()

                if text:
                    sender = "unknown"
                    body = text

                    if ":" in text:
                        parts = text.split(":", 1)
                        sender = parts[0].strip()
                        body = parts[1].strip()

                    key = fingerprint(sender, body)

                    if key != last_seen:
                        last_seen = key
                        process_message(sender, body)

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping watcher...")

    finally:
        browser.close()