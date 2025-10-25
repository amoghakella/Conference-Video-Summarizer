URL = "https://iclr.cc/virtual/2025/events/workshop"
ORAL_URL = "https://iclr.cc/virtual/2025/events/oral"
talk_urls = ["https://iclr.cc/virtual/2025/invited-talk/36785", "https://iclr.cc/virtual/2025/invited-talk/36784", "https://iclr.cc/virtual/2025/invited-talk/36782", "https://iclr.cc/virtual/2025/invited-talk/36783", "https://iclr.cc/virtual/2025/invited-talk/36781"]

# -----------------------------------------------------------------------------

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
from pathlib import Path
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
    api_key=""
)

# --- Configuration ---
import shutil

CHROMEDRIVER_PATH = shutil.which("chromedriver")

if CHROMEDRIVER_PATH is None:
    raise RuntimeError("chromedriver not found in PATH")
OUTPUT_DIR = "slides_ocr_output"

# --- Clear existing output directory ---
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Setup Chrome ---
options = Options()
options.add_argument("--window-size=1920,1080")
#options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")

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

def ask_claude_with_retry(image_b64, prompt, retries=5):
    for i in range(retries):
        try:
            response = client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=500,
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

def resize_image_for_claude(image, width=640, height=360, threshold=120, enhance_contrast=2.0):
    # Grayscale
    gray = image.convert("L")

    # Contrast enhancement
    if enhance_contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(enhance_contrast)

    # Binarization (black/white)
    bw = gray.point(lambda x: 0 if x < threshold else 255, "1")

    # Resize
    resized = bw.resize((width, height), Image.LANCZOS)

    # Encode as base64 PNG
    buffered = BytesIO()
    resized.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def resized_image_for_claude(image, width=320, height=180, threshold=120, enhance_contrast=2.0):
    resized = image.resize((width, height), Image.LANCZOS)

    # Encode as base64 PNG
    buffered = BytesIO()
    resized.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def get_total_slide_count():
    try:
        slide_count_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-slp-target="slideCount"]'))
        )
        count = int(slide_count_el.text.strip())
        print(f"Found total slide count from page: {count}")
        return count
    except Exception as e:
        print(f"Failed to parse slide count: {e}")
        return 25  # default fallback

