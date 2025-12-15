"""
Georgia SOS Business Scraper
Scrapes business data from Georgia Secretary of State website
"""

import asyncio
import random
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from pathlib import Path
from loguru import logger
from playwright.async_api import Page, Browser, BrowserContext
from urllib.parse import urlparse
import shutil
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from cloudflareSolver import get_bypassed_page, solve_cloudflare_challenge, CloudflareTurnstileExtractor
from cloudflare_utils import is_session_valid
from naics_classifier_ai import enrich_naics_codes_ai as enrich_naics_codes
from google_scraper_selenium import (
    search_google_for_website,
    search_google_for_linkedin,
    search_google_for_facebook,
    get_google_business_profile,
    create_undetected_driver,
    human_delay as google_human_delay
)
import undetected_chromedriver as uc
from contact_extractor import ContactExtractor
from website_validator import select_best_website, extract_domain, extract_domain_from_email


def setup_logging(log_filename: str = None):
    """
    Set up logging to both console and file
    
    Args:
        log_filename: Name of the log file (default: logs/scraper_YYYYMMDD_HHMMSS.log)
    """
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Generate log filename with timestamp if not provided
    if not log_filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"scraper_{timestamp}.log"
    
    log_path = log_dir / log_filename
    
    # Add file handler to logger (loguru automatically handles console)
    logger.add(
        log_path,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",  # Rotate when file reaches 10MB
        retention="7 days",  # Keep logs for 7 days
        compression="zip"  # Compress rotated logs
    )
    
    logger.info(f"📝 Logging to file: {log_path}")
    return log_path


async def human_delay(min_seconds: float = 0.5, max_seconds: float = 2.0):
    """
    Random delay to simulate human behavior
    
    Args:
        min_seconds: Minimum delay in seconds
        max_seconds: Maximum delay in seconds
    """
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


async def simulate_human_behavior(page: Page):
    """
    Simulate human-like behavior: mouse movements, scrolling, etc.
    """
    try:
        # Random scroll (humans don't scroll in one go)
        scroll_amount = random.randint(100, 400)
        scroll_direction = random.choice([1, -1])
        await page.mouse.wheel(0, scroll_amount * scroll_direction)
        await human_delay(0.3, 0.8)
        
        # Random mouse movement
        if random.random() < 0.3:  # 30% chance
            viewport = page.viewport_size
            if viewport:
                x = random.randint(100, viewport['width'] - 100)
                y = random.randint(100, viewport['height'] - 100)
                await page.mouse.move(x, y)
                await human_delay(0.1, 0.3)
        
    except Exception as e:
        logger.debug(f"Error simulating human behavior: {str(e)}")


async def human_like_type(page: Page, selector: str, text: str):
    """
    Type text with human-like delays between keystrokes
    """
    await page.click(selector)
    await human_delay(0.2, 0.5)
    
    for char in text:
        await page.type(selector, char, delay=random.uniform(50, 150))
        if random.random() < 0.1:  # 10% chance
            await human_delay(0.3, 0.8)


async def check_and_solve_cloudflare(page: Page, context: BrowserContext) -> bool:
    """
    Check if Cloudflare challenge is present and solve it if needed
    
    Args:
        page: Playwright page object
        context: Browser context
        
    Returns:
        True if no challenge or challenge solved successfully, False otherwise
    """
    try:
        # Check if session is still valid
        is_valid = await is_session_valid(page)
        
        if is_valid:
            logger.debug("✅ No Cloudflare challenge detected")
            return True
        
        logger.warning("⚠️ Cloudflare challenge detected! Attempting to solve...")
        
        # Extract domain from URL
        parsed_url = urlparse(page.url)
        domain = parsed_url.netloc
        
        # CRITICAL FIX: Reuse extractor instance from context (created in get_bypassed_page)
        # This ensures network monitoring persists and captures requests across page navigations
        extractor = getattr(context, '_cloudflare_extractor', None)
        
        if extractor is None:
            # No extractor found on context, create new one and attach it
            logger.debug("No existing extractor found on context, creating new one...")
            extractor = CloudflareTurnstileExtractor()
            await extractor.setup_network_monitoring(page)
            context._cloudflare_extractor = extractor
        else:
            logger.debug(f"✅ Reusing existing extractor instance (has {len(extractor.captured_requests)} captured requests)")
            # Ensure monitoring is set up on this page (handlers are page-specific)
            if not extractor.monitoring_setup:
                logger.debug("Setting up network monitoring on this page...")
                await extractor.setup_network_monitoring(page)
            else:
                # Monitoring already set up - handlers persist across navigations on the same page
                logger.debug("Network monitoring already active from previous setup")
        
        # Initialize variables
        sitekey = None
        turnstile_params = None
        
        # FIRST: Check if sitekey was already captured in window.turnstileParams
        # (from initial get_bypassed_page call - don't reset it!)
        existing_params = await page.evaluate("() => window.turnstileParams")
        if existing_params and existing_params.get('sitekey'):
            existing_sitekey = existing_params['sitekey']
            if extractor._is_valid_turnstile_sitekey(existing_sitekey):
                logger.info(f"✅ Using previously captured sitekey from window.turnstileParams: {existing_sitekey}")
                sitekey = existing_sitekey
                turnstile_params = existing_params
            else:
                logger.debug(f"Existing turnstileParams found but invalid sitekey: {existing_sitekey}")
                existing_params = None
        
        # Check if sitekey was already captured in extractor from previous requests
        # IMPORTANT: Even if we have sitekey from network, we still need turnstile_params (action, data, pagedata)
        # for 2captcha API, so we'll inject the interceptor below
        if not existing_params and extractor.sitekey_from_network:
            logger.info(f"✅ Using sitekey from previous network monitoring: {extractor.sitekey_from_network}")
            sitekey = extractor.sitekey_from_network
            # Don't set turnstile_params yet - we'll try to capture it via interceptor below
            # Don't set existing_params = True - we still need to inject interceptor for turnstile_params
            logger.debug("⚠️ Sitekey found but turnstile_params missing - will inject interceptor to capture them")
        
        # Only skip interceptor injection if we already have both sitekey AND turnstile_params
        has_sitekey_and_params = existing_params and existing_params.get('sitekey') and existing_params.get('action')
        
        # Set up monitoring and inject interceptor if we don't have complete params
        if not has_sitekey_and_params:
            logger.debug("No existing sitekey found, setting up network monitoring...")
            # Monitoring may already be set up (checked above), but ensure it's active
            if not extractor.monitoring_setup:
                await extractor.setup_network_monitoring(page)
            
            # Inject turnstile interceptor (only reset if not already set)
            await page.evaluate("""
                () => {
                    // Only reset if turnstileParams doesn't exist or is null/empty
                    if (!window.turnstileParams || !window.turnstileParams.sitekey) {
                        window.turnstileParams = null;
                        const interval = setInterval(() => {
                            if (window.turnstile) {
                                clearInterval(interval);
                                const originalRender = window.turnstile.render;
                                window.turnstile.render = function(container, options) {
                                    window.turnstileParams = {
                                        sitekey: options.sitekey,
                                        action: options.action || null,
                                        cData: options.cData || null,
                                        chlPageData: options.chlPageData || null,
                                        callback: options.callback || null
                                    };
                                    if (originalRender) {
                                        return originalRender.call(this, container, options);
                                    }
                                    return 'foo';
                                };
                            }
                        }, 10);
                    }
                }
            """)
            
            # Wait for challenge to load and turnstile to render
            await page.wait_for_timeout(5000)
            
            # Try to trigger turnstile render if it hasn't rendered yet
            await page.evaluate("""
                () => {
                    // Try to find and render turnstile if it exists but hasn't rendered
                    if (window.turnstile && typeof window.turnstile.render === 'function') {
                        const containers = document.querySelectorAll('[data-sitekey]');
                        containers.forEach(container => {
                            if (!container.querySelector('iframe')) {
                                try {
                                    window.turnstile.render(container, {
                                        sitekey: container.getAttribute('data-sitekey'),
                                        callback: function(token) {
                                            console.log('Turnstile rendered with token');
                                        }
                                    });
                                } catch(e) {
                                    console.log('Error rendering turnstile:', e);
                                }
                            }
                        });
                    }
                }
            """)
            
            # Wait a bit more for turnstile to potentially render
            await page.wait_for_timeout(3000)
            
            # Extract sitekey from network (only if we don't already have one)
            if not sitekey:
                sitekey = await extractor.get_sitekey(page, wait_time=10000)  # Increased wait time
            
            # Always check for turnstile_params after interceptor injection
            # (This is critical - we need action, data, pagedata for 2captcha API)
            captured_params = await page.evaluate("() => window.turnstileParams")
            if captured_params:
                turnstile_params = captured_params
                logger.debug(f"✅ Captured turnstile_params: action={captured_params.get('action')}, has_data={bool(captured_params.get('cData'))}, has_pagedata={bool(captured_params.get('chlPageData'))}")
            elif not turnstile_params:
                # Check one more time after a longer wait (Turnstile might be slow to render)
                await page.wait_for_timeout(5000)
                captured_params = await page.evaluate("() => window.turnstileParams")
                if captured_params:
                    turnstile_params = captured_params
                    logger.debug(f"✅ Captured turnstile_params after longer wait")
        
        # CRITICAL FIX: Fallback to known sitekey if extraction failed (same as get_bypassed_page)
        if not sitekey:
            logger.warning("⚠️ Network monitoring didn't capture sitekey")
            logger.warning("⚠️ Using known sitekey for ecorp.sos.ga.gov domain as fallback")
            sitekey = "0x4AAAAAAADnPIDROrmt1Wwj"
            logger.info(f"✓ Fallback sitekey applied: {sitekey}")
        
        logger.info(f"🔧 Found sitekey: {sitekey}, solving challenge...")
        if turnstile_params:
            logger.debug(f"Turnstile params: {turnstile_params}")
        else:
            logger.debug("No turnstile params captured (this is OK)")
        
        # Solve the challenge
        success = await solve_cloudflare_challenge(page, context, domain, sitekey, turnstile_params)
        
        if success:
            # Wait for page to redirect after solving
            await page.wait_for_load_state("networkidle", timeout=30000)
            await human_delay(2.0, 4.0)
            
            # Verify challenge is solved
            is_valid_after = await is_session_valid(page)
            if is_valid_after:
                logger.info("✅ Cloudflare challenge solved successfully!")
                return True
            else:
                logger.warning("⚠️ Challenge may not be fully solved")
                return False
        else:
            logger.error("❌ Failed to solve Cloudflare challenge")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error checking/solving Cloudflare challenge: {str(e)}")
        logger.exception(e)
        return False


