"""
Google Search Scraper Module
Searches Google using browser automation with human-like behavior
Optimized to minimize detection and handle anti-bot measures
"""

import asyncio
import random
import re
from typing import Optional, List, Dict
from loguru import logger
from playwright.async_api import Page, Browser, BrowserContext
from urllib.parse import quote_plus


# User agents pool for rotation (common browser user agents)
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# Standard window size (common resolution)
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080


async def human_delay(min_seconds: float = 0.5, max_seconds: float = 2.0):
    """
    Random delay to simulate human behavior
    
    Args:
        min_seconds: Minimum delay in seconds
        max_seconds: Maximum delay in seconds
    """
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


async def human_like_type(page: Page, selector: str, text: str):
    """
    Type text with human-like delays between keystrokes
    
    Args:
        page: Playwright page object
        selector: CSS selector for input field
        text: Text to type
    """
    await page.click(selector)
    await human_delay(0.2, 0.5)
    
    for char in text:
        await page.type(selector, char, delay=random.uniform(50, 200))
        
        # Occasional longer pause (like human thinking)
        if random.random() < 0.1:  # 10% chance
            await human_delay(0.3, 0.8)
        
        # Occasional backspace (like human correcting)
        if random.random() < 0.03:  # 3% chance
            await page.keyboard.press("Backspace")
            await human_delay(0.1, 0.3)


async def human_like_scroll(page: Page):
    """
    Simulate human-like scrolling behavior
    
    Args:
        page: Playwright page object
    """
    try:
        # Get viewport size
        viewport = page.viewport_size
        if not viewport:
            return
        
        # Random scroll amount (humans don't scroll in one go)
        scroll_amount = random.randint(200, 600)
        
        # Random scroll direction (mostly down)
        if random.random() < 0.1:  # 10% chance to scroll up
            scroll_direction = -1
        else:
            scroll_direction = 1
        
        # Smooth scroll
        await page.mouse.wheel(0, scroll_amount * scroll_direction)
        await human_delay(0.5, 1.5)
        
        # Occasional longer scroll pause (like reading)
        if random.random() < 0.2:  # 20% chance
            await human_delay(1.0, 2.5)
        
    except Exception as e:
        logger.debug(f"Error during human-like scroll: {str(e)}")


async def rotate_user_agent(context: BrowserContext):
    """
    Rotate user agent for the browser context
    
    Args:
        context: Browser context to update
    """
    user_agent = random.choice(USER_AGENTS)
    
    # Set user agent
    await context.set_extra_http_headers({
        'User-Agent': user_agent
    })
    
    logger.debug(f"Rotated user agent: {user_agent[:50]}...")
    return user_agent


def get_stealth_script() -> str:
    """
    Get comprehensive stealth script to hide all automation indicators
    Based on playwright-stealth and undetected-chromedriver techniques
    """
    return """
    () => {
        // ========== Hide webdriver property ==========
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false
        });
        
        // Remove webdriver from prototype chain
        delete Object.getPrototypeOf(navigator).webdriver;
        
        // ========== Chrome property ==========
        if (!window.chrome) {
            window.chrome = {};
        }
        if (!window.chrome.runtime) {
            window.chrome.runtime = {};
        }
        
        // ========== Permissions API ==========
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // ========== Languages ==========
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        
        // ========== Plugins ==========
        const mockPlugins = [];
        for (let i = 0; i < 5; i++) {
            mockPlugins.push({
                name: `Plugin ${i}`,
                filename: `plugin${i}.dll`,
                description: `Plugin ${i} Description`
            });
        }
        Object.defineProperty(navigator, 'plugins', {
            get: () => mockPlugins
        });
        
        // ========== Platform ==========
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32'
        });
        
        // ========== Hardware ==========
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });
        
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });
        
        // ========== GetBattery API ==========
        if (navigator.getBattery) {
            delete navigator.getBattery;
        }
        
        // ========== Connection API ==========
        if (navigator.connection) {
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                })
            });
        }
        
        // ========== User Agent ==========
        const originalUserAgent = navigator.userAgent;
        Object.defineProperty(navigator, 'userAgent', {
            get: () => originalUserAgent.replace(/HeadlessChrome/g, 'Chrome')
        });
        
        // ========== Vendor ==========
        Object.defineProperty(navigator, 'vendor', {
            get: () => 'Google Inc.'
        });
        
        // ========== Max Touch Points ==========
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: () => 0
        });
        
        // ========== WebGL Vendor/Renderer ==========
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                return 'Intel Inc.';
            }
            if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                return 'Intel Iris OpenGL Engine';
            }
            return getParameter.call(this, parameter);
        };
        
        // ========== Canvas Fingerprinting Protection ==========
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {
            const context = this.getContext('2d');
            if (context) {
                const imageData = context.getImageData(0, 0, this.width, this.height);
                // Add subtle noise (not too much to break functionality)
                for (let i = 0; i < imageData.data.length; i += 4) {
                    if (Math.random() < 0.01) { // 1% of pixels
                        imageData.data[i] += Math.random() * 2 - 1; // R
                        imageData.data[i + 1] += Math.random() * 2 - 1; // G
                        imageData.data[i + 2] += Math.random() * 2 - 1; // B
                    }
                }
                context.putImageData(imageData, 0, 0);
            }
            return originalToDataURL.apply(this, arguments);
        };
        
        // ========== Audio Context Fingerprinting ==========
        if (window.AudioContext) {
            const originalCreateAnalyser = AudioContext.prototype.createAnalyser;
            AudioContext.prototype.createAnalyser = function() {
                const analyser = originalCreateAnalyser.call(this);
                const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
                analyser.getFloatFrequencyData = function(array) {
                    originalGetFloatFrequencyData.call(this, array);
                    // Add subtle noise
                    for (let i = 0; i < array.length; i++) {
                        array[i] += (Math.random() - 0.5) * 0.0001;
                    }
                };
                return analyser;
            };
        }
        
        // ========== Chrome DevTools Protocol Detection ==========
        if (window.chrome && window.chrome.runtime) {
            Object.defineProperty(window.chrome.runtime, 'onConnect', {
                value: undefined
            });
        }
        
        // ========== Automation Indicators ==========
        // Hide automation-related properties
        ['__playwright', '__pw_manual', '__PUPPETEER_WORLD__'].forEach(prop => {
            try {
                delete window[prop];
                delete document[prop];
            } catch (e) {}
        });
        
        // ========== Function toString Protection ==========
        const originalToString = Function.prototype.toString;
        Function.prototype.toString = function() {
            if (this === navigator.webdriver || 
                (this.toString && this.toString.toString().includes('webdriver'))) {
                return 'function webdriver() { [native code] }';
            }
            return originalToString.apply(this, arguments);
        };
        
        // ========== Document Properties ==========
        Object.defineProperty(document, '$cdc_asdjflasutopfhvcZLmcfl_', {
            get: () => undefined,
            configurable: true
        });
        Object.defineProperty(document, '$chrome_asyncScriptInfo', {
            get: () => undefined,
            configurable: true
        });
        
        // ========== Window Properties ==========
        Object.defineProperty(window, 'outerHeight', {
            get: () => window.innerHeight
        });
        Object.defineProperty(window, 'outerWidth', {
            get: () => window.innerWidth
        });
        
        // ========== Notification Permission ==========
        if (Notification.permission === 'default') {
            Object.defineProperty(Notification, 'permission', {
                get: () => 'default'
            });
        }
        
        // ========== Override toString methods ==========
        const originalToString2 = Object.prototype.toString;
        Object.prototype.toString = function() {
            if (this === navigator.webdriver) {
                return '[object Navigator]';
            }
            return originalToString2.apply(this, arguments);
        };
        
        // ========== Remove automation indicators from window ==========
        Object.keys(window).forEach(key => {
            if (key.includes('selenium') || key.includes('webdriver') || key.includes('__driver')) {
                try {
                    delete window[key];
                } catch (e) {}
            }
        });
        
        // ========== Override console.debug to hide automation logs ==========
        const originalConsoleDebug = console.debug;
        console.debug = function(...args) {
            const message = args.join(' ');
            if (message.includes('webdriver') || 
                message.includes('ChromeDriver') || 
                message.includes('automation')) {
                return;
            }
            return originalConsoleDebug.apply(console, args);
        };
    }
    """


