#!/usr/bin/env python3
"""
Contact Information Web Scraper - Streamlit App
A user-friendly web application for extracting contact information from websites.
"""

import streamlit as st
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import json
from typing import Dict, List, Set
import pandas as pd
from datetime import datetime
import io

# Page configuration
st.set_page_config(
    page_title="Contact Info Scraper",
    page_icon="🔍",
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
</style>
""", unsafe_allow_html=True)


class ContactInfoScraper:
    def __init__(self, delay: float = 1.0):
        """Initialize the scraper with configurable delay between requests."""
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
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
    
    def validate_url(self, url: str) -> bool:
        """Validate if the URL is properly formatted."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def fetch_page(self, url: str) -> str:
        """Fetch the HTML content of a webpage."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            st.error(f"Error fetching {url}: {e}")
            return ""
    
    def extract_emails(self, text: str) -> Set[str]:
        """Extract email addresses from text."""
        emails = set(self.patterns['email'].findall(text))
        # Filter out common false positives
        filtered_emails = {
            email for email in emails 
            if not email.endswith(('.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.svg'))
            and '@' in email
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
    
    def find_contact_pages(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find links to contact or about pages."""
        contact_keywords = ['contact', 'about', 'team', 'support', 'help', 'reach', 'connect']
        contact_links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().lower()
            
            # Check if link text or href contains contact keywords
            if any(keyword in text or keyword in href.lower() for keyword in contact_keywords):
                # Resolve relative URLs
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == urlparse(base_url).netloc:  # Same domain
                    contact_links.append(full_url)
        
        return list(set(contact_links))[:10]  # Limit to 10 unique links
    
    def scrape_contact_info(self, url: str) -> Dict:
        """Main method to scrape contact information from a URL."""
        # Validate URL
        if not self.validate_url(url):
            st.error("Invalid URL format. Please include http:// or https://")
            return {}
        
        # Fetch the page
        html = self.fetch_page(url)
        if not html:
            return {}
        
        # Parse with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        
        # Extract all contact information
        contact_info = {
            'url': url,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'emails': list(self.extract_emails(text)),
            'phones': list(self.extract_phones(text)),
            'addresses': self.extract_addresses(soup),
            'social_media': {k: list(v) for k, v in self.extract_social_media(str(soup)).items()},
            'contact_pages': self.find_contact_pages(soup, url)
        }
        
        return contact_info


def create_download_link(data: Dict, format: str = 'json'):
    """Create a download link for the scraped data."""
    if format == 'json':
        json_str = json.dumps(data, indent=2)
        return json_str
    elif format == 'csv':
        # Flatten the data for CSV
        flat_data = {
            'URL': data['url'],
            'Timestamp': data['timestamp'],
            'Emails': ', '.join(data['emails']),
            'Phones': ', '.join(data['phones']),
            'Addresses': ', '.join([addr['street'] or '' for addr in data['addresses']]),
            'States': ', '.join([addr['state'] or '' for addr in data['addresses'] if addr['state']]),
            'ZIP Codes': ', '.join([addr['zip'] or '' for addr in data['addresses'] if addr['zip']]),
        }
        # Add social media
        for platform, links in data['social_media'].items():
            flat_data[f'{platform.capitalize()}'] = ', '.join(links)
        
        df = pd.DataFrame([flat_data])
        return df.to_csv(index=False)
    return ""


def main():
    # Header
    st.title("🔍 Contact Information Scraper")
    st.markdown("Extract emails, phone numbers, addresses, and social media links from any website")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        
        delay = st.slider(
            "Delay between requests (seconds)",
            min_value=0.5,
            max_value=5.0,
            value=1.0,
            step=0.5,
            help="Time to wait between requests to be respectful to servers"
        )
        
        st.divider()
        
        st.header("📝 Instructions")
        st.markdown("""
        1. Enter a URL in the main panel
        2. Click 'Scrape Website'
        3. View extracted information
        4. Download results as JSON or CSV
        
        **Ethical Guidelines:**
        - Check robots.txt
        - Respect Terms of Service
        - Use appropriate delays
        - Get permission for bulk scraping
        """)
        
        st.divider()
        
        st.header("🎯 What's Extracted")
        st.markdown("""
        - 📧 Email addresses
        - 📞 Phone numbers
        - 📍 Physical addresses
        - 🌐 Social media links
        - 📄 Contact page URLs
        """)
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        url_input = st.text_input(
            "Enter Website URL",
            placeholder="https://example.com",
            help="Enter the full URL including http:// or https://"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        scrape_button = st.button("🔍 Scrape Website", type="primary", use_container_width=True)
    
    # Scraping logic
    if scrape_button and url_input:
        # Initialize scraper
        scraper = ContactInfoScraper(delay=delay)
        
        # Progress indicator
        with st.spinner(f"Scraping {url_input}..."):
            progress_bar = st.progress(0)
            progress_bar.progress(30)
            
            # Scrape the website
            result = scraper.scrape_contact_info(url_input)
            progress_bar.progress(100)
            time.sleep(0.5)
            progress_bar.empty()
        
        if result and any([result['emails'], result['phones'], result['addresses'], result['social_media']]):
            st.success("✅ Scraping completed successfully!")
            
            # Display metrics
            st.markdown("### 📊 Summary")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Emails Found", len(result['emails']))
            with col2:
                st.metric("Phone Numbers", len(result['phones']))
            with col3:
                st.metric("Addresses", len(result['addresses']))
            with col4:
                total_social = sum(len(links) for links in result['social_media'].values())
                st.metric("Social Links", total_social)
            
            # Display detailed results
            st.markdown("### 📋 Detailed Results")
            
            # Create tabs for different types of information
            tabs = st.tabs(["📧 Emails", "📞 Phones", "📍 Addresses", "🌐 Social Media", "📄 Contact Pages"])
            
            with tabs[0]:
                if result['emails']:
                    for email in result['emails']:
                        st.code(email)
                else:
                    st.info("No email addresses found")
            
            with tabs[1]:
                if result['phones']:
                    for phone in result['phones']:
                        st.code(phone)
                else:
                    st.info("No phone numbers found")
            
            with tabs[2]:
                if result['addresses']:
                    for addr in result['addresses']:
                        address_text = f"📍 {addr.get('street', 'N/A')}"
                        if addr.get('state'):
                            address_text += f", {addr['state']}"
                        if addr.get('zip'):
                            address_text += f" {addr['zip']}"
                        st.write(address_text)
                else:
                    st.info("No addresses found")
            
            with tabs[3]:
                if result['social_media']:
                    for platform, links in result['social_media'].items():
                        st.subheader(f"{platform.capitalize()}")
                        for link in links:
                            st.write(f"🔗 [{link}]({link})")
                else:
                    st.info("No social media links found")
            
            with tabs[4]:
                if result['contact_pages']:
                    st.write("Found these potential contact/about pages:")
                    for page in result['contact_pages']:
                        st.write(f"🔗 [{page}]({page})")
                else:
                    st.info("No additional contact pages found")
            
            # Download section
            st.markdown("### 💾 Download Results")
            col1, col2 = st.columns(2)
            
            with col1:
                json_data = create_download_link(result, 'json')
                st.download_button(
                    label="📥 Download as JSON",
                    data=json_data,
                    file_name=f"contact_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )
            
            with col2:
                csv_data = create_download_link(result, 'csv')
                st.download_button(
                    label="📥 Download as CSV",
                    data=csv_data,
                    file_name=f"contact_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            
            # Store in session state for history
            if 'history' not in st.session_state:
                st.session_state.history = []
            st.session_state.history.append(result)
            
        else:
            st.warning("⚠️ No contact information found on this page. Try checking the contact or about pages.")
    
    # History section
    if 'history' in st.session_state and st.session_state.history:
        with st.expander("📜 Scraping History"):
            for i, item in enumerate(reversed(st.session_state.history[-5:])):  # Show last 5
                st.write(f"**{i+1}. {item['url']}** - {item['timestamp']}")
                st.write(f"   Found: {len(item['emails'])} emails, {len(item['phones'])} phones")
    
    # Footer
    st.divider()
    st.markdown("""
    <div style='text-align: center; color: #666;'>
        <small>
        ⚠️ <b>Important:</b> Always respect website terms of service and robots.txt files.<br>
        This tool is for educational purposes. Use responsibly and ethically.
        </small>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