async def search_business(
    search_term: str,
    page: Optional[Page] = None
) -> Page:
    """
    Search for businesses on Georgia SOS website
    
    Args:
        search_term: Business name to search for (e.g., "landscap")
        page: Optional page instance (if already bypassed Cloudflare)
        
    Returns:
        Page object after search is complete and results are loaded
    """
    target_url = "https://ecorp.sos.ga.gov/BusinessSearch"
    
    # Get bypassed page if not provided
    if not page:
        logger.info("🔐 Bypassing Cloudflare challenge...")
        playwright, browser, context, page = await get_bypassed_page(target_url, headless=False)
    
    current_url = page.url
    if "BusinessSearch" not in current_url:
        logger.info(f"Navigating to {target_url}...")
        await page.goto(target_url)
        await page.wait_for_load_state("domcontentloaded")
    
    # Wait for the search form to be visible
    logger.info("Waiting for search form...")
    try:
        await page.wait_for_selector("#txtBusinessName", timeout=10000)
        logger.info("✅ Search form loaded")
    except Exception as e:
        logger.error(f"Failed to find search form: {str(e)}")
        raise
    
    # Fill in the business name search field with human-like typing
    logger.info(f"Entering search term: '{search_term}'")
    await human_like_type(page, "#txtBusinessName", search_term)
    await human_delay(0.5, 1.5)  # Pause after typing (human reading)
    logger.info("✅ Search term entered")
    
    # CRITICAL: Ensure network monitoring is active BEFORE clicking search
    # This ensures we capture sitekey immediately when challenge appears
    extractor = getattr(page.context, '_cloudflare_extractor', None)
    if extractor:
        if not extractor.monitoring_setup:
            logger.debug("Setting up network monitoring before search click...")
            await extractor.setup_network_monitoring(page)
        else:
            logger.debug("✅ Network monitoring already active, ready to capture sitekey")
    
    # Simulate human behavior before clicking
    await simulate_human_behavior(page)
    await human_delay(0.3, 0.8)
    
    # Click the Search button with human-like delay
    logger.info("Clicking Search button...")
    search_button = page.locator("#btnSearch")
    # Hover first (humans hover before clicking)
    await search_button.hover()
    await human_delay(0.2, 0.5)
    await search_button.click()
    logger.info("✅ Search button clicked")
    
    # Wait for search results to load
    logger.info("⏳ Waiting for search results to load...")
    try:
        # Wait for results table or content to appear
        # Common indicators: table, results container, or change in page content
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        # Additional wait to ensure results are rendered
        await page.wait_for_timeout(2000)
        
        logger.info("✅ Search results loaded")
        
        # Check for Cloudflare challenge after search
        await check_and_solve_cloudflare(page, page.context)
        
        # Verify results are present (check for table or results container)
        try:
            # Look for results table
            results_table = await page.query_selector("table")
            if results_table:
                logger.info("✅ Results table found")
            else:
                logger.warning("⚠️ No results table found, but page loaded")
        except:
            logger.debug("Could not verify results table")
        
    except Exception as e:
        logger.error(f"Timeout waiting for search results: {str(e)}")
        # Continue anyway - results might still be loading
    
    return page


