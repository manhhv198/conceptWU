
import os
import sys
import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- Configuration ---
URL = "https://finance.vietstock.vn/giao-dich-nha-dau-tu-nuoc-ngoai"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def configure_stdout():
    if sys.platform.startswith('win'):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def parse_foreign_data(page):
    print("Navigating to Foreign Transaction page...")
    page.goto(URL, timeout=60000)
    page.wait_for_load_state("networkidle")
    
    # Force reload to ensure fresh data
    print("Reloading page...")
    page.reload(wait_until="domcontentloaded")
    time.sleep(5) # Wait for charts to render
    
    data = {
        "summary": {},
        "top_buy": [],
        "top_sell": []
    }
    
    # 1. Parse Left Chart (Daily Summary) via Highcharts Object
    # This is more robust than hovering
    print("Extracting Daily Summary...")
    try:
        summary_data = page.evaluate("""() => {
            const chart = Highcharts.charts[0];
            if (!chart) return null;
            
            const lastIdx = chart.series[0].options.data.length - 1;
            if (lastIdx < 0) return null;
            
            const result = {};
            chart.series.forEach(s => {
                const point = s.options.data[lastIdx];
                result[s.name] = {
                    value: point.y,
                    date: point.custom ? point.custom.customTradingDate : 'N/A'
                };
            });
            return result;
        }""")
        
        if summary_data:
            data['summary'] = summary_data
            date_str = list(summary_data.values())[0]['date']
            print(f"Summary Data (Date: {date_str}): {summary_data}")
        else:
            print("Failed to extract summary data.")
            
    except Exception as e:
        print(f"Error extracting summary: {e}")

    # 2. Parse Right Charts (Top Net Buy / Top Net Sell)
    # Based on investigation: code and value are text elements in SVG
    
    print("Extracting Top Stocks...")
    # There are usually 3 charts specific to this page in structure.
    # Chart 0: Daily Summary
    # Chart 1: Top Sell (Wait, verify order)
    # Chart 2: Top Buy
    
    # Helper to parse text pairs from a chart container
    def parse_chart_texts(container_index):
        return page.evaluate(f"""() => {{
            const charts = document.querySelectorAll('.highcharts-container');
            if (charts.length <= {container_index}) return null;
            
            const container = charts[{container_index}];
            // Get all text elements
            const texts = Array.from(container.querySelectorAll('text')).map(t => t.textContent.trim()).filter(t => t.length > 0);
            return texts;
        }}""")

    # Let's get both and heuristically decide or use strict index
    # Subagent found: Index 1 had HDB (Sell), Index 2 had STB (Buy).
    # But let's check titles to be sure? Titles might be outside SVG.
    # The container titles are text in .foreign__chart-title
    
    titles = page.locator(".foreign__chart-title").all_text_contents()
    # Expecting: "Giá trị giao dịch NĐTNN...", "Top mua ròng...", "Top bán ròng..." ??
    # Actually site layout might vary.
    # Let's trust the parse and check values.
    
    def pars_stock_list(raw_texts):
        # Debug Output structure: ['72.06', ..., 'HDB', ...]
        # Pattern: All Values First, then All Codes.
        
        stock_pattern = re.compile(r'^[A-Z]{3}$')
        
        values = []
        codes = []
        
        for t in raw_texts:
            # Check if code
            if stock_pattern.match(t):
                codes.append(t)
            else:
                # Check if value
                try:
                    val_clean = t.replace(',', '')
                    val = float(val_clean)
                    values.append(val)
                except:
                    pass
        
        # Map them
        # Assuming equal length and order
        combined = []
        min_len = min(len(values), len(codes))
        
        for i in range(min_len):
            combined.append({'code': codes[i], 'value': values[i]})
            
        return combined

    # Try Index 1 and 2
    # Based on Debug:
    # Container 1: HDB, LPB -> Top Sell
    # Container 2: STB, VPL -> Top Buy
    
    raw_1 = parse_chart_texts(1)
    raw_2 = parse_chart_texts(2)
    
    list_1 = pars_stock_list(raw_1) if raw_1 else []
    list_2 = pars_stock_list(raw_2) if raw_2 else []
    
    # Explicit Mapping based on investigation
    data['top_sell'] = list_1
    data['top_buy'] = list_2
        
    return data

def format_report(data):
    now = datetime.now()
    md = [f"# Foreign Investor Transactions - {now.strftime('%Y-%m-%d %H:%M:%S')}\n"]
    md.append(f"Source: {URL}\n\n")
    
    # Summary Table
    if data.get('summary'):
        md.append("### Daily Summary\n\n")
        # Extract date
        date_val = list(data['summary'].values())[0]['date']
        md.append(f"**Date:** {date_val}\n\n")
        
        md.append("| Category | Value (Billion VND) |\n")
        md.append("| --- | --- |\n")
        
        order = ["Giá trị mua", "Giá trị bán", "Giá trị mua ròng"]
        for k in order:
            item = data['summary'].get(k)
            if item:
                md.append(f"| {k} | {item['value']:.2f} |\n")
        md.append("\n")
        
    # Top Buy
    md.append("### Top Net Buy (Top Mua Ròng)\n\n")
    md.append("| Stock Code | Value (Billion VND) |\n")
    md.append("| --- | --- |\n")
    for item in data['top_buy']:
        md.append(f"| {item['code']} | {item['value']:.2f} |\n")
    md.append("\n")

    # Top Sell
    md.append("### Top Net Sell (Top Bán Ròng)\n\n")
    md.append("| Stock Code | Value (Billion VND) |\n")
    md.append("| --- | --- |\n")
    for item in data['top_sell']:
        md.append(f"| {item['code']} | {item['value']:.2f} |\n")
    md.append("\n")
    
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
            data = parse_foreign_data(page)
            
            if data:
                report_content = format_report(data)
                
                # Save to file
                now = datetime.now()
                date_dir = now.strftime("%Y%m%d")
                full_dir = os.path.join(OUTPUT_DIR, date_dir)
                ensure_directory_exists(full_dir)
                
                filename = f"foreign_transaction_{now.strftime('%H%M')}.md"
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
