
import os
import sys
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- Configuration ---
URL = "https://www.tradingview.com/symbols/HOSE-VNINDEX/technicals/"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def configure_stdout():
    if sys.platform.startswith('win'):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def parse_tradingview_technicals(page):
    print("Navigating to TradingView Technicals page...")
    page.goto(URL, timeout=90000)
    # Wait for the main technicals containers
    page.wait_for_selector('div[class*="tableWrapper"]', timeout=60000)
    time.sleep(5) 
    
    data = {
        "oscillators": {"headers": [], "rows": []},
        "moving_averages": {"headers": [], "rows": []},
        "pivots": {"headers": [], "rows": []}
    }
    
    # 1. Ensure "1 day" timeframe is selected
    print("Checking timeframe '1 day'...")
    try:
        # Avoid CSS error for ID starting with digit
        btn_1d = page.locator('button[id="1D"]')
        if btn_1d.count() > 0:
            is_active = btn_1d.evaluate("el => el.getAttribute('aria-checked') === 'true' || el.classList.contains('active')")
            if not is_active:
                print("Clicking 1D timeframe...")
                btn_1d.click()
                time.sleep(5) # Wait for reload
        else:
            print("Timeframe button 1D not found.")
    except Exception as e:
        print(f"Error checking timeframe: {e}")

    # --- Helper to extract table by Section Title ---
    def extract_section_by_title(title):
        print(f"Searching for section: {title}...")
        try:
            # Scroll to end to ensure all lazy elements load
            page.mouse.wheel(0, 500)
            time.sleep(1)
            
            # Use JS to find section accurately
            table_info = page.evaluate(f"""(titleText) => {{
                const findHeader = (text) => {{
                    return Array.from(document.querySelectorAll('h2, a, span'))
                                .find(el => el.textContent.trim() === text);
                }};
                
                const header = findHeader(titleText);
                if (!header) return null;
                
                // Find nearest container
                let container = header.closest('div[class*="container-"], div[class*="tablesWrapper-"], div[class*="tableWrapper-"]');
                if (!container) {{
                    let p = header.parentElement;
                    while (p && p !== document.body) {{
                        if (p.querySelector('table') || p.querySelector('div[class*="row-"]')) {{
                            container = p;
                            break;
                        }}
                        p = p.parentElement;
                    }}
                }}
                
                if (!container) return null;
                
                // Try finding rows - could be tr or div with row- class
                const rowElements = Array.from(container.querySelectorAll('tr, div[class*="row-"]'));
                if (rowElements.length === 0) return null;
                
                // Identify headers (often first row or thead)
                let headers = [];
                const thead = container.querySelector('thead');
                if (thead) {{
                    headers = Array.from(thead.querySelectorAll('th')).map(th => th.innerText.trim());
                }} else if (rowElements.length > 0) {{
                    // Fallback to first row items if they look like headers
                    headers = Array.from(rowElements[0].querySelectorAll('td, div[class*="cell-"], div[class*="headCell-"]'))
                                   .map(c => c.innerText.trim());
                }}
                
                // If headers still empty, provide defaults or try to infer
                if (headers.length === 0) {{
                    if (titleText === "Pivots") headers = ["Pivot", "Classic", "Fibonacci", "Camarilla", "Woodie", "DM"];
                    else headers = ["Name", "Value", "Action"];
                }}

                const rows = rowElements.map(row => {{
                    const cells = Array.from(row.querySelectorAll('td, div[class*="cell-"]'));
                    return cells.map(cell => cell.innerText.trim().replace(/\\n/g, ' ')).filter(txt => txt !== "");
                }}).filter(r => r.length > 0);
                
                return {{ headers, rows }};
            }}""", title)
            
            if table_info:
                print(f"Found {len(table_info.get('rows', []))} rows for {title}.")
            else:
                print(f"No data found for {title}.")
                
            return table_info
        except Exception as e:
            print(f"Error extracting section {title}: {e}")
            return None

    # 2. Extract Sections
    data['oscillators'] = extract_section_by_title("Oscillators")
    data['moving_averages'] = extract_section_by_title("Moving Averages")
    data['pivots'] = extract_section_by_title("Pivots")
        
    return data

def format_technicals_report(data):
    now = datetime.now()
    md = [f"# TradingView Technical Analysis - VNINDEX - {now.strftime('%Y-%m-%d %H:%M:%S')}\n"]
    md.append(f"Source: {URL}\n")
    md.append("Timeframe: 1 Day\n\n")
    
    def dict_to_md_table(title, table_dict):
        if not table_dict or not table_dict.get('headers'):
            return f"### {title}: No Data\n\n"
        
        lines = [f"### {title}\n\n"]
        headers = table_dict['headers']
        rows = table_dict['rows']
        
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            row_clean = row + [""] * (max(0, len(headers) - len(row)))
            lines.append("| " + " | ".join(row_clean) + " |")
        lines.append("\n")
        return "\n".join(lines)

    md.append(dict_to_md_table("Oscillators", data.get('oscillators')))
    md.append(dict_to_md_table("Moving Averages", data.get('moving_averages')))
    md.append(dict_to_md_table("Pivots", data.get('pivots')))
    
    return "".join(md)

def main():
    configure_stdout()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1200}
        )
        page = context.new_page()
        
        try:
            data = parse_tradingview_technicals(page)
            
            if any(v and v.get('rows') for v in data.values()):
                report_content = format_technicals_report(data)
                
                # Save to file
                now = datetime.now()
                date_dir = now.strftime("%Y%m%d")
                full_dir = os.path.join(OUTPUT_DIR, date_dir)
                ensure_directory_exists(full_dir)
                
                filename = f"vnindex_technicals_{now.strftime('%H%M')}.md"
                filepath = os.path.join(full_dir, filename)
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(report_content)
                
                print(f"Saved report to {filepath}")
            else:
                print("No data extracted. Verify if page structure changed.")
                
        except Exception as e:
            print(f"Fatal error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
