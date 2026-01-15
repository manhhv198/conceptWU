import os
import sys
import time
import datetime
from playwright.sync_api import sync_playwright

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

def get_current_timestamp():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M")
    return date_str, time_str, now

def ensure_directory(date_str):
    if not os.path.exists(date_str):
        os.makedirs(date_str)
    return date_str

def save_markdown(content, date_str, time_str):
    folder = ensure_directory(date_str)
    filename = os.path.join(folder, f"liquidity_summary_{time_str}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved summary to {filename}")

def analyze_liquidity_summary(url="https://finance.vietstock.vn/thanh-khoan-thi-truong"):
    report_content = []
    
    date_str, time_str, now_obj = get_current_timestamp()
    report_content.append(f"# Liquidity Summary - {now_obj.strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_content.append(f"Source: {url}\n")
    report_content.append(f"Index: VN-INDEX (Default)\n\n")

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
            
            # Ensure fresh data by reloading and waiting for network idle
            print("Reloading page to ensure fresh data...")
            page.reload(wait_until="domcontentloaded")
            time.sleep(5) # Give it some breathe time
            
            # Wait for meaningful content
            # .liquidity-content__chart might be slow, wait for body first then check
            page.wait_for_selector("body", timeout=30000)
            print("Page loaded, looking for components...")

            # Close popup if exists
            try:
                # Wait a bit for popup
                time.sleep(3)
                close_btn = page.locator("#btn-close-ad, .close-popup, [class*='close']").first
                if close_btn.is_visible(timeout=3000):
                    print("Closing popup...")
                    close_btn.click()
            except:
                pass

            # 1. Chart Interaction "1D" & Summary
            print("Processing Chart (VN-INDEX 1D)...")
            try:
                # Click 1D button
                btn_1d = page.locator(".liquidity-content__time .btn-group button:has-text('1D'), .general-markets__chart-timeframe:has-text('1D')").first
                if btn_1d.is_visible():
                    print("Clicking 1D chart button...")
                    btn_1d.click()
                    time.sleep(2)
                
                # Get Chart Summary Text
                # Improved strategy similar to market summary tool
                print("Reading chart info...")
                chart_summary_text = "No summary found."
                
                # Try finding the content area directly using updated selectors from debugging
                # Main container identified as .liquidity__chart-content or .liquidity-content
                
                chart_summary_text = "No summary found."
                
                # List of potential selectors for the summary text area
                # .liquidity__chart-content seems to be the one containing the SVG/Highcharts and text
                selectors = [".liquidity__chart-content", ".liquidity-content__chart", ".liquidity-content"]
                
                found_text = False
                for sel in selectors:
                    container = page.locator(sel).first
                    if container.is_visible():
                         # Get all inner text
                         full_text = container.inner_text()
                         lines = full_text.split('\n')
                         
                         valid_lines = [line.strip() for line in lines if len(line.strip()) > 5]
                         
                         # Filter for specific keywords: "Thanh khoản" and ("đạt" or "tăng" or "giảm")
                         summary_candidates = [t for t in valid_lines if "Thanh khoản" in t and ("đạt" in t or "tăng" in t)]
                         
                         if summary_candidates:
                             # Taking the longest one often gives the full sentence
                             chart_summary_text = max(summary_candidates, key=len)
                             found_text = True
                             print(f"Found summary in {sel}: {chart_summary_text[:50]}...")
                             break
                
                if not found_text:
                    print("Could not find summary with keywords. Dumping all text from .liquidity__chart-content for debugging.")
                    try:
                        debug_text = page.locator(".liquidity__chart-content").first.inner_text()
                        chart_summary_text = f"DEBUG CONTENT: {debug_text[:200]}..."
                    except:
                        pass
                
                report_content.append("## Chart Summary\n")
                report_content.append(f"{chart_summary_text}\n\n")

            except Exception as e:
                print(f"Error processing chart: {e}")
                report_content.append(f"*Error processing chart: {e}*\n\n")

            # 2. Table Data (Top 10)
            print("Processing Table (Top 10)...")
            try:
                # Select Top 10
                # Assuming there is a dropdown or option for Top 10
                # Selector gathered: #option-top-stock-liquidity
                top_select = page.locator("#option-top-stock-liquidity")
                if top_select.is_visible():
                    # Debug: Print available options
                    print(f"Select options: {top_select.inner_text()}")
                    
                    print("Selecting Top 10...")
                    # Try selecting by value "10" first (more consistent)
                    try:
                        top_select.select_option(value="10")
                    except:
                        # Fallback to label containing "10"
                        top_select.select_option(label="Top 10")
                    
                    time.sleep(3) # Wait for table update
                else:
                    print("Top 10 selector not found, using default view.")

                report_content.append("## Top 10 Liquidity Stocks\n")
                
                # Check for table rows
                rows = page.locator(".liquidity-content__detail-table table tr, .table-liquidity-top tr")
                count = rows.count()
                
                if count > 0:
                    report_content.append("| Row | Content |\n")
                    report_content.append("| --- | --- |\n")
                    
                    # Get headers if possible (usually first row)
                    # Limit to 11 rows (Header + 10 data rows)
                    limit = min(count, 12) 
                    
                    for i in range(limit):
                        row_text = rows.nth(i).inner_text().replace("\n", " | ").strip()
                        import re
                        row_text = re.sub(r'\s+', ' ', row_text)
                        report_content.append(f"| {i+1} | {row_text} |\n")
                else:
                    report_content.append("*No data rows found.*\n")

            except Exception as e:
                print(f"Error processing table: {e}")
                report_content.append(f"*Error processing table: {e}*\n\n")

        except Exception as e:
            print(f"Global error: {e}")
            report_content.append(f"\n# Error Occurred\n{e}\n")
        finally:
            browser.close()

    # Save to file
    full_content = "".join(report_content)
    save_markdown(full_content, date_str, time_str)

if __name__ == "__main__":
    analyze_liquidity_summary()
