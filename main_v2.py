import os
import sys
import time
import json
import re
from datetime import datetime
from urllib.parse import urlparse
from firecrawl import FirecrawlApp
# Note: google.generativeai and Pillow are removed from this specific workflow 
# as the user requested a specific Map -> Filter -> Scrape -> Output flow
# focusing on getting "Clean Markdown" via Firecrawl.

# Force UTF-8 logging
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "fc-04b104bc02724e0fae8bff5f981ec24b")
HISTORY_FILE = "history.json"
KEYWORD_FILE = "keyword.txt"
OUTPUT_DIR = "news_output"

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

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history_set), f)

def load_keywords():
    if os.path.exists(KEYWORD_FILE):
        with open(KEYWORD_FILE, "r", encoding="utf-8") as f:
            return [line.strip().lower() for line in f if line.strip()]
    return []

# --- STEP 1: RECON (MAP) ---
def step_1_recon(app, target_url, keywords=None):
    print(f"\n🚀 STEP 1: RECON - Mapping URL: {target_url}")
    
    # Prepare map options
    map_params = {
        'sitemap': 'skip',
        'limit': 100,
        'include_subdomains': False, 
        'ignore_query_parameters': True
    }
    
    
    # params: sitemap='skip', include_subdomains=False, ignore_query_params=True
    print(f"   -> Filter Mode: No search filter, Sitemap='skip', Limit=100")

    try:
        # map returns a list of URLs
        # Using kwargs unpacking for parameters
        map_result = app.map(target_url, **map_params)
        
        # Firecrawl map result structure handling
        if isinstance(map_result, dict) and 'links' in map_result:
             raw_list = map_result['links']
        elif hasattr(map_result, 'links'): # Handle MapData object
             raw_list = map_result.links
        elif isinstance(map_result, list):
             raw_list = map_result
        else:
             print(f"⚠️  Cấu trúc phản hồi Map lạ: {type(map_result)} - Content: {str(map_result)}")
             return []

        # Normalize to list of strings
        links = []
        for item in raw_list:
            if hasattr(item, 'url'):
                links.append(item.url)
            elif isinstance(item, dict) and 'url' in item:
                links.append(item['url'])
            elif isinstance(item, str):
                links.append(item)
            else:
                pass 

        # Ensure target_url is included in the list
        if target_url not in links:
            links.insert(0, target_url)

        print(f"   -> Tìm thấy {len(links)} links.")
        
        # Save raw links
        with open("recon_links.txt", "w", encoding="utf-8") as f:
            for link in links:
                f.write(f"link : {link}\n")
        
        return links
    except Exception as e:
        print(f"❌ Lỗi Step 1: {e}")
        return []

def remove_accents(input_str):
    s1 = u'ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯưẠạẢảẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẸẹẺẻẼẽẾếỀềỂểỄễỆệỈỉỊịỌọỎỏỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỤụỦủỨứỪừỬửỮữỰựỲỳỴỵỶỷỸỹ'
    s0 = u'AAAAEEEIIOOOOUUYaaaaeeeiioooouuyAaDdIiUuOoUuAaAaAaAaAaAaAaAaAaAaEeEeEeEeEeEeEeEeIiIiOoOoOoOoOoOoOoOoOoOoOoOoUuUuUuUuUuUuUuYyYyYyYy'
    s = ''
    for c in input_str:
        if c in s1:
            s += s0[s1.index(c)]
        else:
            s += c
    return s.lower()