async def human_like_mouse_movement(page: Page):
    """
    Simulate human-like mouse movements
    """
    try:
        # Get random coordinates within viewport
        viewport = page.viewport_size
        if not viewport:
            return
        
        # Random number of movements (humans move mouse around)
        num_movements = random.randint(2, 5)
        
        for _ in range(num_movements):
            x = random.randint(100, viewport['width'] - 100)
            y = random.randint(100, viewport['height'] - 100)
            
            # Move mouse smoothly
            await page.mouse.move(x, y, steps=random.randint(10, 30))
            await human_delay(0.1, 0.3)
    except Exception as e:
        logger.debug(f"Mouse movement error (non-critical): {str(e)}")


async def setup_google_search_context(
    browser: Browser,
    user_agent: Optional[str] = None
) -> BrowserContext:
    """
    Create and set up browser context for Google search with proper settings and stealth
    
    Args:
        browser: Browser instance
        user_agent: Optional specific user agent (if None, random will be chosen)
        
    Returns:
        Configured browser context with constant window size and stealth features
    """
    # Get user agent (rotate if not provided)
    if not user_agent:
        user_agent = random.choice(USER_AGENTS)
    
    # Create context with viewport size (constant size as requested) and additional stealth options
    context = await browser.new_context(
        viewport={
            "width": WINDOW_WIDTH,
            "height": WINDOW_HEIGHT
        },
        user_agent=user_agent,
        # Additional stealth options
        locale='en-US',
        timezone_id='America/New_York',
        permissions=['geolocation'],
        color_scheme='light',
        # Add realistic geolocation
        geolocation={'latitude': 33.7490, 'longitude': -84.3880},  # Atlanta, GA
        # Hide automation
        has_touch=False,
        is_mobile=False,
        # Realistic screen size
        screen={
            "width": WINDOW_WIDTH,
            "height": WINDOW_HEIGHT
        }
    )
    
    # Set additional headers to look more human
    await context.set_extra_http_headers({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
    })
    
    # Inject stealth script on context (applies to all pages)
    await context.add_init_script(get_stealth_script())
    
    logger.debug(f"Created browser context with viewport {WINDOW_WIDTH}x{WINDOW_HEIGHT} and user agent: {user_agent[:50]}...")
    
    return context


