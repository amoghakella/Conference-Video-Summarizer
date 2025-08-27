import sys

if len(sys.argv) < 2:
    print("Usage: python script.py <URL>")
    sys.exit(1)

URL = sys.argv[1]

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from PIL import Image, ImageEnhance
from io import BytesIO
import base64
import pytesseract
import time
import os
import openai
import shutil
import anthropic
import random
import re

client = anthropic.Anthropic(
    api_key="INSERT API KEY"
)

# --- Configuration ---
import shutil

CHROMEDRIVER_PATH = shutil.which("chromedriver")

if CHROMEDRIVER_PATH is None:
    raise RuntimeError("chromedriver not found in PATH")

options = Options()
options.add_argument("--window-size=1920,1080")
#options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
wait = WebDriverWait(driver, 15)

def extract_iframe_src_from_page(page_url):
    print(f"Loading page: {page_url}")
    driver.get(page_url)
    time.sleep(5)
    wait = WebDriverWait(driver, 15)

    try:
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        iframe_src = iframe.get_attribute("src")
        print(f"Found iframe src: {iframe_src}")
        return iframe_src
    except Exception as e:
        print(f"Failed to extract iframe: {e}")
        return None

def login_to_icml(driver, username, password, login_url="https://icml.cc/accounts/login/", wait_time=5):
    driver.get(login_url)

    driver.find_element(By.ID, "id_username").send_keys(username)
    driver.find_element(By.ID, "id_password").send_keys(password)

    driver.find_element(By.ID, "id_password").send_keys(Keys.RETURN)
    time.sleep(wait_time)

