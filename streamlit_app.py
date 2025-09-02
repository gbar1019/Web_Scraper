#!/usr/bin/env python3
"""
Advanced Contact Information Web Scraper - Streamlit App
Multi-page scraping with depth control for comprehensive data extraction
"""

import streamlit as st
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, urldefrag
import time
import json
from typing import Dict, List, Set, Tuple
import pandas as pd
from datetime import datetime
import io
from collections import deque
import concurrent.futures
from threading import Lock

# Page configuration
st.set_page_config(
    page_title="Advanced Contact Scraper",
    page_icon="🕷️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .stAlert {
        margin-top: 1rem;
    }
    .contact-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .metric-card {
        background-color: #ffffff;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .scraped-page {
        padding: 0.5rem;
        background: #f8f9fa;
        border-left: 3px solid #0066cc;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


class MultiPageScraper:
    def __init__(self, delay: float = 1.0, max_pages: int = 10, max_depth: int = 2):
        """
        Initialize the multi-page scraper.
        
        Args:
            delay: Time between requests in seconds
            max_pages: Maximum number of pages to scrape
            max_depth: Maximum depth for crawling (0 = main page only)
        """
        self.delay = delay
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Track visited URLs to avoid duplicates
        self.visited_urls = set()
        self.scraped_data = []
        self.pages_scraped = 0
        self.lock = Lock()
        
        # Regex patterns for contact information
        self.patterns = {
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'phone': re.compile(r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),
            'zip_code': re.compile(r'\b\d{5}(?:-\d{4})?\b'),
            'social_media': {
                'twitter': re.compile(r'(?:https?://)?(?:www\.)?twitter\.com/[A-Za-z0-9_]+'),
                'linkedin': re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/(?:in|company)/[A-Za-z0-9-]+'),
                'facebook': re.compile(r'(?:https?://)?(?:www\.)?facebook\.com/[A-Za-z0-9.]+'),
                'instagram': re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/[A-Za-z0-9_.]+'),
                'youtube': re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/(?:c/|channel/|user/)?[A-Za-z0-9_-]+'),
            }
        }
        
        # US States
        self.us_states = [
            'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut',
            'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa',
            'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan',
            'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire',
            'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio',
            'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
            'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
            'Wisconsin', 'Wyoming', 'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
            'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS',
            'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA',
            'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
        ]
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL to avoid duplicate visits."""
        # Remove fragment
        url, _ = urldefrag(url)
        # Remove trailing slash
        if url.endswith('/'):
            url = url[:-1]
        # Convert to lowercase for consistency
        return url.lower()
    
    def validate_url(self, url: str) -> bool:
        """Validate if the URL is properly formatted."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def is_valid_subpage(self, url: str, base_domain: str) -> bool:
        """Check if URL is a valid subpage of the base domain."""
        try:
            parsed = urlparse(url)
            base_parsed = urlparse(base_domain)
            
            # Must be same domain
            if parsed.netloc != base_parsed.netloc:
                return False
            
            # Avoid common non-content URLs
            avoid_extensions = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.exe', 
                              '.dmg', '.pkg', '.deb', '.rpm', '.tar', '.gz', '.mp3', 
                              '.mp4', '.avi', '.mov', '.wmv', '.doc', '.docx', '.xls', 
                              '.xlsx', '.ppt', '.pptx')
            
            if any(url.lower().endswith(ext) for ext in avoid_extensions):
                return False
            
            # Avoid certain URL patterns
            avoid_patterns = ['mailto:', 'javascript:', 'tel:', '#', 'whatsapp:', 'sms:']
            if any(pattern in url.lower() for pattern in avoid_patterns):
                return False
            
            return True
        except:
            return False
    
    def fetch_page(self, url: str) -> Tuple[str, int]:
        """
        Fetch the HTML content of a webpage.
        Returns tuple of (content, status_code)
        """
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text, response.status_code
        except requests.RequestException as e:
            return "", 0
    
    def extract_emails(self, text: str) -> Set[str]:
        """Extract email addresses from text."""
        emails = set(self.patterns['email'].findall(text))
        # Filter out common false positives
        filtered_emails = {
            email for email in emails 
            if not email.endswith(('.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.svg'))
            and '@' in email
            and len(email) < 100  # Avoid extremely long false positives
        }
        return filtered_emails
    
    def extract_phones(self, text: str) -> Set[str]:
        """Extract phone numbers from text."""
        phones = set(self.patterns['phone'].findall(text))
        # Clean up phone numbers
        cleaned_phones = set()
        for phone in phones:
            # Remove common false positives (like dates)
            if not re.search(r'19\d{2}|20[0-1]\d', phone):
                cleaned_phones.add(phone.strip())
        return cleaned_phones
    
    def extract_addresses(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract potential addresses from the page."""
        addresses = []
        text = soup.get_text()
        
        # Look for state mentions
        found_states = []
        for state in self.us_states:
            if re.search(r'\b' + re.escape(state) + r'\b', text, re.IGNORECASE):
                found_states.append(state)
        
        # Look for zip codes
        zip_codes = self.patterns['zip_code'].findall(text)
        
        # Try to find address-like patterns
        address_pattern = re.compile(
            r'\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl|Way|Circle|Cir|Square|Sq)',
            re.IGNORECASE
        )
        street_addresses = address_pattern.findall(text)
        
        # Combine findings
        for i, street in enumerate(street_addresses[:5]):  # Limit to first 5 addresses
            address_info = {
                'street': street.strip(),
                'state': found_states[0] if found_states else None,
                'zip': zip_codes[i] if i < len(zip_codes) else None
            }
            addresses.append(address_info)
        
        return addresses
    
    def extract_social_media(self, text: str) -> Dict[str, Set[str]]:
        """Extract social media links from text."""
        social_media = {}
        for platform, pattern in self.patterns['social_media'].items():
            links = set(pattern.findall(text))
            if links:
                social_media[platform] = links
        return social_media
    
    def find_subpages(self, soup: BeautifulSoup, base_url: str, current_depth: int) -> List[Tuple[str, int]]:
        """
        Find all valid subpages from the current page.
        Returns list of (url, depth) tuples.
        """
        subpages = []
        
        if current_depth >= self.max_depth:
            return subpages
        
        # Priority keywords for important pages
        priority_keywords = ['contact', 'about', 'team', 'staff', 'location', 'office', 
                           'support', 'help', 'service', 'product', 'solution', 'careers']
        
        all_links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            normalized_url = self.normalize_url(full_url)
            
            if (self.is_valid_subpage(full_url, base_url) and 
                normalized_url not in self.visited_urls):
                
                # Check if link contains priority keywords
                link_text = link.get_text().lower()
                href_lower = href.lower()
                
                is_priority = any(keyword in link_text or keyword in href_lower 
                                for keyword in priority_keywords)
                
                all_links.append((full_url, current_depth + 1, is_priority))
        
        # Sort links: priority links first
        all_links.sort(key=lambda x: (not x[2], x[0]))
        
        # Return limited number of links based on remaining page budget
        remaining_pages = self.max_pages - len(self.visited_urls)
        for url, depth, _ in all_links[:remaining_pages]:
            subpages.append((url, depth))
        
        return subpages
    
    def scrape_single_page(self, url: str, depth: int = 0) -> Dict:
        """Scrape contact information from a single page."""
        normalized_url = self.normalize_url(url)
        
        # Check if already visited
        with self.lock:
            if normalized_url in self.visited_urls:
                return {}
            self.visited_urls.add(normalized_url)
        
        # Fetch the page
        html, status_code = self.fetch_page(url)
        if not html:
            return {}
        
        # Parse with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        
        # Extract all contact information
        contact_info = {
            'url': url,
            'depth': depth,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'emails': list(self.extract_emails(text)),
            'phones': list(self.extract_phones(text)),
            'addresses': self.extract_addresses(soup),
            'social_media': {k: list(v) for k, v in self.extract_social_media(str(soup)).items()},
        }
        
        # Find subpages for crawling
        if depth < self.max_depth:
            contact_info['subpages'] = self.find_subpages(soup, url, depth)
        else:
            contact_info['subpages'] = []
        
        return contact_info
    
    def scrape_website(self, start_url: str, progress_callback=None) -> Dict:
        """
        Main method to scrape a website and its subpages.
        
        Args:
            start_url: The starting URL
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dictionary containing all scraped data
        """
        # Reset for new scraping session
        self.visited_urls.clear()
        self.scraped_data = []
        self.pages_scraped = 0
        
        # Validate starting URL
        if not self.validate_url(start_url):
            return {'error': 'Invalid URL format'}
        
        # Queue for pages to visit (URL, depth)
        pages_queue = deque([(start_url, 0)])
        
        # Track all found contact info
        all_emails = set()
        all_phones = set()
        all_addresses = []
        all_social_media = {}
        pages_details = []
        
        while pages_queue and len(self.visited_urls) < self.max_pages:
            current_url, current_depth = pages_queue.popleft()
            
            # Skip if already visited
            if self.normalize_url(current_url) in self.visited_urls:
                continue
            
            # Update progress
            if progress_callback:
                progress = min(95, (len(self.visited_urls) / self.max_pages) * 100)
                progress_callback(progress, f"Scraping: {current_url[:50]}...")
            
            # Scrape the page
            page_data = self.scrape_single_page(current_url, current_depth)
            
            if page_data:
                # Collect all contact info
                all_emails.update(page_data['emails'])
                all_phones.update(page_data['phones'])
                all_addresses.extend(page_data['addresses'])
                
                # Merge social media links
                for platform, links in page_data.get('social_media', {}).items():
                    if platform not in all_social_media:
                        all_social_media[platform] = set()
                    all_social_media[platform].update(links)
                
                # Store page details
                pages_details.append({
                    'url': page_data['url'],
                    'depth': page_data['depth'],
                    'emails_found': len(page_data['emails']),
                    'phones_found': len(page_data['phones']),
                    'addresses_found': len(page_data['addresses'])
                })
                
                # Add subpages to queue
                for subpage_url, subpage_depth in page_data.get('subpages', []):
                    if len(pages_queue) + len(self.visited_urls) < self.max_pages:
                        pages_queue.append((subpage_url, subpage_depth))
                
                # Respect rate limiting
                time.sleep(self.delay)
        
        # Compile final results
        results = {
            'start_url': start_url,
            'pages_scraped': len(self.visited_urls),
            'max_depth_reached': max([p['depth'] for p in pages_details]) if pages_details else 0,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'all_emails': list(all_emails),
            'all_phones': list(all_phones),
            'all_addresses': self.deduplicate_addresses(all_addresses),
            'all_social_media': {k: list(v) for k, v in all_social_media.items()},
            'pages_details': pages_details,
            'visited_urls': list(self.visited_urls)
        }
        
        return results
    
    def deduplicate_addresses(self, addresses: List[Dict]) -> List[Dict]:
        """Remove duplicate addresses based on street address."""
        seen = set()
        unique_addresses = []
        
        for addr in addresses:
            street = addr.get('street', '')
            if street and street not in seen:
                seen.add(street)
                unique_addresses.append(addr)
        
        return unique_addresses[:10]  # Limit to 10 unique addresses


def create_download_data(data: Dict, format: str = 'json') -> str:
    """Create downloadable data in specified format."""
    if format == 'json':
        return json.dumps(data, indent=2)
    
    elif format == 'csv':
        # Create main summary
        summary_data = {
            'Website': data['start_url'],
            'Pages Scraped': data['pages_scraped'],
            'Timestamp': data['timestamp'],
            'Total Emails': len(data['all_emails']),
            'Total Phones': len(data['all_phones']),
            'Total Addresses': len(data['all_addresses']),
            'Emails': ', '.join(data['all_emails'][:10]),  # First 10
            'Phones': ', '.join(data['all_phones'][:10]),  # First 10
        }
        
        # Add social media
        for platform, links in data['all_social_media'].items():
            summary_data[f'{platform.capitalize()}'] = ', '.join(list(links)[:3])
        
        df = pd.DataFrame([summary_data])
        return df.to_csv(index=False)
    
    elif format == 'detailed_csv':
        # Create detailed page-by-page report
        pages_df = pd.DataFrame(data['pages_details'])
        return pages_df.to_csv(index=False)
    
    return ""


def main():
    # Header with new title
    st.title("🕷️ Advanced Multi-Page Contact Scraper")
    st.markdown("**Automatically crawl websites and subpages** to extract comprehensive contact information")
    
    # Alert about new features
    st.info("🆕 This scraper can now crawl multiple pages! Set the depth and page limit to control how many subpages to explore.")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Scraping Settings")
        
        col1, col2 = st.columns(2)
        
        with col1:
            max_pages = st.number_input(
                "Max Pages to Scrape",
                min_value=1,
                max_value=50,
                value=10,
                help="Maximum number of pages to scrape from the website"
            )
        
        with col2:
            max_depth = st.number_input(
                "Max Crawl Depth",
                min_value=0,
                max_value=3,
                value=1,
                help="How deep to crawl (0=main only, 1=main+direct links, etc.)"
            )
        
        delay = st.slider(
            "Delay between requests (seconds)",
            min_value=0.5,
            max_value=5.0,
            value=1.0,
            step=0.5,
            help="Time to wait between requests"
        )
        
        st.divider()
        
        st.header("📊 Crawling Strategy")
        st.markdown(f"""
        **Current Configuration:**
        - 📄 Will scrape up to **{max_pages} pages**
        - 🔍 Will go **{max_depth} level(s) deep**
        - ⏱️ Will wait **{delay}s** between requests
        
        **Depth Examples:**
        - Depth 0: Main page only
        - Depth 1: Main + linked pages
        - Depth 2: Main + linked + sub-linked
        """)
        
        st.divider()
        
        st.header("🎯 What's Extracted")
        st.markdown("""
        From **each page**, the scraper extracts:
        - 📧 Email addresses
        - 📞 Phone numbers
        - 📍 Physical addresses
        - 🌐 Social media links
        - 🔗 Subpage URLs
        
        All data is **aggregated and deduplicated** across all scraped pages.
        """)
        
        st.divider()
        
        st.header("⚠️ Important Notes")
        st.warning("""
        - Respect robots.txt
        - Check Terms of Service
        - Large crawls may take time
        - Some sites may block scrapers
        """)
    
    # Main content area
    col1, col2 = st.columns([3, 1])
    
    with col1:
        url_input = st.text_input(
            "Enter Website URL to Start Crawling",
            placeholder="https://example.com",
            help="The scraper will start here and automatically find subpages"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        scrape_button = st.button("🕷️ Start Crawling", type="primary", use_container_width=True)
    
    # Display estimated time
    if url_input:
        estimated_time = max_pages * (delay + 0.5)  # Rough estimate
        st.caption(f"⏱️ Estimated time: {estimated_time:.0f} seconds for {max_pages} pages")
    
    # Scraping logic
    if scrape_button and url_input:
        # Initialize scraper
        scraper = MultiPageScraper(delay=delay, max_pages=max_pages, max_depth=max_depth)
        
        # Create progress containers
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Progress callback
        def update_progress(progress, message):
            progress_bar.progress(int(progress))
            status_text.text(message)
        
        # Start scraping
        with st.spinner("Initializing crawler..."):
            results = scraper.scrape_website(url_input, progress_callback=update_progress)
        
        # Clear progress indicators
        progress_bar.progress(100)
        status_text.text("Crawling completed!")
        time.sleep(1)
        progress_bar.empty()
        status_text.empty()
        
        if 'error' in results:
            st.error(f"❌ {results['error']}")
        elif results['pages_scraped'] > 0:
            st.success(f"✅ Successfully crawled {results['pages_scraped']} pages!")
            
            # Display summary metrics
            st.markdown("### 📊 Crawling Summary")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Pages Crawled", results['pages_scraped'])
            with col2:
                st.metric("Max Depth", results['max_depth_reached'])
            with col3:
                st.metric("Emails Found", len(results['all_emails']))
            with col4:
                st.metric("Phones Found", len(results['all_phones']))
            with col5:
                total_social = sum(len(links) for links in results['all_social_media'].values())
                st.metric("Social Links", total_social)
            
            # Create tabs for results
            tabs = st.tabs(["📧 Emails", "📞 Phones", "📍 Addresses", "🌐 Social Media", "📄 Pages Crawled", "🔍 Raw Data"])
            
            with tabs[0]:  # Emails
                if results['all_emails']:
                    st.write(f"Found **{len(results['all_emails'])} unique email addresses** across all pages:")
                    
                    # Create columns for better display
                    email_cols = st.columns(2)
                    for i, email in enumerate(results['all_emails']):
                        with email_cols[i % 2]:
                            st.code(email)
                else:
                    st.info("No email addresses found")
            
            with tabs[1]:  # Phones
                if results['all_phones']:
                    st.write(f"Found **{len(results['all_phones'])} unique phone numbers** across all pages:")
                    
                    phone_cols = st.columns(2)
                    for i, phone in enumerate(results['all_phones']):
                        with phone_cols[i % 2]:
                            st.code(phone)
                else:
                    st.info("No phone numbers found")
            
            with tabs[2]:  # Addresses
                if results['all_addresses']:
                    st.write(f"Found **{len(results['all_addresses'])} unique addresses** across all pages:")
                    
                    for addr in results['all_addresses']:
                        address_text = f"📍 {addr.get('street', 'N/A')}"
                        if addr.get('state'):
                            address_text += f", {addr['state']}"
                        if addr.get('zip'):
                            address_text += f" {addr['zip']}"
                        st.write(address_text)
                else:
                    st.info("No addresses found")
            
            with tabs[3]:  # Social Media
                if results['all_social_media']:
                    st.write("**Social media profiles found across all pages:**")
                    
                    for platform, links in results['all_social_media'].items():
                        with st.expander(f"{platform.capitalize()} ({len(links)} links)"):
                            for link in links:
                                st.write(f"🔗 [{link}]({link})")
                else:
                    st.info("No social media links found")
            
            with tabs[4]:  # Pages Crawled
                st.write(f"**Crawled {results['pages_scraped']} pages** from {results['start_url']}")
                
                # Show page details
                if results['pages_details']:
                    st.markdown("#### Page-by-page breakdown:")
                    
                    for page in results['pages_details']:
                        depth_indicator = "　" * page['depth'] + "└─" if page['depth'] > 0 else "📄"
                        
                        with st.expander(f"{depth_indicator} {page['url'][:80]}..."):
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Emails", page['emails_found'])
                            with col2:
                                st.metric("Phones", page['phones_found'])
                            with col3:
                                st.metric("Addresses", page['addresses_found'])
            
            with tabs[5]:  # Raw Data
                st.write("**Complete scraped data in JSON format:**")
                st.json(results)
            
            # Download section
            st.markdown("### 💾 Download Options")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                json_data = create_download_data(results, 'json')
                st.download_button(
                    label="📥 Download Full JSON",
                    data=json_data,
                    file_name=f"scrape_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    help="Complete data including all pages and details"
                )
            
            with col2:
                csv_data = create_download_data(results, 'csv')
                st.download_button(
                    label="📥 Download Summary CSV",
                    data=csv_data,
                    file_name=f"scrape_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    help="Summary of all found contact information"
                )
            
            with col3:
                detailed_csv = create_download_data(results, 'detailed_csv')
                st.download_button(
                    label="📥 Download Pages Report",
                    data=detailed_csv,
                    file_name=f"pages_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    help="Page-by-page breakdown of results"
                )
            
            # Store in session state
            if 'crawl_history' not in st.session_state:
                st.session_state.crawl_history = []
            
            st.session_state.crawl_history.append({
                'url': results['start_url'],
                'timestamp': results['timestamp'],
                'pages': results['pages_scraped'],
                'emails': len(results['all_emails']),
                'phones': len(results['all_phones'])
            })
            
        else:
            st.warning("⚠️ No pages could be scraped. The website may be blocking automated access.")
    
    # History section
    if 'crawl_history' in st.session_state and st.session_state.crawl_history:
        with st.expander("📜 Crawling History"):
            for i, item in enumerate(reversed(st.session_state.crawl_history[-5:])):  # Show last 5
                st.write(f"**{i+1}. {item['url']}** - {item['timestamp']}")
                st.write(f"   📊 Scraped {item['pages']} pages | Found {item['emails']} emails, {item['phones']} phones")
    
    # Footer
    st.divider()
    st.markdown("""
    <div style='text-align: center; color: #666;'>
        <small>
        ⚠️ <b>Important:</b> Always respect website terms of service and robots.txt files.<br>
        This tool crawls multiple pages automatically. Use responsibly and ethically.<br>
        Consider the server load when scraping many pages.
        </small>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
