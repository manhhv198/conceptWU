import os
import sys
import time
import datetime
from playwright.sync_api import sync_playwright

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

def get_current_timestamp():
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
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
    filename = os.path.join(folder, f"mktsumary{time_str}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved summary to {filename}")

def analyze_market_summary(url="https://finance.vietstock.vn/tong-hop-cac-thi-truong"):
    report_content = []
    
    date_str, time_str, now_obj = get_current_timestamp()
    report_content.append(f"# Market Summary - {now_obj.strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_content.append(f"Source: {url}\n\n")

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
            page.reload(wait_until="networkidle")
            
            # Wait for main content
            page.wait_for_selector(".markets-section__nav-bar-item", timeout=15000)

            # Close popup if exists
            try:
                close_btn = page.locator("#btn-close-ad, .close-popup, [class*='close']").first
                if close_btn.is_visible(timeout=3000):
                    print("Closing popup...")
                    close_btn.click()
            except:
                pass

            menus = ["Chứng khoán", "Hàng hóa", "Tiền tệ", "Tiền ảo"]
            
            for menu_name in menus:
                print(f"Processing menu: {menu_name}...")
                report_content.append(f"## {menu_name}\n")
                
                # 1. Click Menu
                try:
                    menu_item = page.locator(f".markets-section__nav-bar-item:has-text('{menu_name}')")
                    if menu_item.is_visible():
                        menu_item.click()
                        time.sleep(2) # Wait for content to switch
                    else:
                        print(f"Menu {menu_name} not found, skipping.")
                        report_content.append("*Menu item not found*\n")
                        continue
                except Exception as e:
                    print(f"Error clicking menu {menu_name}: {e}")
                    report_content.append(f"*Error accessing menu: {e}*\n")
                    continue

                # 2. Click Chart "1D"
                # The chart timeframe buttons might be shared or specific. We try to find the active one or just click "1D"
                try:
                    # Look for 1D button within the chart area or generally
                    btn_1d = page.locator(".general-markets__chart-timeframe:has-text('1D')").first
                    if btn_1d.is_visible():
                        print("Clicking 1D chart button...")
                        btn_1d.click()
                        time.sleep(2) # Wait for chart to update
                    else:
                        print("1D button not found.")
                except Exception as e:
                    print(f"Error clicking 1D button: {e}")

                # 3. Read Chart Summary info
                try:
                    # Attempt to find text inside highcharts container or specific info box
                    print("Reading chart info...")
                    chart_info_text = "No distinct chart info found."
                    
                    # Strategy 1: Look for specific chart info container if exists
                    info_box = page.locator("#general-markets-left .general-markets__chart-info").first
                    if info_box.is_visible():
                        chart_info_text = info_box.text_content().strip()
                    else:
                         # Strategy 2: Look for text nodes in highcharts
                         # This is tricky as highcharts splits text. We grab meaningful text.
                         container = page.locator("#general-markets-left .highcharts-container").first
                         if container.is_visible():
                             texts = container.locator("text").all_text_contents()
                             # Filter out empty or very short strings (axis labels)
                             valid_texts = [t.strip() for t in texts if len(t.strip()) > 3]
                             chart_info_text = " | ".join(valid_texts[:10]) # Take first few lines usually containing title/price
                    
                    report_content.append("### Chart Summary (1D)\n")
                    report_content.append(f"{chart_info_text}\n\n")
                    
                except Exception as e:
                    print(f"Error reading chart info: {e}")
                    report_content.append(f"*Error reading chart info: {e}*\n\n")

                # 4. Table Interaction "Tất cả" & Read Data
                try:
                    print("Reading table data...")
                    # Find table sub-tabs
                    all_btn = page.locator(".general-markets__data-subTabs-item:has-text('Tất cả')").first
                    if all_btn.is_visible():
                         print("Clicking 'Tất cả' button...")
                         all_btn.click()
                         # Wait for table reload
                         time.sleep(2) 
                    
                    # Read table
                    rows = page.locator(".js-general-market-data-content tr")
                    count = rows.count()
                    
                    report_content.append("### Table Data\n")
                    
                    if count > 0:
                        report_content.append("| Row | Content |\n")
                        report_content.append("| --- | --- |\n")
                        
                        # Limit rows to avoid huge files if necessary, but request said "toàn bộ"
                        for i in range(count):
                            row_text = rows.nth(i).inner_text().replace("\n", " | ").strip()
                            # Clean up multiple spaces
                            import re
                            row_text = re.sub(r'\s+', ' ', row_text)
                            report_content.append(f"| {i+1} | {row_text} |\n")
                    else:
                        report_content.append("*No data rows found.*\n")
                    
                    report_content.append("\n")

                except Exception as e:
                    print(f"Error reading table: {e}")
                    report_content.append(f"*Error reading table: {e}*\n\n")
                
                report_content.append("---\n\n")

        except Exception as e:
            print(f"Global error: {e}")
            report_content.append(f"\n# Error Occurred\n{e}\n")
        finally:
            browser.close()

    # Save to file
    full_content = "".join(report_content)
    save_markdown(full_content, date_str, time_str)

if __name__ == "__main__":
    analyze_market_summary()
