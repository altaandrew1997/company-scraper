"""
DuckDuckGo Search Scraper using Selenium + undetected-chromedriver
Switched from Google to DuckDuckGo to avoid CAPTCHAs
Original Google implementation replaced - function names kept for backwards compatibility
"""

import time
import random
import re
from typing import Optional, Dict, List
from loguru import logger
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from urllib.parse import quote_plus


def human_delay(min_seconds: float = 2.0, max_seconds: float = 5.0):
    """Random delay to simulate human behavior"""
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


def simulate_human_interaction(driver: uc.Chrome):
    """Simulate human-like behavior: scrolling, mouse movements"""
    try:
        # Random scroll
        scroll_amount = random.randint(300, 700)
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(0.5, 1.5))
        
        # Random mouse movement
        action = ActionChains(driver)
        # Move to a random element or offset if possible, or just reset
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            x_offset = random.randint(-100, 100)
            y_offset = random.randint(-100, 100)
            action.move_to_element_with_offset(body, x_offset, y_offset).perform()
        except:
            pass
            
        time.sleep(random.uniform(0.5, 1.0))
        
        # Scroll back up a bit sometimes
        if random.random() > 0.7:
             driver.execute_script(f"window.scrollBy(0, -{random.randint(100, 300)});")
             time.sleep(random.uniform(0.5, 1.0))
             
    except Exception as e:
        logger.debug(f"Human interaction simulation failed: {e}")

def check_for_captcha(driver: uc.Chrome) -> bool:
    """Check if Google CAPTCHA is present and pause for manual resolution if needed (or just log it)"""
    try:
        # Common Google CAPTCHA indicators
        captcha_elements = driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="recaptcha"], #captcha-form, .g-recaptcha')
        if captcha_elements or "sorry" in driver.current_url:
            logger.warning("⚠️ CAPTCHA detected! Pausing for 60 seconds to allow manual resolution or cooldown...")
            # If running headlessly, this pause is just a cooldown. If visible, user can solve it.
            # Ideally, we would detect if we are headless. 
            # For now, let's just sleep and hope the user solves it or the IP block clears (unlikely for block).
            time.sleep(5) 
            return True
        return False
    except:
        return False


def validate_business_match(business_name: str, url: str, title: str = "", min_match_score: int = 2) -> tuple:
    """
    Validate if a search result matches the business name.
    
    Args:
        business_name: Original business name to match
        url: URL of the search result
        title: Title of the search result
        min_match_score: Minimum score required (default: 2 = at least 2 words or strong match)
        
    Returns:
        Tuple of (is_valid, match_score)
    """
    # Clean and normalize business name
    clean_name = business_name.upper()
    for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
        clean_name = clean_name.replace(suffix, '')
    clean_name = clean_name.strip().strip(',').strip()
    
    # Get significant words (2+ chars, not common/industry words)
    # Industry words are too common to be unique identifiers
    stop_words = {
        # Common words
        'THE', 'AND', 'FOR', 'WITH', 'FROM', 'SERVICES', 'SERVICE', 'COMPANY', 'GROUP',
        # Industry-specific words (common in many business names - not unique)
        'LANDSCAPING', 'LANDSCAPE', 'LAWN', 'CARE', 'TREE', 'GARDEN', 'GARDENING',
        'CONSTRUCTION', 'BUILDING', 'BUILDERS', 'PLUMBING', 'ELECTRIC', 'ELECTRICAL',
        'ROOFING', 'PAINTING', 'CLEANING', 'MAINTENANCE', 'REPAIR', 'SOLUTIONS',
        'CONSULTING', 'MANAGEMENT', 'PROPERTIES', 'REALTY', 'REAL', 'ESTATE'
    }
    words = [w for w in clean_name.split() if len(w) >= 2 and w not in stop_words]
    
    if not words:
        # If no significant words, allow any result
        return True, 0
    
    url_lower = url.lower()
    title_lower = title.lower() if title else ""
    combined = url_lower + " " + title_lower
    
    match_score = 0
    matched_words = []
    
    for word in words:
        word_lower = word.lower()
        # Check if word appears in URL domain or title
        # URL domain matching is stronger
        if word_lower in url_lower:
            match_score += 2
            matched_words.append(word)
        elif word_lower in title_lower:
            match_score += 1
            matched_words.append(word)
    
    # Bonus for consecutive words matching (e.g., "FP Landscaping" in "fplandscaping.com")
    name_condensed = ''.join(words).lower()
    if len(name_condensed) >= 5 and name_condensed in url_lower.replace('-', '').replace('_', ''):
        match_score += 3
    
    # Check for initials match (e.g., "FP" for "First Priority")
    if len(words) >= 2:
        initials = ''.join(w[0] for w in words).lower()
        if len(initials) >= 2 and initials in url_lower:
            match_score += 2
    
    is_valid = match_score >= min_match_score
    
    if is_valid:
        logger.debug(f"   ✓ Match validated: score={match_score}, words={matched_words}")
    else:
        logger.debug(f"   ✗ Match rejected: score={match_score} < {min_match_score}, words={matched_words}")
    
    return is_valid, match_score


