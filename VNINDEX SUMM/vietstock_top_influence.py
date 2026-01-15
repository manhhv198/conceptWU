import os
import sys
import time
import datetime
import re
from playwright.sync_api import sync_playwright

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

def get_current_timestamp():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M")
    return date_str, time_str, now

OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))

def ensure_directory(date_str):
    full_path = os.path.join(OUTPUT_DIR, date_str)
    if not os.path.exists(full_path):
        os.makedirs(full_path)
    return full_path

def save_markdown(content, date_str, time_str):
    folder = ensure_directory(date_str)
    filename = os.path.join(folder, f"top_influence_{time_str}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved summary to {filename}")

def parse_chart_data(page, chart_id, chart_title):
    print(f"Processing {chart_title} ({chart_id})...")
    
    chart_data = {
        "gainers": [],
        "losers": []
    }
    
    try:
        # Locate the chart container
        chart_container = page.locator(f"#{chart_id}")
        if not chart_container.is_visible():
            print(f"Chart {chart_id} not visible.")
            return None

        # Extract textual data AND coordinates to assist classification
        # We assume Left Side = Losers, Right Side = Gainers (Standard divergence chart)
        # Also extract Y coordinate to handle deduplication of identical values correctly
        
        items_info = chart_container.locator(".highcharts-data-labels span").evaluate_all("""
            spans => spans.map(s => ({
                text: s.textContent.trim(),
                x: s.getBoundingClientRect().x,
                y: s.getBoundingClientRect().y,
                is_hidden: s.style.visibility === 'hidden' || s.style.opacity === '0'
            }))
        """)
        
        # Filter and deduplicate
        # Logic: Only filter if Text is same AND distance is very small (Shadow effect)
        # If Text is same but distance is large, it's a different data point (e.g. 2 stocks with -0.26)
        
        cleaned_items = []
        if items_info:
            cleaned_items.append(items_info[0])
            for i in range(1, len(items_info)):
                prev = items_info[i-1]
                curr = items_info[i]
                
                is_same_text = curr['text'] == prev['text']
                dist = ((curr['x'] - prev['x'])**2 + (curr['y'] - prev['y'])**2)**0.5
                
                # Threshold for shadow: < 5 pixels
                if is_same_text and dist < 5:
                    continue
                else:
                    cleaned_items.append(curr)
        
        items = [i for i in cleaned_items if i['text'] and not i.get('is_hidden')]
        
        stock_pattern = re.compile(r'^[A-Z]{3}$')
        
        def is_code(s):
            return bool(stock_pattern.match(s))
        
        def parse_val(s):
            try:
                return float(s.replace(',', ''))
            except:
                return None
        
        pos_values = [] # Should map to Gainers
        neg_values = [] # Should map to Losers
        codes_with_x = []
        
        for item in items:
            txt = item['text']
            val = parse_val(txt)
            
            if is_code(txt):
                codes_with_x.append(item)
            elif val is not None:
                if val >= 0:
                    pos_values.append(val)
                else:
                    neg_values.append(val)
                    
        # Classify Codes by Horizontal Position
        if not codes_with_x:
            print("No codes found.")
            return None
            
        # Determine visual split using Largest Gap Strategy
        # Sort items by X to find the visual break between Left (Losers) and Right (Gainers)
        # Note: We must maintain original order for mapping, so we only use X to find the cutoff index.
        
        # 1. Sort a copy by X
        sorted_by_x = sorted(codes_with_x, key=lambda i: i['x'])
        xs = [c['x'] for c in sorted_by_x]
        
        # 2. Find largest gap between adjacent X's
        max_gap = 0
        split_val = 0
        
        if len(xs) > 1:
            for i in range(len(xs) - 1):
                gap = xs[i+1] - xs[i]
                if gap > max_gap:
                    max_gap = gap
                    split_val = (xs[i] + xs[i+1]) / 2
        
        # 3. Classify based on split_val
        # Strategy: Use Gap Split, but Validate against known Value Counts.
        
        # Calculate Valid Split Range
        # Losers must be at least num_neg (Values for Losers)
        # Gainers must be at least num_pos (Values for Gainers)
        # So split_index (start of Gainers) must be:
        # split_index >= num_neg
        # len(codes) - split_index >= num_pos => split_index <= len(codes) - num_pos
        
        valid_min = len(neg_values)
        valid_max = len(codes_with_x) - len(pos_values)
        
        # Calculate Gap Split Index
        # Count items < split_val
        gap_split_index = sum(1 for c in codes_with_x if c['x'] < split_val)
        
        print(f"Gap Split Index: {gap_split_index}. Valid Range: [{valid_min}, {valid_max}]")
        
        final_split_index = gap_split_index
        
        # Fallback Logic
        if final_split_index < valid_min:
            print("Gap Split too low. Using Min Valid.")
            final_split_index = valid_min
        elif final_split_index > valid_max:
            print("Gap Split too high. Using Min Valid (Conservative).")
            # Why Min? In VN30 case, Gap was 14 (High), Valid Max was 7. User wanted 6 (Min).
            # This implies if visual is weird, trust the Loser Value Count as the baseline.
            final_split_index = valid_min
            
        print(f"Final Split Index: {final_split_index}")
        
        # Apply Split
        # We iterate list by Index since we use split_index logic now
        all_code_texts = [c['text'] for c in codes_with_x]
        
        loser_codes = all_code_texts[:final_split_index]
        gainer_codes = all_code_texts[final_split_index:]
        
        # Mapping: Left -> Losers (NegVals), Right -> Gainers (PosVals)
        # Mapping Gainers (First Gainer Code -> First Pos Value)
        # Mapping Losers (First Loser Code -> First Neg Value)
        
        for i in range(min(len(gainer_codes), len(pos_values))):
            chart_data['gainers'].append({"code": gainer_codes[i], "point": pos_values[i]})
            
        for i in range(min(len(loser_codes), len(neg_values))):
            chart_data['losers'].append({"code": loser_codes[i], "point": neg_values[i]})
            
    except Exception as e:
        print(f"Error parsing {chart_id}: {e}")
        return None
        
    return chart_data