# --- STEP 2: INTELLIGENT FILTER ---
def step_2_filter(links, keywords, history_set, target_url=None):
    print(f"\n🔍 STEP 2: INTELLIGENT FILTER (Input: {len(links)})")
    
    filtered_links = []
    new_links_count = 0
    keyword_match_count = 0
    
    # Pre-process keywords: Create unaccented versions
    normalized_keywords = [remove_accents(k) for k in keywords]
    
    # 1. Deduplicate input list while PRESERVING ORDER
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            unique_links.append(link)
            seen.add(link)
    
    # Ensure target_url is in unique_links if passed
    if target_url and target_url not in unique_links:
        unique_links.insert(0, target_url)

    for link in unique_links:
        # Filter 1: Check History (Database)
        if link in history_set:
            continue
        new_links_count += 1
        
        # Filter 2: Check Keywords in URL (Simple heuristic)
        link_lower = link.lower()
        
        # Determine if this is the target URL (exempt from checks)
        is_target = False
        if target_url:
            # Compare with trailing slash handling
            if link.rstrip('/') == target_url.rstrip('/'):
                is_target = True

        # Basic constraints: Must look like an article 
        # Bypass length check for target_url
        if not is_target and len(link) < 20: continue
        
        # Keywords check
        has_keyword = False
        if not keywords or is_target: # If no keywords OR is target, take it
            has_keyword = True
        else:
            # Check against normalized keywords since URLs are often unaccented
            # Also replace hyphens with spaces in URL to match keywords better? 
            # e.g. "thi-truong" -> "thi truong" matches "thị trường" (normalized -> "thi truong")
            url_text = remove_accents(link_lower).replace('-', ' ')
            
            for nk in normalized_keywords:
                if nk in url_text:
                    has_keyword = True
                    # print(f"      [MATCH] {nk} in {link}") # Debug match
                    break
        
        if has_keyword:
            keyword_match_count += 1
            filtered_links.append(link)
    
    # Limit to 20-50 links
    target_count = 30
    final_list = filtered_links[:50] # Take top 50 matches
    
    print(f"   -> Link mới chưa có trong DB: {new_links_count}")
    print(f"   -> Link khớp từ khóa: {keyword_match_count}")
    print(f"   -> Giữ lại để xử lý: {len(final_list)}")
    
    return final_list

def clean_markdown(text):
    """
    Post-process markdown to remove known noise artifacts 
    that Firecrawl misses (ads, menus, icons).
    """
    if not text: return ""
    
    lines = text.split('\n')
    cleaned_lines = []
    
    # Patterns to skip (regex or substring)
    skip_patterns = [
        r'!\[iconGift\]',          # Gift/Ad icons
        r'!\[menubar\]',           # Menu bar images
        r'!\[thong-bao\]',         # Notification icons
        r'!\[nang-cap-tai-khoan\]', # Upgrade account ads
        r'!\[search\]',            # Search icons
        r'!\[user\]',              # User login icons
        r'!\[.*\]\(.*icon.*\.svg\)', # Generic icon handling
        r'!\[.*Trend\]',           # Trend charts (VNIndexTrend etc)
        r'!\[close\]',             # Close icons
        r'!\[iconArrow\]',         # Arrow icons
        r'!\[searchBlack\]',       # Search icons
        r'Bản quyền thuộc về Vietstock', # Footer
        r'Chat Bot AI - CHỨNG SĨ', # Chatbot ads
        r'^!\[.*\]\(.*\)$',        # Standalone images (aggressive)
        r'^\s*-\s*\d{2}:\d{2}',    # News ticker timestamps (e.g. "- 08:30")
        r'^Tin mới nhất$',
        r'^Cập nhật$'
    ]
    
    # Specific menu headers to skip
    skip_headers = {
        'VĨ MÔ', 'NGÀNH', 'DOANH NGHIỆP', 'CỔ PHIẾU', 'PHÁI SINH', 
        'TRÁI PHIẾU', 'CÔNG CỤ ĐẦU TƯ', 'XUẤT DỮ LIỆU', 'TIN MỚI',
        'Tổng hợp doanh nghiệp', 'Báo cáo tài chính', 'Báo cáo tài chính ngành'
    }

    for line in lines:
        should_skip = False
        stripped = line.strip()
        
        # Check specific noisy patterns
        for pattern in skip_patterns:
            if re.search(pattern, line):
                should_skip = True
                break
        
        # Check for menu headers
        if stripped in skip_headers:
            should_skip = True

        # Check for menu links block (heuristic: line is just a link)
        # e.g. "- [Text](url) |" OR "[Text](url)"
        # This removes lines that are ONLY a link (or link + separator)
        # Regex: Start with optional dash, then [text](url), optional |, end
        # Be careful: this might remove valid list items if they only contain a link. 
        # But for this site, valid content is usually tables or text paragraphs.
        if re.match(r'^\s*(- )?\[.*?\]\(http.*?\)\s*(\|)?\s*$', line):
             if len(line) < 200: # Assuming menu links are short
                 should_skip = True
                 
        if not should_skip:
            cleaned_lines.append(line)
            
    # Re-join and remove excessive empty lines
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result

