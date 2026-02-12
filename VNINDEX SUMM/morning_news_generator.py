
import os
import sys
import datetime
import subprocess
import google.generativeai as genai
from dotenv import load_dotenv
import json
import re
import wave
import io
import google.auth

# Fix encoding
sys.stdout.reconfigure(encoding='utf-8')

# Load Env
load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDonSs_FcxC9pfyXwW6NiSGxLgbVZqg8_E")
# Hardcode GCS Config to verify path
BUCKET_NAME = "wealth-up-storage"
GCS_PREFIX = "dailyVnindexdata/latest/"
LOCAL_MOCK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gcs_mock"))

# Determine Environment
# 1. Default to False (Production-first safety)
IS_LOCAL = False
raw_local = os.environ.get("LOCAL_MODE", "False")
if raw_local.lower() == "true":
    IS_LOCAL = True

# 2. Force False if running in Cloud Run (K_SERVICE is present)
if os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"):
    print(f"Detected Cloud Run environment. Forcing IS_LOCAL=False.")
    IS_LOCAL = False

print(f"Config: BUCKET={BUCKET_NAME}, LOCAL_MODE={IS_LOCAL}")

# Try importing library for Cloud Storage and TTS
HAS_GCS_LIB = False
try:
    from google.cloud import storage
    from google.cloud import texttospeech
    print("✅ Google Cloud Libraries loaded.")
    HAS_GCS_LIB = True
except ImportError:
    print("⚠️  Google Cloud Libraries NOT found. This script requires them for full functionality.")

