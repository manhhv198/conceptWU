
import os
import sys
import json
from firecrawl import FirecrawlApp
from dotenv import load_dotenv

# Force UTF-8 logging
sys.stdout.reconfigure(encoding='utf-8')

# Load environment variables
load_dotenv()

def main():
    print("=== FIRECRAWL EXTRACT (V4) ===")
    
    # 1. Get configuration
    api_key = os.getenv('FIRECRAWL_API_KEY', "fc-04b104bc02724e0fae8bff5f981ec24b")
    if not api_key:
        print("Error: FIRECRAWL_API_KEY not found in environment variables.")
        return

    # 2. Parse CLI Arguments
    if len(sys.argv) < 2:
        print("\nUsage: python main_v4.py <URL> [Prompt]")
        print("Example: python main_v4.py https://example.com 'Extract the main product price and name'")
        
        # Interactive mode fallback
        url = input("\nEnter URL to Extract: ").strip()
        if not url: return
        prompt = input("Enter Prompt (default: 'Extract main content'): ").strip()
    else:
        url = sys.argv[1]
        prompt = sys.argv[2] if len(sys.argv) > 2 else ""

    if not prompt:
        prompt = "Extract the main content from this page."

    # 3. Initialize App
    try:
        app = FirecrawlApp(api_key=api_key)
    except Exception as e:
        print(f"Failed to initialize FirecrawlApp: {e}")
        return

    print(f"\nExtracting from: {url}")
    print(f"Prompt: {prompt}")

    # 4. Define Schema (Optional - using a generic dynamic schema if needed, but 'extract' works without one too)
    # The documentation allows prompt-only extraction for flexible results.
    
    try:
        # Call the extract method
        # Note: Based on documentation: .extract(urls=['...'], prompt='...')
        result = app.extract(
            urls=[url],
            prompt=prompt,
            # schema=... # can be added if defined
        )
        
        # 5. Output Result
        print("\nExtraction Complete!")
        
        # Handle response object serialization
        if hasattr(result, 'data'):
            output_data = result.__dict__
        elif hasattr(result, 'dict'):
             output_data = result.dict()
        else:
             output_data = result if isinstance(result, dict) else str(result)
             
        print(json.dumps(output_data, indent=2, ensure_ascii=False, default=str))
        
        # Save to file
        output_file = "extract_output.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"Result saved to: {output_file}")

    except AttributeError:
        print("\nError: Your 'firecrawl-py' library might be outdated and missing the 'extract' method.")
        print("Try running: pip install --upgrade firecrawl-py")
    except Exception as e:
        print(f"\nExtraction Error: {e}")

if __name__ == "__main__":
    main()
