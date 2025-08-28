# Conference Video Summarizer

This project automates the extraction and summarization of conference slide presentations. It uses **Selenium** to navigate and capture slides, **OCR (Tesseract)** to extract text, and **Anthropic’s Claude API** to generate concise 2–3 paragraph summaries of the presentations. This is based on my internship work at RelationalAI. 

---

## Features

* Automatically loads conference presentations (tested on ICML virtual conference site).
* Extracts text from slides with **Tesseract OCR**.
* Detects slides containing useful graphics not captured in text.
* Sends text + images to Claude (Anthropic API) for high-level summaries.
* Works on entire slide decks end-to-end.

---

## Requirements

### Python Dependencies

Install all required dependencies with:

```bash
pip install -r requirements.txt
```

If you don’t want to use `requirements.txt`, you can install packages manually:

```bash
pip install selenium pillow pytesseract openai anthropic
```

### System Dependencies

* **Google Chrome**
* **ChromeDriver** (must match your Chrome version and be in your `PATH`)
* **Tesseract OCR**

  * macOS: `brew install tesseract`
  * Ubuntu/Debian: `sudo apt-get install tesseract-ocr`
  * Windows: [Download installer](https://github.com/tesseract-ocr/tesseract/wiki)

---

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/amoghakella/Conference-Video-Summarizer.git
   cd Conference-Video-Summarizer
   ```

2. Insert your **Anthropic API key** into `summarizer.py`:

   ```python
   client = anthropic.Anthropic(
       api_key="INSERT API KEY"
   )
   ```

3. (Optional) If a site requires authentication, update the `login_to_icml()` function with your conference credentials.

---

## Usage

Run the summarizer with:

```bash
python summarize.py "https://icml.cc/virtual/2025/workshop/39950"
```

---

## Example Output

When successful, the script prints summaries of each detected slideshow:

```
Summary of slideshow 1:
[Generated 2–3 paragraph summary here...]
```

---

## Visualizing Summaries with NotebookLM

Once the summaries are generated, you can optionally feed them into **[NotebookLM](https://notebooklm.google/)** to create interactive **mind-graph visualizations** of the workshop content. NotebookLM automatically structures the summarized information into a knowledge graph, making it easier to explore relationships between concepts, papers, and ideas presented in the slides.

For best results:
1. Run the script to generate summaries.
2. Copy the output into a .txt or .md file.
3. Upload the file to **NotebookLM**.
4. Use the mind-graph view to explore the extracted knowledge.

## Notes

* The script launches Chrome and interacts with slides automatically.
* Summaries are generated with **Claude**, so Anthropic API credits are required.
* OCR results may vary depending on slide formatting.

Here are the improvements in summarizer_robust.py relative to summarizer.py.
* Improve error handling and produce meaningful messages instead of crashing.
* Organize the code into modular functions.
* Add checks for missing dependencies, invalid credentials, invalid URLs, API errors, and Selenium issues.
* Make the flow clearer and shorter while preserving existing functionality.

Here are the improvements in summarizer_faster.py relative to summarizer_robust.py. 
* Adding parallel Claude API calls to speed up summarization. 
* Caching OCR results to skip reprocessing slides.
* Adding logging and a progress bar for better usability.