async def search_google(
    query: str,
    page: Page,
    max_results: int = 10,
    scroll_results: bool = True,
    use_direct_url: bool = True  # Use direct URL search instead of typing
) -> List[Dict[str, str]]:
    """
    Search Google using browser automation with human-like behavior and stealth
    
    Args:
        query: Search query string
        page: Playwright page object (must be configured with proper context)
        max_results: Maximum number of results to extract (default: 10)
        scroll_results: Whether to scroll through results (default: True)
        
    Returns:
        List of dictionaries containing search results:
        [
            {
                'title': 'Result title',
                'url': 'https://...',
                'snippet': 'Result description',
                'position': 1
            },
            ...
        ]
    """
    try:
        # Navigate to Google with realistic timing
        # Note: Stealth script should be injected before page creation (via add_init_script)
        logger.info(f"🔍 Searching Google for: '{query}'")
        await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30000)
        
        # Additional stealth injection after page load (backup)
        await page.evaluate("""
            () => {
                // Ensure webdriver is hidden
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false
                });
                // Remove automation indicator from document
                Object.defineProperty(document, '$cdc_asdjflasutopfhvcZLmcfl_', {
                    get: () => undefined
                });
                // Remove notification that page is controlled by automation
                delete window.navigator.webdriver;
            }
        """)
        
        # Human-like mouse movements while page loads
        await human_like_mouse_movement(page)
        await human_delay(1.5, 3.0)  # Humans take time to read/understand page
        
        # Simulate human reading the page (hover over different elements)
        try:
            # Hover over random page elements (like human exploring)
            body = page.locator('body')
            if await body.count() > 0:
                await body.hover()
                await human_delay(0.3, 0.8)
        except:
            pass
        
        # Check if we hit CAPTCHA or challenge (before searching)
        page_content = await page.content()
        page_url = page.url
        if "captcha" in page_content.lower() or "unusual traffic" in page_content.lower() or "sorry/index" in page_url.lower():
            logger.warning("⚠️ Google challenge detected before search, waiting longer...")
            # Longer wait and more human behavior
            await human_like_mouse_movement(page)
            await human_delay(8.0, 15.0)
            # Try clicking "I'm not a robot" if present
            try:
                not_robot = page.locator('text=/not.*robot/i').first
                if await not_robot.count() > 0:
                    await not_robot.click()
                    await human_delay(5.0, 10.0)
            except:
                pass
        
        # Find search input (try multiple selectors)
        search_selectors = [
            'textarea[name="q"]',
            'input[name="q"]',
            'textarea[aria-label*="Search"]',
            'input[aria-label*="Search"]',
            'textarea[type="search"]',
            'input[type="search"]'
        ]
        
        search_input = None
        for selector in search_selectors:
            try:
                search_input = page.locator(selector).first
                if await search_input.count() > 0:
                    break
            except:
                continue
        
        if not search_input or await search_input.count() == 0:
            logger.error("❌ Could not find Google search input")
            return []
        
        # Human-like interaction: hover before clicking
        await search_input.hover()
        await human_delay(0.2, 0.5)
        
        # Human-like clicking with slight movement
        bbox = await search_input.bounding_box()
        if bbox:
            # Click slightly offset from center (more human-like)
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)
            await page.mouse.click(bbox['x'] + bbox['width']/2 + offset_x, 
                                   bbox['y'] + bbox['height']/2 + offset_y)
        else:
            await search_input.click()
        
        await human_delay(0.4, 0.9)  # Longer pause before typing
        
        # Clear any existing text (humans sometimes select all)
        await page.keyboard.press("Control+A")
        await human_delay(0.15, 0.4)
        
        # Type query with very human-like behavior
        query_text = query
        typing_delays = []
        
        for i, char in enumerate(query_text):
            # Vary delay based on character type and position
            base_delay = random.uniform(100, 300)
            
            # Longer delays for spaces and punctuation (humans pause)
            if char in [' ', '.', ',', '"', "'"]:
                base_delay = random.uniform(150, 400)
            
            # Occasional longer pause mid-typing (like human thinking)
            if i > 0 and random.random() < 0.12:  # 12% chance
                await human_delay(0.3, 0.8)
            
            # Type character
            await page.keyboard.type(char, delay=base_delay)
            
            # Occasional typo correction (realistic human behavior)
            if random.random() < 0.03 and i > 2:  # 3% chance, not at start
                await page.keyboard.press("Backspace")
                await human_delay(0.15, 0.4)
                await page.keyboard.type(char, delay=base_delay)
            
            # Very occasional pause to "read" what was typed
            if random.random() < 0.05:  # 5% chance
                await human_delay(0.2, 0.5)
        
        # Humans often pause before submitting (especially for longer queries)
        pause_time = min(len(query_text) * 0.05, 2.0)  # Up to 2 seconds
        await human_delay(0.5 + pause_time, 1.5 + pause_time)
        
        # Random mouse movement before pressing enter
        await human_like_mouse_movement(page)
        await human_delay(0.2, 0.5)
        
        # Press Enter to search
        await page.keyboard.press("Enter")
        
        # Wait for results to load (humans wait and watch)
        await human_delay(0.5, 1.0)  # Brief pause
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except:
            # Sometimes networkidle doesn't trigger, wait for DOM
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        
        await human_delay(2.0, 4.0)  # Humans take time to see results
        
        # Human-like mouse movements while results load
        await human_like_mouse_movement(page)
        
        # Check for CAPTCHA or blocked search after search
        page_content = await page.content()
        page_url = page.url
        
        # Check for various Google blocking indicators
        has_captcha = "captcha" in page_content.lower() or "unusual traffic" in page_content.lower() or "sorry/index" in page_url.lower()
        has_no_results_msg = "your search did not match any documents" in page_content.lower() or "did not match any documents" in page_content.lower()
        is_blank_page = len(page_content) < 5000  # Very short page content
        
        if has_captcha:
            logger.warning("⚠️ Google CAPTCHA detected after search, simulating human behavior...")
            # More human behavior
            await human_like_mouse_movement(page)
            # Scroll a bit (humans scroll even when seeing CAPTCHA)
            await human_like_scroll(page)
            await human_delay(10.0, 20.0)
            
            # Try to interact with CAPTCHA elements
            try:
                # Look for checkbox or button
                checkbox = page.locator('[role="checkbox"]').first
                if await checkbox.count() > 0:
                    await checkbox.hover()
                    await human_delay(1.0, 2.0)
                    await checkbox.click()
                    await human_delay(3.0, 6.0)
            except:
                pass
            
            # Check again after CAPTCHA interaction
            page_content = await page.content()
            page_url = page.url
        
        if has_no_results_msg or is_blank_page:
            logger.warning("⚠️ Google blocked search or returned no results - trying alternative method...")
            # Try using direct Google search URL
            logger.info("🔄 Attempting direct URL search as fallback...")
            encoded_query = quote_plus(query)
            search_url = f"https://www.google.com/search?q={encoded_query}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2.0, 4.0)
            
            # Re-check for blocking
            page_content = await page.content()
            page_url = page.url
            has_captcha = "captcha" in page_content.lower() or "unusual traffic" in page_content.lower() or "sorry/index" in page_url.lower()
            
            if has_captcha:
                logger.error("❌ Google is still blocking - CAPTCHA required")
                return []
        
        # Human-like scrolling through results (more realistic)
        if scroll_results:
            # Scroll down gradually multiple times (like human reading)
            scroll_count = random.randint(2, 4)
            for i in range(scroll_count):
                await human_like_scroll(page)
                # Pause between scrolls (humans read between scrolls)
                await human_delay(1.5, 3.0)
                
                # Occasional mouse movement while scrolling
                if random.random() < 0.4:
                    await human_like_mouse_movement(page)
        
        # Extract search results
        results = await extract_google_results(page, max_results)
        
        logger.info(f"✅ Found {len(results)} search results")
        return results
        
    except Exception as e:
        logger.error(f"❌ Error searching Google: {str(e)}")
        return []


