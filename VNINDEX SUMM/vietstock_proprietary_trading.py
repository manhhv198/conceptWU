
import os
import sys
import time
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# --- Configuration ---
URL = "https://finance.vietstock.vn/giao-dich-tu-doanh"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def configure_stdout():
    if sys.platform.startswith('win'):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def parse_prop_trading_data(page):
    print("Navigating to Proprietary Trading page...")
    page.goto(URL, timeout=60000)
    page.wait_for_load_state("networkidle")
    
    # Force reload
    print("Reloading page...")
    page.reload(wait_until="domcontentloaded")
    time.sleep(5) 
    
    data = {
        "summary": {},
        "top_buy": [],
        "top_sell": []
    }
    
    # 1. Parse Left Chart (Daily Summary) via Highcharts Object
    # Highcharts.charts[0]
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
            date_val = list(summary_data.values())[0]['date']
            print(f"Summary Data (Date: {date_val}): {summary_data}")
        else:
            print("Failed to extract summary data.")
            
    except Exception as e:
        print(f"Error extracting summary: {e}")

    # 2. Parse Right Charts (Top Net Buy / Top Net Sell)
    # Survey findings:
    # Top Sell = Index 1
    # Top Buy = Index 2
    # Pattern: Values then Codes
    
    print("Extracting Top Stocks...")
    
    def parse_chart_texts(container_index):
        return page.evaluate(f"""() => {{
            const charts = document.querySelectorAll('.highcharts-container');
            if (charts.length <= {container_index}) return null;
            
            const container = charts[{container_index}];
            const texts = Array.from(container.querySelectorAll('text')).map(t => t.textContent.trim()).filter(t => t.length > 0);
            return texts;
        }}""")

    def pars_stock_list_values_first(raw_texts):
        # Pattern: All Values First, then All Codes.
        stock_pattern = re.compile(r'^[A-Z]{3}$')
        
        values = []
        codes = []
        
        for t in raw_texts:
            if stock_pattern.match(t):
                codes.append(t)
            else:
                try:
                    val_clean = t.replace(',', '')
                    val = float(val_clean)
                    values.append(val)
                except:
                    pass
        
        combined = []
        min_len = min(len(values), len(codes))
        for i in range(min_len):
            combined.append({'code': codes[i], 'value': values[i]})
        return combined

    # Extract Top Sell (Index 1)
    try:
        raw_sell = parse_chart_texts(1)
        if raw_sell:
            data['top_sell'] = pars_stock_list_values_first(raw_sell)
            print(f"Parsed {len(data['top_sell'])} sell stocks.")
    except Exception as e:
        print(f"Error parsing Top Sell: {e}")

    # Extract Top Buy (Index 2)
    try:
        raw_buy = parse_chart_texts(2)
        if raw_buy:
            data['top_buy'] = pars_stock_list_values_first(raw_buy)
            print(f"Parsed {len(data['top_buy'])} buy stocks.")
    except Exception as e:
        print(f"Error parsing Top Buy: {e}")
        
    return data

def format_report(data):
    now = datetime.now(timezone(timedelta(hours=7)))
    md = [f"# Proprietary Trading (Tu Doanh) - {now.strftime('%Y-%m-%d %H:%M:%S')}\n"]
    md.append(f"Source: {URL}\n\n")
    
    # Summary Table
    if data.get('summary'):
        md.append("### Daily Summary\n\n")
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
            data = parse_prop_trading_data(page)
            
            if data:
                report_content = format_report(data)
                
                # Save to file
                now = datetime.now(timezone(timedelta(hours=7)))
                date_dir = now.strftime("%Y%m%d")
                full_dir = os.path.join(OUTPUT_DIR, date_dir)
                ensure_directory_exists(full_dir)
                
                filename = f"proprietary_trading_{now.strftime('%H%M')}.md"
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