def run_gcloud_cmd(args):
    try:
        cmd = ["gcloud"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', shell=(os.name=='nt'))
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception as e:
        print(f"Error running gcloud: {e}")
        return None

def list_files_gcs(bucket_name, prefix):
    try:
        from google.cloud import storage
        print(f"DEBUG: GCS Connect - Bucket='{bucket_name}' (repr={repr(bucket_name)})")
        client = storage.Client()
        print(f"DEBUG: GCS Client Project: {client.project}")
        bucket = client.bucket(bucket_name)
        # cleanup prefix
        prefix_clean = prefix.strip("/")
        blobs = bucket.list_blobs(prefix=prefix_clean) 
        
        files = []
        for blob in blobs:
            if blob.name.endswith(".md"):
                files.append(blob.name) # blob.name is relative to bucket
        print(f"   [Debugging] Found {len(files)} files in GCS.")
        return files
    except Exception as e:
        print(f"⚠️ GCS List Error: {e}")
        return []

def read_file_gcs(bucket_name, blob_name):
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️ GCS Read Error: {e}")
        return ""

def list_files_local(mock_dir, prefix):
    target_dir = os.path.join(mock_dir, prefix.strip("/"))
    if not os.path.exists(target_dir): return []
    files = []
    for f in os.listdir(target_dir):
        if f.endswith(".md"): files.append(os.path.join(target_dir, f))
    return files

def read_file_local(path):
    try:
        with open(path, "r", encoding="utf-8") as f: return f.read()
    except Exception: return ""

def generate_morning_news():
    print("=== Morning News Generator (Long Audio TTS) ===")
    print(f"Config: BUCKET={BUCKET_NAME}, LOCAL_MODE={IS_LOCAL}")


    genai.configure(api_key=GEMINI_KEY)

    # Use Gemini 2.5 Pro for script generation
    model = genai.GenerativeModel('gemini-2.5-pro') 

    # --- 1. Load Data ---
    all_content = []
    if IS_LOCAL:
        print(f"Source: Local Mock ({LOCAL_MOCK_DIR}/latest)")
        files = list_files_local(LOCAL_MOCK_DIR, "latest")
        for f in files:
            print(f"   [+] Reading {os.path.basename(f)}...")
            content = read_file_local(f)
            all_content.append(f"--- FILE: {os.path.basename(f)} ---\n{content}\n")
    else:
        print(f"Source: GCS ({BUCKET_NAME}/{GCS_PREFIX})")
        files = list_files_gcs(BUCKET_NAME, GCS_PREFIX)
        for fname in files:
            print(f"   [Cloud] Reading {fname}...")
            content = read_file_gcs(BUCKET_NAME, fname)
            all_content.append(f"--- FILE: {fname} ---\n{content}\n")

    if not all_content:
        print(f"Warning: No data found in {GCS_PREFIX if not IS_LOCAL else LOCAL_MOCK_DIR}")
        return 
    
    full_data_context = "\n".join(all_content)

    # --- 2. Prompt for JSON (ENFORCING LONG SCRIPT) ---
    prompt_template = """
**VAI TRÒ:** Bạn là Đạo diễn nội dung số kiêm Chuyên gia Phân tích Tài chính.
**MỤC TIÊU:** Tạo kịch bản bản tin sáng "WEALTH UP MORNING BRIEF".

**YÊU CẦU ĐỘ DÀI (BẮT BUỘC):**
-   **Độ dài:** 600 - 800 từ (Tương đương 4-5 phút đọc).
-   **Số lượt lời:** Tối thiểu 15 lượt đối đáp giữa Mai và Hùng.

**NHÂN VẬT:**
1.  **Mai (MC Nữ)**: Dẫn dắt, số liệu.
2.  **Hùng (MC Nam)**: Phân tích sâu sắc.

**CẤU TRÚC KỊCH BẢN CHI TIẾT:**
1.  **Intro (30s)**: Lời chào năng lượng + Quote đầu tư.
2.  **Quốc tế & Hàng hóa (60s)**:
    - Mai: Cập nhật Dow Jones, Dầu, Vàng.
    - Hùng: Phân tích tác động liên thị trường tới VN-Index hôm nay.
3.  **Trong nước (90s)**:
    - Mai: VN-Index, Thanh khoản, Khối ngoại.
    - Hùng: "Đọc vị" dòng tiền, phân tích tâm lý.
4.  **Tâm điểm (60s)**:
    - Mai: Mã cổ phiếu biến động mạnh.
    - Hùng: Giải thích lý do (Tin đồn, KQKD, Vĩ mô).
5.  **Outro (30s)**: Tổng kết & Chào.

**DATA INPUT:**
{full_data_context}

**OUTPUT JSON FORMAT:**
```json
{
  "dialogue": [
    {
      "speaker": "Mai",
      "text": "Xin chào quý vị! [happy] Rất vui..."
    },
    ... (tiếp tục ít nhất 15 turn) ...
  ]
}
```
    """

    prompt = prompt_template.replace("{full_data_context}", full_data_context)
    
    print("Generating script content with Gemini...")
    try:
        response = model.generate_content(prompt)
        raw_content = response.text
        
        # Clean JSON
        clean_content = raw_content.strip()
        if clean_content.startswith("```json"): clean_content = clean_content.replace("```json", "", 1)
        if clean_content.startswith("```"): clean_content = clean_content.replace("```", "", 1)
        if clean_content.endswith("```"): clean_content = clean_content[:-3]
        clean_content = clean_content.strip()

        script_data = json.loads(clean_content)
        print(f"✅ JSON Script parsed. Turns: {len(script_data.get('dialogue', []))}")

        # Save JSON/MD
        today = datetime.datetime.now()
        year_str = today.strftime("%Y")
        month_str = today.strftime("%m")
        day_str = today.strftime("%d")

        script_filename = "morningnewscript.json"
        local_json_path = "/tmp/" + script_filename if not IS_LOCAL else os.path.join(os.path.dirname(__file__), script_filename)
        with open(local_json_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ Script saved: {local_json_path}")

        # --- IMMEDIATE UPLOAD JSON (Safety) ---
        if HAS_GCS_LIB and BUCKET_NAME and not IS_LOCAL:
             try:
                 storage_client = storage.Client()
                 bucket = storage_client.bucket(BUCKET_NAME)
                 gcs_json_path = f"dailyVnindexdata/{year_str}/{month_str}/{day_str}/{script_filename}"
                 blob_json = bucket.blob(gcs_json_path)
                 blob_json.upload_from_filename(local_json_path, content_type='application/json')
                 print(f"✅ Uploaded JSON immediately: {gcs_json_path}")
             except Exception as e:
                 print(f"⚠️ JSON Upload Error: {e}")

        # --- 3. Long Audio TTS Generation ---
        print(f">>> Starting Long Audio TTS for {len(script_data.get('dialogue', []))} turns...")
        
        try:
            # Check availability of Long Audio Client
            if not hasattr(texttospeech, "TextToSpeechLongAudioSynthesizeClient"):
                 print("❌ TextToSpeechLongAudioSynthesizeClient not found in this version of google-cloud-texttospeech. Please upgrade.")
                 return

            client = texttospeech.TextToSpeechLongAudioSynthesizeClient()
            print("✅ Long Audio TTS Client initialized")

            # Get Project ID from auth
            try:
                credentials, project_id = google.auth.default()
                print(f"✅ Authenticated with Project ID: {project_id}")
            except Exception as auth_err:
                print(f"⚠️ Auth error (using default 'wealth-up' fallback): {auth_err}")
                project_id = "wealth-up" # Fallback if auth check fails locally

            # Setup Location - Long Audio usually requires a specific location like us-central1 or eu-west-1
            location = "us-central1" 
            parent = f"projects/{project_id}/locations/{location}"

            from google.cloud.texttospeech_v1.types import MultiSpeakerMarkup, MultiSpeakerVoiceConfig, MultispeakerPrebuiltVoice
            
            turns = []
            for turn in script_data.get("dialogue", []):
                speaker_name = turn.get("speaker", "Mai")
                text = turn.get("text", "")
                if not text or not text.strip(): continue

                # Map local names to generic Speaker aliases
                alias = "Speaker2" if ("Hùng" in speaker_name or "Nam" in speaker_name) else "Speaker1"
                
                # Cleanup text for TTS
                text = text.replace("[pause]", "")
                text = re.sub(r'\[(?!break)[^\]]+\]', '', text)
                
                turns.append(MultiSpeakerMarkup.Turn(
                    text=text,
                    speaker=alias
                ))

            if not turns:
                print("❌ ERROR: No valid turns found for TTS.")
                return

            print(f">>> Sending {len(turns)} turns to Long Audio API (Gemini 2.5 Pro TTS)...")
            print(f"    Parent: {parent}")

            # Configure Speaker Mapping
            ms_config = MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    MultispeakerPrebuiltVoice(speaker_alias="Speaker1", speaker_id="Aoede"),  # Mai
                    MultispeakerPrebuiltVoice(speaker_alias="Speaker2", speaker_id="Charon")  # Hùng
                ]
            )

            # Configure Voice Params
            voice = texttospeech.VoiceSelectionParams(
                language_code="vi-VN", 
                model_name="gemini-2.5-pro-tts",
                multi_speaker_voice_config=ms_config
            )

            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000 
            )

            # Input with Markup
            synthesis_input = texttospeech.SynthesisInput(
                multi_speaker_markup=MultiSpeakerMarkup(turns=turns)
            )

            # Output Config
            # Construct formatted GCS URI
            now_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_filename = f"morning_news_{now_str}.wav"
            
            # Use 'latest' convention or date-based?
            # Existing system uses 'latest' prefix in BUCKET_NAME/GCS_PREFIX?
            # Input GCS_PREFIX is 'dailyVnindexdata/latest/'
            # Let's write to date folder AND latest if possible, but Long Audio outputs 1 file.
            # We'll write to date folder for persistence.
            
            today_path = datetime.datetime.now().strftime("dailyVnindexdata/%Y/%m/%d")
            gcs_uri = f"gs://{BUCKET_NAME}/{today_path}/{output_filename}"
            
            print(f"   Target GCS URI: {gcs_uri}")

            # Call Long Audio API
            request = texttospeech.SynthesizeLongAudioRequest(
                parent=parent,
                input=synthesis_input,
                audio_config=audio_config,
                voice=voice,
                output_gcs_uri=gcs_uri
            )

            operation = client.synthesize_long_audio(request=request)
            
            print(">>> Operation submitted. Waiting for completion (this may take a minute)...")
            result = operation.result(timeout=600) # Wait up to 10 minutes
            
            print(f"✅ Long Audio TTS success! Output saved to: {gcs_uri}")
            
        except Exception as tts_error:
            print(f"❌ CRITICAL ERROR during Long Audio TTS generation: {tts_error}")
            import traceback
            traceback.print_exc()
            return

    except Exception as e:
        print(f"Critical Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    generate_morning_news()