def format_table(data, title):
    md = []
    md.append(f"### {title}\n\n")
    
    if not data or (not data['gainers'] and not data['losers']):
        md.append("*No data found.*\n\n")
        return "".join(md)

    # Top Gainers Table
    md.append("#### Top Gainers\n")
    md.append("| Stock Code | Contribution |\n")
    md.append("| --- | --- |\n")
    for item in data['gainers']:
        md.append(f"| {item['code']} | {item['point']:.2f} |\n")
    md.append("\n")

    # Top Losers Table
    md.append("#### Top Losers\n")
    md.append("| Stock Code | Contribution |\n")
    md.append("| --- | --- |\n")
    for item in data['losers']:
        md.append(f"| {item['code']} | {item['point']:.2f} |\n")
    
    md.append("\n")
    return "".join(md)

def format_table(data, title):
    md = []
    md.append(f"### {title}\n\n")
    
    if not data or (not data['gainers'] and not data['losers']):
        md.append("*No data found.*\n\n")
        return "".join(md)

    md.append("| Top Gainers | Points | Top Losers | Points |\n")
    md.append("| --- | --- | --- | --- |\n")
    
    max_rows = max(len(data['gainers']), len(data['losers']))
    
    for i in range(max_rows):
        g_code = data['gainers'][i]['code'] if i < len(data['gainers']) else ""
        g_point = f"{data['gainers'][i]['point']:.2f}" if i < len(data['gainers']) else ""
        
        l_code = data['losers'][i]['code'] if i < len(data['losers']) else ""
        l_point = f"{data['losers'][i]['point']:.2f}" if i < len(data['losers']) else ""
        
        md.append(f"| {g_code} | {g_point} | {l_code} | {l_point} |\n")
    
    md.append("\n")
    return "".join(md)

def analyze_top_influence(url="https://finance.vietstock.vn/"):
    report_content = []
    
    date_str, time_str, now_obj = get_current_timestamp()
    report_content.append(f"# Top Influence Stocks - {now_obj.strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_content.append(f"Source: {url}#top-influence\n\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Set User Agent
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        try:
            print(f"Navigating to {url}...")
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            print("Reloading page to ensure fresh data...")
            page.reload(wait_until="domcontentloaded")
            time.sleep(5)
            
            # Scroll to Top Influence section to ensure charts are rendered
            print("Scrolling to #top-influence...")
            try:
                # Need to wait for element to be present
                page.wait_for_selector("#top-influence", timeout=30000)
                page.locator("#top-influence").scroll_into_view_if_needed()
                time.sleep(3) # Wait for animation/render
            except Exception as e:
                print(f"Could not scroll to element: {e}")

            # Define charts to scrape
            charts_to_scrape = [
                {"id": "top-influence-1", "title": "VN-INDEX"},
                {"id": "top-influence-4", "title": "VN30-INDEX"},
                {"id": "top-influence-2", "title": "HNX-INDEX"}
            ]

            for chart_info in charts_to_scrape:
                data = parse_chart_data(page, chart_info["id"], chart_info["title"])
                if data:
                    report_content.append(format_table(data, chart_info["title"]))
                else:
                    report_content.append(f"### {chart_info['title']}\n*Could not extract data.*\n\n")

        except Exception as e:
            print(f"Global error: {e}")
            report_content.append(f"\n# Error Occurred\n{e}\n")
        finally:
            browser.close()

    # Save to file
    full_content = "".join(report_content)
    save_markdown(full_content, date_str, time_str)

if __name__ == "__main__":
    analyze_top_influence()
