import sys
import time
import base64
import random
import re
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
import pytesseract
import anthropic
import shutil

# ---------------------------
# CONFIGURATION
# ---------------------------

CLAUDE_API_KEY = "INSERT_API_KEY"
CHROMEDRIVER_PATH = shutil.which("chromedriver")

if CHROMEDRIVER_PATH is None:
    sys.exit("Error: chromedriver not found in PATH. Please install it or add it to PATH.")

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

options = Options()
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
wait = WebDriverWait(driver, 15)

# ---------------------------
# UTILITY FUNCTIONS
# ---------------------------

def safe_get_url(url):
    """Load a page safely with error handling."""
    try:
        print(f"Loading page: {url}")
        driver.get(url)
        return True
    except Exception as e:
        print(f"[Error] Could not load page: {e}")
        return False


def extract_iframe_src(page_url):
    """Extract the iframe URL from the page."""
    if not safe_get_url(page_url):
        return None
    try:
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        iframe_src = iframe.get_attribute("src")
        print(f"Found iframe src: {iframe_src}")
        return iframe_src
    except Exception as e:
        print(f"[Warning] Failed to extract iframe: {e}")
        return None


def ask_claude(image_b64, prompt, retries=5):
    """Query Claude API with retry logic."""
    for i in range(retries):
        try:
            response = client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=100,
                temperature=0.0,
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
            print(f"Rate limited. Retrying in {wait_time:.2f}s...")
            time.sleep(wait_time)
        except Exception as e:
            print(f"[Error] Claude API failed: {e}")
            return None
    return None


def get_total_slides():
    """Extract total slide count from HTML or default to 25."""
    try:
        html = driver.page_source
        match = re.search(r'data-slp-target="slideCount"[^>]*>(\d+)</', html)
        return int(match.group(1)) if match else 25
    except Exception:
        return 25


def capture_slide_text():
    """Take a screenshot, enhance, and extract text."""
    png = driver.get_screenshot_as_png()
    image = Image.open(BytesIO(png))
    gray = image.convert("L")
    contrast = ImageEnhance.Contrast(gray).enhance(2)
    bw = contrast.point(lambda x: 0 if x < 140 else 255, "1")
    return pytesseract.image_to_string(bw, config="--psm 6"), image


def summarize_slides(url):
    """Main pipeline to summarize slides."""
    iframe_url = extract_iframe_src(url)
    if not iframe_url:
        print("[Error] Could not extract iframe. Exiting.")
        return

    if not safe_get_url(iframe_url):
        print("[Error] Could not load iframe. Exiting.")
        return

    max_slides = get_total_slides()
    slide_data = []

    for slide_num in range(1, max_slides + 1):
        print(f"Capturing slide {slide_num}/{max_slides}...")
        text, image = capture_slide_text()

        resized = image.resize((320, 180))
        buffered = BytesIO()
        resized.save(buffered, format="PNG")
        image_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        slide_data.append((text, image_b64))

        try:
            ActionChains(driver).send_keys(Keys.ARROW_RIGHT).perform()
            time.sleep(1.2)
        except Exception as e:
            print(f"[Warning] Failed to advance slide: {e}")
            break

    summaries = []
    for i, (text, image_b64) in enumerate(slide_data):
        prompt = (
            "You are given a slideshow image and its extracted text. "
            "Generate a concise, technically deep 2-3 paragraph summary."
        )
        response = ask_claude(image_b64, prompt)
        if response:
            summaries.append(f"\n[Slide {i + 1} Summary]\n{response}")

    return "\n".join(summaries) if summaries else "[No summaries generated]"

# ---------------------------
# ENTRY POINT
# ---------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python summarize_slides.py <URL>")
        sys.exit(1)

    url = sys.argv[1]
    summary = summarize_slides(url)
    print("\n=== FINAL SUMMARY ===")
    print(summary)
    driver.quit()