def validate_linkedin_match(business_name: str, url: str, title: str = "") -> bool:
    """
    Validate if a LinkedIn result matches the business.
    Requires minimum score of 2 (industry stop words already filtered).
    """
    is_valid, score = validate_business_match(business_name, url, title, min_match_score=2)
    return is_valid


def validate_facebook_match(business_name: str, url: str, title: str = "") -> bool:
    """
    Validate if a Facebook result matches the business.
    Requires minimum score of 2 (industry stop words already filtered).
    """
    is_valid, score = validate_business_match(business_name, url, title, min_match_score=2)
    return is_valid



def extract_duckduckgo_results_selenium(driver: uc.Chrome, max_results: int = 10) -> List[Dict[str, str]]:
    """
    Extract search results from DuckDuckGo search results page using JavaScript
    
    Args:
        driver: Selenium WebDriver
        max_results: Maximum number of results to extract
        
    Returns:
        List of result dictionaries with 'title', 'url', 'snippet', 'position'
    """
    try:
        # Use JavaScript execution to extract results from DuckDuckGo
        results = driver.execute_script("""
            var maxResults = arguments[0];
            var searchResults = [];
            var seen = new Set();
            
            // DuckDuckGo result selectors
            // Method 1: New DDG layout (data-testid="result")
            var resultContainers = Array.from(document.querySelectorAll('article[data-testid="result"]'));
            
            // Method 2: Fallback to older DDG layout
            if (resultContainers.length === 0) {
                resultContainers = Array.from(document.querySelectorAll('.result, .results_links_deep, .web-result'));
            }
            
            // Method 3: Another DDG layout variant
            if (resultContainers.length === 0) {
                resultContainers = Array.from(document.querySelectorAll('div[data-nrn="result"]'));
            }
            
            for (var i = 0; i < resultContainers.length; i++) {
                if (searchResults.length >= maxResults) break;
                
                try {
                    var container = resultContainers[i];
                    
                    // Find the main link - DDG uses h2 > a for result links
                    var link = container.querySelector('h2 a[href^="http"]') || 
                              container.querySelector('a[data-testid="result-title-a"]') ||
                              container.querySelector('a.result__a') ||
                              container.querySelector('a[href^="http"]');
                    
                    if (!link) continue;
                    
                    // Extract URL
                    var url = link.getAttribute('href');
                    if (!url) continue;
                    
                    // Skip DuckDuckGo internal pages
                    if (url.includes('duckduckgo.com')) {
                        continue;
                    }
                    
                    // Skip empty or invalid URLs
                    if (!url || url === '#' || url.startsWith('javascript:')) {
                        continue;
                    }
                    
                    // Create unique key
                    var key = url.toLowerCase();
                    if (seen.has(key)) continue;
                    seen.add(key);
                    
                    // Extract title
                    var title = '';
                    var titleEl = container.querySelector('h2') || 
                                  container.querySelector('a[data-testid="result-title-a"]') ||
                                  container.querySelector('.result__title') ||
                                  link;
                    if (titleEl && titleEl.textContent) {
                        title = titleEl.textContent.trim();
                    }
                    
                    // Extract snippet/description
                    var snippet = '';
                    var snippetEl = container.querySelector('[data-testid="result-snippet"]') ||
                                   container.querySelector('.E2eLOJr8HctVnDOTM8fs') ||
                                   container.querySelector('.result__snippet') ||
                                   container.querySelector('span[class*="snippet"]');
                    if (snippetEl && snippetEl.textContent) {
                        snippet = snippetEl.textContent.trim();
                    }
                    
                    // Only add if we have URL and title
                    if (url && title && url.startsWith('http')) {
                        searchResults.push({
                            title: title,
                            url: url,
                            snippet: snippet,
                            position: searchResults.length + 1
                        });
                    }
                } catch (e) {
                    // Skip this container if there's an error
                    continue;
                }
            }
            
            // Fallback: If no results found, try finding all links
            if (searchResults.length === 0) {
                var allLinks = Array.from(document.querySelectorAll('a[href^="http"]'));
                
                for (var i = 0; i < allLinks.length; i++) {
                    if (searchResults.length >= maxResults) break;
                    
                    var link = allLinks[i];
                    var url = link.getAttribute('href');
                    if (!url || url.includes('duckduckgo.com')) continue;
                    
                    var key = url.toLowerCase();
                    if (seen.has(key)) continue;
                    seen.add(key);
                    
                    var title = link.textContent.trim() || link.innerText.trim();
                    
                    if (url && title && url.startsWith('http') && title.length > 5) {
                        searchResults.push({
                            title: title,
                            url: url,
                            snippet: '',
                            position: searchResults.length + 1
                        });
                    }
                }
            }
            
            return searchResults.slice(0, maxResults);
        """, max_results)
        
        # Validate and clean results
        valid_results = []
        for result in results:
            if result.get('url') and result.get('url').startswith('http'):
                valid_results.append(result)
        
        return valid_results
        
    except Exception as e:
        logger.error(f"❌ Error extracting DuckDuckGo results: {str(e)}")
        return []