async def extract_google_results(page: Page, max_results: int = 10) -> List[Dict[str, str]]:
    """
    Extract search results from Google search results page
    
    Args:
        page: Playwright page object
        max_results: Maximum number of results to extract
        
    Returns:
        List of result dictionaries
    """
    try:
        # Wait a bit for results to fully render
        await human_delay(1.0, 2.0)
        
        # Check if we're on a valid results page
        page_url = page.url
        page_content = await page.content()
        
        # Debug: Log page URL and check for blocking
        logger.debug(f"Page URL: {page_url}")
        
        # Check for blocking indicators
        if "sorry/index" in page_url.lower() or "captcha" in page_content.lower():
            logger.warning("⚠️ CAPTCHA page detected - cannot extract results")
            return []
        
        if "your search did not match any documents" in page_content.lower():
            logger.warning("⚠️ Google returned 'no results' - page may be blocked")
            # Still try to extract if there are any results
            logger.debug("Attempting extraction anyway...")
        
        # Check for actual result containers before extraction
        has_results = await page.evaluate("""
            () => {
                const containers = document.querySelectorAll('div.g');
                return containers.length > 0;
            }
        """)
        
        if not has_results:
            logger.warning("⚠️ No result containers found on page - Google may have blocked the search")
            # Try to see what's on the page
            page_text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
            logger.debug(f"Page content preview: {page_text}")
        
        results = await page.evaluate("""
            (maxResults) => {
                const searchResults = [];
                const seen = new Set();
                
                // Method 1: Try standard Google result selectors (most reliable)
                const resultContainers = Array.from(document.querySelectorAll('div.g'));
                
                for (const container of resultContainers) {
                    if (searchResults.length >= maxResults) break;
                    
                    try {
                        // Find the main link
                        const link = container.querySelector('a[href^="http"]') || 
                                    container.querySelector('a[href^="/url"]') ||
                                    container.querySelector('a[data-ved]');
                        
                        if (!link) continue;
                        
                        // Extract URL
                        let url = link.getAttribute('href');
                        if (!url) continue;
                        
                        // Handle Google's redirect URLs (/url?q=...)
                        if (url.startsWith('/url?')) {
                            const match = url.match(/[?&]q=([^&]+)/);
                            if (match) {
                                url = decodeURIComponent(match[1]);
                            }
                        }
                        
                        // Skip Google internal pages
                        if (url.includes('google.com') && !url.includes('plus.google.com') && !url.includes('maps.google.com')) {
                            continue;
                        }
                        
                        // Skip empty or invalid URLs
                        if (!url || url === '#' || url.startsWith('javascript:')) {
                            continue;
                        }
                        
                        // Create unique key
                        const key = url.toLowerCase();
                        if (seen.has(key)) continue;
                        seen.add(key);
                        
                        // Extract title (try multiple selectors)
                        let title = '';
                        const titleSelectors = [
                            'h3.LC20lb',
                            'h3',
                            '.DKV0Md',
                            '.yuRUbf h3',
                            'a h3'
                        ];
                        
                        for (const selector of titleSelectors) {
                            const titleEl = container.querySelector(selector);
                            if (titleEl && titleEl.textContent.trim()) {
                                title = titleEl.textContent.trim();
                                break;
                            }
                        }
                        
                        // Fallback to link text if no title found
                        if (!title && link.textContent) {
                            title = link.textContent.trim();
                        }
                        
                        // Extract snippet/description
                        let snippet = '';
                        const snippetSelectors = [
                            '.VwiC3b',
                            '.s',
                            '.IsZvec',
                            'span[style*="-webkit-line-clamp"]',
                            '.aCOpRe'
                        ];
                        
                        for (const selector of snippetSelectors) {
                            const snippetEl = container.querySelector(selector);
                            if (snippetEl && snippetEl.textContent.trim()) {
                                snippet = snippetEl.textContent.trim();
                                break;
                            }
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
                
                // If no results found with div.g, try alternative methods
                if (searchResults.length === 0) {
                    // Try finding all links that look like search results
                    const allLinks = Array.from(document.querySelectorAll('a[href^="http"]'));
                    
                    for (const link of allLinks) {
                        if (searchResults.length >= maxResults) break;
                        
                        const url = link.getAttribute('href');
                        if (!url || url.includes('google.com')) continue;
                        
                        const key = url.toLowerCase();
                        if (seen.has(key)) continue;
                        seen.add(key);
                        
                        const title = link.textContent.trim() || link.innerText.trim();
                        
                        if (url && title && url.startsWith('http')) {
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
            }
        """, max_results)
        
        # Validate and clean results
        valid_results = []
        for result in results:
            if result.get('url') and result.get('url').startswith('http'):
                valid_results.append(result)
        
        return valid_results
        
    except Exception as e:
        logger.error(f"❌ Error extracting Google results: {str(e)}")
        return []


