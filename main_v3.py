import os
import sys
import time
import json
import re
from urllib.parse import urlparse, parse_qs, urljoin
from datetime import datetime
from firecrawl import FirecrawlApp

# Force UTF-8 logging
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "fc-04b104bc02724e0fae8bff5f981ec24b")
OUTPUT_DIR = "news_output_v3"

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_firecrawl_app():
    global FIRECRAWL_API_KEY
    if not FIRECRAWL_API_KEY:
        print("\n⚠️  Firecrawl API Key chưa được thiết lập (biến môi trường FIRECRAWL_API_KEY).")
        FIRECRAWL_API_KEY = input("👉 Vui lòng nhập Firecrawl API Key của bạn (bắt đầu bằng 'fc-'): ").strip()
        if not FIRECRAWL_API_KEY:
            print("❌ Cần có API Key để chạy Firecrawl!")
            sys.exit(1)
    return FirecrawlApp(api_key=FIRECRAWL_API_KEY)

def normalize_url(url):
    """Normalized URL for comparison (removes trailing slash)"""
    return url.rstrip('/')

def is_same_base_path(url1, url2):
    """Check if two URLs share the same base path (ignoring query/fragment)"""
    p1 = urlparse(url1)
    p2 = urlparse(url2)
    return p1.netloc == p2.netloc and p1.path == p2.path

def clean_markdown_aggressive(text):
    """
    Aggressive cleaning:
    1. Regex filtering of known noise.
    2. Header Slicing: Detect start of Data Table and cut everything before it.
    """
    if not text: return ""
    
    # 1. Regex Cleaning (Pre-slice)
    lines = text.split('\n')
    cleaned_lines = []
    
    # Generic patterns to skip
    skip_patterns = [
        r'!\[iconGift\]', r'!\[menubar\]', r'!\[thong-bao\]', r'!\[nang-cap-tai-khoan\]',
        r'!\[search\]', r'!\[user\]', r'!\[.*\]\(.*icon.*\.svg\)', 
        r'!\[.*Trend\]', r'!\[close\]', r'!\[iconArrow\]', r'!\[searchBlack\]',
        r'Bản quyền thuộc về', r'Chat Bot AI', 
        r'^!\[.*\]\(.*\)$', # Standalone images
        r'^\s*-\s*\d{2}:\d{2}', # Tickers " - 08:30"
        r'^Tin mới nhất$', r'^Cập nhật$', r'^Đăng nhập$', 
        r'^VĨ MÔ$', r'^NGÀNH$', r'^DOANH NGHIỆP$', r'^CỔ PHIẾU$', r'^PHÁI SINH$',
        r'^TRÁI PHIẾU$', r'^CÔNG CỤ ĐẦU TƯ$', r'^XUẤT DỮ LIỆU$', r'^TIN MỚI$'
    ]
    
    for line in lines:
        should_skip = False
        for pattern in skip_patterns:
            if re.search(pattern, line):
                should_skip = True
                break
        
        # Skip lines that are JUST a link (Menu items)
        # e.g. "[Link Text](url)" or "- [Link Text](url) |"
        if re.match(r'^\s*(- )?\[.*?\]\(http.*?\)\s*(\|)?\s*$', line):
             if len(line) < 150: # Valid article links might be long
                 should_skip = True

        if not should_skip:
            cleaned_lines.append(line)
            
    text = '\n'.join(cleaned_lines)
    

        
    # 3. Footer Slicing (The "Footer Guillotine")
    # Cut everything after known footer sections
    footer_markers = [
        r'^#### Tính năng \(\-\)',
        r'^#### Ngành \(\-\)',
        r'^#### Tin tức \(\-\)',
        r'^#### Mã chứng khoán \(\-\)',
        r'^Tất cảGiờ qua24 giờ qua'
    ]
    
    lines = text.split('\n')
    cut_footer_index = -1
    for i, line in enumerate(lines):
        for marker in footer_markers:
            if re.search(marker, line):
                cut_footer_index = i
                break
        if cut_footer_index > -1:
            break
            
    if cut_footer_index > -1:
        text = '\n'.join(lines[:cut_footer_index])

    return text.strip()