# Keep old function name as alias for backwards compatibility
def extract_google_results_selenium(driver: uc.Chrome, max_results: int = 10) -> List[Dict[str, str]]:
    """Alias for backwards compatibility - now uses DuckDuckGo"""
    return extract_duckduckgo_results_selenium(driver, max_results)


def _create_chrome_options(headless: bool = False) -> uc.ChromeOptions:
    """
    Create fresh ChromeOptions for undetected Chrome driver.
    
    Args:
        headless: Whether to run in headless mode
        
    Returns:
        Configured ChromeOptions
    """
    options = uc.ChromeOptions()
    
    if headless:
        options.add_argument('--headless=new')
    
    # Additional stealth options
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--start-maximized')
    
    # Add session persistence
    options.add_argument('--user-data-dir=/tmp/chrome_user_data')
    
    return options


def create_undetected_driver(headless: bool = False) -> uc.Chrome:
    """
    Create undetected Chrome driver for Google searches
    
    Args:
        headless: Whether to run in headless mode
        
    Returns:
        Configured undetected Chrome driver
    """
    # Strategy 1: Let undetected-chromedriver auto-detect (most reliable)
    try:
        logger.info("🚀 Creating driver with auto-detection...")
        options = _create_chrome_options(headless)
        driver = uc.Chrome(
            options=options,
            use_subprocess=True
        )
        driver.maximize_window()
        logger.debug("✅ Created undetected Chrome driver (auto-detect)")
        return driver
    except Exception as e:
        logger.warning(f"⚠️ Auto-detection failed: {str(e)}")
    
    # Strategy 2: Try with explicit version detection
    try:
        import subprocess
        # Try different Chrome executable names - prioritize Google Chrome (138) over Chromium (111)
        chrome_commands = [
            '/opt/google/chrome/google-chrome',  # Installed Google Chrome 138
            'google-chrome',
            'google-chrome-stable',
            'chromium-browser',  # Fallback to Chromium 111
            'chromium',
            'chrome'
        ]
        chrome_version = None
        
        for cmd in chrome_commands:
            try:
                result = subprocess.run(
                    [cmd, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    version_str = result.stdout.strip()
                    logger.debug(f"🔍 Found: {cmd} -> {version_str}")
                    # Extract major version number (e.g., "138" from "Google Chrome 138.0.7204.183")
                    match = re.search(r'(\d+)\.', version_str)
                    if match:
                        chrome_version = int(match.group(1))
                        logger.info(f"🔍 Using Chrome version: {chrome_version} from {cmd}")
                        break
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                continue
        
        if chrome_version:
            logger.info(f"🚀 Creating driver for Chrome version {chrome_version}...")
            options = _create_chrome_options(headless)  # Fresh options
            driver = uc.Chrome(
                options=options,
                version_main=chrome_version,
                use_subprocess=True
            )
            driver.maximize_window()
            logger.debug("✅ Created undetected Chrome driver")
            return driver
            
    except Exception as e:
        logger.warning(f"⚠️ Explicit version creation failed: {str(e)}")
    
    # Strategy 3: Last resort - minimal options
    try:
        logger.info("🔄 Final retry with minimal options...")
        options = _create_chrome_options(headless)  # Fresh options
        driver = uc.Chrome(options=options)
        driver.maximize_window()
        logger.debug("✅ Created undetected Chrome driver (minimal)")
        return driver
    except Exception as e:
        logger.error(f"❌ All attempts failed: {str(e)}")
        raise


def search_google_for_website(
    business_name: str,
    driver: uc.Chrome,
    city: Optional[str] = None,
    state: str = "GA"
) -> Optional[str]:
    """
    Search Google for business website using Selenium
    
    Args:
        business_name: Name of the business
        driver: Selenium WebDriver (undetected Chrome)
        city: Optional city name
        state: State name (default: GA)
        
    Returns:
        Website URL if found, None otherwise
    """
    try:
        # Clean business name - remove LLC, INC, CORP, etc.
        clean_name = business_name
        for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
            clean_name = clean_name.replace(suffix, '')
        clean_name = clean_name.strip().strip(',').strip()
        
        # Build search query
        if city:
            query = f"{clean_name} {city} {state} official website"
        else:
            query = f"{clean_name} {state} official website"
        
        # Navigate to DuckDuckGo (no CAPTCHA!)
        search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&t=h_&ia=web"
        driver.get(search_url)
        
        human_delay(2.0, 4.0)
        
        # Wait for DuckDuckGo results to load
        try:
            WebDriverWait(driver, 20).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, "article[data-testid='result']")) > 0 or 
                         len(d.find_elements(By.CSS_SELECTOR, ".result")) > 0 or
                         len(d.find_elements(By.CSS_SELECTOR, "a[href^='http']")) > 0
            )
        except TimeoutException:
            logger.debug("Search results didn't load in time")
            pass
        
        # Additional wait for results to fully render
        human_delay(1.5, 2.5)
        
        # Check if we have results before extracting
        has_results = driver.execute_script("""
            return document.querySelectorAll('article[data-testid="result"]').length > 0 || 
                   document.querySelectorAll('.result').length > 0 ||
                   document.querySelectorAll('a[href^="http"]').length > 5;
        """)
        
        if not has_results:
            logger.debug("No result containers found on page")
            return None
        
        # Extract results using DuckDuckGo extractor
        results = extract_duckduckgo_results_selenium(driver, max_results=10)
        
        if not results:
            logger.debug("No results extracted")
            return None
        
        # Filter out social media and directories
        skip_domains = ['facebook.com', 'linkedin.com', 'instagram.com', 'twitter.com', 
                       'yelp.com', 'yellowpages.com', 'superpages.com', 'manta.com',
                       'bizapedia.com', 'zoominfo.com', 'dnb.com', 'bloomberg.com',
                       'crunchbase.com', 'bbb.org', 'mapquest.com', 'google.com']
        
        # Look for website in search results - with validation
        best_match = None
        best_score = 0
        
        for result in results:
            url = result.get('url', '')
            title = result.get('title', '')
            if not url:
                continue
            
            url_lower = url.lower()
            # Skip social media and directories
            if any(domain in url_lower for domain in skip_domains):
                continue
            
            # Validate that the result matches the business name
            is_valid, match_score = validate_business_match(business_name, url, title, min_match_score=2)
            
            if is_valid and match_score > best_score:
                best_match = url
                best_score = match_score
        
        if best_match:
            logger.debug(f"Found validated website: {best_match} (score: {best_score})")
            return best_match
        
        return None
        
    except Exception as e:
        logger.error(f"Error searching for website: {str(e)}")
        return None