async def search_google_for_website(
    business_name: str,
    page: Page,
    city: Optional[str] = None,
    state: Optional[str] = None
) -> Optional[str]:
    """
    Search Google specifically for business website
    
    Args:
        business_name: Name of the business
        city: Optional city name
        state: Optional state name
        page: Playwright page object
        
    Returns:
        Website URL if found, None otherwise
    """
    # Clean business name - remove LLC, INC, CORP, etc.
    clean_name = business_name
    for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
        clean_name = clean_name.replace(suffix, '')
    clean_name = clean_name.strip().strip(',').strip()
    
    # Try multiple query strategies
    queries = []
    
    # Strategy 1: Simple query with location
    if city and state:
        queries.append(f'{clean_name} {city} {state}')
    elif state:
        queries.append(f'{clean_name} {state}')
    else:
        queries.append(clean_name)
    
    # Strategy 2: Add "official website" 
    if city:
        queries.append(f'{clean_name} {city} official website')
    
    # Strategy 3: If simple name, try quoted
    if len(clean_name.split()) <= 3 and city:
        queries.append(f'"{clean_name}" {city}')
    
    # Try each query
    for query in queries:
        logger.debug(f"Trying website query: {query}")
        results = await search_google(query, page, max_results=10, scroll_results=False)
        
        if not results:
            continue
        
        # Filter out social media and directories
        skip_domains = ['facebook.com', 'linkedin.com', 'instagram.com', 'twitter.com', 
                       'yelp.com', 'yellowpages.com', 'superpages.com', 'manta.com',
                       'bizapedia.com', 'zoominfo.com', 'dnb.com', 'bloomberg.com',
                       'crunchbase.com', 'bbb.org', 'mapquest.com']
        
        for result in results:
            url = result.get('url', '').lower()
            if any(domain in url for domain in skip_domains):
                continue
            # Found a potential website
            return result.get('url')
    
    return None


async def search_google_for_linkedin(
    business_name: str,
    page: Page
) -> Optional[str]:
    """
    Search Google for business LinkedIn page
    
    Args:
        business_name: Name of the business
        page: Playwright page object
        
    Returns:
        LinkedIn URL if found, None otherwise
    """
    # Clean business name
    clean_name = business_name
    for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
        clean_name = clean_name.replace(suffix, '')
    clean_name = clean_name.strip().strip(',').strip()
    
    # Try multiple query strategies
    queries = [
        f'site:linkedin.com/company {clean_name}',  # Most specific
        f'{clean_name} linkedin',  # Broader search
        f'"{clean_name}" site:linkedin.com',  # Alternative with quotes
    ]
    
    for query in queries:
        logger.debug(f"Trying LinkedIn query: {query}")
        results = await search_google(query, page, max_results=5, scroll_results=False)
        
        if not results:
            continue
        
        # Find LinkedIn company URL
        for result in results:
            url = result.get('url', '')
            if 'linkedin.com/company' in url.lower():
                return url
            elif 'linkedin.com' in url.lower() and '/in/' not in url.lower():
                return url
    
    return None


async def search_google_for_facebook(
    business_name: str,
    page: Page
) -> Optional[str]:
    """
    Search Google for business Facebook page
    
    Args:
        business_name: Name of the business
        page: Playwright page object
        
    Returns:
        Facebook URL if found, None otherwise
    """
    # Clean business name
    clean_name = business_name
    for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
        clean_name = clean_name.replace(suffix, '')
    clean_name = clean_name.strip().strip(',').strip()
    
    # Try multiple query strategies
    queries = [
        f'site:facebook.com {clean_name}',  # Most specific
        f'{clean_name} facebook',  # Broader search
        f'"{clean_name}" site:facebook.com',  # Alternative with quotes
    ]
    
    for query in queries:
        logger.debug(f"Trying Facebook query: {query}")
        results = await search_google(query, page, max_results=5, scroll_results=False)
        
        if not results:
            continue
        
        # Find Facebook URL
        for result in results:
            url = result.get('url', '')
            if 'facebook.com' in url.lower():
                # Skip Facebook pages directory and other non-business pages
                if any(x in url.lower() for x in ['/pages/', '/photo', '/events/', '/groups/']):
                    continue
                return url
    
    return None


