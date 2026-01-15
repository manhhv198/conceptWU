
import requests
from xml.etree import ElementTree
import datetime
import sys

# Fix encoding
sys.stdout.reconfigure(encoding='utf-8')

SOURCES = {
    "CafeF": "https://cafef.vn/vi-mo-dau-tu.rss",
    "Cafebiz": "https://cafebiz.vn/rss/cau-chuyen-kinh-doanh.rss",
}

def parse_rss_date(date_str):
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z"
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except:
            continue
    return None

def debug_rss(name, url):
    print(f"\n=== DEBUGGING {name} ===")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        root = ElementTree.fromstring(resp.content)
        items = root.findall(".//item")
        print(f"Total items found: {len(items)}")
        
        for i, item in enumerate(items[:5]):
            title = item.find("title").text if item.find("title") is not None else "N/A"
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else "N/A"
            parsed = parse_rss_date(pub_date)
            print(f"Item {i+1}:")
            print(f"  Title: {title[:50]}...")
            print(f"  Raw pubDate: {pub_date}")
            print(f"  Parsed: {parsed}")
            if parsed:
                print(f"  Date only: {parsed.date()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    for name, url in SOURCES.items():
        debug_rss(name, url)
    
    print(f"\nSystem Today: {datetime.datetime.now().date()}")
