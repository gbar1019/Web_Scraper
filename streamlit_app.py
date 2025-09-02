
import os
import re
import io
import time
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd
import streamlit as st

# Optional imports for Selenium pieces (handled gracefully if not installed/available)
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except Exception:
    SELENIUM_AVAILABLE = False

# -------------------- Logging to Streamlit --------------------
class StreamlitLogHandler(logging.Handler):
    """A log handler that buffers logs so we can dump them into Streamlit."""
    def __init__(self):
        super().__init__()
        self.buffer = io.StringIO()

    def emit(self, record):
        msg = self.format(record)
        self.buffer.write(msg + "\\n")

    def get_value(self):
        return self.buffer.getvalue()

log_handler = StreamlitLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger("UltimateWebScraper")
logger.setLevel(logging.INFO)
logger.handlers = []  # avoid duplicate logs on rerun
logger.addHandler(log_handler)

# -------------------- Core Scraper --------------------
class UltimateWebScraper:
    """Main web scraper class that mimics PandaExtract functionality"""

    def __init__(self, use_selenium: bool = False, headless: bool = True, user_agent: Optional[str] = None):
        """
        Initialize the scraper
        Args:
            use_selenium: Use Selenium for JavaScript-rendered content
            headless: Run browser in headless mode (no GUI)
            user_agent: Optional custom user-agent
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent or (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
            )
        })
        self.use_selenium = bool(use_selenium and SELENIUM_AVAILABLE)
        self.driver = None

        if self.use_selenium and SELENIUM_AVAILABLE:
            self._setup_selenium(headless)
        elif use_selenium and not SELENIUM_AVAILABLE:
            logger.warning("Selenium requested but not available. Falling back to requests/BeautifulSoup.")

    def _setup_selenium(self, headless: bool = True):
        """Setup Selenium WebDriver"""
        try:
            chrome_options = Options()
            if headless:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--window-size=1920,1080")
            self.driver = webdriver.Chrome(options=chrome_options)
            logger.info("Selenium WebDriver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Selenium: {e}")
            self.use_selenium = False

    def close(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            logger.info("Selenium WebDriver closed")

    def get_page_content(self, url: str, wait_time: int = 10) -> Optional[str]:
        """
        Get HTML content from a URL
        Args:
            url: The URL to fetch
            wait_time: Maximum wait time for page load (for Selenium)
        Returns:
            HTML content as string or None if failed
        """
        try:
            if self.use_selenium and self.driver:
                self.driver.get(url)
                WebDriverWait(self.driver, wait_time).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(1)  # small grace period for dynamic content
                return self.driver.page_source
            else:
                response = self.session.get(url, timeout=wait_time)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def extract_structured_data(self, url: str, css_selectors: Dict[str, str] = None) -> List[Dict]:
        """
        Extract structured data from lists and tables (Smart Selection Tool)
        Args:
            url: The URL to scrape
            css_selectors: Dictionary of field names and their CSS selectors
        Returns:
            List of dictionaries containing extracted data
        """
        html = self.get_page_content(url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        data = []

        # Auto-detect tables if no selectors provided
        if not css_selectors:
            tables = soup.find_all('table')
            for table in tables:
                headers = [th.get_text(strip=True) for th in table.find_all('th')]
                for row in table.find_all('tr')[1:]:  # Skip header
                    cells = row.find_all('td')
                    if cells:
                        row_data = {headers[i] if i < len(headers) else f"col_{i+1}": cells[i].get_text(strip=True)
                                    for i in range(len(cells))}
                        data.append(row_data)

            # Auto-detect lists
            lists = soup.find_all(['ul', 'ol'])
            for lst in lists:
                for item in lst.find_all('li'):
                    item_data = {
                        'text': item.get_text(strip=True),
                        'links': [a.get('href') for a in item.find_all('a')]
                    }
                    data.append(item_data)
        else:
            # Use provided CSS selectors
            containers = soup.select(css_selectors.get('container', 'body'))
            for container in containers:
                item = {}
                for field, selector in css_selectors.items():
                    if field == 'container':
                        continue
                    el = container.select_one(selector)
                    if el:
                        # for anchor tags, prefer href when present
                        if el.name == 'a' and el.get('href'):
                            item[field] = urljoin(url, el.get('href'))
                        else:
                            item[field] = el.get_text(strip=True)
                if item:
                    data.append(item)

        logger.info(f"Extracted {len(data)} items from {url}")
        return data

    def bulk_extract(self, urls: List[str], css_selectors: Dict[str, str] = None, delay_sec: float = 1.0) -> List[Dict]:
        """Extract data from multiple similar pages."""
        all_data = []
        for i, u in enumerate(urls, 1):
            logger.info(f"Processing {i}/{len(urls)}: {u}")
            items = self.extract_structured_data(u, css_selectors)
            for it in items:
                it['source_url'] = u
            all_data.extend(items)
            time.sleep(max(0.0, delay_sec))
        return all_data

    def extract_emails(self, urls: List[str], deep_scan: bool = False) -> List[Dict]:
        """Extract email addresses from websites. Optionally deep-scan same-domain links."""
        email_pattern = re.compile(r'\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b')
        all_emails = []
        processed_urls: Set[str] = set()

        def extract_from_url(u: str) -> Set[str]:
            if u in processed_urls:
                return set()
            processed_urls.add(u)

            html = self.get_page_content(u)
            if not html:
                return set()

            found = set(email_pattern.findall(html))

            soup = BeautifulSoup(html, 'html.parser')
            for link in soup.find_all('a', href=True):
                if link['href'].startswith('mailto:'):
                    email = link['href'].replace('mailto:', '').split('?')[0]
                    found.add(email)
            return found

        for u in urls:
            logger.info(f"Scanning {u} for emails...")
            emails_here = extract_from_url(u)

            if deep_scan:
                html = self.get_page_content(u)
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    base_domain = urlparse(u).netloc
                    for link in soup.find_all('a', href=True):
                        full = urljoin(u, link['href'])
                        if urlparse(full).netloc == base_domain:
                            emails_here.update(extract_from_url(full))

            for em in sorted(emails_here):
                all_emails.append({
                    'email': em,
                    'source_url': u,
                    'timestamp': datetime.now().isoformat()
                })

        logger.info(f"Found {len(all_emails)} total emails")
        return all_emails

    def download_images(self, url: str, output_dir: str = "downloaded_images") -> List[Dict]:
        """Download images from a page into a local folder and return metadata."""
        html = self.get_page_content(url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        os.makedirs(output_dir, exist_ok=True)

        images = []
        img_tags = soup.find_all('img')
        for i, img in enumerate(img_tags):
            img_url = img.get('src') or img.get('data-src')
            if not img_url:
                continue
            img_url = urljoin(url, img_url)
            try:
                img_response = self.session.get(img_url, timeout=10)
                img_response.raise_for_status()
                filename = os.path.basename(urlparse(img_url).path) or f"image_{i}.jpg"
                filepath = os.path.join(output_dir, filename)
                with open(filepath, 'wb') as f:
                    f.write(img_response.content)
                images.append({
                    'url': img_url,
                    'alt_text': img.get('alt', ''),
                    'saved_as': filepath,
                    'size_bytes': len(img_response.content)
                })
                logger.info(f"Downloaded: {filename}")
            except Exception as e:
                logger.error(f"Failed to download image {img_url}: {e}")
        return images

    def extract_text_content(self, urls: List[str]) -> List[Dict]:
        """Extract clean text content and metadata from pages."""
        out = []
        for u in urls:
            logger.info(f"Extracting text from {u}")
            html = self.get_page_content(u)
            if not html:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            for s in soup(["script", "style"]):
                s.decompose()

            metadata = {
                'url': u,
                'title': soup.title.string if soup.title else '',
                'description': '',
                'keywords': '',
                'author': ''
            }
            for meta in soup.find_all('meta'):
                name = (meta.get('name') or '').lower()
                if name == 'description':
                    metadata['description'] = meta.get('content', '')
                elif name == 'keywords':
                    metadata['keywords'] = meta.get('content', '')
                elif name == 'author':
                    metadata['author'] = meta.get('content', '')

            # main text
            text = soup.get_text(separator=' ')
            text = re.sub(r'\\s+', ' ', text).strip()

            headings = {
                'h1': [h.get_text(strip=True) for h in soup.find_all('h1')],
                'h2': [h.get_text(strip=True) for h in soup.find_all('h2')],
                'h3': [h.get_text(strip=True) for h in soup.find_all('h3')]
            }

            out.append({
                **metadata,
                'text_content': text[:5000],
                'word_count': len(text.split()),
                'headings': json.dumps(headings, ensure_ascii=False),
                'timestamp': datetime.now().isoformat()
            })
        return out


# -------------------- Streamlit UI --------------------

st.set_page_config(page_title="Ultimate Web Scraper (Streamlit)", page_icon="🕷️", layout="wide")
st.title("🕷️ Ultimate Web Scraper")
st.caption("A friendly Streamlit UI that wraps requests/BeautifulSoup with optional Selenium support.")

with st.sidebar:
    st.header("Settings")
    use_selenium = st.toggle("Use Selenium (for JS-heavy sites)", value=False, help="Requires a working Chrome/Chromedriver environment.")
    headless = st.toggle("Headless Browser", value=True, help="Only applies if Selenium is enabled.")
    ua = st.text_input("User-Agent (optional)", value="")
    request_delay = st.number_input("Delay between requests (seconds)", min_value=0.0, value=1.0, step=0.5)
    st.divider()
    st.subheader("Quick Tips")
    st.markdown(
        "- Provide one or more URLs (one per line).\n"
        "- For structured scraping, you can paste a JSON of CSS selectors like:\n"
        "```json\n"
        "{\n"
        "  \"container\": \"article.product_pod\",\n"
        "  \"title\": \"h3 a\",\n"
        "  \"price\": \"p.price_color\",\n"
        "  \"availability\": \"p.availability\"\n"
        "}\n"
        "```\n"
        "- Leave selectors empty to auto-detect tables/lists.",
        help="Selectors example"
    )

# Instantiate scraper
scraper = UltimateWebScraper(use_selenium=use_selenium, headless=headless, user_agent=(ua or None))

tabs = st.tabs([
    "Structured Extract",
    "Bulk Extract",
    "Email Finder",
    "Image Downloader",
    "Text Extractor",
    "Export & Logs"
])

# --------------- Structured Extract ---------------
with tabs[0]:
    st.subheader("Structured Data from a Single Page")
    url = st.text_input("Target URL", placeholder="https://books.toscrape.com/")
    selectors_json = st.text_area("CSS Selectors (JSON)", value="", height=160,
                                  help="Optional. Include 'container' plus fields and selectors.")
    go = st.button("Extract", type="primary", use_container_width=True)
    if go:
        css_selectors = None
        if selectors_json.strip():
            try:
                css_selectors = json.loads(selectors_json)
            except Exception as e:
                st.error(f"Invalid JSON for selectors: {e}")
        if not url.strip():
            st.warning("Please provide a URL.")
        else:
            with st.spinner("Scraping..."):
                data = scraper.extract_structured_data(url.strip(), css_selectors)
            if data:
                df = pd.DataFrame(data)
                st.success(f"Extracted {len(df)} rows")
                st.dataframe(df, use_container_width=True, height=380)
                st.session_state['last_df'] = df
            else:
                st.info("No data extracted. Try providing selectors or a different page.")

# --------------- Bulk Extract ---------------
with tabs[1]:
    st.subheader("Bulk Extract from Multiple Pages")
    urls_text = st.text_area("List of URLs (one per line)",
                             value="https://books.toscrape.com/catalogue/page-1.html\nhttps://books.toscrape.com/catalogue/page-2.html")
    selectors_json2 = st.text_area("CSS Selectors (JSON)", value="", height=160)
    go2 = st.button("Run Bulk Extract", type="primary", use_container_width=True)

    if go2:
        url_list = [u.strip() for u in urls_text.splitlines() if u.strip()]
        css_selectors2 = None
        if selectors_json2.strip():
            try:
                css_selectors2 = json.loads(selectors_json2)
            except Exception as e:
                st.error(f"Invalid JSON for selectors: {e}")
        if not url_list:
            st.warning("Please provide at least one URL.")
        else:
            results = []
            prog = st.progress(0.0)
            for i, u in enumerate(url_list, 1):
                with st.spinner(f"Scraping {u} ({i}/{len(url_list)})..."):
                    items = scraper.extract_structured_data(u, css_selectors2)
                    for it in items:
                        it['source_url'] = u
                    results.extend(items)
                prog.progress(i / len(url_list))
                time.sleep(request_delay)
            if results:
                df2 = pd.DataFrame(results)
                st.success(f"Extracted {len(df2)} total rows from {len(url_list)} pages")
                st.dataframe(df2, use_container_width=True, height=380)
                st.session_state['last_df'] = df2
            else:
                st.info("No data extracted. Try providing selectors or different pages.")

# --------------- Email Finder ---------------
with tabs[2]:
    st.subheader("Email Finder")
    urls_text3 = st.text_area("List of URLs to scan (one per line)", placeholder="https://example.com")
    deep_scan = st.toggle("Deep Scan same-domain links", value=False)
    go3 = st.button("Find Emails", type="primary", use_container_width=True)
    if go3:
        url_list3 = [u.strip() for u in urls_text3.splitlines() if u.strip()]
        if not url_list3:
            st.warning("Please provide at least one URL.")
        else:
            with st.spinner("Scanning for emails..."):
                emails = scraper.extract_emails(url_list3, deep_scan=deep_scan)
            if emails:
                df3 = pd.DataFrame(emails).drop_duplicates(subset=['email', 'source_url'])
                st.success(f"Found {len(df3)} unique emails")
                st.dataframe(df3, use_container_width=True, height=380)
                st.session_state['last_df'] = df3
            else:
                st.info("No emails found.")

# --------------- Image Downloader ---------------
with tabs[3]:
    st.subheader("Image Downloader")
    img_url = st.text_input("Page URL to scan for images", placeholder="https://books.toscrape.com/")
    out_dir = st.text_input("Output folder (created if missing)", value="downloaded_images")
    go4 = st.button("Download Images", type="primary", use_container_width=True)
    if go4:
        if not img_url.strip():
            st.warning("Please provide a URL.")
        else:
            with st.spinner("Downloading images..."):
                imgs = scraper.download_images(img_url.strip(), output_dir=out_dir.strip())
            if imgs:
                df4 = pd.DataFrame(imgs)
                st.success(f"Downloaded {len(df4)} images")
                st.dataframe(df4, use_container_width=True, height=380)
                st.session_state['last_df'] = df4
            else:
                st.info("No images downloaded.")

# --------------- Text Extractor ---------------
with tabs[4]:
    st.subheader("Text Extractor")
    urls_text5 = st.text_area("List of URLs (one per line)", placeholder="https://example.com")
    go5 = st.button("Extract Text", type="primary", use_container_width=True)
    if go5:
        url_list5 = [u.strip() for u in urls_text5.splitlines() if u.strip()]
        if not url_list5:
            st.warning("Please provide at least one URL.")
        else:
            with st.spinner("Extracting text..."):
                text_data = scraper.extract_text_content(url_list5)
            if text_data:
                df5 = pd.DataFrame(text_data)
                st.success(f"Extracted text from {len(df5)} pages")
                st.dataframe(df5, use_container_width=True, height=380)
                st.session_state['last_df'] = df5
            else:
                st.info("No text extracted.")

# --------------- Export & Logs ---------------
with tabs[5]:
    st.subheader("Export Last Results")
    df = st.session_state.get('last_df')
    if df is not None and isinstance(df, pd.DataFrame):
        c1, c2, c3 = st.columns(3)
        with c1:
            csv_bytes = df.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Download CSV", csv_bytes, file_name="exported_data.csv", mime="text/csv", use_container_width=True)
        with c2:
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="data")
            st.download_button("⬇️ Download Excel", excel_buf.getvalue(), file_name="exported_data.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with c3:
            json_bytes = df.to_json(orient="records", indent=2).encode('utf-8')
            st.download_button("⬇️ Download JSON", json_bytes, file_name="exported_data.json", mime="application/json", use_container_width=True)
    else:
        st.info("No results yet. Run one of the tools first.")

    st.divider()
    st.subheader("Logs")
    st.code(log_handler.get_value() or "No logs yet.", language="text")

# Cleanup when app stops (noop in Streamlit cloud, safe locally)
# (We don't call scraper.close() directly here because reruns are frequent in Streamlit.)
