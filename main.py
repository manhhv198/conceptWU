import re
import requests
import google.generativeai as genai
from PIL import Image, UnidentifiedImageError
from io import BytesIO
import os
import time
import sys
import xml.etree.ElementTree as ET

# Force UTF-8 logging so emojis don't crash Windows terminals
sys.stdout.reconfigure(encoding='utf-8')

# --- CẤU HÌNH ---
# 1. API Key Gemini
# Prefer environment variable, fallback to placeholder or user input
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyAAr00S3VxBdwXHJZYtji-VMW6gBCulxR8")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# 2. Jina Reader Endpoint (Dùng miễn phí, không cần key cho mức độ cơ bản)
JINA_READER_URL = "https://r.jina.ai/"

# Global Token Counters
token_usage = {
    "jina": {"in": 0, "out": 0},
    "gemini": {"in": 0, "out": 0}
}

def get_text_from_jina(target_url):
    """Gọi Jina để lấy nội dung Markdown sạch (có Retry)"""
    print(f"1️⃣  Đang gọi Jina Reader để lấy văn bản: {target_url}")
    headers = {
        'X-Return-Format': 'html',
        # Target Selector: Mở rộng để bắt các class biểu đồ phổ biến như Highcharts, canvas, svg
        'X-Target-Selector': 'article, main, .main, #main, .content, #content, .post, .entry, table, figure, img, .chart, .graph, .highcharts-container, .highcharts-root, svg, canvas',
        # Remove Selector: Giữ nguyên nhưng đảm bảo không xóa nhầm class chứa chart
        'X-Remove-Selector': 'header, footer, nav, aside, .menu, .sidebar, .ad, .advertisement, .related, .comments, .cookie-banner, .popup, .highcharts-credits',
        'X-WaitFor-Selector': '.highcharts-root' # Chờ chart tải xong
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(JINA_READER_URL + target_url, headers=headers, timeout=60) # Tăng timeout client lên 60s
            
            if response.status_code == 200:
                # Jina không trả token usage trong header chuẩn, ta ước lượng hoặc lấy từ header nếu sau này có update
                # Input: URL length (ước lượng thô)
                token_usage["jina"]["in"] += len(target_url) 
                # Output: Content length
                token_usage["jina"]["out"] += len(response.text)
                
                return response.text
            elif response.status_code == 524 or response.status_code >= 500:
                print(f"   ⚠️ Lỗi server Jina ({response.status_code}). Đang thử lại ({attempt + 1}/{max_retries})...")
                time.sleep(3) # Đợi 3s trước khi thử lại
            else:
                print(f"❌ Lỗi Jina: {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            print(f"   ⚠️ Timeout kết nối (Client). Đang thử lại ({attempt + 1}/{max_retries})...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ Lỗi kết nối Jina: {e}")
            return None
            
    print("❌ Thất bại sau nhiều lần thử.")
    return None

# ... (images code unchanged) ...

def process_content_hybrid(url):
    # Bước 1: Lấy Text sạch từ Jina
    markdown_content = get_text_from_jina(url)
    if not markdown_content:
        return []

    print("2️⃣  Đang xử lý nội dung và quét ảnh...")
    
    # Regex phát hiện ảnh: ![alt](url)
    image_pattern = re.compile(r'!\[.*?\]\((https?://.*?)\)')
    
    # Regex để loại bỏ link [text](url) -> giữ lại text
    # Negative lookbehind (?<!!) đảm bảo không match ![...] (ảnh)
    link_pattern = re.compile(r'(?<!!)\[([^\]]+)\]\([^\)]+\)')
    
    labeled_data = [] # List of tuples: (type, content) -> ("TEXT", "...") or ("IMAGE", "...")

    # Tách dòng để xử lý từng phần
    lines = markdown_content.split('\n')
    
    # --- Jina đã lọc bằng Selector nên không cần extract_main_body quá gắt gao nữa ---
    # lines = extract_main_body(lines) 
    # Nhưng vẫn gọi để loại bỏ phần thừa nếu Jina sót (ví dụ text rác ở đầu/cuối post)
    lines = extract_main_body(lines)
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Kiểm tra xem dòng này có phải ảnh không
        img_match = image_pattern.search(line)
        if img_match:
            img_url = img_match.group(1)
            description = analyze_image_with_gemini(img_url)
            if description:
                labeled_data.append(("IMAGE", description))
        else:
            # Xử lý Text:
            # 1. Loại bỏ link Markdown, chỉ giữ text
            clean_line = link_pattern.sub(r'\1', line)
            
            # 2. Lọc text rác/menu
            if len(clean_line) < 20: 
                continue
                
            # Nếu đạt chuẩn thì lưu vào
            labeled_data.append(("TEXT", clean_line))

    print(f"   -> Đã xử lý xong. Tổng số mục: {len(labeled_data)}")
    return labeled_data

def analyze_image_with_gemini(img_url, hint=""):
    """Tải ảnh và nhờ Gemini mô tả. Đối với SVG thì trích xuất text."""
    print(f"   Analysing Image: {img_url[:40]}...")
    try:
        # Tải ảnh về
        headers = {'User-Agent': 'Mozilla/5.0'} 
        img_resp = requests.get(img_url, headers=headers, timeout=10)
        
        if img_resp.status_code != 200:
            print(f"   -> Lỗi tải ảnh: Status {img_resp.status_code}")
            return None

        content_type = img_resp.headers.get('Content-Type', '').lower()
        
        # --- XỬ LÝ RIÊNG CHO SVG ---
        # Sửa logic: Không chặn SVG ngay, mà check nội dung
        if 'svg' in content_type or img_url.lower().endswith('.svg'):
            try:
                svg_content = img_resp.content.decode('utf-8', errors='ignore')
                root = ET.fromstring(svg_content)
                
                # 1. Check kích thước (Heuristic đơn giản)
                width = root.get('width')
                height = root.get('height')
                
                def parse_dim(val):
                    if not val: return 0
                    # Lấy số đầu tiên tìm thấy
                    nums = re.findall(r'\d+', str(val))
                    return int(nums[0]) if nums else 0

                w_val = parse_dim(width)
                h_val = parse_dim(height)
                
                # Nếu có kích thước và cả 2 đều nhỏ < 150 -> Logo/Icon
                # EXCEPTION: Nếu là chart trend (hint) thì giữ lại
                is_chart_hint = 'trend' in hint or 'chart' in hint
                if not is_chart_hint and w_val > 0 and h_val > 0 and (w_val < 100 or h_val < 100):
                     print(f"   -> Bỏ qua SVG nhỏ ({w_val}x{h_val})")
                     return None
                
                # 2. Trích xuất Text
                # Namespace thường gặp trong SVG {http://www.w3.org/2000/svg}
                # Dùng .iter() để quét hết mọi node, lấy .text
                texts = []
                for elem in root.iter():
                    if elem.text and elem.text.strip():
                        texts.append(elem.text.strip())
                
                full_text = " ".join(texts)
                
                # Nếu text quá ngắn -> Có thể vẫn là logo dạng chữ -> Bỏ qua
                if len(full_text) < 20: 
                    print(f"   -> Bỏ qua SVG ít nội dung ({len(full_text)} chars)")
                    return None
                    
                return f"[SVG TEXT EXTRACTION]: {full_text}"
                
            except Exception as e:
                print(f"   -> Lỗi parse SVG: {e}")
                return None

        # --- XỬ LÝ ẢNH RASTER (JPG/PNG/WEBP) ---
        if not content_type.startswith('image/'):
             # Fallback check extension if content-type is missing/octet-stream
             if not any(x in img_url.lower() for x in ['.jpg', '.png', '.webp', '.jpeg']):
                print(f"   -> Bỏ qua không phải ảnh: {content_type}")
                return None

        img_data = Image.open(BytesIO(img_resp.content))
        
        # Bỏ qua ảnh quá nhỏ (icon/logo)
        # EXCEPTION: Nếu là chart trend (hint) thì giữ lại
        is_chart_hint = 'trend' in hint or 'chart' in hint
        if not is_chart_hint and (img_data.size[0] < 150 or img_data.size[1] < 150):
            print(f"   -> Bỏ qua ảnh nhỏ ({img_data.size}).")
            return None

        prompt = """
Đóng vai trò là một công cụ OCR và trích xuất dữ liệu thô. Hãy phân tích hình ảnh này và thực hiện nhiệm vụ sau:

1. TRÍCH XUẤT: Ghi lại chính xác các đoạn văn bản (text) và các con số/số liệu đi kèm xuất hiện trong ảnh.
2. ĐỐI VỚI BIỂU ĐỒ/BẢNG: Chỉ liệt kê các nhãn (label) và giá trị số tương ứng (value) mà bạn nhìn thấy rõ.

TUÂN THỦ NGHIÊM NGẶT CÁC QUY TẮC CẤM SAU (NEGATIVE CONSTRAINTS):
- KHÔNG mô tả các yếu tố thị giác (màu sắc, hình dáng, kích thước, bố cục, font chữ, độ sáng).
- KHÔNG dùng các từ ngữ mô tả thẩm mỹ (đẹp, xấu, trực quan, rõ ràng).
- KHÔNG diễn giải ý nghĩa, không phân tích xu hướng (ví dụ: KHÔNG nói "biểu đồ cho thấy xu hướng tăng" hay "lợi nhuận rất tốt").
- KHÔNG suy luận những thông tin không hiển thị trực tiếp bằng chữ hoặc số trên ảnh.

Đầu ra chỉ bao gồm dữ liệu văn bản và số liệu thô."""
        response = model.generate_content([prompt, img_data])
        
        # Track Gemini Usage
        if response.usage_metadata:
            token_usage["gemini"]["in"] += response.usage_metadata.prompt_token_count
            token_usage["gemini"]["out"] += response.usage_metadata.candidates_token_count
            
        return response.text.strip()
    except UnidentifiedImageError:
        print(f"   -> Lỗi: Không nhận dạng được định dạng ảnh (có thể là WebP lỗi hoặc file hỏng).")
        return None
    except Exception as e:
        print(f"   -> Lỗi xử lý ảnh khác: {e}")
        return None # Bỏ qua nếu lỗi tải ảnh

def print_token_report():
    print("\n" + "="*40)
    print("📊 BÁO CÁO TOKEN USAGE")
    print("="*40)
    print(f"🔹 Jina Reader (Ước lượng char):")
    print(f"   - Input : {token_usage['jina']['in']} chars")
    print(f"   - Output: {token_usage['jina']['out']} chars")
    print(f"🔹 Gemini AI (Token chính xác):")
    print(f"   - Input : {token_usage['gemini']['in']} tokens")
    print(f"   - Output: {token_usage['gemini']['out']} tokens")
    print("="*40 + "\n")



def extract_main_body(lines):
    """
    Heuristic đơn giản để loại bỏ Header/Footer:
    1. Tìm 'start_index': Dòng đầu tiên có độ dài > 50 ký tự và không phải là link đơn thuần.
    2. Tìm 'end_index': Dòng cuối cùng có độ dài > 50 ký tự.
    3. Cắt bỏ phần đầu và cuối ngoài khoảng này, vì thường là menu/footer links.
    """
    if not lines:
        return []
        
    start_index = 0
    end_index = len(lines)
    
    # 1. Quét từ trên xuống tìm điểm bắt đầu nội dung chính
    # Bỏ qua các dòng ngắn hoặc dòng chỉ là link [text](url)
    for i, line in enumerate(lines):
        line = line.strip()
        is_link = line.startswith('[') and line.endswith(')') and '](' in line
        # Logic mới: Nếu gặp Ảnh, SVG, hoặc Table thì coi là bắt đầu nội dung ngay
        is_media = '![' in line or '<svg' in line or line.startswith('|')
        
        if (len(line) > 80 and not is_link) or is_media:
            start_index = i
            break
            
    # 2. Quét từ dưới lên tìm điểm kết thúc
    for i in range(len(lines) - 1, start_index, -1):
        line = lines[i].strip()
        is_link = line.startswith('[') and line.endswith(')') and '](' in line
        
        # Stop words cho footer
        lower_line = line.lower()
        if "bản quyền" in lower_line or "copyright" in lower_line or "liên hệ" in lower_line:
            end_index = i
            continue # Tiếp tục lùi để cắt bỏ dòng này
        
        # Logic mới: Nếu gặp Ảnh, SVG, hoặc Table thì coi là phần nội dung, không cắt
        is_media = '![' in line or '<svg' in line or line.startswith('|')
        
        if (len(line) > 80 and not is_link) or is_media:
            end_index = i + 1 # Giữ lại dòng này
            break
            
    # Safety: Nếu cắt quá nhiều (còn < 10% dòng), có thể heuristics sai -> trả về nguyên gốc hoặc fallback
    if end_index - start_index < len(lines) * 0.1:
        print("   -> Cảnh báo: Heuristics cắt quá nhiều, giữ nguyên nội dung gốc.")
        return lines

    print(f"   -> Cắt Header ({start_index} dòng) và Footer ({len(lines)-end_index} dòng).")
    return lines[start_index:end_index]

def process_content_hybrid(url):
    # Bước 1: Lấy Text sạch từ Jina
    markdown_content = get_text_from_jina(url)
    if not markdown_content:
        return []

    print("2️⃣  Đang xử lý nội dung HTML...")
    
    # Regex Patterns
    # 1. Capture SVGs (Start to End, DOTALL to span lines)
    svg_pattern = re.compile(r'(<svg[^>]*>.*?</svg>)', re.DOTALL | re.IGNORECASE)
    # 2. Capture Img Tags
    img_pattern = re.compile(r'<img[^>]+src=["\'](https?://[^"\']+)["\'][^>]*>', re.IGNORECASE)
    
    labeled_data = [] 

    # --- Step 1: Extract & Process SVGs first (to avoid stripping them) ---
    # We find all SVGs, process them, and then replace them with a placeholder or remove them
    def svg_handler(match):
        svg_content = match.group(1)
        # Check if it's an empty/self-closing SVG tag caught by regex (rare if strictly matched, but safecheck)
        if "viewBox" not in svg_content and len(svg_content) < 100:
             return ""
             
        # Extract text from SVG
        # Simple text extraction: remove tags
        text_content = re.sub(r'<[^>]+>', ' ', svg_content).strip()
        text_content = re.sub(r'\s+', ' ', text_content) # Normalize whitespace
        
        if len(text_content) > 20:
             print(f"   -> Found SVG Chart Data: {text_content[:50]}...")
             labeled_data.append(("CHART_DATA", f"[SVG_EXTRACT]: {text_content}"))
        else:
             print("   -> Found SVG but empty text/data.")
        
        return "" # Remove from main text

    # Apply SVG handler and remove SVGs from content
    content_no_svg = svg_pattern.sub(svg_handler, markdown_content)
    print(f"   -> DEBUG: content_no_svg len: {len(content_no_svg)}")
    with open("debug_content.txt", "w", encoding="utf-8") as f:
        f.write(content_no_svg)

    # --- Step 2: Extract Images ---
    # Improved regex to handle various attribute orders
    # Try a simpler regex first for debugging if the complex one fails
    # img_pattern = re.compile(r'<img[^>]+src=["\'](https?://[^"\']+)["\'][^>]*>', re.IGNORECASE)
    
    # Let's try finding ALL src attributes in img tags roughly
    img_matches = re.finditer(r'<img\s+[^>]*src=["\']([^"\']+)["\']', content_no_svg, re.IGNORECASE)
    
    match_list = list(img_matches)
    print(f"   -> DEBUG block: Tìm thấy {len(match_list)} thẻ img tiềm năng.")
    
    for img_match in match_list:
        url = img_match.group(1)
        
        # --- Filter Logic ---
        lower_url = url.lower()
        
        # 1. Skip obvious UI icons/logos UNLESS they are charts
        is_chart = 'trend' in lower_url or 'chart' in lower_url or 'kpi' in lower_url
        if not is_chart and ("icon" in lower_url or "logo" in lower_url or "menu" in lower_url or "btn" in lower_url):
            print(f"      [SKIP-ICON] {url[-20:]}")
            continue
            
        # 2. Skip tracking pixels /ads
        if "delivery/lg.php" in lower_url or "facebook" in lower_url or ".gif" in lower_url:
             print(f"      [SKIP-AD] {url[-20:]}")
             continue
             
        # 3. Handle Relative URLs (Vietstock uses relative paths)
        if not url.startswith('http'):
            # Basic join (assuming base is target_url domain)
            # Just print for now to see if this is the issue
            print(f"      [SKIP-RELATIVE] {url}")
            continue

        print(f"      [PROCESS] Check: {url}")
        description = analyze_image_with_gemini(url, lower_url)
        if description:
             labeled_data.append(("IMAGE", description))
        else:
             print("      [FAIL-GEMINI] Không lấy được mô tả.")

    # --- Step 3: Cleanup Text ---
    # Convert HTML to Text (strip tags) using a regex or simple method
    # Since we don't have BeautifulSoup, we use regex to strip tags
    clean_text = content_no_svg
    # Remove scripts/styles first
    clean_text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', ' ', clean_text) 
    
    lines = clean_text.split('\n')
    # Filter blank lines
    lines = [line.strip() for line in lines if line.strip()]
    
    # Use extract_main_body but be careful not to strip too much if structure is different
    # For now, let's keep it simple: just filter short lines
    
    for line in lines:
        if len(line) < 20 and not line.startswith('|') and not line.startswith('VN-Index'):
            continue
        labeled_data.append(("TEXT", line))

    print(f"   -> Đã xử lý xong. Tổng số mục: {len(labeled_data)}")
    return labeled_data

def save_file(data):
    filename = "structured_output.txt"
    with open(filename, "w", encoding="utf-8") as f:
        for item_type, content in data:
            # Format: Object - content
            # Xử lý xuống dòng trong content để đảm bảo format trên 1 dòng (nếu cần) hoặc giữ nguyên khối
            # Yêu cầu: "Object - content". Để dễ đọc, có thể cho content nằm cùng dòng hoặc ngay sau.
            # Ở đây ta sẽ replace newline trong content thành space để đúng format 1 dòng logic
            clean_content = content.replace('\n', ' ').strip()
            f.write(f"{item_type} - {clean_content}\n")
            
    print(f"\n✅ Xong! Kết quả lưu tại: {filename}")

# --- CHẠY ---
if __name__ == "__main__":
    url_input = input("\nNhap URL bai viet can xu ly: ").strip()
    # url_input = "https://finance.vietstock.vn/"
    
    if not url_input:
        print("❌ Vui lòng nhập URL hợp lệ!")
    else:
        result = process_content_hybrid(url_input)
        if result:
            save_file(result)
        print_token_report()