async def search_google_for_executive_linkedin(
    executive_name: str,
    business_name: str,
    page: Page
) -> Optional[str]:
    """
    Search Google for executive LinkedIn profile
    
    Args:
        executive_name: Name of the executive/owner
        business_name: Name of the business
        page: Playwright page object
        
    Returns:
        LinkedIn profile URL if found, None otherwise
    """
    # Clean business name
    clean_biz = business_name
    for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
        clean_biz = clean_biz.replace(suffix, '')
    clean_biz = clean_biz.strip().strip(',').strip()
    
    # Try multiple query strategies
    queries = [
        f'site:linkedin.com/in {executive_name} {clean_biz}',  # Most specific
        f'{executive_name} {clean_biz} linkedin',  # Broader
        f'"{executive_name}" site:linkedin.com {clean_biz}',  # Alternative
    ]
    
    for query in queries:
        logger.debug(f"Trying executive LinkedIn query: {query}")
        results = await search_google(query, page, max_results=5, scroll_results=False)
        
        if not results:
            continue
        
        # Find LinkedIn profile URL
        for result in results:
            url = result.get('url', '')
            if 'linkedin.com/in/' in url.lower() or 'linkedin.com/pub/' in url.lower():
                return url
    
    return None


async def get_google_business_profile(
    business_name: str,
    page: Page,
    city: Optional[str] = None,
    state: Optional[str] = None
) -> Optional[Dict[str, any]]:
    """
    Search Google for business and extract Google Business Profile (Knowledge Panel) data
    
    This extracts the structured business information panel that appears on the right
    side of Google search results, including phone, address, website, ratings, etc.
    
    Args:
        business_name: Name of the business
        city: Optional city name
        state: Optional state name
        page: Playwright page object
        
    Returns:
        Dictionary with business profile data or None if not found:
        {
            'phone': '(404) 621-5252',
            'address': '1754 Bouldercrest Rd SE, Atlanta, GA 30316',
            'website': 'searchcarriers.com',
            'rating': 4.5,
            'review_count': 15,
            'hours': {...},
            'category': 'Logistics Company'
        }
    """
    # Clean business name
    clean_name = business_name
    for suffix in [' LLC', ' L.L.C.', ' INC', ' INC.', ' CORP', ' CORPORATION', ' LTD', ' CO', ' CO.']:
        clean_name = clean_name.replace(suffix, '')
    clean_name = clean_name.strip().strip(',').strip()
    
    # Build search query
    query_parts = [clean_name]
    if city:
        query_parts.append(city)
    if state:
        query_parts.append(state)
    
    query = ' '.join(query_parts)
    
    logger.info(f"🔍 Searching Google Business Profile for: '{query}'")
    
    try:
        # Use existing search_google function but don't extract results yet
        # We want to extract the Knowledge Panel directly
        await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30000)
        
        # Human-like delay
        await human_delay(1.5, 3.0)
        
        # Find and click search input
        search_selectors = [
            'textarea[name="q"]',
            'input[name="q"]',
            'textarea[aria-label*="Search"]',
            'input[aria-label*="Search"]'
        ]
        
        search_input = None
        for selector in search_selectors:
            try:
                search_input = page.locator(selector).first
                if await search_input.count() > 0:
                    break
            except:
                continue
        
        if not search_input or await search_input.count() == 0:
            logger.warning("⚠️ Could not find Google search input")
            return None
        
        # Type and search
        await search_input.click()
        await human_delay(0.3, 0.6)
        await page.keyboard.press("Control+A")
        await human_delay(0.15, 0.3)
        
        # Type query with human-like delays
        for char in query:
            await page.keyboard.type(char, delay=random.uniform(100, 250))
        
        await human_delay(0.5, 1.0)
        await page.keyboard.press("Enter")
        
        # Wait for results
        await human_delay(1.0, 2.0)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        
        await human_delay(2.0, 3.0)  # Wait for Knowledge Panel to load
        
        # Extract Knowledge Panel / Business Profile data
        profile_data = await page.evaluate("""
            () => {
                const result = {
                    phone: null,
                    address: null,
                    website: null,
                    rating: null,
                    review_count: null,
                    hours: null,
                    category: null
                };
                
                // Method 1: Look for the Knowledge Panel (right side panel)
                // This is the structured data panel that Google shows
                
                // Try to find the main Knowledge Panel container
                const panel = document.querySelector('[data-attrid="kc:/location/location:address"]')?.closest('[data-ved]') ||
                             document.querySelector('[data-attrid="kc:/organization/organization:address"]')?.closest('[data-ved]') ||
                             document.querySelector('div[data-ved].kp-blk') ||
                             document.querySelector('[jsname="fkbRMb"]') ||
                             document.querySelector('[jsname="bVqjv"]');
                
                if (!panel) {
                    // Try alternative selectors
                    const panels = document.querySelectorAll('[data-ved]');
                    for (const p of panels) {
                        const text = p.innerText.toLowerCase();
                        if (text.includes('address') || text.includes('phone') || text.includes('hours')) {
                            // Likely the knowledge panel
                            const panelText = p.innerText;
                            
                            // Extract phone (various formats)
                            const phoneMatch = panelText.match(/[\\(]?\\d{3}[\\)]?[-.\\s]?\\d{3}[-.\\s]?\\d{4}/);
                            if (phoneMatch) {
                                result.phone = phoneMatch[0];
                            }
                            
                            // Extract address (looks for street address patterns)
                            const addressMatch = panelText.match(/\\d+\\s+[A-Za-z0-9\\s,]+(?:Avenue|Street|Road|Drive|Boulevard|Lane|Court|Way|Place|Circle|Georgia|GA|\\d{5})/i);
                            if (addressMatch) {
                                result.address = addressMatch[0];
                            }
                            break;
                        }
                    }
                } else {
                    // Extract from Knowledge Panel
                    const panelText = panel.innerText;
                    const panelHTML = panel.innerHTML;
                    
                    // Extract phone number
                    const phonePatterns = [
                        /[\\(]?\\d{3}[\\)]?[-.\\s]?\\d{3}[-.\\s]?\\d{4}/,
                        /\\+1[-.\\s]?[\\(]?\\d{3}[\\)]?[-.\\s]?\\d{3}[-.\\s]?\\d{4}/
                    ];
                    
                    for (const pattern of phonePatterns) {
                        const match = panelText.match(pattern);
                        if (match) {
                            result.phone = match[0];
                            break;
                        }
                    }
                    
                    // Extract address
                    const addressPatterns = [
                        /\\d+\\s+[A-Za-z0-9\\s,]+(?:Avenue|Street|Road|Drive|Boulevard|Lane|Court|Way|Place|Circle)[^\\n]*/i,
                        /\\d+\\s+[A-Za-z0-9\\s,]+(?:Georgia|GA)[^\\n]*\\d{5}/i
                    ];
                    
                    for (const pattern of addressPatterns) {
                        const match = panelText.match(pattern);
                        if (match) {
                            result.address = match[0].trim();
                            break;
                        }
                    }
                    
                    // Extract rating
                    const ratingMatch = panelText.match(/(\\d+\\.\\d+)\\s*stars?/i) || 
                                       panelText.match(/(\\d+\\.\\d+)\\s*★/);
                    if (ratingMatch) {
                        result.rating = parseFloat(ratingMatch[1]);
                    }
                    
                    // Extract review count
                    const reviewMatch = panelText.match(/(\\d+[,.]?\\d*)\\s*(?:reviews?|ratings?)/i);
                    if (reviewMatch) {
                        result.review_count = parseInt(reviewMatch[1].replace(/,/g, ''));
                    }
                    
                    // Extract website
                    const websiteLink = panel.querySelector('a[href^="http"]');
                    if (websiteLink) {
                        result.website = websiteLink.href;
                    }
                    
                    // Extract category
                    const categoryEl = panel.querySelector('[data-attrid="subtitle"]') ||
                                      panel.querySelector('.YhemCb');
                    if (categoryEl) {
                        result.category = categoryEl.innerText.trim();
                    }
                }
                
                // Method 2: Look for structured data in JSON-LD
                try {
                    const jsonLd = document.querySelector('script[type="application/ld+json"]');
                    if (jsonLd) {
                        const data = JSON.parse(jsonLd.textContent);
                        if (data['@type'] === 'LocalBusiness' || data['@type'] === 'Organization') {
                            if (!result.phone && data.telephone) result.phone = data.telephone;
                            if (!result.address && data.address) {
                                const addr = data.address;
                                result.address = `${addr.streetAddress || ''} ${addr.addressLocality || ''}, ${addr.addressRegion || ''} ${addr.postalCode || ''}`.trim();
                            }
                            if (!result.rating && data.aggregateRating) {
                                result.rating = parseFloat(data.aggregateRating.ratingValue);
                                result.review_count = parseInt(data.aggregateRating.reviewCount);
                            }
                            if (!result.website && data.url) result.website = data.url;
                        }
                    }
                } catch (e) {
                    // JSON-LD parsing failed, continue
                }
                
                // Return only non-null values
                const cleaned = {};
                for (const key in result) {
                    if (result[key] !== null) {
                        cleaned[key] = result[key];
                    }
                }
                
                return Object.keys(cleaned).length > 0 ? cleaned : null;
            }
        """)
        
        if profile_data:
            logger.info(f"✅ Found Google Business Profile:")
            if profile_data.get('phone'):
                logger.info(f"   Phone: {profile_data['phone']}")
            if profile_data.get('address'):
                logger.info(f"   Address: {profile_data['address']}")
            if profile_data.get('website'):
                logger.info(f"   Website: {profile_data['website']}")
            if profile_data.get('rating'):
                logger.info(f"   Rating: {profile_data['rating']} ({profile_data.get('review_count', 'N/A')} reviews)")
            return profile_data
        else:
            logger.warning("⚠️ No Google Business Profile found")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error getting Google Business Profile: {str(e)}")
        return None


