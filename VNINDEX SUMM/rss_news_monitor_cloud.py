
import os
import sys
import time
import datetime
import re
import json
import hashlib
import tempfile
from xml.etree import ElementTree
import requests
from flask import Flask, jsonify, request
from playwright.sync_api import sync_playwright

# --- Configuration ---
RSS_SOURCES = {
    "CafeF": "https://cafef.vn/vi-mo-dau-tu.rss",
    "Vietstock": "https://vietstock.vn/768/kinh-te/kinh-te-dau-tu.rss",
    "Cafebiz": "https://cafebiz.vn/rss/cau-chuyen-kinh-doanh.rss",
    "VnEconomy": "https://vneconomy.vn/tin-moi.rss",
    "Vietnambiz": "https://vietnambiz.vn/kinh-doanh.rss",
    "VnExpress": "https://vnexpress.net/rss/kinh-doanh.rss",
    "Vietnamnet": "https://vietnamnet.vn/rss/kinh-doanh.rss",
    "Tuoi Tre": "https://tuoitre.vn/rss/kinh-te.rss",
    "Bao Tin Tuc": "https://baotintuc.vn/kinh-te.rss",
    "Ngan Hang Vietnam": "https://nganhangvietnam.vn/rss/kinh-doanh.rss"
}

# Env vars
bucket_name = os.environ.get("BUCKET_NAME", "vnindex-news-bucket")
is_local = os.environ.get("LOCAL_MODE", "True").lower() == "true"
mock_gcs_dir = "gcs_mock"

app = Flask(__name__)

# --- Storage Abstraction ---
def load_from_storage(filename):
    """Load text content from GCS or Local Mock"""
    if is_local:
        local_path = os.path.join(mock_gcs_dir, filename)
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        return None
    else:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(filename)
        if blob.exists():
            return blob.download_as_text(encoding="utf-8")
        return None

def save_to_storage(filename, content):
    """Save text content to GCS or Local Mock"""
    if is_local:
        local_path = os.path.join(mock_gcs_dir, filename)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[Local] Saved to {local_path}")
    else:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(content, content_type="text/markdown")
        print(f"[Cloud] Uploaded to gs://{bucket_name}/{filename}")

# --- Helper Logic ---
def get_current_date_info():
    now = datetime.datetime.now()
    # SVN Timezone if needed, but assuming server time or UTC is fine if consistent.
    # For reporting, let's auto-adjust to +7 if server is UTC
    # Simple hack: add 7 hours if UTC
    if time.timezone == 0:
        now = now + datetime.timedelta(hours=7)
    return now.strftime("%Y%m%d"), now.strftime("%H%M"), now

def parse_rss_date(date_str):
    if not date_str: return None
    date_str = re.sub(r' ([+-]\d{2})$', r' \100', date_str)
    formats = [
        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"
    ]
    # Fallback remove day name
    clean_date = re.sub(r'^[A-Za-z]{3}, ', '', date_str)
    
    for d in [date_str, clean_date]:
        for fmt in formats:
            try: return datetime.datetime.strptime(d, fmt)
            except: continue
    return None

def generate_item_hash(link, title):
    raw = f"{link}|{title}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def extract_article_content_playwright(items):
    """Extract content for a list of items using one browser session"""
    results = {}
    if not items: return results
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            
            for item in items:
                url = item['link']
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    content = page.evaluate("""() => {
                        const noise = document.querySelectorAll('script, style, iframe, nav, header, footer, .sidebar, .ads, .comment');
                        noise.forEach(el => el.remove());
                        const selectors = ['article', '.article-content', '.content-detail', '#main-detail-content', '[itemprop="articleBody"]'];
                        for (let s of selectors) {
                            let el = document.querySelector(s);
                            if (el && el.innerText.length > 200) return el.innerText;
                        }
                        let bestDiv = null, maxP = 0;
                        document.querySelectorAll('div').forEach(div => {
                            let p = div.querySelectorAll('p').length;
                            if (p > maxP) { maxP = p; bestDiv = div; }
                        });
                        return (bestDiv && bestDiv.innerText.length > 200) ? bestDiv.innerText : document.body.innerText;
                    }""")
                    results[item['hash']] = re.sub(r'\n{3,}', '\n\n', content).strip()
                except:
                    results[item['hash']] = "Content extraction failed."
            browser.close()
    except Exception as e:
        print(f"Playwright Error: {e}")
        
    return results

# --- Main Job Logic ---
@app.route('/run_job', methods=['POST'])
def run_job():
    print("--- Starting RSS Job ---")
    
    # 1. Load State
    state_file = "rss_state.json"
    state_content = load_from_storage(state_file)
    state = json.loads(state_content) if state_content else {"seen_items": {}}
    
    date_str, time_str, now_obj = get_current_date_info()
    today = now_obj.date()
    
    new_items = []
    
    # 2. Fetch RSS
    for source, url in RSS_SOURCES.items():
        try:
            # We could implement ETag/Last-Modified here using state info if we saved it
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200: continue
            
            root = ElementTree.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pubDate = item.find("pubDate").text if item.find("pubDate") is not None else ""
                
                dt = parse_rss_date(pubDate)
                if not dt: continue
                
                # Filter Today
                if dt.date() == today:
                    h = generate_item_hash(link, title)
                    if h not in state["seen_items"]:
                        new_items.append({
                            "source": source,
                            "title": title.strip(),
                            "link": link.strip(),
                            "time_str": dt.strftime("%H:%M"),
                            "date": dt,
                            "hash": h
                        })
        except Exception as e:
            print(f"Error fetching {source}: {e}")

    # 3. Process New Items
    if new_items:
        print(f"Found {len(new_items)} new items.")
        
        # Sort oldest to newest
        new_items.sort(key=lambda x: x['date'] if x['date'] else datetime.datetime.min)
        
        # Extract Content
        contents = extract_article_content_playwright(new_items)
        
        # Prepare Report Update
        report_file = f"{date_str}/[news summary]{date_str}.md"
        current_report = load_from_storage(report_file) or f"# Real-time News Timeline - {date_str}\n\n"
        
        append_text = ""
        for item in new_items:
            content = contents.get(item['hash'], "No content.")
            append_text += f"### [{item['time_str']}] [{item['source']}] {item['title']}\n"
            append_text += f"- **Link**: {item['link']}\n"
            append_text += f"- **Content**:\n\n{content}\n\n---\n\n"
            
            # Update State
            state["seen_items"][item['hash']] = time_str
            
        full_report = current_report + append_text
        
        # 4. Save Updates
        save_to_storage(report_file, full_report)
        save_to_storage(state_file, json.dumps(state, ensure_ascii=False, indent=2))
        
        return jsonify({"status": "success", "new_items": len(new_items)})
    
    else:
        print("No new items.")
        return jsonify({"status": "success", "new_items": 0})

if __name__ == "__main__":
    # Local Dev Run
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