def extract_city_state_from_address(address: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract city and state from Principal Office Address
    
    Args:
        address: Address string (e.g., "1754 Bouldercrest Rd SE, Atlanta, GA 30316")
        
    Returns:
        Tuple of (city, state) or (None, None) if not found
    """
    if not address:
        return None, None
    
    try:

        import re
        
        # Pattern 1: "City, ST ZIP" or "City, State ZIP"
        pattern1 = r',\s*([A-Za-z\s]+?),\s*([A-Z]{2})(?:\s+\d{5})?$'
        match = re.search(pattern1, address)
        if match:
            city = match.group(1).strip()
            state = match.group(2).strip()
            return city, state
        
        # Pattern 2: Last two words before ZIP (if ZIP exists)
        pattern2 = r'([A-Za-z\s]+?),\s*([A-Z]{2})\s+\d{5}'
        match = re.search(pattern2, address)
        if match:
            city = match.group(1).strip()
            state = match.group(2).strip()
            return city, state
        
        # Pattern 3: Split by comma and check last parts
        parts = [p.strip() for p in address.split(',')]
        if len(parts) >= 2:
            # Last part might be "ST ZIP" or "State ZIP"
            last_part = parts[-1]
            state_match = re.search(r'\b([A-Z]{2})\b', last_part)
            if state_match:
                state = state_match.group(1)
                # City is second-to-last part
                if len(parts) >= 2:
                    city = parts[-2]
                    return city, state
        
        # Pattern 4: If no ZIP, try last comma-separated part as state
        if ',' in address:
            parts = [p.strip() for p in address.split(',')]
            if len(parts) >= 2:
                last_part = parts[-1]
                # Check if last part is a 2-letter state code
                if re.match(r'^[A-Z]{2}$', last_part):
                    state = last_part
                    city = parts[-2] if len(parts) >= 2 else None
                    return city, state
        
        return None, None
        
    except Exception as e:
        logger.debug(f"Error extracting city/state from address '{address}': {str(e)}")
        return None, None


async def enrich_contact_info(
    business_name: str,
    page: Page,
    city: Optional[str] = None,
    state: Optional[str] = None,
    google_driver: Optional[uc.Chrome] = None
) -> Dict[str, any]:
    """
    Enrich business data with contact information using Google search (Selenium)
    
    Args:
        business_name: Name of the business
        page: Playwright page object (for email extraction from website)
        city: Optional city name
        state: Optional state name (default: 'GA')
        google_driver: Selenium WebDriver (undetected Chrome) for Google searches
        
    Returns:
        Dictionary with contact information:
        {
            'Website': 'https://...',
            'Email': 'email@domain.com',
            'LinkedIn': 'https://linkedin.com/company/...',
            'Facebook': 'https://facebook.com/...',
            'Google_Business_Phone': '(404) 621-5252',
            'Google_Business_Address': '1754 Bouldercrest Rd SE...',
            'Google_Business_Rating': 4.5,
            'Google_Business_Website': 'https://...',
        }
    """
    result = {
        'Website': None,
        'Email': None,
        'LinkedIn': None,
        'Facebook': None,
        'Google_Business_Phone': None,
        'Google_Business_Address': None,
        'Google_Business_Rating': None,
        'Google_Business_Website': None,
    }
    
    if not google_driver:
        logger.warning("   ⚠️ No Google driver provided, skipping Google enrichment")
        return result
    
    try:
        # Default state to GA if not provided
        if not state:
            state = 'GA'
        
        logger.info(f"   🔍 Enriching contact info via Google search (Selenium)...")
        
        # Step 1: Search for website (run in thread pool since Selenium is sync)
        try:
            website = await asyncio.to_thread(search_google_for_website, business_name, google_driver, city, state)
            if website:
                result['Website'] = website
                logger.info(f"   ✅ Found website: {website}")
            else:
                logger.debug(f"   ⚠️ No website found")
        except Exception as e:
            logger.debug(f"   ⚠️ Error searching for website: {str(e)}")
        
        # Delay between searches
        await asyncio.sleep(random.uniform(3.0, 5.0))
        
        # Step 2: Search for LinkedIn
        try:
            linkedin = await asyncio.to_thread(search_google_for_linkedin, business_name, google_driver)
            if linkedin:
                result['LinkedIn'] = linkedin
                logger.info(f"   ✅ Found LinkedIn: {linkedin}")
        except Exception as e:
            logger.debug(f"   ⚠️ Error searching for LinkedIn: {str(e)}")
        
        # Delay between searches
        await asyncio.sleep(random.uniform(3.0, 5.0))
        
        # Step 3: Search for Facebook
        try:
            facebook = await asyncio.to_thread(search_google_for_facebook, business_name, google_driver)
            if facebook:
                result['Facebook'] = facebook
                logger.info(f"   ✅ Found Facebook: {facebook}")
        except Exception as e:
            logger.debug(f"   ⚠️ Error searching for Facebook: {str(e)}")
        
        # Delay between searches
        await asyncio.sleep(random.uniform(3.0, 5.0))
        
        # Step 4: Get Google Business Profile
        google_website = None
        try:
            profile = await asyncio.to_thread(get_google_business_profile, business_name, google_driver, city, state)
            if profile:
                result['Google_Business_Phone'] = profile.get('phone')
                result['Google_Business_Address'] = profile.get('address')
                result['Google_Business_Rating'] = profile.get('rating')
                google_website = profile.get('website')
                result['Google_Business_Website'] = google_website
                logger.info(f"   ✅ Found Google Business Profile")
        except Exception as e:
            logger.debug(f"   ⚠️ Error getting Google Business Profile: {str(e)}")
        
        # Step 5: Extract email from website if found (still use Playwright for this)
        email_domain = None
        if result['Website'] and page:
            try:
                extractor = ContactExtractor()
                contact_data = await extractor.extract_from_page(page, result['Website'])
                
                if contact_data and contact_data.get('emails'):
                    # Get primary email (first in prioritized list)
                    result['Email'] = contact_data['emails'][0] if contact_data['emails'] else None
                    if result['Email']:
                        email_domain = extract_domain_from_email(result['Email'])
                        logger.info(f"   ✅ Extracted email: {result['Email']}")
            except Exception as e:
                logger.debug(f"   ⚠️ Error extracting email from website: {str(e)}")
        
        # Step 6: Collect multiple website sources and validate
        website_sources = []
        
        # Source 1: Google Business Profile (highest confidence)
        if google_website:
            website_sources.append({
                'url': google_website,
                'source': 'google_business'
            })
        
        # Source 2: LinkedIn company page domain
        if result.get('LinkedIn'):
            linkedin_domain = extract_domain(result['LinkedIn'])
            # LinkedIn company pages have format: linkedin.com/company/company-name
            # We can't extract the actual company website from LinkedIn URL directly
            # But we can use it as a validation signal
        
        # Source 3: Email domain (if email found)
        if email_domain:
            # Construct potential website from email domain
            email_website = f"https://{email_domain}"
            website_sources.append({
                'url': email_website,
                'source': 'email'
            })
        
        # Source 4: Google search result
        if result.get('Website'):
            website_sources.append({
                'url': result['Website'],
                'source': 'google_search'
            })
        
        # Select best validated website
        if website_sources:
            best_website = select_best_website(website_sources, business_name)
            if best_website:
                result['Website'] = best_website['url']
                result['Website_Confidence'] = best_website['combined_confidence']
                result['Website_Source'] = best_website['source']
                result['Website_Validation_Reason'] = best_website['validation']['reason']
                logger.info(f"   ✅ Validated website: {best_website['url']} (confidence: {best_website['combined_confidence']:.0%}, source: {best_website['source']})")
            else:
                # Keep original if validation fails
                logger.warning(f"   ⚠️ Website validation failed, keeping original")
        
        # Log summary
        found_items = [k for k, v in result.items() if v and k not in ['Website_Confidence', 'Website_Source', 'Website_Validation_Reason']]
        if found_items:
            logger.info(f"   ✅ Contact enrichment complete: {len(found_items)} items found")
        else:
            logger.debug(f"   ⚠️ No contact info found")
        
        return result
        
    except Exception as e:
        logger.error(f"   ❌ Error enriching contact info: {str(e)}")
        return result


async def extract_detail_page_data(page: Page, control_number: str) -> Dict[str, str]:
    """
    Extract additional data from business detail page
    
    Args:
        page: Playwright page object
        control_number: Control number for verification
        
    Returns:
        Dictionary with additional business data fields
    """
    try:
        # Wait for page to load
        await page.wait_for_load_state("domcontentloaded")
        await human_delay(1.5, 3.0)  # Variable wait time (more human-like)
        
        # Extract data from detail page
        detail_data = await page.evaluate("""
            () => {
                const data = {};
                
                // Find Business Information table (table with cellpadding="4")
                const tables = document.querySelectorAll('table[cellpadding="4"]');
                let businessTable = null;
                
                // Find the table that contains "Business Information" header
                for (let table of tables) {
                    const header = table.querySelector('td.inner_databg');
                    if (header && header.textContent.includes('Business Information')) {
                        businessTable = table;
                        break;
                    }
                }
                
                if (businessTable) {
                    const rows = businessTable.querySelectorAll('tbody tr');
                    
                    rows.forEach(row => {
                        const cells = row.querySelectorAll('td');
                        
                        // Handle rows with 4 cells (label-value pairs side by side)
                        if (cells.length >= 4) {
                            // First pair
                            let label = cells[0].textContent.trim().replace(':', '').trim();
                            let value = cells[1].querySelector('strong') 
                                ? cells[1].querySelector('strong').textContent.trim() 
                                : cells[1].textContent.trim();
                            
                            // Second pair
                            let label2 = cells[2].textContent.trim().replace(':', '').trim();
                            let value2 = cells[3].querySelector('strong')
                                ? cells[3].querySelector('strong').textContent.trim()
                                : cells[3].textContent.trim();
                            
                            // Extract fields (only new ones, skip duplicates from table)
                            // NAICS fields - Georgia SOS website source
                            if (label === 'NAICS Code' && value) {
                                data['Georgia_SOS_NAICS'] = value;
                                data['NAICS_Source'] = 'Georgia SOS Website';
                            }
                            if (label === 'NAICS Sub Code' && value) data['Georgia_SOS_NAICS_Sub'] = value;
                            if (label === 'Date of Formation / Registration Date' && value) data['Date of Formation'] = value;
                            if (label === 'State of Formation' && value) data['State of Formation'] = value;
                            if (label === 'Last Annual Registration Year' && value2) data['Last Annual Registration Year'] = value2;
                            if (label === 'Dissolved Date' && value) data['Dissolved Date'] = value;
                            
                            // Check second column
                            if (label2 === 'NAICS Code' && value2) {
                                data['Georgia_SOS_NAICS'] = value2;
                                data['NAICS_Source'] = 'Georgia SOS Website';
                            }
                            if (label2 === 'NAICS Sub Code' && value2) data['Georgia_SOS_NAICS_Sub'] = value2;
                            if (label2 === 'Date of Formation / Registration Date' && value2) data['Date of Formation'] = value2;
                            if (label2 === 'State of Formation' && value2) data['State of Formation'] = value2;
                            if (label2 === 'Last Annual Registration Year' && value2) data['Last Annual Registration Year'] = value2;
                            if (label2 === 'Dissolved Date' && value2) data['Dissolved Date'] = value2;
                        }
                        // Handle rows with 2 cells (single field)
                        else if (cells.length === 2) {
                            let label = cells[0].textContent.trim().replace(':', '').trim();
                            let value = cells[1].querySelector('strong')
                                ? cells[1].querySelector('strong').textContent.trim()
                                : cells[1].textContent.trim();
                            
                            if (label === 'Dissolved Date' && value) data['Dissolved Date'] = value;
                        }
                    });
                }
                
                // Registered Agent Information (in .data_pannel div)
                const agentPanels = document.querySelectorAll('.data_pannel');
                for (let panel of agentPanels) {
                    const header = panel.querySelector('td.inner_databg');
                    if (header && header.textContent.includes('Registered Agent Information')) {
                        const agentTable = panel.querySelector('table');
                        if (agentTable) {
                            const rows = agentTable.querySelectorAll('tr');
                            
                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 2) {
                                    let label = cells[0].textContent.trim().replace(':', '').trim();
                                    let value = cells[1].querySelector('strong')
                                        ? cells[1].querySelector('strong').textContent.trim()
                                        : cells[1].textContent.trim();
                                    
                                    if (label === 'Physical Address' && value) {
                                        data['Registered Agent Physical Address'] = value;
                                    }
                                    if (label === 'County' && value) {
                                        data['Registered Agent County'] = value;
                                    }
                                }
                            });
                        }
                        break;
                    }
                }
                
                // Officer Information (optional - may not exist for all businesses)
                const officerPanels = document.querySelectorAll('.data_pannel');
                for (let panel of officerPanels) {
                    const header = panel.querySelector('td.inner_databg');
                    if (header && header.textContent.includes('Officer Information')) {
                        // Find the officer table (grid_principalList)
                        const officerTable = panel.querySelector('#grid_principalList');
                        if (officerTable) {
                            const officers = [];
                            const rows = officerTable.querySelectorAll('tbody tr');
                            
                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 3) {
                                    const name = cells[0].textContent.trim();
                                    const title = cells[1].textContent.trim();
                                    const address = cells[2].textContent.trim();
                                    
                                    officers.push({
                                        name: name,
                                        title: title,
                                        address: address
                                    });
                                }
                            });
                            
                            if (officers.length > 0) {
                                // Store as JSON string (can be parsed later)
                                data['Officers'] = JSON.stringify(officers);
                                
                                // Store as formatted string (more readable in Excel)
                                const formattedOfficers = officers.map(o => `${o.name} (${o.title})`).join('; ');
                                data['Officers_Formatted'] = formattedOfficers;
                                data['Officer_Count'] = officers.length;
                            }
                        }
                        break;
                    }
                }
                
                return data;
            }
        """)
        
        # Verify we're on the correct page by checking control number
        page_control_number = await page.evaluate("""
            () => {
                // Find the Business Information table
                const tables = document.querySelectorAll('table[cellpadding="4"]');
                for (let table of tables) {
                    const header = table.querySelector('td.inner_databg');
                    if (header && header.textContent.includes('Business Information')) {
                        const rows = table.querySelectorAll('tr');
                        for (let row of rows) {
                            const cells = row.querySelectorAll('td');
                            for (let i = 0; i < cells.length; i++) {
                                const cellText = cells[i].textContent.trim();
                                if (cellText === 'Control Number:' || cellText.includes('Control Number')) {
                                    // Get the next cell which should contain the control number
                                    if (i + 1 < cells.length) {
                                        const valueCell = cells[i + 1];
                                        const strong = valueCell.querySelector('strong');
                                        if (strong) {
                                            return strong.textContent.trim();
                                        }
                                        return valueCell.textContent.trim();
                                    }
                                }
                            }
                        }
                    }
                }
                return '';
            }
        """)
        
        if page_control_number:
            if page_control_number != control_number:
                logger.warning(f"⚠️ Control number mismatch: expected {control_number}, got {page_control_number}")
            else:
                logger.debug(f"✅ Control number verified: {control_number}")
        else:
            logger.debug(f"⚠️ Could not extract control number from page for verification")
        
        logger.debug(f"✅ Extracted detail data for control number: {control_number}")
        return detail_data
        
    except Exception as e:
        logger.error(f"Error extracting detail page data: {str(e)}")
        return {}


async def extract_table_data(page: Page) -> List[Dict[str, str]]:
    """
    Extract business data from the results table on current page
    
    Returns:
        List of dictionaries containing business information
    """
    try:
        # Check for Cloudflare challenge before extracting data
        await check_and_solve_cloudflare(page, page.context)
        
        # Wait for table to be present
        await page.wait_for_selector("#grid_businessList", timeout=10000)
        
        # Extract table data using JavaScript
        table_data = await page.evaluate("""
            () => {
                const table = document.querySelector('#grid_businessList');
                if (!table) return [];
                
                const rows = table.querySelectorAll('tbody tr');
                const data = [];
                
                rows.forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 6) {
                        // Extract business name and link
                        const nameCell = cells[0];
                        const nameLink = nameCell.querySelector('a');
                        const businessName = nameLink ? nameLink.textContent.trim() : nameCell.textContent.trim();
                        const businessLink = nameLink ? nameLink.href : '';
                        
                        // Extract other fields
                        const controlNumber = cells[1].textContent.trim();
                        const businessType = cells[2].textContent.trim();
                        const principalAddress = cells[3].textContent.trim();
                        const registeredAgent = cells[4].textContent.trim();
                        const status = cells[5].textContent.trim();
                        
                        data.push({
                            'Business Name': businessName,
                            'Business Link': businessLink,
                            'Control Number': controlNumber,
                            'Business Type': businessType,
                            'Principal Office Address': principalAddress,
                            'Registered / Designated Agent Name': registeredAgent,
                            'Status': status
                        });
                    }
                });
                
                return data;
            }
        """)
        
        logger.info(f"✅ Extracted {len(table_data)} records from current page")
        return table_data
        
    except Exception as e:
        logger.error(f"Error extracting table data: {str(e)}")
        return []


async def get_total_pages(page: Page) -> int:
    """
    Get total number of pages from pagination info
    
    Returns:
        Total number of pages
    """
    try:
        total_pages = await page.evaluate("""
            () => {
                const hiddenInput = document.querySelector('#hdnTotalPgCount');
                if (hiddenInput) {
                    return parseInt(hiddenInput.value) || 1;
                }
                // Fallback: try to parse from pageinfo text
                const pageInfo = document.querySelector('.pageinfo');
                if (pageInfo) {
                    const text = pageInfo.textContent || '';
                    const match = text.match(/Page \d+ of (\d+)/);
                    if (match) {
                        return parseInt(match[1]) || 1;
                    }
                }
                return 1;
            }
        """)
        
        logger.info(f"📄 Total pages found: {total_pages}")
        return total_pages
        
    except Exception as e:
        logger.warning(f"Could not determine total pages: {str(e)}")
        return 1


async def go_to_page(page: Page, page_number: int) -> bool:
    """
    Navigate to a specific page number using JavaScript pagination
    
    Args:
        page: Playwright page object
        page_number: Page number to navigate to (1-based)
        
    Returns:
        True if successfully navigated, False otherwise
    """
    try:
        # Wait for pagination to be ready
        await page.wait_for_selector("#pagination-digg", timeout=5000)
        
        # Get current page before navigation
        current_page_before = await page.evaluate("""
            () => {
                const activePage = document.querySelector('#pagination-digg .activeGrid');
                if (activePage) {
                    return parseInt(activePage.textContent.trim()) || 1;
                }
                // Fallback: parse from pageinfo
                const pageInfo = document.querySelector('.pageinfo');
                if (pageInfo) {
                    const text = pageInfo.textContent || '';
                    const match = text.match(/Page (\d+) of \d+/);
                    if (match) {
                        return parseInt(match[1]);
                    }
                }
                return 1;
            }
        """)
        
        # If already on the target page, return success
        if current_page_before == page_number:
            logger.info(f"Already on page {page_number}")
            return True
        
        # Simulate human behavior: scroll to pagination
        pagination_element = page.locator("#pagination-digg")
        await pagination_element.scroll_into_view_if_needed()
        await human_delay(0.5, 1.0)
        
        # Always use JavaScript pagination directly (more reliable than clicking links)
        logger.info(f"Navigating to page {page_number} using JavaScript...")
        success = await page.evaluate(f"""
            (pageNum) => {{
                try {{
                    if (typeof businessGrid !== 'undefined' && typeof businessGrid.paging === 'function') {{
                        businessGrid.paging(pageNum);
                        return true;
                    }}
                    return false;
                }} catch(e) {{
                    console.error('Error calling pagination:', e);
                    return false;
                }}
            }}
        """, page_number)
        
        if not success:
            logger.warning(f"Could not call pagination function for page {page_number}")
            return False
        
        # Wait for the table to update - wait for network requests to complete
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        # Check for Cloudflare challenge after navigation
        if not await check_and_solve_cloudflare(page, page.context):
            logger.warning(f"⚠️ Cloudflare challenge detected on page {page_number}, attempting to solve...")
        
        # Wait for pagination to update - poll until activeGrid changes
        max_wait_time = 10  # seconds
        wait_interval = 0.5  # seconds
        waited = 0
        
        while waited < max_wait_time:
            await human_delay(wait_interval, wait_interval)
            waited += wait_interval
            
            current_page = await page.evaluate("""
                () => {
                    // Method 1: Check activeGrid
                    const activePage = document.querySelector('#pagination-digg .activeGrid');
                    if (activePage) {
                        const pageNum = parseInt(activePage.textContent.trim());
                        if (pageNum) return pageNum;
                    }
                    
                    // Method 2: Parse from pageinfo text (more reliable)
                    const pageInfo = document.querySelector('.pageinfo');
                    if (pageInfo) {
                        const text = pageInfo.textContent || '';
                        const match = text.match(/Page (\d+) of \d+/);
                        if (match) {
                            return parseInt(match[1]);
                        }
                    }
                    
                    return 0;
                }
            """)
            
            if current_page == page_number:
                logger.info(f"✅ Navigated to page {page_number}")
                # Additional wait for table to fully render
                await human_delay(1.0, 2.0)
                return True
            
            # If page changed but not to target, wait a bit more
            if current_page != current_page_before:
                await human_delay(0.5, 1.0)
                continue
        
        # Final check
        final_page = await page.evaluate("""
            () => {
                const pageInfo = document.querySelector('.pageinfo');
                if (pageInfo) {
                    const text = pageInfo.textContent || '';
                    const match = text.match(/Page (\d+) of \d+/);
                    if (match) {
                        return parseInt(match[1]);
                    }
                }
                const activePage = document.querySelector('#pagination-digg .activeGrid');
                if (activePage) {
                    return parseInt(activePage.textContent.trim()) || 0;
                }
                return 0;
            }
        """)
        
        if final_page == page_number:
            logger.info(f"✅ Navigated to page {page_number} (verified)")
            return True
        else:
            logger.warning(f"⚠️ Expected page {page_number}, but on page {final_page}")
            return False
        
    except Exception as e:
        logger.error(f"Error navigating to page {page_number}: {str(e)}")
        return False


async def scrape_all_pages(page: Page, max_pages: Optional[int] = None, max_records: Optional[int] = None) -> List[Dict[str, str]]:
    """
    Scrape all pages of search results
    
    Args:
        page: Playwright page object with search results
        max_pages: Optional limit on number of pages to scrape (for testing)
        max_records: Optional limit on number of records to scrape (stops when reached)
        
    Returns:
        List of all business records from all pages
    """
    all_data = []
    
    # Get total pages
    total_pages = await get_total_pages(page)
    
    if max_pages:
        total_pages = min(total_pages, max_pages)
        logger.info(f"⚠️ Limiting to {max_pages} pages for testing")
    
    if max_records:
        logger.info(f"⚠️ Will stop after collecting {max_records} records")
    
    logger.info(f"📊 Starting to scrape {total_pages} pages...")
    
    for page_num in range(1, total_pages + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"📄 Scraping page {page_num} of {total_pages}")
        logger.info(f"{'='*60}")
        
        # Simulate human reading the page
        await simulate_human_behavior(page)
        await human_delay(1.0, 2.5)  # Human reading time
                # Extract data from current page
        page_data = await extract_table_data(page)
        
        if page_data:
            all_data.extend(page_data)
            logger.info(f"✅ Added {len(page_data)} records (Total: {len(all_data)})")
            
            # Check if we've reached max_records limit
            if max_records and len(all_data) >= max_records:
                logger.info(f"⚠️ Reached limit of {max_records} records. Stopping.")
                all_data = all_data[:max_records]  # Trim to exact limit
                break
        else:
            logger.warning(f"⚠️ No data found on page {page_num}")
        
        # Go to next page if not on last page and haven't reached limit
        if page_num < total_pages and (not max_records or len(all_data) < max_records):
            # Human pause before clicking next (like reviewing the page)
            await human_delay(1.0, 3.0)
            
            next_page_num = page_num + 1
            success = await go_to_page(page, next_page_num)
            if not success:
                logger.warning(f"Could not navigate to page {next_page_num}. Stopping at page {page_num}")
                break
            
            # Human-like wait after navigation
            await human_delay(1.5, 3.0)
            
            # Occasional longer pause (like taking a break)
            if random.random() < 0.05:  # 5% chance
                break_time = random.uniform(3.0, 8.0)
                logger.info(f"⏸️  Taking a short break... ({break_time:.1f}s)")
                await asyncio.sleep(break_time)
    
    logger.info(f"\n✅ Scraping complete! Total records collected: {len(all_data)}")
    return all_data


async def extract_detail_pages_only(
    page: Page, 
    df: pd.DataFrame, 
    save_progress_every: int = 100, 
    output_file: Optional[str] = None
) -> pd.DataFrame:
    """
    Extract detail page data ONLY (no Google enrichment)
    This function completes ALL detail page scraping before moving to next step
    
    Args:
        page: Playwright page object (same browser session)
        df: DataFrame with existing business data (must have 'Business Link' and 'Control Number' columns)
        save_progress_every: Save progress every N records
        output_file: Path to Excel file for incremental saves
        
    Returns:
        DataFrame with detail page data (no Google enrichment)
    """
    if df.empty:
        logger.warning("No data to enrich")
        return df
    
    # Add new columns if they don't exist (detail page fields only, no Google fields)
    new_columns = [
        # Georgia SOS Website NAICS data
        'Georgia_SOS_NAICS',  # NAICS from Georgia SOS website (may be text description)
        'Georgia_SOS_NAICS_Sub',  # NAICS Sub Code from website
        'NAICS_Source',  # Source: "Georgia SOS Website" or "Gemini AI"
        # Gemini AI enriched NAICS (uppercase)
        'NAICS Code',  # 6-digit numeric code from Gemini AI
        'NAICS Title',  # NAICS Title from Gemini AI
        'NAICS Confidence',  # Confidence score from Gemini
        'NAICS Classification Method',  # Method used: Gemini AI or keyword
        # Other fields
        'Date of Formation',
        'State of Formation',
        'Last Annual Registration Year',
        'Dissolved Date',
        'Registered Agent Physical Address',
        'Registered Agent County',
        'Officers',  # JSON string of officers array
        'Officers_Formatted',  # Human-readable format
        'Officer_Count',  # Number of officers
    ]
    
    for col in new_columns:
        if col not in df.columns:
            df[col] = ''
    
    total_records = len(df)
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting DETAIL PAGE extraction for {total_records} businesses")
    logger.info(f"   (Google enrichment will be done separately)")
    logger.info(f"{'='*60}")
    
    processed = 0
    failed = 0
    
    # Store original URL to navigate back to results if needed
    original_url = page.url
    
    for idx, row in df.iterrows():
        processed += 1
        
        business_link = row.get('Business Link', '')
        control_number = row.get('Control Number', '')
        business_name = row.get('Business Name', '')
        
        if not business_link:
            logger.warning(f"⚠️ Row {idx + 1}: No business link, skipping")
            continue
        
        # Check if link is relative or absolute
        if business_link.startswith('/'):
            business_link = f"https://ecorp.sos.ga.gov{business_link}"
        
        logger.info(f"\n📄 [{processed}/{total_records}] Extracting detail page: {business_name[:50]}...")
        logger.info(f"   Control Number: {control_number}")
        logger.info(f"   URL: {business_link}")
        
        try:
            # Human-like pause before navigating
            await human_delay(0.5, 1.5)
            
            # Navigate to detail page
            await page.goto(business_link, wait_until="domcontentloaded")
            
            # Check for Cloudflare challenge after navigation
            await check_and_solve_cloudflare(page, page.context)
            
            # Human-like wait for page to render (humans don't process instantly)
            await human_delay(1.0, 2.5)
            
            # Simulate reading the page
            await simulate_human_behavior(page)
            await human_delay(0.5, 1.5)
            
            # Extract detail page data
            detail_data = await extract_detail_page_data(page, control_number)
            
            if detail_data:
                # Map extracted NAICS data to DataFrame columns
                import re
                # If we have Georgia_SOS_NAICS field from website
                if 'Georgia_SOS_NAICS' in detail_data and detail_data['Georgia_SOS_NAICS']:
                    df.at[idx, 'Georgia_SOS_NAICS'] = detail_data['Georgia_SOS_NAICS']
                    df.at[idx, 'NAICS_Source'] = 'Georgia SOS Website'
                
                # Map Georgia_SOS_NAICS_Sub
                if 'Georgia_SOS_NAICS_Sub' in detail_data and detail_data['Georgia_SOS_NAICS_Sub']:
                    df.at[idx, 'Georgia_SOS_NAICS_Sub'] = detail_data['Georgia_SOS_NAICS_Sub']
                
                # Update DataFrame row with new data
                for key, value in detail_data.items():
                    if key in df.columns:
                        df.at[idx, key] = value
                
                logger.info(f"   ✅ Extracted {len(detail_data)} fields from detail page")
            else:
                logger.warning(f"   ⚠️ No data extracted from detail page")
                failed += 1
            
            # Save progress periodically
            if processed % save_progress_every == 0:
                if output_file:
                    df.to_excel(output_file, index=False, engine='openpyxl')
                    logger.info(f"   💾 Progress saved: {processed}/{total_records} processed")
            
            # Variable delay between requests (more human-like)
            base_delay = random.uniform(2.0, 4.0)  # 2-4 seconds base
            await asyncio.sleep(base_delay)
            
            # Occasional longer pause (10% chance - like human taking break)
            if random.random() < 0.1:
                break_time = random.uniform(5.0, 15.0)
                logger.info(f"   ⏸️  Taking a short break... ({break_time:.1f}s)")
                await asyncio.sleep(break_time)
            
            # Very occasional long pause (1% chance - like human getting distracted)
            elif random.random() < 0.01:
                long_break = random.uniform(20.0, 60.0)
                logger.info(f"   ⏸️  Taking a longer break... ({long_break:.1f}s)")
                await asyncio.sleep(long_break)
            
        except Exception as e:
            logger.error(f"   ❌ Error processing {business_link}: {str(e)}")
            failed += 1
            # Continue with next record
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ DETAIL PAGE extraction complete!")
    logger.info(f"   Total processed: {processed}/{total_records}")
    logger.info(f"   Successful: {processed - failed}")
    logger.info(f"   Failed: {failed}")
    logger.info(f"{'='*60}")
    
    return df


async def enrich_google_data_only(
    df: pd.DataFrame,
    google_driver: uc.Chrome,
    page: Optional[Page] = None,
    save_progress_every: int = 50,
    output_file: Optional[str] = None
) -> pd.DataFrame:
    """
    Enrich DataFrame with Google data ONLY (no detail page extraction)
    This function is called AFTER all detail pages have been scraped
    
    Args:
        df: DataFrame with business data (already has detail page data)
        google_driver: Selenium WebDriver (undetected Chrome) for Google searches
        page: Optional Playwright page for email extraction from websites
        save_progress_every: Save progress every N records
        output_file: Path to Excel file for incremental saves
        
    Returns:
        DataFrame enriched with Google contact information
    """
    if df.empty:
        logger.warning("No data to enrich with Google")
        return df
    
    # Add Google contact info columns if they don't exist
    google_columns = [
        'Website',
        'Website_Confidence',
        'Website_Source',
        'Website_Validation_Reason',
        'Email',
        'LinkedIn',
        'Facebook'
        # Google Business Profile columns removed - using DuckDuckGo instead
    ]
    
    for col in google_columns:
        if col not in df.columns:
            df[col] = ''
    
    total_records = len(df)
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting GOOGLE enrichment for {total_records} businesses")
    logger.info(f"{'='*60}")
    
    processed = 0
    failed = 0
    
    # Internal driver reference that we can rotate
    current_driver = google_driver
    
    for idx, row in df.iterrows():
        processed += 1
        
        business_name = row.get('Business Name', '') or row.get('Entity Name', '')
        
        if not business_name:
            logger.warning(f"⚠️ Row {idx + 1}: No business name, skipping")
            continue
        
        logger.info(f"\n🔍 [{processed}/{total_records}] Google enrichment: {business_name[:50]}...")
        
        try:
            # Extract city and state from Principal Office Address
            principal_address = row.get('Principal Office Address', '')
            city, state = extract_city_state_from_address(principal_address)
            
            # If we couldn't extract from address, try to get from existing row data
            if not city and 'City' in row and row.get('City'):
                city = row.get('City')
            if not state:
                state = 'GA'  # Default to Georgia
            
            # Enrich contact info via Google search (using Selenium driver)
            # Use local current_driver which might be rotated
            contact_info = await enrich_contact_info(
                business_name=business_name,
                page=page,  # Playwright page for email extraction
                city=city,
                state=state,
                google_driver=current_driver  # Selenium driver for Google searches
            )
            
            # SESSION ROTATION LOGIC
            # Rotate after every 3 searches to avoid CAPTCHAs
            if processed % 3 == 0:
                logger.info("🔄 Rotating browser session (3 searches reached)...")
                try:
                    current_driver.quit()
                    logger.debug("   Closed old driver")
                except Exception as e:
                    logger.debug(f"   Error closing driver: {e}")
                
                # Small human pause
                await asyncio.sleep(2)
                
                # Clear user data
                try:
                    shutil.rmtree('/tmp/chrome_user_data', ignore_errors=True)
                    logger.debug("   Cleared /tmp/chrome_user_data")
                except Exception as e:
                    logger.debug(f"   Error clearing user data: {e}")
                
                # Create NEW driver
                logger.info("   🚀 Launching fresh browser...")
                try:
                    current_driver = await asyncio.to_thread(create_undetected_driver, headless=False)
                    logger.info("   ✅ Fresh browser ready")
                except Exception as e:
                    logger.error(f"   ❌ Failed to create new driver: {e}")
                    # Try one more time? Or just fail?
                    # Let's try to proceed, but if it failed, next iteration will fail.
                    # We should probably raise or break, but let's let the next try/catch handle it
                    pass
            
            # Update DataFrame with contact information
            for key, value in contact_info.items():
                if key in df.columns:
                    df.at[idx, key] = value if value else ''
            
            # Log what was found
            found_contact_items = [k for k, v in contact_info.items() if v and k not in ['Website_Confidence', 'Website_Source', 'Website_Validation_Reason']]
            if found_contact_items:
                logger.info(f"   ✅ Contact info enriched: {', '.join(found_contact_items)}")
            else:
                logger.debug(f"   ⚠️ No contact info found")
            
            # Save progress periodically
            if processed % save_progress_every == 0:
                if output_file:
                    df.to_excel(output_file, index=False, engine='openpyxl')
                    logger.info(f"   💾 Progress saved: {processed}/{total_records} processed")
            
            # Additional delay between Google searches (rate limiting is handled in Selenium functions)
            # But add extra delay here for safety
            base_delay = random.uniform(2.0, 4.0)  # Additional 2-4 seconds between records
            await asyncio.sleep(base_delay)
            
        except Exception as e:
            logger.warning(f"   ⚠️ Error enriching Google data for {business_name}: {str(e)}")
            failed += 1
            # Continue with next record
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ GOOGLE enrichment complete!")
    logger.info(f"   Total processed: {processed}/{total_records}")
    logger.info(f"   Successful: {processed - failed}")
    logger.info(f"   Failed: {failed}")
    logger.info(f"{'='*60}")
    
    # Close the final driver instance
    try:
        if current_driver:
            current_driver.quit()
            logger.info("✅ Closed final Selenium driver")
    except:
        pass

    return df


async def enrich_business_data(
    page: Page, 
    df: pd.DataFrame, 
    save_progress_every: int = 100, 
    output_file: Optional[str] = None,
    enrich_contact_info: bool = True,
    google_page: Optional[Page] = None
) -> pd.DataFrame:
    """
    Enrich existing business data by visiting each detail page
    
    Args:
        page: Playwright page object (same browser session)
        df: DataFrame with existing business data (must have 'Business Link' and 'Control Number' columns)
        save_progress_every: Save progress every N records
        output_file: Path to Excel file for incremental saves
        enrich_contact_info: Whether to enrich with contact info via Google search (default: True)
        
    Returns:
        Enriched DataFrame with additional detail page data
    """
    if df.empty:
        logger.warning("No data to enrich")
        return df
    
    # Add new columns if they don't exist
    new_columns = [
        # Georgia SOS Website NAICS data
        'Georgia_SOS_NAICS',  # NAICS from Georgia SOS website (may be text description)
        'Georgia_SOS_NAICS_Sub',  # NAICS Sub Code from website
        'NAICS_Source',  # Source: "Georgia SOS Website" or "Gemini AI"
        # Gemini AI enriched NAICS (uppercase)
        'NAICS Code',  # 6-digit numeric code from Gemini AI
        'NAICS Title',  # NAICS Title from Gemini AI
        'NAICS Confidence',  # Confidence score from Gemini
        'NAICS Classification Method',  # Method used: Gemini AI or keyword
        # Other fields
        'Date of Formation',
        'State of Formation',
        'Last Annual Registration Year',
        'Dissolved Date',
        'Registered Agent Physical Address',
        'Registered Agent County',
        'Officers',  # JSON string of officers array
        'Officers_Formatted',  # Human-readable format
        'Officer_Count',  # Number of officers
        # Contact information from DuckDuckGo search
        'Website',
        'Website_Confidence',
        'Website_Source',
        'Website_Validation_Reason',
        'Email',
        'LinkedIn',
        'Facebook'
        # Google Business Profile columns removed - using DuckDuckGo instead
    ]
    
    for col in new_columns:
        if col not in df.columns:
            df[col] = ''
    
    total_records = len(df)
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting data enrichment for {total_records} businesses")
    logger.info(f"{'='*60}")
    
    processed = 0
    failed = 0
    
    # Store original URL to navigate back to results if needed
    original_url = page.url
    
    for idx, row in df.iterrows():
        processed += 1
        
        business_link = row.get('Business Link', '')
        control_number = row.get('Control Number', '')
        business_name = row.get('Business Name', '')
        
        if not business_link:
            logger.warning(f"⚠️ Row {idx + 1}: No business link, skipping")
            continue
        
        # Check if link is relative or absolute
        if business_link.startswith('/'):
            business_link = f"https://ecorp.sos.ga.gov{business_link}"
        
        logger.info(f"\n📄 [{processed}/{total_records}] Processing: {business_name[:50]}...")
        logger.info(f"   Control Number: {control_number}")
        logger.info(f"   URL: {business_link}")
        
        try:
            # Human-like pause before navigating
            await human_delay(0.5, 1.5)
            
            # Navigate to detail page
            await page.goto(business_link, wait_until="domcontentloaded")
            
            # Check for Cloudflare challenge after navigation
            await check_and_solve_cloudflare(page, page.context)
            
            # Human-like wait for page to render (humans don't process instantly)
            await human_delay(1.0, 2.5)
            
            # Simulate reading the page
            await simulate_human_behavior(page)
            await human_delay(0.5, 1.5)
            
            # Extract detail page data
            detail_data = await extract_detail_page_data(page, control_number)
            
            if detail_data:
                # Map extracted NAICS data to DataFrame columns
                import re
                # If we have Georgia_SOS_NAICS field from website
                if 'Georgia_SOS_NAICS' in detail_data and detail_data['Georgia_SOS_NAICS']:
                    df.at[idx, 'Georgia_SOS_NAICS'] = detail_data['Georgia_SOS_NAICS']
                    df.at[idx, 'NAICS_Source'] = 'Georgia SOS Website'
                
                # Map Georgia_SOS_NAICS_Sub
                if 'Georgia_SOS_NAICS_Sub' in detail_data and detail_data['Georgia_SOS_NAICS_Sub']:
                    df.at[idx, 'Georgia_SOS_NAICS_Sub'] = detail_data['Georgia_SOS_NAICS_Sub']
                
                # Update DataFrame row with new data
                for key, value in detail_data.items():
                    if key in df.columns:
                        df.at[idx, key] = value
                
                logger.info(f"   ✅ Extracted {len(detail_data)} fields")
            else:
                logger.warning(f"   ⚠️ No data extracted from detail page")
                failed += 1
            
            # Step 2: Enrich with contact information via Google search (if enabled)
            if enrich_contact_info:
                try:
                    # Extract city and state from Principal Office Address
                    principal_address = row.get('Principal Office Address', '')
                    city, state = extract_city_state_from_address(principal_address)
                    
                    # If we couldn't extract from address, try to get from existing row data
                    if not city and 'City' in row and row.get('City'):
                        city = row.get('City')
                    if not state:
                        state = 'GA'  # Default to Georgia
                    
                    # Enrich contact info via Google search
                    contact_info = await enrich_contact_info(
                        business_name=business_name,
                        page=page,
                        city=city,
                        state=state,
                        google_page=google_page  # Use separate Google page if provided
                    )
                    
                    # Update DataFrame with contact information
                    for key, value in contact_info.items():
                        if key in df.columns:
                            df.at[idx, key] = value if value else ''
                    
                    # Log what was found
                    found_contact_items = [k for k, v in contact_info.items() if v]
                    if found_contact_items:
                        logger.info(f"   ✅ Contact info enriched: {', '.join(found_contact_items)}")
                    else:
                        logger.debug(f"   ⚠️ No contact info found")
                        
                except Exception as e:
                    logger.warning(f"   ⚠️ Error enriching contact info: {str(e)}")
                    # Continue - don't mark as failed, contact info is optional
            
            # Save progress periodically
            if processed % save_progress_every == 0:
                if output_file:
                    df.to_excel(output_file, index=False, engine='openpyxl')
                    logger.info(f"   💾 Progress saved: {processed}/{total_records} processed")
            
            # Variable delay between requests (more human-like)
            base_delay = random.uniform(2.0, 4.0)  # 2-4 seconds base
            await asyncio.sleep(base_delay)
            
            # Occasional longer pause (10% chance - like human taking break)
            if random.random() < 0.1:
                break_time = random.uniform(5.0, 15.0)
                logger.info(f"   ⏸️  Taking a short break... ({break_time:.1f}s)")
                await asyncio.sleep(break_time)
            
            # Very occasional long pause (1% chance - like human getting distracted)
            elif random.random() < 0.01:
                long_break = random.uniform(20.0, 60.0)
                logger.info(f"   ⏸️  Taking a longer break... ({long_break:.1f}s)")
                await asyncio.sleep(long_break)
            
        except Exception as e:
            logger.error(f"   ❌ Error processing {business_link}: {str(e)}")
            failed += 1
            # Continue with next record
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Enrichment complete!")
    logger.info(f"   Total processed: {processed}/{total_records}")
    logger.info(f"   Successful: {processed - failed}")
    logger.info(f"   Failed: {failed}")
    logger.info(f"{'='*60}")
    
    return df


def save_to_excel(data: List[Dict[str, str]], filename: Optional[str] = None) -> str:
    """
    Save scraped data to Excel file
    
    Args:
        data: List of dictionaries containing business data
        filename: Optional custom filename (default: auto-generated with timestamp)
        
    Returns:
        Path to saved Excel file
    """
    if not data:
        logger.warning("No data to save to Excel")
        return ""
    
    # Generate filename if not provided
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"georgia_sos_business_data_{timestamp}.xlsx"
    
    # Ensure .xlsx extension
    if not filename.endswith('.xlsx'):
        filename += '.xlsx'
    
    # Create output directory if needed
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    filepath = output_dir / filename
    
    # Convert to DataFrame and save
    df = pd.DataFrame(data)
    df.to_excel(filepath, index=False, engine='openpyxl')
    
    logger.info(f"💾 Data saved to Excel: {filepath}")
    logger.info(f"   Total records: {len(data)}")
    logger.info(f"   Columns: {', '.join(df.columns)}")
    
    return str(filepath)


async def main(excel_file_path: Optional[str] = None, detail_only: bool = False):
    """
    Main function to scrape business data
    
    Args:
        excel_file_path: Optional path to existing Excel file (for detail-only mode)
        detail_only: If True, only run detail page enrichment (requires excel_file_path)
    """
    # Set up logging to file
    log_path = setup_logging()
    
    # Verify 2captcha API key is loaded
    import os
    twocaptcha_key = os.getenv('TWOCAPTCHA_API_KEY')
    if twocaptcha_key:
        logger.info(f"✅ 2captcha API key loaded: {twocaptcha_key[:10]}...")
    else:
        logger.warning("⚠️ TWOCAPTCHA_API_KEY not found in environment variables!")
        logger.warning("⚠️ Set it in .env file or export as environment variable")
        logger.warning("⚠️ Cloudflare challenges will not be solved without 2captcha API key")
    
    search_term = "landscap"
    
    try:
        if detail_only and excel_file_path:
            # Detail-only mode: Load existing Excel and enrich
            logger.info(f"📂 Loading existing data from: {excel_file_path}")
            
            if not Path(excel_file_path).exists():
                logger.error(f"❌ File not found: {excel_file_path}")
                return
            
            # Load existing data
            df = pd.read_excel(excel_file_path, engine='openpyxl')
            logger.info(f"✅ Loaded {len(df)} records from Excel file")
            
            # Get bypassed page (needed for navigation)
            target_url = "https://ecorp.sos.ga.gov/BusinessSearch"
            logger.info("🔐 Bypassing Cloudflare challenge...")
            playwright, browser, context, page = await get_bypassed_page(target_url, headless=False)
            
            logger.info("\n" + "="*60)
            logger.info("🔍 Starting data enrichment from detail pages...")
            logger.info("="*60)
            
            # Enrich with detail page data
            enriched_df = await enrich_business_data(
                page, 
                df, 
                save_progress_every=50,  # Save every 50 records
                output_file=excel_file_path  # Update same file incrementally
            )
            
            # Enrich missing NAICS codes using Gemini AI-enhanced classification
            logger.info("\n" + "="*60)
            logger.info("🏷️  Enriching missing NAICS codes using Gemini AI-enhanced classification...")
            logger.info("="*60)
            enriched_df = enrich_naics_codes(
                enriched_df, 
                excel_file_path="2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
                use_ai=True,  # Enable Gemini AI
                gemini_model="gemini-2.5-flash",  
                min_confidence=0.50,
                api_delay=1.5,  # 1.5 seconds delay between API calls (rate limiting)
                save_progress_every=25,  # Save progress every 25 classifications
                output_file_path=excel_file_path  # Save progress to the same file
            )
            
            # Final save
            enriched_df.to_excel(excel_file_path, index=False, engine='openpyxl')
            logger.info(f"\n✅ Final enriched data saved to: {excel_file_path}")
            logger.info(f"   Total records: {len(enriched_df)}")
            logger.info(f"   Columns: {len(enriched_df.columns)}")
            
            # Keep browser open for inspection
            input("\nPress Enter to close browser...")
            
            # Close browser
            await browser.close()
            
        else:
            # Full scraping mode
            logger.info(f"🚀 Starting business search for: '{search_term}'")
            
            # Step 1: Search for businesses
            page = await search_business(search_term)
            
            logger.info("✅ Search completed successfully!")
            logger.info(f"Current URL: {page.url}")
            
            logger.info("\n" + "="*60)
            logger.info("📊 Starting data extraction from all pages...")
            logger.info("="*60)
            
            all_data = await scrape_all_pages(page, max_pages=10) 
            
            if all_data:
                excel_file = save_to_excel(all_data)
                logger.info(f"\n✅ Initial data saved to: {excel_file}")
                
                logger.info("\n" + "="*60)
                logger.info("🔍 Starting data enrichment from detail pages...")
                logger.info("="*60)
                
                # Convert to DataFrame
                df = pd.DataFrame(all_data)
                
                # Enrich with detail page data
                enriched_df = await enrich_business_data(
                    page, 
                    df, 
                    save_progress_every=50,  # Save every 50 records
                    output_file=excel_file  # Update same file incrementally
                )
                
                logger.info("\n" + "="*60)
                logger.info("🏷️  Enriching missing NAICS codes using Gemini AI-enhanced classification...")
                logger.info("="*60)
                enriched_df = enrich_naics_codes(
                    enriched_df, 
                    excel_file_path="2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
                    use_ai=True,
                    gemini_model="gemini-2.5-flash",  
                    min_confidence=0.50,
                    api_delay=1.5,  # 1.5 seconds delay between API calls (rate limiting)
                    save_progress_every=25,  # Save progress every 25 classifications
                    output_file_path=excel_file  # Save progress to the same file
                )
                
                # Final save
                enriched_df.to_excel(excel_file, index=False, engine='openpyxl')
                logger.info(f"\n✅ Final enriched data saved to: {excel_file}")
                logger.info(f"   Total records: {len(enriched_df)}")
                logger.info(f"   Columns: {len(enriched_df.columns)}")
            else:
                logger.warning("⚠️ No data collected!")
            
            # Keep browser open for inspection
            input("\nPress Enter to close browser...")
            
            # Close browser
            await page.context.browser.close()
        
    except Exception as e:
        logger.error(f"❌ Error during scraping: {str(e)}")
        logger.exception(e)
        raise


if __name__ == "__main__":
    import sys
    
    # Set up logging first
    setup_logging()
    
    # Check command line arguments
    if len(sys.argv) > 1:
        excel_file = sys.argv[1]
        
        # Check for enrichment mode flags
        if len(sys.argv) > 2:
            if sys.argv[2] == "--google-only":
                # Google-only enrichment mode (no Cloudflare, no detail pages)
                # Check for --headless flag
                headless_mode = "--headless" in sys.argv or "-h" in sys.argv
                logger.info(f"🌐 Running Google-only enrichment mode (headless={headless_mode})...")
                asyncio.run(enrich_google_only(excel_file_path=excel_file, headless=headless_mode))
            elif sys.argv[2] == "--apollo":
                # Apollo enrichment mode
                from apollo_enricher import enrich_excel_with_apollo
                logger.info(f"🔍 Running Apollo enrichment mode...")
                asyncio.run(enrich_excel_with_apollo(
                    excel_file_path=excel_file,
                    max_executives_per_company=5,
                    only_companies_with_website=True,
                    min_website_confidence=0.5
                ))
            else:
                # Detail-only mode: Load existing Excel and enrich (includes Cloudflare bypass)
                asyncio.run(main(excel_file_path=excel_file, detail_only=True))
        else:
            # Detail-only mode: Load existing Excel and enrich (includes Cloudflare bypass)
            asyncio.run(main(excel_file_path=excel_file, detail_only=True))
    else:
        # Run full scraping
        asyncio.run(main())