def discover_tabs(app, start_url):
    print(f"\n🔎 Discovering tabs for: {start_url}")
    try:
        # Scrape the main page first to get links
        # We use a fast scrap just for links (no markdown needed really, but mapping is better?)
        # Actually scrape is better to see actual DOM links.
        # But 'map' is designed for this. Let's use 'map' on the single URL?
        # Firecrawl map usually crawls deeper. 
        # Let's use scrape with 'formats': ['links'] if available, or just scrape html and parse?
        # SDK scrape returns document. Let's just scrape markdown/html and regex links.
        
        scrape_result = app.scrape(start_url, 
            formats=['markdown'], # Markdown contains links [text](url)
            wait_for=3000
        )
        
        found_links = set()
        if hasattr(scrape_result, 'markdown'):
            # Extract links from markdown: [text](http...)
            links = re.findall(r'\]\((http[^\)]+)\)', scrape_result.markdown)
            found_links.update(links)
        
        # Filter for "Tabs"
        # Logic: Link MUST have same base path as start_url
        base_parsed = urlparse(start_url)
        tabs = []
        
        processed_start_url = normalize_url(start_url)
        tabs.append(start_url) # Always include self
        
        for link in found_links:
            parsed = urlparse(link)
            # Check domain and path match
            if parsed.netloc == base_parsed.netloc and parsed.path == base_parsed.path:
                # Check if it has query params or is different from start
                if normalize_url(link) != processed_start_url:
                    # It's a tab! (e.g. ?tab=X)
                    if link not in tabs:
                        tabs.append(link)
        
        print(f"   -> Found {len(tabs)} potential tabs (including main).")
        return tabs

    except Exception as e:
        print(f"⚠️  Discovery failed: {e}. Proceeding with single URL.")
        return [start_url]

def process_url(app, url):
    print(f"   Now Scraping: {url}")
    try:
        # Scrape with aggressive settings
        scrape_kwargs = {
            'formats': ['markdown'], # Request markdown only
            'only_main_content': True,
            'exclude_tags': [
                'nav', 'header', 'footer', 'aside', 
                '.sidebar', '.menu', '.banner', '.ads', '.promo', 
                '.breadcrumbs', '.intro', '.social-share', 
                '#top-menu', '#main-menu', '.ticker'
            ],
            'actions': [{'type': 'scroll', 'direction': 'down', 'distance': 1500}]
        }
        
        result = app.scrape(url, **scrape_kwargs)
        
        # Extract Data
        markdown = getattr(result, 'markdown', "") or (result.get('markdown') if isinstance(result, dict) else "")

        
        # Aggressive Cleaning
        cleaned_md = clean_markdown_aggressive(markdown)
        
        # Filename Generation
        parsed = urlparse(url)
        # Create a slug including query params to distinguish tabs
        # e.g. path-tab-thong-ke
        slug_path = parsed.path.strip("/").replace("/", "-")
        query = parse_qs(parsed.query)
        slug_query = ""
        if 'tab' in query:
            slug_query = f"-tab-{query['tab'][0]}"
        elif 'view' in query:
             slug_query = f"-view-{query['view'][0]}"
             
        slug = (slug_path + slug_query)[-100:] # Limit length
        if not slug: slug = "index"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        base_filename = f"{slug}_{timestamp}"
        
        # Save Markdown
        with open(os.path.join(OUTPUT_DIR, base_filename + ".md"), "w", encoding="utf-8") as f:
            f.write(f"Source: {url}\n\n")
            f.write(cleaned_md)
            
        print(f"      ✅ Saved: {base_filename} (.md)")
        
        return True
        
    except Exception as e:
        print(f"      ❌ Error scraping {url}: {e}")
        return False


def main(target_url=None):
    print("=== FIRECRAWL DIRECT SCRAPER (V3) ===")
    app = get_firecrawl_app()
    
    if not target_url:
        target_url = input("\n🔗 Nhập URL cần Scrape: ").strip()
    
    if not target_url: return

    # 1. Discover Tabs
    tabs = discover_tabs(app, target_url)
    
    print(f"\n🚀 Starting Batch Processing ({len(tabs)} URLs)...")
    
    # 2. Process Each
    for i, tab_url in enumerate(tabs):
        print(f"\n[{i+1}/{len(tabs)}] Processing...")
        process_url(app, tab_url)
        # Politeness
        if i < len(tabs) - 1:
            time.sleep(3)

    print(f"\n✨ Completed! Check folder '{OUTPUT_DIR}'")

if __name__ == "__main__":
    import sys
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(url_arg)