def ask_claude_with_retry(image_b64, prompt, retries=5):
    for i in range(retries):
        try:
            response = client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=20,
                temperature=0.0,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64
                            }},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ]
            )
            return response.content[0].text.strip()
        except anthropic.RateLimitError as e:
            wait_time = 2 ** i + random.random()
            print(f"Rate limit or overload. Retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)
        except Exception as e:
            return f"[Error: {e}]"
    return "[Failed after retries]"

def get_total_slide_count():
    try:
        html = driver.page_source
        match = re.search(r'data-slp-target="slideCount"[^>]*>(\d+)</', html)
        if match:
            count = int(match.group(1))
            print(f"Found total slide count from HTML: {count}")
            return count
        else:
            print("Slide count element not found in page source.")
            return 25
    except Exception as e:
        print(f"Failed to parse slide count: {e}")
        return 25

    print("Could not focus the SlidesLive player.")
    return False

def summarize(PAGE_URL):
    IFRAME_URL = extract_iframe_src_from_page(PAGE_URL)

    if not IFRAME_URL:
        raise RuntimeError("Could not extract iframe from page")

    try:
        print("Loading slide deck...")
        driver.get(IFRAME_URL)
        time.sleep(1)
        MAX_SLIDES = get_total_slide_count()
        driver.execute_script("""
        const videoEl = document.querySelector('video');
        if (videoEl) videoEl.muted = true;
        const selectorsToRemove = [
            '[data-slp-target="liveSlidesVideoControls"]',
            '[data-slp-target="liveSlidesVideoControlsGradient"]',
            '.slp__menu',
            '.slp__video',
            '.slp__videoWrapper',
            '.slp__player',
            '.slp__bigPlay',
            '.slp__zoom',
            'video',
            'iframe'
        ];
        selectorsToRemove.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => el.remove());
        });
        document.querySelectorAll('.slp__bigButton--next svg, .slp__bigButton--prev svg').forEach(el => {
            el.style.display = "none";
        });
        document.querySelectorAll('.slp__bigButton--next, .slp__bigButton--prev').forEach(button => {
            button.style.pointerEvents = "auto";
            button.style.background = "transparent";
            button.style.border = "none";
            button.style.boxShadow = "none";
            button.setAttribute("data-tooltip-content", "");
            button.removeAttribute("data-tooltip-content");
        });
        document.querySelectorAll('[data-tooltip-content], [data-tooltip-show], .tw-bg-opacity-89, [class*="tooltip"]').forEach(el => {
            el.style.display = "none";
        });
        const bottomButtonSelectors = [
            '.slp__button--syncSlidesToVideo',
            '.slp__button--syncVideoToSlides',
            '.slp__slideStats'
        ];
        bottomButtonSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => el.remove());
        });
        document.documentElement.style.height = "100%";
        document.documentElement.style.margin = "0";
        document.documentElement.style.padding = "0";
        document.body.style.height = "100%";
        document.body.style.margin = "0";
        document.body.style.padding = "0";
        const sc = document.querySelector('.slp__slides');
        if (sc) {
            const w = parseFloat(sc.style.width || sc.offsetWidth);
            const h = parseFloat(sc.style.height || sc.offsetHeight);
            const ratio = (w && h) ? w / h : (16 / 9);
            const newHeight = window.innerHeight;
            const newWidth = ratio * newHeight;
            sc.style.width = newWidth + "px";
            sc.style.height = newHeight + "px";
            sc.style.position = "fixed";
            sc.style.top = "0";
            sc.style.left = "50%";
            sc.style.transform = "translateX(-50%)";
            sc.style.overflow = "hidden";
        }
        """)
        slide_data = []
        for slide_num in range(1, MAX_SLIDES + 1):
            print(f"\nCapturing slide {slide_num}...")
            png = driver.get_screenshot_as_png()
            image = Image.open(BytesIO(png))
            gray = image.convert("L")
            contrast = ImageEnhance.Contrast(gray).enhance(2)
            bw = contrast.point(lambda x: 0 if x < 140 else 255, '1')
            text = pytesseract.image_to_string(bw, config="--psm 6")
            resized = image.resize((320, 180))
            buffered = BytesIO()
            resized.save(buffered, format="PNG")
            image_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            slide_data.append((text, image_b64))
            if slide_num == MAX_SLIDES:
                break
            try:
                # Use arrow key for headless compatibility
                ActionChains(driver).send_keys(Keys.ARROW_RIGHT).perform()
                time.sleep(1.2)
            except Exception as e:
                print(f"Could not send arrow key: {e}")
                break

        all_text = []
        all_responses = ""
        all_img = []
        for i, (text, image_b64) in enumerate(slide_data):
            answer = ask_claude_with_retry(image_b64, "Does the text on this slide say 'ICML International Conference of Learning Representations' or anything similar? Also, is the background of the slide a blue and black gradient with a bit of green? If the answer to both of these questions is yes, then say 'yes'. Otherwise, say 'no'. Do not answer with anything other than 'yes' or 'no'. Do not explain your answer. The texts 'yes' and 'no' are case sensitive (they must be lowercase) and do not contain periods at the end. ")
            all_responses += f"\n--- Slide {i+1} ---\n{answer}\n"
            if answer == "yes":
                all_text.append("")
                all_img.append([])
            if len(all_text) == 0:
                all_text.append("")
                all_img.append([])
            all_text[len(all_text) - 1] += text
            answer2 = ask_claude_with_retry(image_b64, f"Does this slide (as shown in the picture) contain very useful information in a graphic that is NOT contained within the text on the slide? This means two things: 1. the graphic contains really useful information and 2. the information is not found in the text from the slide. If the answer to both of these questions is yes, then say 'yes'. Otherwise, say 'no'. Do not answer with anything other than 'yes' or 'no'. Do not explain your answer. The texts 'yes' and 'no' are case sensitive (they must be lowercase) and do not contain periods at the end. Here is the text from the slide, as interpreted by an OCR: \n\n{text}")
            if answer2 == "yes":
                all_img[len(all_img) - 1].append(image_b64)

        summaries = ""
        for i, st in enumerate(all_text):
            if len(st) > 200:
                content = []
                prompt = f"You are about to be given a series of texts and images from a slideshow. Use what you can understand from the texts and images to create a clear, concise, technically deep 2-3 paragraph summary of the slideshow. If there is anything that you do not understand (such as random symbols, misplaced words, or jumbled letters), ignore it. Avoid repetition. Images will likely be given along with this prompt. Do not begin your response with anything like 'Here's a concise 2-3 paragraph summary of the key points from the slideshow:'. Instead, just start the summary immediately. IMPORTANT: Please remember to give a 2-3 PARAGRPH summary. Do not summarize the slides in a set of bullet points or in a list. Here is your text: \n\n{st}"
                for j, img in enumerate(all_img[i]):
                    if j < 20:
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img
                            }
                        })
                content.append({
                    "type": "text",
                    "text": prompt
                })
                response = client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=500,
                    temperature=0.1,
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ]
                )
                print("\nSummary of slideshow " + str(i + 1) + ":")
                summaries = summaries + "\nSummary of slideshow " + str(i + 1) + ":\n" + response.content[0].text.strip()
                print(response.content[0].text.strip())
        return summaries

    except Exception as e:
        print(f"Error: {e}")

    finally:
        print("Finished.")

summarize(URL)
