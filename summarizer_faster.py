import sys
import os
import time
import base64
import random
import re
import json
import shutil
from io import BytesIO
from PIL import Image, ImageEnhance
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import pytesseract
import anthropic

# ---------------------------
# CONFIGURATION
# ---------------------------

CLAUDE_API_KEY = "INSERT_API_KEY"
MAX_PARALLEL_REQUESTS = 5
CACHE_DIR = ".cache"

# Setup Anthropic client
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# Ensure chromedriver is installed
CHROMEDRIVER_PATH = shutil.which("chromedriver")
if CHROMEDRIVER_PATH is None:
    sys.exit("Error: chromedriver not found in PATH. Please install it.")

# Setup Selenium options
options = Options()
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
wait = WebDriverWait(driver, 15)

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------
# UTILITY FUNCTIONS
# ---------------------------

def cache_path(url):
    """Generate a unique cache file path based on URL."""
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", url)
    return os.path.join(CACHE_DIR, f"{sanitized}.json")


def load_cache(url):
    """Load cached OCR + summary data if available."""
    path = cache_path(url)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"slides": {}, "summaries": {}}


def save_cache(url, data):
    """Save OCR + summary data to cache."""
    path = cache_path(url)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def safe_get_url(url):
    """Safely load a URL."""
    try:
        driver.get(url)
        return True
    except Exception as e:
        print(f"[Error] Failed to load URL {url}: {e}")
        return False


def extract_iframe_src(url):
    """Extract iframe URL from ICML page."""
    if not safe_get_url(url):
        return None
    try:
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        return iframe.get_attribute("src")
    except Exception as e:
        print(f"[Warning] No iframe found: {e}")
        return None


def ask_claude(image_b64, prompt, retries=5):
    """Send image + prompt to Claude API with retries."""
    for i in range(retries):
        try:
            response = client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=500,
                temperature=0.1,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64
                        }},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            return response.content[0].text.strip()
        except anthropic.RateLimitError:
            wait_time = 2 ** i + random.random()
            print(f"[Retry] Rate limited, retrying in {wait_time:.2f}s...")
            time.sleep(wait_time)
        except Exception as e:
            print(f"[Error] Claude API call failed: {e}")
            return None
    return None


def get_total_slides():
    """Get slide count from page HTML, fallback to 25."""
    try:
        html = driver.page_source
        match = re.search(r'data-slp-target="slideCount"[^>]*>(\d+)</', html)
        return int(match.group(1)) if match else 25
    except Exception:
        return 25


def capture_slide_text():
    """Capture screenshot, enhance it, and OCR text."""
    png = driver.get_screenshot_as_png()
    image = Image.open(BytesIO(png))
    gray = image.convert("L")
    contrast = ImageEnhance.Contrast(gray).enhance(2)
    bw = contrast.point(lambda x: 0 if x < 140 else 255, "1")
    return pytesseract.image_to_string(bw, config="--psm 6"), image


def summarize_slide(i, text, image_b64):
    """Generate a concise 2-3 paragraph summary for one slide."""
    prompt = (
        "You are given a slideshow image and OCR text. "
        "Produce a clear, concise, technically deep 2-3 paragraph summary."
    )
    return ask_claude(image_b64, prompt)


# ---------------------------
# MAIN LOGIC
# ---------------------------

def summarize_slides(url):
    cache = load_cache(url)
    iframe_url = extract_iframe_src(url)
    if not iframe_url:
        print("[Error] Could not extract iframe.")
        return "[No summary]"

    if not safe_get_url(iframe_url):
        print("[Error] Could not load iframe.")
        return "[No summary]"

    max_slides = get_total_slides()
    slide_data = []

    # Step 1. OCR Phase
    print(f"\n[INFO] Extracting text from {max_slides} slides...")
    for slide_num in tqdm(range(1, max_slides + 1), desc="OCR Progress", unit="slide"):
        if str(slide_num) in cache["slides"]:
            text, image_b64 = cache["slides"][str(slide_num)]
            slide_data.append((slide_num, text, image_b64))
        else:
            text, image = capture_slide_text()
            resized = image.resize((320, 180))
            buffered = BytesIO()
            resized.save(buffered, format="PNG")
            image_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            cache["slides"][str(slide_num)] = (text, image_b64)
            slide_data.append((slide_num, text, image_b64))
            save_cache(url, cache)
        try:
            ActionChains(driver).send_keys(Keys.ARROW_RIGHT).perform()
            time.sleep(1.1)
        except Exception:
            break

    # Step 2. Summarization Phase
    print("\n[INFO] Summarizing slides using Claude...")
    summaries = {}
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as executor:
        futures = {
            executor.submit(summarize_slide, i, text, image_b64): i
            for i, text, image_b64 in slide_data
            if str(i) not in cache["summaries"]
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc="Claude Summaries"):
            i = futures[future]
            result = future.result()
            if result:
                cache["summaries"][str(i)] = result
                save_cache(url, cache)

    # Step 3. Combine summaries
    summaries = [cache["summaries"][str(i)] for i in sorted(cache["summaries"].keys(), key=int)]
    return "\n\n".join(summaries)


# ---------------------------
# ENTRY POINT
# ---------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python summarize_slides.py <URL>")
        sys.exit(1)

    url = sys.argv[1]
    result = summarize_slides(url)
    print("\n=== FINAL SUMMARY ===\n")
    print(result)
    driver.quit()
