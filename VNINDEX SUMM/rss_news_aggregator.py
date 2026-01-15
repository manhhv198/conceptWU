
import os
import sys
import time
import datetime
import re
from xml.etree import ElementTree
import requests
from playwright.sync_api import sync_playwright

# Fix encoding for Windows
sys.stdout.reconfigure(encoding='utf-8')

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

def get_current_date_info():
    now = datetime.datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%H%M"), now

def ensure_directory(date_str):
    if not os.path.exists(date_str):
        os.makedirs(date_str)
    return date_str

def parse_rss_date(date_str):
    """
    Parse RFC 822 date into datetime object with extra robustness.
    Example: Sun, 04 Jan 26 14:25:00 +0700
             Sun, 04 Jan 2026 21:48:00 +07
    """
    if not date_str:
        return None
        
    # Pre-processing to handle common variations
    # 1. Handle +HH instead of +HHMM
    date_str = re.sub(r' ([+-]\d{2})$', r' \100', date_str)
    
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %y %H:%M:%S %z", # 2-digit year
        "%a, %d %b %Y %H:%M:%S GMT",
        "%a, %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z"
    ]
    
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except:
            continue
            
    # Fallback: try common date patterns without Day name
    try:
        # Remove Day name part if it exists (e.g. "Sun, ")
        clean_date = re.sub(r'^[A-Za-z]{3}, ', '', date_str)
        for fmt in ["%d %b %Y %H:%M:%S %z", "%d %b %y %H:%M:%S %z"]:
            try:
                return datetime.datetime.strptime(clean_date, fmt)
            except:
                continue
    except:
        pass
        
    return None

def extract_article_content(page, url):
    """
    Navigate to article link and extract main text content using heuristics.
    """
    try:
        print(f"   - Fetching content: {url[:60]}...")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        
        # Heuristic for main content: find the largest text block or common article containers
        content = page.evaluate("""() => {
            // Remove noise
            const noise = document.querySelectorAll('script, style, iframe, nav, header, footer, .sidebar, .ads, .comment, .popup');
            noise.forEach(el => el.remove());
            
            // Try common article containers
            const selectors = [
                'article', '.article-content', '.content-detail', '#main-detail-content',
                '.detail-content', '.post-content', '.cms-body', '[itemprop="articleBody"]',
                '.detail__content', '.fck_detail', '.content_detail'
            ];
            
            for (let s of selectors) {
                let el = document.querySelector(s);
                if (el && el.innerText.length > 200) return el.innerText;
            }
            
            // Fallback: choose the div with the most p elements
            let bestDiv = null;
            let maxP = 0;
            document.querySelectorAll('div').forEach(div => {
                let pCount = div.querySelectorAll('p').length;
                if (pCount > maxP) {
                    maxP = pCount;
                    bestDiv = div;
                }
            });
            
            if (bestDiv && bestDiv.innerText.length > 200) return bestDiv.innerText;
            
            return document.body.innerText;
        }""")
        
        # Clean up text (remove excessive newlines)
        if content:
            content = re.sub(r'\n{3,}', '\n\n', content).strip()
            # Truncate if extremely long (optional)
            return content
        return "Could not extract content."
    except Exception as e:
        return f"Error: {e}"

def main():
    date_str, time_str, now_obj = get_current_date_info()
    today = now_obj.date()
    
    report = []
    report.append(f"# News Summary - {now_obj.strftime('%Y-%m-%d %H:%M')}\n")
    
    # We'll collect all valid items first to process them with Playwright once
    tasks = []
    
    print(f"Fetching RSS feeds for {today}...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"[*] Processing {source_name}...")
        try:
            resp = requests.get(rss_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"    [!] Failed to fetch RSS: {resp.status_code}")
                continue
                
            root = ElementTree.fromstring(resp.content)
            items = root.findall(".//item")
            
            source_items = []
            for item in items:
                title = item.find("title").text if item.find("title") is not None else "No Title"
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date_str = item.find("pubDate").text if item.find("pubDate") is not None else ""
                
                dt = parse_rss_date(pub_date_str)
                # Check if news is from today
                if dt and dt.date() == today:
                    source_items.append({
                        "title": title.strip(),
                        "link": link.strip(),
                        "date": dt
                    })
            
            if source_items:
                # Sort by date descending (newest first)
                source_items.sort(key=lambda x: x['date'] if x['date'] else datetime.datetime.min, reverse=True)
                # Limit to top 15 items
                limited_items = source_items[:15]
                tasks.append((source_name, limited_items))
                print(f"    [+] Found {len(source_items)} items for today. Keeping latest {len(limited_items)}.")
            else:
                print(f"    [-] No items for today.")
                
        except Exception as e:
            print(f"    [!] Error parsing RSS: {e}")

    if not tasks:
        print("No news found for today.")
        report.append("No news found for today.")
    else:
        # Start Playwright to fetch content
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": headers["User-Agent"]})
            
            print(f"\n[*] Total sources with news: {len(tasks)}")
            for source_name, items in tasks:
                print(f"[*] Writing section for {source_name} ({len(items)} items)...")
                report.append(f"## Nguồn: {source_name}\n")
                
                for idx, news in enumerate(items):
                    print(f"    - [{source_name}] Item {idx+1}/{len(items)}: {news['title'][:50]}...")
                    content = extract_article_content(page, news["link"])
                    
                    report.append(f"### {idx+1}. {news['title']}\n")
                    report.append(f"- **Link**: {news['link']}\n")
                    report.append(f"- **Thời gian**: {news['date'].strftime('%H:%M:%S')}\n")
                    report.append(f"- **Nội dung**:\n\n{content}\n\n")
                    report.append("---\n\n")
            
            browser.close()

    # Save report
    ensure_directory(date_str)
    # User requested [news sumary][time hh:mm] -> filename [news summary]HHMM.md
    filename = os.path.join(date_str, f"[news summary]{time_str}.md")
    
    full_report = "".join(report)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(full_report)
        
    print(f"\nDone! Report saved to {filename}")

if __name__ == "__main__":
    main()