# --- STEP 3 & 4: EXTRACTION & OUTPUT ---
def step_3_4_extraction_output(app, links, history_set):
    print(f"\n⛏️  STEP 3 & 4: EXTRACTION & OUTPUT")
    
    success_count = 0
    
    for i, link in enumerate(links):
        print(f"   [{i+1}/{len(links)}] Scraping: {link}")
        
        try:
            # Scrape
            # Updated params: strict cleaning to remove nav/ads
            scrape_kwargs = {
                'formats': ['markdown'],
                'only_main_content': True,
                'exclude_tags': ['nav', 'header', 'footer', 'aside', '.banner', '.ads', '#menu', '.box_search', '.quick-link'],
                'wait_for': 5000,           # Increased to 5s
                # Attempt to scroll to trigger lazy loading
                'actions': [
                    {'type': 'scroll', 'direction': 'down', 'distance': 1500}
                ]
            }
            scrape_result = app.scrape(link, **scrape_kwargs) 
            
            # Check if result is dict or Document object
            markdown = None
            if hasattr(scrape_result, 'markdown'):
                markdown = scrape_result.markdown
            elif isinstance(scrape_result, dict) and 'markdown' in scrape_result:
                markdown = scrape_result['markdown']
            
            if markdown:
                # Cleaning noise
                markdown = clean_markdown(markdown)
                
                # --- Step 4: Output ---
                # Generate filename: fc_[slug]_[date].md
                # Get slug from URL
                parsed = urlparse(link)
                path = parsed.path.strip("/")
                slug = path.replace("/", "-")[-50:] # Take last 50 chars of path
                if not slug: slug = "index"
                
                date_str = datetime.now().strftime("%Y%m%d")
                filename = f"fc_{slug}_{date_str}.md"
                # Clean invalid chars
                filename = re.sub(r'[<>:"/\\|?*]', '', filename)
                
                filepath = os.path.join(OUTPUT_DIR, filename)
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"URL: {link}\n")
                    f.write(f"Date: {datetime.now().isoformat()}\n")
                    f.write("-" * 20 + "\n\n")
                    f.write(markdown)
                
                print(f"      -> ✅ Saved: {filename}")
                
                # Update History
                history_set.add(link)
                success_count += 1
                
                # Rate limit politeness
                # Firecrawl Free Tier ~ 5-10 req/min => sleep 10s
                time.sleep(12) 
                
            else:
                print(f"      -> ⚠️ No markdown returned. Response keys: {scrape_result.keys() if isinstance(scrape_result, dict) else type(scrape_result)}")
                # print(scrape_result) # Un-comment to see full error if needed
                time.sleep(2)
                
        except Exception as e:
            if "Rate Limit" in str(e):
                 print(f"      -> ⏳ Rate Limit Hit! Sleeping 60s...")
                 time.sleep(60)
            else:
                 print(f"      -> ❌ Error: {e}")
            
    return success_count

# --- MAIN FLOW ---
def main():
    print("=== FIRECRAWL INTELLIGENT CRAWLER ===")
    
    # Setup
    app = get_firecrawl_app()
    history = load_history()
    keywords = load_keywords()
    print(f"📚 Loaded History: {len(history)} links")
    print(f"� Loaded Keywords: {len(keywords)} terms")
    
    # Input
    target_url = input("\nNhập URL trang chủ/chuyên mục cần quét: ").strip()
    if not target_url: return

    # Workflow
    # Step 1
    raw_links = step_1_recon(app, target_url, keywords)
    if not raw_links:
        print("❌ Không tìm thấy link nào. Dừng.")
        return

    # Step 2
    filtered_links = step_2_filter(raw_links, keywords, history, target_url)
    if not filtered_links:
        print("❌ Không còn link nào sau khi lọc. Dừng.")
        return

    # Step 3 & 4
    processed_count = step_3_4_extraction_output(app, filtered_links, history)
    
    # Save History
    save_history(history)
    print(f"\n✅ HOÀN TẤT! Đã xử lý thành công: {processed_count} bài.")
    print(f"📂 Kiểm tra thư mục '{OUTPUT_DIR}' để xem kết quả.")

if __name__ == "__main__":
    main()
