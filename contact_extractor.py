"""
Contact Information Extractor Module
Extracts emails, phone numbers, and social media links from business websites
Uses Playwright for JavaScript-heavy sites and BeautifulSoup for static content
"""

import re
import asyncio
from typing import Optional, List, Dict, Set
from urllib.parse import urljoin, urlparse
from loguru import logger
from playwright.async_api import Page, Browser, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup


class ContactExtractor:
    """Extract contact information from business websites"""
    
    def __init__(self):
        # Regex patterns for contact information
        self.email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        
        # US phone number patterns (various formats)
        self.phone_patterns = [
            re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),  # (123) 456-7890 or 123-456-7890
            re.compile(r'\+1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),  # +1-123-456-7890
            re.compile(r'1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),  # 1-123-456-7890
        ]
        
        # Social media patterns
        self.social_patterns = {
            'linkedin': re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9-]+/?'),
            'facebook': re.compile(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9.]+/?'),
            'twitter': re.compile(r'https?://(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9_]+/?'),
            'instagram': re.compile(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.]+/?'),
            'youtube': re.compile(r'https?://(?:www\.)?youtube\.com/(?:channel|c|user)/[a-zA-Z0-9_-]+/?'),
        }
        
        # Common email prefixes to prioritize
        self.priority_email_prefixes = ['info', 'contact', 'sales', 'support', 'hello', 'admin']
        
        # Skip these common non-business emails
        self.skip_email_domains = ['example.com', 'test.com', 'domain.com', 'email.com', 'sentry.io', 'wixpress.com']
    
    
    def clean_phone_number(self, phone: str) -> Optional[str]:
        """
        Clean and format phone number to standard format
        
        Args:
            phone: Raw phone number string
            
        Returns:
            Cleaned phone number in format: (XXX) XXX-XXXX or None if invalid
        """
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', phone)
        
        # Remove leading 1 if present (US country code)
        if digits.startswith('1') and len(digits) == 11:
            digits = digits[1:]
        
        # Validate length
        if len(digits) != 10:
            return None
        
        # Format as (XXX) XXX-XXXX
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    
    
    def is_valid_email(self, email: str) -> bool:
        """
        Check if email is valid and not a common placeholder
        
        Args:
            email: Email address to validate
            
        Returns:
            True if valid business email, False otherwise
        """
        email = email.lower()
        
        # Skip placeholder domains
        domain = email.split('@')[1] if '@' in email else ''
        if domain in self.skip_email_domains:
            return False
        
        # Skip very generic emails
        if email.startswith(('noreply@', 'no-reply@', 'donotreply@')):
            return False
        
        # Skip image/asset URLs that look like emails
        if any(ext in email for ext in ['.jpg', '.png', '.gif', '.css', '.js']):
            return False
        
        return True
    
    
    def prioritize_emails(self, emails: Set[str]) -> List[str]:
        """
        Sort emails by priority (info@, contact@, etc. first)
        
        Args:
            emails: Set of email addresses
            
        Returns:
            Sorted list with priority emails first
        """
        priority = []
        regular = []
        
        for email in emails:
            prefix = email.split('@')[0].lower()
            if any(p in prefix for p in self.priority_email_prefixes):
                priority.append(email)
            else:
                regular.append(email)
        
        return sorted(priority) + sorted(regular)
    
    
    async def _extract_all_tabs(self, page: Page):
        """
        Click through all tabs to load all content
        This ensures we capture information hidden in tabs (like Contact, About, etc.)
        
        Args:
            page: Playwright page object
        """
        try:
            logger.debug("🔍 Looking for tabs to click through...")
            
            # Find all tab buttons using common tab selectors
            tab_selectors = [
                'button[role="tab"]',
                'a[role="tab"]',
                '[data-slot="tabs-trigger"]',
                '.tab-button',
                '.tab',
                'li[role="tab"]'
            ]
            
            tabs_found = False
            
            for selector in tab_selectors:
                try:
                    tabs = await page.locator(selector).all()
                    
                    if len(tabs) > 0:
                        logger.debug(f"Found {len(tabs)} tabs with selector: {selector}")
                        tabs_found = True
                        
                        # Click through each tab
                        for i, tab in enumerate(tabs, 1):
                            try:
                                # Check if tab is visible and clickable
                                if await tab.is_visible():
                                    tab_text = await tab.inner_text()
                                    logger.debug(f"  Clicking tab {i}: {tab_text.strip()[:30]}")
                                    await tab.click()
                                    await page.wait_for_timeout(800)  # Let content load
                            except Exception as e:
                                logger.debug(f"  Could not click tab {i}: {str(e)}")
                                continue
                        
                        break  # Found and clicked tabs, no need to try other selectors
                        
                except Exception as e:
                    logger.debug(f"Error with selector {selector}: {str(e)}")
                    continue
            
            if not tabs_found:
                logger.debug("No tabs found on page")
            else:
                logger.debug("✓ Finished clicking through tabs")
                
        except Exception as e:
            logger.debug(f"Error in _extract_all_tabs: {str(e)}")
    
    
    async def extract_from_page(
        self,
        page: Page,
        url: str,
        follow_contact_links: bool = True
    ) -> Dict[str, any]:
        """
        Extract contact information from a webpage
        
        Args:
            page: Playwright page object
            url: URL of the website to extract from
            follow_contact_links: Whether to follow "Contact" page links
            
        Returns:
            Dictionary with extracted contact information
        """
        result = {
            'url': url,
            'emails': [],
            'phones': [],
            'social_media': {},
            'contact_page_url': None,
            'success': False,
            'error': None
        }
        
        try:
            logger.info(f"🔍 Extracting contact info from: {url}")
            
            # Navigate to the URL
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)  # Let JavaScript load
            except PlaywrightTimeout:
                logger.warning(f"⚠️ Timeout loading {url}, trying to extract anyway...")
            except Exception as e:
                result['error'] = f"Failed to load page: {str(e)}"
                logger.error(f"❌ {result['error']}")
                return result
            
            # Click through all tabs to load hidden content (Contact, About, etc.)
            await self._extract_all_tabs(page)
            
            # Get page content (after clicking tabs)
            html = await page.content()
            text = await page.evaluate("() => document.body.innerText")
            
            # Extract emails
            emails = set()
            for match in self.email_pattern.finditer(html + ' ' + text):
                email = match.group().lower()
                if self.is_valid_email(email):
                    emails.add(email)
            
            result['emails'] = self.prioritize_emails(emails)
            
            # Extract phone numbers
            phones = set()
            for pattern in self.phone_patterns:
                for match in pattern.finditer(text):
                    cleaned = self.clean_phone_number(match.group())
                    if cleaned:
                        phones.add(cleaned)
            
            result['phones'] = sorted(list(phones))
            
            # Extract social media links
            for platform, pattern in self.social_patterns.items():
                matches = pattern.finditer(html)
                for match in matches:
                    if platform not in result['social_media']:
                        result['social_media'][platform] = match.group()
                        break  # Only take first match per platform
            
            # Look for contact page link if we should follow it
            if follow_contact_links and not result['emails']:
                contact_link = await self._find_contact_page_link(page, url)
                if contact_link:
                    result['contact_page_url'] = contact_link
                    logger.info(f"📄 Found contact page: {contact_link}")
                    
                    # Visit contact page and extract
                    try:
                        await page.goto(contact_link, wait_until="domcontentloaded", timeout=20000)
                        await page.wait_for_timeout(2000)
                        
                        # Click through tabs on contact page too
                        await self._extract_all_tabs(page)
                        
                        contact_html = await page.content()
                        contact_text = await page.evaluate("() => document.body.innerText")
                        
                        # Extract emails from contact page
                        contact_emails = set()
                        for match in self.email_pattern.finditer(contact_html + ' ' + contact_text):
                            email = match.group().lower()
                            if self.is_valid_email(email):
                                contact_emails.add(email)
                        
                        # Merge with existing emails
                        all_emails = set(result['emails']) | contact_emails
                        result['emails'] = self.prioritize_emails(all_emails)
                        
                        # Extract phones from contact page
                        for pattern in self.phone_patterns:
                            for match in pattern.finditer(contact_text):
                                cleaned = self.clean_phone_number(match.group())
                                if cleaned:
                                    phones.add(cleaned)
                        
                        result['phones'] = sorted(list(phones))
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Could not extract from contact page: {str(e)}")
            
            result['success'] = True
            
            # Log results
            logger.info(f"✅ Extracted from {url}:")
            logger.info(f"   Emails: {len(result['emails'])} found")
            logger.info(f"   Phones: {len(result['phones'])} found")
            logger.info(f"   Social: {', '.join(result['social_media'].keys())}")
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"❌ Error extracting from {url}: {str(e)}")
            return result
    
    
    async def _find_contact_page_link(self, page: Page, base_url: str) -> Optional[str]:
        """
        Find "Contact" or "About" page link
        
        Args:
            page: Playwright page object
            base_url: Base URL of the website
            
        Returns:
            Contact page URL if found, None otherwise
        """
        try:
            # Look for common contact page link texts
            contact_keywords = ['contact', 'contact us', 'get in touch', 'reach us', 'about', 'about us']
            
            # Get all links
            links = await page.evaluate("""
                () => {
                    const links = [];
                    document.querySelectorAll('a').forEach(a => {
                        links.push({
                            href: a.href,
                            text: a.innerText.toLowerCase().trim()
                        });
                    });
                    return links;
                }
            """)
            
            # Find contact page
            for link in links:
                text = link['text']
                href = link['href']
                
                # Check if link text contains contact keywords
                if any(keyword in text for keyword in contact_keywords):
                    # Make sure it's a valid URL and not external
                    if href and href.startswith(('http://', 'https://')):
                        link_domain = urlparse(href).netloc
                        base_domain = urlparse(base_url).netloc
                        
                        # Only follow links on same domain
                        if link_domain == base_domain or link_domain == f"www.{base_domain}" or base_domain == f"www.{link_domain}":
                            return href
            
            return None
            
        except Exception as e:
            logger.debug(f"Error finding contact page: {str(e)}")
            return None
    
    
    async def extract_from_url(
        self,
        url: str,
        browser: Browser,
        follow_contact_links: bool = True
    ) -> Dict[str, any]:
        """
        Extract contact information from a URL (creates its own page)
        
        Args:
            url: URL to extract from
            browser: Playwright browser instance
            follow_contact_links: Whether to follow contact page links
            
        Returns:
            Dictionary with extracted contact information
        """
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page = await context.new_page()
        
        try:
            result = await self.extract_from_page(page, url, follow_contact_links)
            return result
        finally:
            await page.close()
            await context.close()
    
    
    async def extract_batch(
        self,
        urls: List[str],
        browser: Browser,
        max_concurrent: int = 3,
        delay_between: float = 2.0
    ) -> List[Dict[str, any]]:
        """
        Extract contact information from multiple URLs
        
        Args:
            urls: List of URLs to process
            browser: Playwright browser instance
            max_concurrent: Maximum concurrent extractions
            delay_between: Delay between batches in seconds
            
        Returns:
            List of extraction results
        """
        results = []
        
        # Process in batches to avoid overwhelming the browser
        for i in range(0, len(urls), max_concurrent):
            batch = urls[i:i + max_concurrent]
            
            logger.info(f"📦 Processing batch {i//max_concurrent + 1} ({len(batch)} URLs)")
            
            # Process batch concurrently
            tasks = [self.extract_from_url(url, browser) for url in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle exceptions
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Error processing {batch[j]}: {str(result)}")
                    results.append({
                        'url': batch[j],
                        'emails': [],
                        'phones': [],
                        'social_media': {},
                        'contact_page_url': None,
                        'success': False,
                        'error': str(result)
                    })
                else:
                    results.append(result)
            
            # Delay between batches
            if i + max_concurrent < len(urls):
                logger.info(f"⏸️  Waiting {delay_between}s before next batch...")
                await asyncio.sleep(delay_between)
        
        return results


# Test function
if __name__ == "__main__":
    async def test_extractor():
        """Test the contact extractor"""
        from playwright.async_api import async_playwright
        
        # Test URLs - testing with real small business websites
        test_urls = [
            "https://4seasonscarrier.com",  # Logistics company (has email)
            "https://searchcarriers.com/company/3325181",  # Directory with tabs (has phone)
            "https://www.homedepot.com/c/SF_About_Us",  # Large company contact page
        ]
        
        logger.info("="*80)
        logger.info("🧪 Testing Contact Extractor")
        logger.info("="*80)
        
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=False)
            
            extractor = ContactExtractor()
            
            for url in test_urls:
                result = await extractor.extract_from_url(url, browser)
                
                logger.info("\n" + "="*80)
                logger.info(f"Results for: {url}")
                logger.info("="*80)
                logger.info(f"Success: {result['success']}")
                logger.info(f"Emails: {result['emails']}")
                logger.info(f"Phones: {result['phones']}")
                logger.info(f"Social Media: {result['social_media']}")
                logger.info(f"Contact Page: {result['contact_page_url']}")
                if result['error']:
                    logger.error(f"Error: {result['error']}")
            
            await browser.close()
            await playwright.stop()
            
        except Exception as e:
            logger.error(f"❌ Test failed: {str(e)}")
            logger.exception(e)
    
    asyncio.run(test_extractor())

