
import os
import sys
import time
import datetime
from playwright.sync_api import sync_playwright

# --- Configuration ---
URL = "https://finance.vietstock.vn/du-lieu-nganh.htm#sector-performance"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def configure_stdout():
    if sys.platform.startswith('win'):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def parse_sector_data(page):
    print("Navigating to Sector Data page...")
    page.goto(URL, timeout=90000)
    page.wait_for_load_state("networkidle", timeout=60000)
    
    # Reload to ensure clean state
    print("Reloading page...")
    page.reload(wait_until="domcontentloaded")
    time.sleep(5)
    
    data = {
        "performance": [],
        "cash_flow": []
    }
    
    # --- Helper to select Level 1 Sector ---
    def select_sector_level_1():
        print("Selecting 'Ngành cấp 1'...")
        try:
            # Dropdown is usually the second one
            selects = page.locator("select.form-control").all()
            if len(selects) >= 2:
                selects[1].select_option(value="1")
                selects[1].dispatch_event("change")
                time.sleep(3)
            else:
                # Try finding by looking at the parent container of tabs if possible, or fallback
                # Subagent said "select.form-control" (index 0 or 1).
                # Let's try locating explicitly
                # Based on subagent trace: document.querySelector('select.form-control')
                page.select_option("select.form-control", value="1")
        except Exception as e:
            print(f"Error selecting sector level: {e}")

    # --- Helper to extract table ---
    def extract_table(tab_name):
        print(f"Extracting table for {tab_name}...")
        try:
            # Subagent identified unique wrapper: #table-performance-wrapper
            container = page.locator("#table-performance-wrapper .table-responsive")
            container.wait_for(state="visible", timeout=10000)
            
            # Headers
            headers = container.locator("thead th").all_text_contents()
            headers = [h.strip().replace('\n', ' ') for h in headers if h.strip()]
            
            # Rows
            rows_data = []
            rows = container.locator("tbody tr").all()
            
            for row in rows:
                cols = row.locator("td").all_text_contents()
                cols = [c.strip() for c in cols]
                if cols:
                    rows_data.append(cols)
            
            return {"headers": headers, "rows": rows_data}
            
        except Exception as e:
            print(f"Error extracting table: {e}")
            return None

    # --- Part 1: Sector Performance (Default Tab) ---
    print("Processing 'Hiệu suất ngành'...")
    try:
        # Click Tab explicitly
        # Using selector from subagent: .option-tab:nth-of-type(1) might be fragile if multiple sets.
        # Use text match.
        page.evaluate("Array.from(document.querySelectorAll('a.option-tab')).find(el => el.textContent.trim() === 'Hiệu suất ngành').click()")
        time.sleep(3) # Wait for load
        select_sector_level_1()
        time.sleep(2) # Wait for table update
        perf_data = extract_table("Performance")
        if perf_data:
            data['performance'] = perf_data
    except Exception as e:
        print(f"Error processing Performance tab: {e}")

    # --- Part 2: Sector Cash Flow ---
    print("Processing 'Dòng tiền ngành'...")
    try:
        # Click Tab
        page.evaluate("Array.from(document.querySelectorAll('a.option-tab')).find(el => el.textContent.trim() === 'Dòng tiền ngành').click()")
        time.sleep(3) # Wait for tab switch
        
        # Ensure Sector Level is still 1 (Context might change)
        select_sector_level_1()
        
        cf_data = extract_table("Cash Flow")
        if cf_data:
            data['cash_flow'] = cf_data
            
    except Exception as e:
        print(f"Error processing Cash Flow tab: {e}")
        
    return data

def format_report(data):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
    md = [f"# Sector Data (Dữ liệu Ngành cấp 1) - {now.strftime('%Y-%m-%d %H:%M:%S')}\n"]
    md.append(f"Source: {URL}\n\n")
    
    # 1. Performance Table
    if data.get('performance'):
        headers = data['performance']['headers']
        rows = data['performance']['rows']
        
        md.append("### Hiệu suất ngành\n\n")
        
        # Markdown Table
        header_row = "| " + " | ".join(headers) + " |"
        sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
        md.append(header_row + "\n")
        md.append(sep_row + "\n")
        
        for row in rows:
            # Handle row length mismatch if any (though usually fine)
            # Just join
            md.append("| " + " | ".join(row) + " |\n")
        md.append("\n")
    else:
        md.append("### Hiệu suất ngành: No Data\n\n")

    # 2. Cash Flow Table
    if data.get('cash_flow'):
        headers = data['cash_flow']['headers']
        rows = data['cash_flow']['rows']
        
        md.append("### Dòng tiền ngành\n\n")
        
        header_row = "| " + " | ".join(headers) + " |"
        sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
        md.append(header_row + "\n")
        md.append(sep_row + "\n")
        
        for row in rows:
            md.append("| " + " | ".join(row) + " |\n")
        md.append("\n")
    else:
        md.append("### Dòng tiền ngành: No Data\n\n")
        
    return "".join(md)

def main():
    configure_stdout()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
             viewport={"width": 1280, "height": 720}
        )
        
        try:
            data = parse_sector_data(page)
            
            if data:
                report_content = format_report(data)
                
                # Save to file
                now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
                date_dir = now.strftime("%Y%m%d")
                full_dir = os.path.join(OUTPUT_DIR, date_dir)
                ensure_directory_exists(full_dir)
                
                filename = f"sector_data_{now.strftime('%H%M')}.md"
                filepath = os.path.join(full_dir, filename)
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(report_content)
                
                print(f"Saved report to {filepath}")
                
        except Exception as e:
            print(f"Fatal error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