def search_google_for_linkedin(
    business_name: str,
    driver: uc.Chrome
) -> Optional[str]:
    """
    Search DuckDuckGo for LinkedIn company page using Selenium
    
    Args:
        business_name: Name of the business
        driver: Selenium WebDriver (undetected Chrome)
        
    Returns:
        LinkedIn URL if found, None otherwise
    """
    try:
        # Clean business name
        clean_name = business_name
        for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
            clean_name = clean_name.replace(suffix, '')
        clean_name = clean_name.strip().strip(',').strip()
        
        # Try multiple query strategies
        queries = [
            f'site:linkedin.com/company {clean_name}',  # Most specific
            f'{clean_name} linkedin',  # Broader search
        ]
        
        for query in queries:
            try:
                search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&t=h_&ia=web"
                driver.get(search_url)
                
                human_delay(2.0, 4.0)
                
                # Wait for DuckDuckGo results
                try:
                    WebDriverWait(driver, 20).until(
                        lambda d: len(d.find_elements(By.CSS_SELECTOR, "article[data-testid='result']")) > 0 or 
                                 len(d.find_elements(By.CSS_SELECTOR, ".result")) > 0
                    )
                except TimeoutException:
                    continue
                
                # Additional wait for results to fully render
                human_delay(1.5, 2.5)
                
                # Check if we have results before extracting
                has_results = driver.execute_script("""
                    return document.querySelectorAll('article[data-testid="result"]').length > 0 || 
                           document.querySelectorAll('.result').length > 0;
                """)
                
                if not has_results:
                    continue
                
                # Extract results using DuckDuckGo extractor
                results = extract_duckduckgo_results_selenium(driver, max_results=5)
                
                if not results:
                    continue
                
                # Find LinkedIn company URL with validation
                for result in results:
                    url = result.get('url', '')
                    title = result.get('title', '')
                    
                    if 'linkedin.com/company' in url.lower():
                        # Validate the match
                        if validate_linkedin_match(business_name, url, title):
                            logger.debug(f"Found validated LinkedIn: {url}")
                            return url
                    elif 'linkedin.com' in url.lower() and '/in/' not in url.lower():
                        if validate_linkedin_match(business_name, url, title):
                            logger.debug(f"Found validated LinkedIn: {url}")
                            return url
                        
            except Exception as e:
                logger.debug(f"Error with query '{query}': {str(e)}")
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"Error searching for LinkedIn: {str(e)}")
        return None


