import os
import subprocess
import sys
import glob
import re
from datetime import datetime
from google.cloud import storage

# --- Configuration ---
# Match the list from VNINDEX_SUMM_RUN.py
SCRIPTS = [
    "vietstock_market_summary.py",
    "vietstock_liquidity_summary.py",
    "vietstock_top_influence.py",
    "vietstock_foreign_transaction.py",
    "vietstock_proprietary_trading.py",
    "vietstock_sector_data.py",
    "tradingview_vnindex_technicals.py",
    # "rss_news_aggregator.py" # Optional: decide if this should run too
]

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
# If not set, we can optionally warn or skip upload (useful for local testing)

def upload_to_gcs(local_path, destination_blob_name):
    """Uploads a file to the bucket."""
    if not BUCKET_NAME:
        print(f"[Warn] No GCS_BUCKET_NAME set. Skipping upload for {local_path}")
        return

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)
        # Explicitly set UTF-8 content type to fix browser rendering issues
        blob.upload_from_filename(local_path, content_type='text/markdown; charset=utf-8')
        print(f"[Cloud] Uploaded {local_path} to gs://{BUCKET_NAME}/{destination_blob_name}")
    except Exception as e:
        print(f"[Error] Failed to upload {local_path}: {e}")

def run_scripts():
    print(f"=== CLOUD RUNNER START: {datetime.now()} ===")
    
    current_dir = os.getcwd()
    print(f"Working Directory: {current_dir}")

    # Set OUTPUT_DIR for tradingview script if not set
    # We want everything in current_dir (which will be /tmp in Cloud Run)
    if "OUTPUT_DIR" not in os.environ:
        os.environ["OUTPUT_DIR"] = current_dir

    for script in SCRIPTS:
        print(f"\n>>> Running {script}...")
        script_path = os.path.join(current_dir, script)
        
        if not os.path.exists(script_path):
             # Fallback: maybe scripts are in /app but WORKDIR is /tmp
             # Let's try to assume scripts are in /app if current dir is /tmp
             if current_dir == "/tmp" and os.path.exists(f"/app/{script}"):
                 script_path = f"/app/{script}"
             elif os.path.exists(os.path.join(os.path.dirname(__file__), script)):
                 script_path = os.path.join(os.path.dirname(__file__), script)

        if not os.path.exists(script_path):
            print(f"[!] Script not found: {script}")
            continue

        try:
            # Run the script
            # We pass current env which includes OUTPUT_DIR
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=os.environ
            )
            
            print(result.stdout)
            if result.returncode != 0:
                print(f"[!] Error executing {script}:")
                print(result.stderr)
        except Exception as e:
            print(f"[!] Exception running {script}: {e}")

    print("\n>>> Analysis Phase Complete. Starting Upload Phase...")

    # Recursively find all .md files in the current directory (or subdirs)
    # Since scripts create subfolders like YYYYMMDD/file.md
    files_to_upload = glob.glob("**/*.md", recursive=True)
    
    # Filter out requirements or readme if any (unlikely in /tmp)
    
    today = datetime.now()
    year_str = today.strftime("%Y")
    month_str = today.strftime("%m")
    day_str = today.strftime("%d")
    
    # Base folder in bucket
    base_folder = "dailyVnindexdata"
    uploaded_count = 0

    for local_file in files_to_upload:
        file_name = os.path.basename(local_file)
        
        # 1. Archive Path: dailyVnindexdata/YYYY/MM/DD/filename
        archive_path = f"{base_folder}/{year_str}/{month_str}/{day_str}/{file_name}"
        
        # 2. Latest Path: dailyVnindexdata/latest/filename_without_timestamp
        # Regex to remove datetime pattern (e.g., _0415 or _20260115) from the end of filename
        # Pattern: look for _\d{4}.md or _\d{8}.md at the end
        clean_name = re.sub(r'_\d{4}\.md$', '.md', file_name) 
        clean_name = re.sub(r'_\d{8}\.md$', '.md', clean_name)
        
        latest_path = f"{base_folder}/latest/{clean_name}"
        
        # Upload to Archive
        upload_to_gcs(local_file, archive_path)
        
        # Upload to Latest
        upload_to_gcs(local_file, latest_path)
        
        uploaded_count += 1

    print(f"=== CLOUD RUNNER COMPLETE. Uploaded {uploaded_count} files. ===")

if __name__ == "__main__":
    run_scripts()