def load_slide_deck(PAGE_URL):
    IFRAME_URL = extract_iframe_src_from_page(PAGE_URL)
    if not IFRAME_URL:
        raise RuntimeError("Could not extract iframe from page")
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
        '.slp__menu', '.slp__video', '.slp__videoWrapper', '.slp__player',
        '.slp__bigPlay', '.slp__zoom', 'video', 'iframe'
    ];
    selectorsToRemove.forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
    document.querySelectorAll('.slp__bigButton--next svg, .slp__bigButton--prev svg').forEach(el => el.style.display = "none");
    document.querySelectorAll('.slp__bigButton--next, .slp__bigButton--prev').forEach(btn => {
        btn.style.pointerEvents = "auto";
        btn.style.background = "transparent";
        btn.style.border = "none";
        btn.style.boxShadow = "none";
        btn.removeAttribute("data-tooltip-content");
    });
    document.querySelectorAll('[data-tooltip-content], [data-tooltip-show], .tw-bg-opacity-89, [class*="tooltip"]').forEach(el => el.style.display = "none");
    ['.slp__button--syncSlidesToVideo', '.slp__button--syncVideoToSlides', '.slp__slideStats']
        .forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
    document.documentElement.style.height = document.body.style.height = "100%";
    document.documentElement.style.margin = document.body.style.margin = "0";
    document.documentElement.style.padding = document.body.style.padding = "0";
    const sc = document.querySelector('.slp__slides');
    if (sc) {
        const w = parseFloat(sc.style.width || sc.offsetWidth);
        const h = parseFloat(sc.style.height || sc.offsetHeight);
        const ratio = (w && h) ? w / h : (16 / 9);
        const newHeight = window.innerHeight;
        const newWidth = ratio * newHeight;
        Object.assign(sc.style, {
            width: newWidth + "px",
            height: newHeight + "px",
            position: "fixed",
            top: "0",
            left: "50%",
            transform: "translateX(-50%)",
            overflow: "hidden"
        });
    }
    """)
    return MAX_SLIDES


def capture_slides(MAX_SLIDES):
    slide_data = []
    for slide_num in range(1, MAX_SLIDES + 1):
        print(f"\nCapturing slide {slide_num}...")
        png = driver.get_screenshot_as_png()
        image = Image.open(BytesIO(png))
        gray = ImageEnhance.Contrast(image.convert("L")).enhance(2)
        resized = resize_image_for_claude(image)
        text = ask_claude_with_retry(resized, "You have been given a slide from a slideshow (as shown in the image). To your best ability, answer this prompt with all of the text on the slide. Do not write anything else.")
        print(text)
        image_b64 = resized_image_for_claude(image)
        slide_data.append((text, image_b64))
        if slide_num == MAX_SLIDES:
            break
        try:
            ActionChains(driver).send_keys(Keys.ARROW_RIGHT).perform()
            time.sleep(1.2)
        except Exception as e:
            print(f"Could not send arrow key: {e}")
            break
    return slide_data


def save_images_to_folder(folder, images):
    os.makedirs(folder, exist_ok=True)
    for j, img64 in enumerate(images):
        img_data = base64.b64decode(img64)
        Image.open(BytesIO(img_data)).save(os.path.join(folder, f"image_{j}.png"))


def generate_summary_with_claude(text, images, include_author_title=False):
    prompt = (
        "You are about to be given a series of texts and images from a slideshow. "
        "Use what you can understand from the texts and images to create a clear, concise, technically deep 2-3 paragraph summary of the slideshow. "
        "If there is anything that you do not understand (such as random symbols, misplaced words, or jumbled letters), ignore it. "
        "Avoid repetition. Images will likely be given along with this prompt. "
        "Do not begin your response with anything like 'Here's a concise 2-3 paragraph summary of the key points from the slideshow:'. "
        "Instead, just start the summary immediately. IMPORTANT: Please remember to give a 2-3 PARAGRAPH summary. "
        "Do not summarize the slides in a set of bullet points or in a list."
    )
    if include_author_title:
        prompt += " Also, include the author of the slideshow's name in your summary, and the title of the slideshow."
    prompt += f" Here is your text: \n\n{text}"

    content = [
        *(
            [{
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img}
            } for img in images[:20]]
        ),
        {"type": "text", "text": prompt}
    ]

    response = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=500,
        temperature=0.1,
        messages=[{"role": "user", "content": content}]
    )
    return response.content[0].text.strip()


def extract_slide_data(slide_data, group_mode=False):
    if group_mode:
        # Used by `summarize`
        all_text, all_img, img_folder, slideshownumber, all_responses = [], [], [], 0, ""
        for i, (text, image_b64) in enumerate(slide_data):
            answer = ask_claude_with_retry(image_b64,
                "Does the text on this slide say 'ICLR International Conference on Learning Representations' or anything similar? "
                "Also, is the background of the slide a blue and black gradient with a bit of green? If the answer to both of these questions is yes, then say 'yes'. "
                "Otherwise, say 'no'. Do not answer with anything other than 'yes' or 'no'. Do not explain your answer. The texts 'yes' and 'no' are case sensitive."
            )
            print(f"Claude response for slide {i+1}:", answer)
            all_responses += f"\n--- Slide {i+1} ---\n{answer}\n"
            if answer == "yes":
                all_text.append("")
                all_img.append([])
            if len(all_text) == 0:
                all_text.append("")
                all_img.append([])
            all_text[-1] += text

            answer2 = ask_claude_with_retry(image_b64,
                f"Does this slide (as shown in the picture) contain very useful information in a graphic that is NOT contained within the text on the slide? "
                f"This means two things: 1. the graphic contains really useful information and 2. the information is not found in the text from the slide. "
                f"If the answer to both of these questions is yes, then say 'yes'. Otherwise, say 'no'. "
                f"Do not answer with anything other than 'yes' or 'no'. Here is the text from the slide:\n\n{text}"
            )
            print(f"Claude response for slide {i+1}:", answer2)
            if answer2 == "yes":
                all_img[-1].append(image_b64)
            img_folder.append(image_b64)
        return all_text, all_img, img_folder
    else:
        # Used by oral/invited versions
        all_text, all_img, img_folder = "", [], []
        for i, (text, image_b64) in enumerate(slide_data):
            all_text += text
            answer2 = ask_claude_with_retry(image_b64,
                f"Does this slide (as shown in the picture) contain very useful information in a graphic that is NOT contained within the text on the slide? "
                f"This means two things: 1. the graphic contains really useful information and 2. the information is not found in the text from the slide. "
                f"If the answer to both of these questions is yes, then say 'yes'. Otherwise, say 'no'. "
                f"Do not answer with anything other than 'yes' or 'no'. Here is the text from the slide:\n\n{text}"
            )
            print(f"Claude response for slide {i+1}:", answer2)
            if answer2 == "yes":
                all_img.append(image_b64)
            img_folder.append(image_b64)
        return all_text, all_img, img_folder


def summarize(PAGE_URL, index):
    try:
        MAX_SLIDES = load_slide_deck(PAGE_URL)
        slide_data = capture_slides(MAX_SLIDES)
        all_text, all_img, img_folder = extract_slide_data(slide_data, group_mode=True)
        summaries = ""
        for i, st in enumerate(all_text):
            if len(st) > 200:
                print(f"\nSummary of slideshow {i + 1}:")
                summary = generate_summary_with_claude(st, all_img[i])
                print(summary)
                summaries += f"\nSummary of slideshow {i + 1}:\n{summary}"
        return summaries
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Finished.")


def summarize_one_slideshow_oral(PAGE_URL, index):
    try:
        MAX_SLIDES = load_slide_deck(PAGE_URL)
        slide_data = capture_slides(MAX_SLIDES)
        all_text, all_img, img_folder = extract_slide_data(slide_data)
        oral_dir = os.path.join(OUTPUT_DIR, f"oraltalk{index}")
        save_images_to_folder(oral_dir, img_folder)
        print("\nSummary of oral talk:")
        summary = generate_summary_with_claude(all_text, all_img)
        print(summary)
        return summary
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Finished.")


def summarize_one_slideshow(PAGE_URL, index):
    try:
        MAX_SLIDES = load_slide_deck(PAGE_URL)
        slide_data = capture_slides(MAX_SLIDES)
        all_text, all_img, img_folder = extract_slide_data(slide_data)
        inv_dir = os.path.join(OUTPUT_DIR, f"invtalk{index}")
        save_images_to_folder(inv_dir, img_folder)
        print("\nSummary of invited talk:")
        summary = generate_summary_with_claude(all_text, all_img, include_author_title=True)
        print(summary)
        return summary
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Finished.")

def summarizeList(PAGE_URL):
    driver.get(PAGE_URL)
    time.sleep(2)  # Wait for the page to load

    # Find all <a> tags that link to workshop pages
    elements = driver.find_elements(By.CSS_SELECTOR, "a.small-title")

    # Extract just the full workshop URLs
    base_url = "https://iclr.cc"
    workshop_links = []
    oral_links = []

    for elem in elements:
        href = elem.get_attribute("href")
        if href and "/virtual/2025/workshop/" in href:
            full_url = href if href.startswith("http") else base_url + href
            if full_url not in workshop_links:
                workshop_links.append(full_url)

    driver.get(ORAL_URL)
    time.sleep(2)
    elements = driver.find_elements(By.CSS_SELECTOR, "a.small-title")
    for elem in elements:
        href = elem.get_attribute("href")
        if href and "/virtual/2025/oral/" in href:
            full_url = href if href.startswith("http") else base_url + href
            if full_url not in oral_links:
                oral_links.append(full_url)

    # Print the array
    print(workshop_links)
    print(oral_links)
    
    list_of_summaries = ""
    with open("workshop_summaries.txt", "w") as f:
        for i, talk in enumerate(oral_links):
            try:
                summary = summarize_one_slideshow_oral(talk, i)
            except RuntimeError as e:
                print(f"Skipping {talk}: {e}")
                continue
            if summary:
                entry = f"\nOral Talk {i + 1} summary:\n{summary}\n"
                list_of_summaries += entry
                f.write(entry)
            print("Oral Talk " + str(i + 1) + " done.")
        for i, talk in enumerate(talk_urls):
            try:
                summary = summarize_one_slideshow(talk, i)
            except RuntimeError as e:
                print(f"Skipping {talk}: {e}")
                continue
            if summary:
                entry = f"\nInvited Talk {i + 1} summary:\n{summary}\n"
                list_of_summaries += entry
                f.write(entry)
            print("Invited Talk " + str(i + 1) + " done.")
        for i, workshop_link in enumerate(workshop_links):
            try:
                summary = summarize(workshop_link, i)
            except RuntimeError as e:
                print(f"Skipping {workshop_link}: {e}")
                continue
            if summary:
                entry = f"\nWorkshop {i + 1} summaries:\n{summary}\n"
                list_of_summaries += entry
                f.write(entry)
            print("Workshop " + str(i + 1) + " done.")

    driver.quit()
    return list_of_summaries

workshop_summaries_final = summarizeList(URL)