async def search_google_batch(
    queries: List[str],
    page: Page,
    delay_between_searches: float = 3.0,
    max_results_per_query: int = 5
) -> Dict[str, List[Dict[str, str]]]:
    """
    Perform multiple Google searches with delays between them
    
    Args:
        queries: List of search queries
        page: Playwright page object
        delay_between_searches: Delay in seconds between searches
        max_results_per_query: Maximum results per query
        
    Returns:
        Dictionary mapping queries to their results
    """
    all_results = {}
    
    for i, query in enumerate(queries, 1):
        logger.info(f"Searching {i}/{len(queries)}: '{query}'")
        
        results = await search_google(query, page, max_results=max_results_per_query)
        all_results[query] = results
        
        # Delay between searches (except last one)
        if i < len(queries):
            await human_delay(delay_between_searches, delay_between_searches * 1.5)
        
        # Occasional longer break (like human taking a break)
        if i % 10 == 0 and i < len(queries):
            break_time = random.uniform(10.0, 20.0)
            logger.info(f"⏸️  Taking a break... ({break_time:.1f}s)")
            await asyncio.sleep(break_time)
    
    return all_results


# Test function - hardcoded business for testing
if __name__ == "__main__":
    async def test_google_scraper():
        """Test Google scraper with a hardcoded business"""
        from playwright.async_api import async_playwright
        

        business_name = "BIG BREEZE LANDSCAPING, LLC"
        city = "Lawrenceville"
        state = "GA"
        
        logger.info("="*80)
        logger.info(f"🧪 Testing Google Scraper for: {business_name}")
        logger.info(f"   Location: {city}, {state}")
        logger.info("="*80)
        
        try:
            # Start Playwright with comprehensive stealth options
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=False,
                args=[
                    # Essential stealth flags
                    '--disable-blink-features=AutomationControlled',
                    '--exclude-switches=enable-automation',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-sync',
                    '--disable-default-apps',
                    '--disable-features=IsolateOrigins,site-per-process,TranslateUI,BlinkGenPropertyTrees',
                    '--disable-site-isolation-trials',
                    '--disable-ipc-flooding-protection',
                    '--disable-renderer-backgrounding',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-background-timer-throttling',
                    '--force-color-profile=srgb',
                    '--metrics-recording-only',
                    '--no-first-run',
                    '--password-store=basic',
                    '--use-mock-keychain',
                    '--disable-extensions-file-access-check',
                    '--disable-extensions-http-throttling',
                    # Additional stealth
                    '--disable-web-security',
                    '--disable-features=AudioServiceOutOfProcess',
                    '--window-size=1920,1080',
                    '--start-maximized',
                    '--disable-infobars',
                ]
            )
            
            # Create context with constant window size and user agent rotation
            context = await setup_google_search_context(browser)
            
            # Create page (stealth script already injected on context)
            page = await context.new_page()
            
            # Initialize variables for summary
            website = None
            linkedin = None
            facebook = None
            business_profile = None
            search_results = None
            
            # Test 1: Search for website
            logger.info("\n📋 Test 1: Searching for website...")
            website = await search_google_for_website(business_name, page, city, state)
            if website:
                logger.info(f"✅ Found website: {website}")
            else:
                logger.warning("⚠️ No website found")
            
            # Delay between searches
            await human_delay(3.0, 5.0)
            
            # Test 2: Search for LinkedIn
            logger.info("\n📋 Test 2: Searching for LinkedIn...")
            linkedin = await search_google_for_linkedin(business_name, page)
            if linkedin:
                logger.info(f"✅ Found LinkedIn: {linkedin}")
            else:
                logger.warning("⚠️ No LinkedIn found")
            
            # Delay between searches
            await human_delay(3.0, 5.0)
            
            # Test 3: Search for Facebook
            logger.info("\n📋 Test 3: Searching for Facebook...")
            facebook = await search_google_for_facebook(business_name, page)
            if facebook:
                logger.info(f"✅ Found Facebook: {facebook}")
            else:
                logger.warning("⚠️ No Facebook found")
            
            # Delay between searches
            await human_delay(3.0, 5.0)
            
            # Test 4: Get Google Business Profile
            logger.info("\n📋 Test 4: Getting Google Business Profile...")
            business_profile = await get_google_business_profile(business_name, page, city, state)
            if business_profile:
                logger.info("✅ Found Google Business Profile:")
                for key, value in business_profile.items():
                    logger.info(f"   {key}: {value}")
            else:
                logger.warning("⚠️ No Google Business Profile found")
            
            # Delay between searches
            await human_delay(3.0, 5.0)
            
            # Test 5: Test general search
            logger.info("\n📋 Test 5: General Google search...")
            query = f'"{business_name}" "{city}" "{state}"'
            search_results = await search_google(query, page, max_results=5)
            if search_results:
                logger.info(f"✅ Found {len(search_results)} results:")
                for i, result in enumerate(search_results, 1):
                    logger.info(f"   {i}. {result.get('title', 'N/A')}")
                    logger.info(f"      URL: {result.get('url', 'N/A')}")
            
            # Summary
            logger.info("\n" + "="*80)
            logger.info("📊 TEST RESULTS SUMMARY")
            logger.info("="*80)
            logger.info(f"Business Name: {business_name}")
            logger.info(f"Website: {website if website else 'Not found'}")
            logger.info(f"LinkedIn: {linkedin if linkedin else 'Not found'}")
            logger.info(f"Facebook: {facebook if facebook else 'Not found'}")
            if business_profile:
                logger.info(f"Business Profile Phone: {business_profile.get('phone', 'Not found')}")
                logger.info(f"Business Profile Address: {business_profile.get('address', 'Not found')}")
            logger.info(f"General Search Results: {len(search_results) if search_results else 0}")
            logger.info("="*80)
            
            # Keep browser open briefly for inspection (only if interactive)
            try:
                import sys
                if sys.stdin.isatty():
                    input("\nPress Enter to close browser...")
            except:
                pass
            
            # Close browser
            await browser.close()
            await playwright.stop()
            
        except Exception as e:
            logger.error(f"❌ Test failed: {str(e)}")
            logger.exception(e)
            if 'browser' in locals():
                await browser.close()
            if 'playwright' in locals():
                await playwright.stop()
    
    # Run test
    import asyncio
    asyncio.run(test_google_scraper())

