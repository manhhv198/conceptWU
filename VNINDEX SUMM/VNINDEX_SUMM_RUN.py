
import os
import subprocess
import sys
from datetime import datetime

# --- Configuration ---
SCRIPTS = [
    "vietstock_market_summary.py",
    "vietstock_liquidity_summary.py",
    "vietstock_top_influence.py",
    "vietstock_foreign_transaction.py",
    "vietstock_proprietary_trading.py",
    "vietstock_sector_data.py",
    "tradingview_vnindex_technicals.py",
    "rss_news_aggregator.py",
    "morning_news_generator.py"
]

def main():
    print(f"=== VNINDEX ALL-IN-ONE ANALYSIS RUNNER ===")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 40)
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    for script in SCRIPTS:
        script_path = os.path.join(current_dir, script)
        if not os.path.exists(script_path):
            print(f"[!] Warning: {script} not found in {current_dir}")
            continue
            
        print(f"[*] Running {script}...")
        try:
            # Use sys.executable to ensure the same python environment
            result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, encoding='utf-8', errors='replace')
            if result.returncode == 0:
                print(f"[+] Success: {script}")
                # Print last part of output to show where report was saved
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if "Saved report to" in line:
                        print(f"    {line.strip()}")
            else:
                print(f"[-] Error in {script}:")
                print(result.stderr)
        except Exception as e:
            print(f"[!] Fatal error running {script}: {e}")
            
    print("-" * 40)
    print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("All tasks completed.")

if __name__ == "__main__":
    main()
