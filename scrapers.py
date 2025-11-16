"""
Georgia SOS Business Scraper
Scrapes business data from Georgia Secretary of State website
"""

import asyncio
import random
import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path
from loguru import logger
from playwright.async_api import Page, Browser, BrowserContext
from urllib.parse import urlparse

from cloudflareSolver import get_bypassed_page, solve_cloudflare_challenge, CloudflareTurnstileExtractor
from cloudflare_utils import is_session_valid
from naics_classifier_ai import enrich_naics_codes_ai as enrich_naics_codes


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
        
        # Set up extractor to get sitekey
        extractor = CloudflareTurnstileExtractor()
        
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
        
        # Only set up network monitoring if we don't have a valid sitekey already
        if not existing_params:
            logger.debug("No existing sitekey found, setting up network monitoring...")
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
            
            # Extract sitekey from network
            sitekey = await extractor.get_sitekey(page, wait_time=10000)  # Increased wait time
            turnstile_params = await page.evaluate("() => window.turnstileParams")
        
        if not sitekey:
            logger.error("❌ Could not extract sitekey from Cloudflare challenge")
            return False
        
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
                            if (label === 'NAICS Code' && value) data['NAICS Code'] = value;
                            if (label === 'NAICS Sub Code' && value) data['NAICS Sub Code'] = value;
                            if (label === 'Date of Formation / Registration Date' && value) data['Date of Formation'] = value;
                            if (label === 'State of Formation' && value) data['State of Formation'] = value;
                            if (label === 'Last Annual Registration Year' && value2) data['Last Annual Registration Year'] = value2;
                            if (label === 'Dissolved Date' && value) data['Dissolved Date'] = value;
                            
                            // Check second column
                            if (label2 === 'NAICS Code' && value2) data['NAICS Code'] = value2;
                            if (label2 === 'NAICS Sub Code' && value2) data['NAICS Sub Code'] = value2;
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


async def scrape_all_pages(page: Page, max_pages: Optional[int] = None) -> List[Dict[str, str]]:
    """
    Scrape all pages of search results
    
    Args:
        page: Playwright page object with search results
        max_pages: Optional limit on number of pages to scrape (for testing)
        
    Returns:
        List of all business records from all pages
    """
    all_data = []
    
    # Get total pages
    total_pages = await get_total_pages(page)
    
    if max_pages:
        total_pages = min(total_pages, max_pages)
        logger.info(f"⚠️ Limiting to {max_pages} pages for testing")
    
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
        else:
            logger.warning(f"⚠️ No data found on page {page_num}")
        
        # Go to next page if not on last page
        if page_num < total_pages:
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


async def enrich_business_data(page: Page, df: pd.DataFrame, save_progress_every: int = 100, output_file: Optional[str] = None) -> pd.DataFrame:
    """
    Enrich existing business data by visiting each detail page
    
    Args:
        page: Playwright page object (same browser session)
        df: DataFrame with existing business data (must have 'Business Link' and 'Control Number' columns)
        save_progress_every: Save progress every N records
        output_file: Path to Excel file for incremental saves
        
    Returns:
        Enriched DataFrame with additional detail page data
    """
    if df.empty:
        logger.warning("No data to enrich")
        return df
    
    # Add new columns if they don't exist
    new_columns = [
        'NAICS Code',
        'NAICS Sub Code',
        'Date of Formation',
        'State of Formation',
        'Last Annual Registration Year',
        'Dissolved Date',
        'Registered Agent Physical Address',
        'Registered Agent County',
        'Officers',  # JSON string of officers array
        'Officers_Formatted',  # Human-readable format
        'Officer_Count'  # Number of officers
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
                # Update DataFrame row with new data
                for key, value in detail_data.items():
                    if key in df.columns:
                        df.at[idx, key] = value
                
                logger.info(f"   ✅ Extracted {len(detail_data)} fields")
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
    
    # Check if detail-only mode is requested
    if len(sys.argv) > 1:
        excel_file = sys.argv[1]
        asyncio.run(main(excel_file_path=excel_file, detail_only=True))
    else:
        # Run full scraping
        asyncio.run(main())