def search_google_for_facebook(
    business_name: str,
    driver: uc.Chrome
) -> Optional[str]:
    """
    Search DuckDuckGo for Facebook page using Selenium
    
    Args:
        business_name: Name of the business
        driver: Selenium WebDriver (undetected Chrome)
        
    Returns:
        Facebook URL if found, None otherwise
    """
    try:
        # Clean business name
        clean_name = business_name
        for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
            clean_name = clean_name.replace(suffix, '')
        clean_name = clean_name.strip().strip(',').strip()
        
        # Try multiple query strategies
        queries = [
            f'site:facebook.com {clean_name}',  # Most specific
            f'{clean_name} facebook',  # Broader search
        ]
        
        for query in queries:
            try:
                search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&t=h_&ia=web"
                driver.get(search_url)
                
                human_delay(2.0, 4.0)
                
                # Wait for DuckDuckGo results
                try:
                    WebDriverWait(driver, 20).until(
                        lambda d: len(d.find_elements(By.CSS_SELECTOR, "article[data-testid='result']")) > 0 or 
                                 len(d.find_elements(By.CSS_SELECTOR, ".result")) > 0
                    )
                except TimeoutException:
                    continue
                
                # Additional wait for results to fully render
                human_delay(1.5, 2.5)
                
                # Check if we have results before extracting
                has_results = driver.execute_script("""
                    return document.querySelectorAll('article[data-testid="result"]').length > 0 || 
                           document.querySelectorAll('.result').length > 0;
                """)
                
                if not has_results:
                    continue
                
                # Extract results using DuckDuckGo extractor
                results = extract_duckduckgo_results_selenium(driver, max_results=5)
                
                if not results:
                    continue
                
                # Find Facebook URL with validation
                for result in results:
                    url = result.get('url', '')
                    title = result.get('title', '')
                    
                    if url and 'facebook.com' in url.lower():
                        url_lower = url.lower()
                        # Skip Facebook pages directory and other non-business pages
                        if any(x in url_lower for x in ['/pages/', '/photo', '/events/', '/groups/', '/login']):
                            continue
                        
                        # Validate the match
                        if validate_facebook_match(business_name, url, title):
                            logger.debug(f"Found validated Facebook: {url}")
                            return url
                        
            except Exception as e:
                logger.debug(f"Error with query '{query}': {str(e)}")
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"Error searching for Facebook: {str(e)}")
        return None


def get_google_business_profile(
    business_name: str,
    driver: uc.Chrome,
    city: Optional[str] = None,
    state: str = "GA"
) -> Optional[Dict]:
    """
    Get Google Business Profile information using Selenium
    
    NOTE: Disabled because we switched to DuckDuckGo which doesn't have 
    Google Business Profile data. Returns None to avoid hitting Google.
    
    Args:
        business_name: Name of the business
        driver: Selenium WebDriver (undetected Chrome)
        city: Optional city name
        state: State name (default: GA)
        
    Returns:
        None (disabled to avoid Google CAPTCHAs)
    """
    # DISABLED: DuckDuckGo doesn't have Google Business Profile data
    # Returning None to avoid hitting Google and getting CAPTCHAs
    logger.debug(f"get_google_business_profile disabled (DuckDuckGo mode) for: {business_name}")
    return None



