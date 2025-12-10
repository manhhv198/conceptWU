import requests

JINA_READER_URL = "https://r.jina.ai/"
target_url = "https://finance.vietstock.vn/"

headers = {
    'X-Return-Format': 'html',
    'X-Target-Selector': 'article, main, .main, #main, .content, #content, .post, .entry, table, figure, img, .chart, .graph, .highcharts-container, .highcharts-root, svg, canvas',
    'X-Remove-Selector': 'header, footer, nav, aside, .menu, .sidebar, .ad, .advertisement, .related, .comments, .cookie-banner, .popup, .highcharts-credits',
    'X-WaitFor-Selector': '.highcharts-root'
}

try:
    print(f"Calling Jina for {target_url}...")
    response = requests.get(JINA_READER_URL + target_url, headers=headers)
    print("Status:", response.status_code)
    print("--- RAW CONTENT PREVIEW ---")
    try:
        print(response.text[:2000])
    except:
        print(response.text[:2000].encode('utf-8', errors='ignore'))
    print("--- END PREVIEW ---")
    
    # Check for image syntax and HTML tags
    print("Scanning for images and SVGs...")
    found_any = False
    with open("debug_images.txt", "w", encoding="utf-8") as f:
        for line in response.text.split('\n'):
            if "![" in line or "<svg" in line or "<img" in line:
                f.write(f"MATCH: {line}\n")
                found_any = True
    
    if found_any:
        print("Found media tags. Saved to debug_images.txt")
    else:
        print("NO media tags found.")
        print("NO images found in markdown.")
        
except Exception as e:
    print("Error:", e)
