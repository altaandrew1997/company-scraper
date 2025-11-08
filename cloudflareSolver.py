"""
Cloudflare Turnstile Sitekey Extractor
Extracts sitekey from network traffic for Cloudflare Turnstile CAPTCHA
"""

import re
import time
import os
import asyncio
from urllib.parse import urlparse
from typing import Optional, Dict
from loguru import logger
from playwright.async_api import Page, BrowserContext

# Import Cloudflare session management utilities
from cloudflare_utils import (
    load_cloudflare_session,
    save_cloudflare_session,
    is_session_valid,
    get_session_info
)

try:
    from twocaptcha import TwoCaptcha
    TWOCAPTCHA_AVAILABLE = True
except ImportError:
    TWOCAPTCHA_AVAILABLE = False
    logger.warning("2captcha library not installed. Install with: pip install 2captcha-python")


class CloudflareTurnstileExtractor:
    """Extracts Cloudflare Turnstile sitekey from network traffic"""
    
    def __init__(self):
        """Initialize the sitekey extractor"""
        self.captured_requests = []
        self.sitekey_from_network = None
        self.monitoring_setup = False
    
    async def setup_network_monitoring(self, page: Page):
        """Set up network request monitoring to capture sitekey from network traffic"""
        # Don't set up monitoring twice
        if self.monitoring_setup:
            logger.info("Network monitoring already set up, skipping...")
            return
        
        async def handle_request(request):
            """Capture all network requests"""
            url = request.url
            
            # Check if it's a Cloudflare challenge or Turnstile related request
            if "challenges.cloudflare.com" in url or "turnstile" in url.lower():
                try:
                    # Get request data
                    post_data = request.post_data
                    headers = request.headers
                    
                    request_info = {
                        'url': url,
                        'method': request.method,
                        'headers': dict(headers),
                        'post_data': post_data
                    }
                    
                    self.captured_requests.append(request_info)
                    logger.info(f"Captured request: {request.method} {url[:100]}...")
                    
                    # Try to extract sitekey from URL, headers, or post data
                    sitekey = self._extract_sitekey_from_network_data(request_info)
                    if sitekey:
                        self.sitekey_from_network = sitekey
                        logger.info(f"✅ Found sitekey in network request: {sitekey}")
                    else:
                        logger.debug(f"No sitekey found in request URL: {url[:150]}")
                        
                except Exception as e:
                    logger.error(f"Error capturing request: {str(e)}")
        
        async def handle_response(response):
            """Capture responses and check for sitekey"""
            url = response.url
            
            if "challenges.cloudflare.com" in url or "turnstile" in url.lower():
                try:
                    # Try to get response body (may fail for binary data)
                    try:
                        body = await response.text()
                    except:
                        body = None
                    
                    headers = response.headers
                    
                    response_info = {
                        'url': url,
                        'status': response.status,
                        'headers': dict(headers),
                        'body': body[:1000] if body else None  # Limit body size
                    }
                    
                    logger.info(f"Captured response: {response.status} {url[:100]}...")
                    
                    # Try to extract sitekey from response
                    sitekey = self._extract_sitekey_from_network_data(response_info)
                    if sitekey:
                        self.sitekey_from_network = sitekey
                        logger.info(f"Found sitekey in network response: {sitekey}")
                        
                except Exception as e:
                    logger.error(f"Error capturing response: {str(e)}")
        
        # Set up listeners
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        self.monitoring_setup = True
        logger.info("Network monitoring enabled")
    
    def _is_valid_turnstile_sitekey(self, sitekey: str) -> bool:
        """
        Validate if a string is a valid Cloudflare Turnstile sitekey
        
        Valid sitekeys:
        - Start with 0x or 0X
        - Are typically 20-30 characters after 0x
        - Contain alphanumeric characters
        - Known format: 0x4AAAAAAADnPIDROrmt1Wwj (22 chars after 0x)
        """
        if not sitekey or len(sitekey) < 22 or len(sitekey) > 35:
            return False
        
        if not sitekey.lower().startswith('0x'):
            return False
        
        # Check if it's the known Cloudflare managed challenge sitekey format
        # Common patterns: 0x4AAAAAAADnPIDROrmt1Wwj (22 chars) or similar
        if len(sitekey) >= 22 and len(sitekey) <= 30:
            # Check if contains valid alphanumeric after 0x
            suffix = sitekey[2:]  # After 0x
            if all(c.isalnum() for c in suffix):
                return True
        
        return False
    
    def _extract_sitekey_from_url(self, url: str) -> Optional[str]:
        """
        Extract sitekey from Cloudflare Turnstile URL
        
        URL format:
        - https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/f/ov2/av0/rch/4z2pa/0x4AAAAAAADnPIDROrmt1Wwj/light/fbE/new/normal?lang=auto
        - Sitekey appears in the path as: 0x4AAAAAAADnPIDROrmt1Wwj
        """
        if not url:
            return None
        
        # Only extract from Turnstile URLs to avoid false positives
        if 'turnstile' not in url.lower():
            return None
        
        # Extract from URL path (0x4AAAAAAADnPIDROrmt1Wwj format)
        # Cloudflare sitekeys use alphanumeric characters, not just hex
        # Pattern matches 0x followed by alphanumeric (at least 20 chars for valid sitekey)
        pattern = r'/(0x[0-9A-Za-z]{20,})/'
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            sitekey = match.group(1)
            # Validate it's a real sitekey
            if self._is_valid_turnstile_sitekey(sitekey):
                logger.info(f"✅ Found sitekey in URL path: {sitekey}")
                return sitekey
        
        # Also try without requiring trailing slash (in case it's at end of URL)
        pattern2 = r'/(0x[0-9A-Za-z]{20,})(?:/|$)'
        match = re.search(pattern2, url, re.IGNORECASE)
        if match:
            sitekey = match.group(1)
            if self._is_valid_turnstile_sitekey(sitekey):
                logger.info(f"✅ Found sitekey in URL (end): {sitekey}")
                return sitekey
        
        # Check for sitekey as query parameter
        pattern3 = r'sitekey=([^&]+)'
        match = re.search(pattern3, url, re.IGNORECASE)
        if match:
            sitekey = match.group(1)
            if self._is_valid_turnstile_sitekey(sitekey):
                logger.info(f"✅ Found sitekey in URL query: {sitekey}")
                return sitekey
        
        logger.debug(f"No valid sitekey pattern found in URL: {url[:200]}")
        return None
    
    def _extract_sitekey_from_network_data(self, data: Dict) -> Optional[str]:
        """Extract sitekey from network request/response data"""
        # Check URL first (most reliable) - prioritize Turnstile URLs
        url = data.get('url', '')
        
        # Always check Turnstile URLs first as they're most reliable
        if 'turnstile' in url.lower() and '0x' in url.lower():
            logger.debug(f"Checking Turnstile URL for sitekey: {url[:200]}")
            sitekey = self._extract_sitekey_from_url(url)
            if sitekey and self._is_valid_turnstile_sitekey(sitekey):
                return sitekey
        
        # Check other URLs too, but validate
        sitekey = self._extract_sitekey_from_url(url)
        if sitekey and self._is_valid_turnstile_sitekey(sitekey):
            return sitekey
        
        # Check post data (only if from Turnstile-related requests)
        post_data = data.get('post_data', '')
        if post_data and 'turnstile' in url.lower():
            # Look for sitekey in alphanumeric format
            sitekey_match = re.search(r'0x[0-9A-Za-z]{20,}', post_data, re.IGNORECASE)
            if sitekey_match:
                candidate = sitekey_match.group(0)
                if self._is_valid_turnstile_sitekey(candidate):
                    return candidate
            
            # Look for sitekey parameter
            sitekey_match = re.search(r'sitekey["\']?\s*[:=]\s*["\']?([^"\'\s]+)', post_data, re.IGNORECASE)
            if sitekey_match:
                candidate = sitekey_match.group(1)
                if self._is_valid_turnstile_sitekey(candidate):
                    return candidate
        
        # Check response body (only if from Turnstile-related requests)
        body = data.get('body', '')
        if body and 'turnstile' in url.lower():
            sitekey_match = re.search(r'0x[0-9A-Za-z]{20,}', body, re.IGNORECASE)
            if sitekey_match:
                candidate = sitekey_match.group(0)
                if self._is_valid_turnstile_sitekey(candidate):
                    return candidate
            
            sitekey_match = re.search(r'sitekey["\']?\s*[:=]\s*["\']?([^"\'\s]+)', body, re.IGNORECASE)
            if sitekey_match:
                candidate = sitekey_match.group(1)
                if self._is_valid_turnstile_sitekey(candidate):
                    return candidate
        
        # Check headers
        headers = data.get('headers', {})
        for key, value in headers.items():
            if 'sitekey' in key.lower():
                if self._is_valid_turnstile_sitekey(str(value)):
                    return str(value)
            # Check header value for sitekey pattern
            sitekey_match = re.search(r'0x[0-9A-Za-z]{20,}', str(value), re.IGNORECASE)
            if sitekey_match:
                candidate = sitekey_match.group(0)
                if self._is_valid_turnstile_sitekey(candidate):
                    return candidate
        
        return None
    
    async def get_sitekey(self, page: Page, wait_time: int = 5000) -> Optional[str]:
        """
        Main method to get sitekey from network traffic
        Returns the sitekey string or None if not found
        
        Args:
            page: Playwright page object
            wait_time: How long to wait for network requests (ms)
        """
        # Check if we already found the sitekey
        if self.sitekey_from_network:
            logger.info(f"Sitekey already found via network monitoring: {self.sitekey_from_network}")
            return self.sitekey_from_network
        
        # Check already captured requests first (in case monitoring was set up earlier)
        if self.captured_requests:
            logger.info(f"Checking {len(self.captured_requests)} already captured network requests...")
            
            # First pass: prioritize Turnstile URLs
            turnstile_requests = []
            other_requests = []
            for req in self.captured_requests:
                url = req.get('url', '')
                if 'turnstile' in url.lower():
                    turnstile_requests.append(req)
                else:
                    other_requests.append(req)
            
            # Check Turnstile requests first (most reliable)
            for i, req in enumerate(turnstile_requests):
                url = req.get('url', '')
                logger.info(f"🔍 Checking Turnstile request #{i+1}: {url[:200]}...")
                sitekey = self._extract_sitekey_from_network_data(req)
                if sitekey and self._is_valid_turnstile_sitekey(sitekey):
                    logger.info(f"✅ Found valid sitekey in Turnstile request #{i+1}: {sitekey}")
                    self.sitekey_from_network = sitekey
                    return sitekey
            
            # Fallback: check other requests
            for i, req in enumerate(other_requests):
                sitekey = self._extract_sitekey_from_network_data(req)
                if sitekey and self._is_valid_turnstile_sitekey(sitekey):
                    logger.info(f"✅ Found valid sitekey in other request #{i+1}: {sitekey}")
                    self.sitekey_from_network = sitekey
                    return sitekey
        
        # Set up network monitoring if not already done
        await self.setup_network_monitoring(page)
        
        # Wait for network requests to be captured
        await page.wait_for_timeout(wait_time)
        
        # Check if we got sitekey from network
        if self.sitekey_from_network:
            logger.info(f"Sitekey found via network monitoring: {self.sitekey_from_network}")
            return self.sitekey_from_network
        
        # Check captured requests one more time (with validation)
        if self.captured_requests:
            logger.info(f"Final check: validating {len(self.captured_requests)} captured network requests...")
            
            # Prioritize Turnstile URLs
            turnstile_requests = [r for r in self.captured_requests if 'turnstile' in r.get('url', '').lower()]
            other_requests = [r for r in self.captured_requests if r not in turnstile_requests]
            
            for req in turnstile_requests + other_requests:
                sitekey = self._extract_sitekey_from_network_data(req)
                if sitekey and self._is_valid_turnstile_sitekey(sitekey):
                    logger.info(f"✅ Found valid sitekey in captured request: {sitekey}")
                    self.sitekey_from_network = sitekey
                    return sitekey
        
        return None


# Example usage
async def test_sitekey_extraction():
    """Test the sitekey extraction"""
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        
        # Extract domain from target URL for session management
        target_url = "https://ecorp.sos.ga.gov/BusinessSearch"
        parsed_url = urlparse(target_url)
        domain = parsed_url.netloc  # e.g., 'ecorp.sos.ga.gov'
        
        # Try to load existing session
        logger.info(f"🔍 Checking for saved Cloudflare session for {domain}...")
        context = await load_cloudflare_session(browser, domain)
        
        if context:
            # Session loaded, check if it's still valid
            page = await context.new_page()
            logger.info("📋 Testing loaded session...")
            
            # Set up network monitoring
            extractor = CloudflareTurnstileExtractor()
            await extractor.setup_network_monitoring(page)
            
            # Navigate and check if challenge appears
            await page.goto(target_url)
            await page.wait_for_load_state("domcontentloaded")
            
            # Check if session is valid (no challenge)
            session_valid = await is_session_valid(page)
            if session_valid:
                logger.info("✅ Saved session is still valid! Skipping Cloudflare challenge.")
                print("✅ Using saved session - no challenge needed!")
                # Set extractor for showing captured requests
                extractor = CloudflareTurnstileExtractor()
                # Skip to end (show requests and close) - need_to_solve already False
                need_to_solve = False
            else:
                logger.info("⚠️ Saved session expired or invalid. Will solve challenge...")
                print("⚠️ Session expired - will solve Cloudflare challenge")
                # Close this context and create a new one for solving
                await context.close()
                context = None  # Mark as needing new session
                need_to_solve = True
        
        if not context:
            need_to_solve = True
            # No saved session or session expired - create new context
            logger.info("🆕 Creating new browser context...")
            context = await browser.new_context()
            page = await context.new_page()
            
            # Initialize extractor BEFORE navigating
            extractor = CloudflareTurnstileExtractor()
            
            # Set up network monitoring BEFORE navigation to catch all requests
            await extractor.setup_network_monitoring(page)
            
            # Navigate to GA SOS page
            logger.info(f"Navigating to {target_url}...")
            await page.goto(target_url)
            await page.wait_for_load_state("domcontentloaded")
        
        # Inject script to intercept turnstile.render for Cloudflare Challenge pages (only if needed)
        logger.info("Injecting script to intercept turnstile.render parameters...")
        await page.evaluate("""
            window.turnstileParams = null;
            const interval = setInterval(() => {
                if (window.turnstile) {
                    clearInterval(interval);
                    const originalRender = window.turnstile.render;
                    window.turnstile.render = function(container, options) {
                        // Capture parameters needed for Cloudflare Challenge pages
                        window.turnstileParams = {
                            sitekey: options.sitekey,
                            action: options.action || null,
                            cData: options.cData || null,
                            chlPageData: options.chlPageData || null,
                            callback: options.callback || null
                        };
                        console.log('Turnstile params captured:', window.turnstileParams);
                        // Call original render if it exists
                        if (originalRender) {
                            return originalRender.call(this, container, options);
                        }
                        return 'foo';
                    };
                }
            }, 10);
        """)
        
        # Wait for network requests and dynamic content
        logger.info("Waiting for network requests and dynamic content...")
        await page.wait_for_timeout(10000)
        
        # Only proceed with challenge solving if needed
        if not need_to_solve:
            logger.info("⏭️ Skipping challenge solving (valid session)")
        
        # Extract sitekey (only if challenge detected)
        sitekey = await extractor.get_sitekey(page) if need_to_solve else None
        
        # Get intercepted turnstile parameters
        turnstile_params = await page.evaluate("() => window.turnstileParams") if need_to_solve else None
        if turnstile_params:
            logger.info(f"Captured turnstile parameters: {turnstile_params}")
            print(f"\n📋 Captured Turnstile parameters:")
            print(f"   sitekey: {turnstile_params.get('sitekey', 'N/A')}")
            print(f"   action: {turnstile_params.get('action', 'N/A')}")
            print(f"   cData: {turnstile_params.get('cData', 'N/A')[:50] if turnstile_params.get('cData') else 'N/A'}...")
            print(f"   chlPageData: {turnstile_params.get('chlPageData', 'N/A')[:50] if turnstile_params.get('chlPageData') else 'N/A'}...")
        else:
            turnstile_params = None
            logger.info("No turnstile parameters intercepted (may be standalone captcha)")
        
        if sitekey and need_to_solve:
            print(f"\n✅ Sitekey extracted successfully: {sitekey}")
            
            # Initialize 2captcha solver
            api_key = os.getenv('TWOCAPTCHA_API_KEY')  # Use standard env var name
            if api_key and TWOCAPTCHA_AVAILABLE:
                solver = TwoCaptcha(api_key)
                print(f"✓ 2captcha API key loaded: {api_key[:10]}...")
            else:
                solver = None
                if not TWOCAPTCHA_AVAILABLE:
                    print("⚠ 2captcha library not available. Install with: pip install 2captcha-python")
                else:
                    print("⚠ 2captcha API key not found. CAPTCHA solving will be disabled.")
            
            # Solve CAPTCHA if solver is available
            captured_token = None
            if solver:
                try:
                    # Extract base domain URL ONLY (without any path) - REQUIRED for 2captcha
                    parsed_url = urlparse(page.url)
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"  # Base domain only, no path
                    
                    logger.info("Submitting CAPTCHA to 2captcha...")
                    logger.info(f"  Sitekey: {sitekey}")
                    logger.info(f"  Current page URL: {page.url}")
                    logger.info(f"  Using base URL (for pageurl param): {base_url}")
                    
                    # First, let's check the 2captcha balance to verify API key
                    try:
                        balance = solver.balance()
                        logger.info(f"2captcha balance: ${balance}")
                        print(f"📊 2captcha balance: ${balance}")
                    except Exception as balance_error:
                        logger.warning(f"Could not check balance: {str(balance_error)}")
                    
      
                    
                    import requests
                    logger.info("Using API v2 DIRECT call (for Cloudflare Challenge pages)...")
                    
                    browser_user_agent = await page.evaluate("() => navigator.userAgent")
                    logger.info(f"  Browser User-Agent: {browser_user_agent[:50]}...")
                    
                    task_payload = {
                        "type": "TurnstileTaskProxyless",
                        "websiteURL": base_url,  # Base domain only
                        "websiteKey": sitekey
                    }
                    
             
                    if browser_user_agent:
                        task_payload['userAgent'] = browser_user_agent
                        logger.info(f"  Sending browser User-Agent to 2captcha for consistency")
                    
                    # Add Cloudflare Challenge parameters if available
                    if turnstile_params:
                        if turnstile_params.get('action'):
                            task_payload['action'] = turnstile_params['action']
                            logger.info(f"  Adding action: {turnstile_params['action']}")
                        if turnstile_params.get('cData'):
                            task_payload['data'] = turnstile_params['cData']
                            logger.info(f"  Adding cData: {turnstile_params['cData'][:50]}...")
                        if turnstile_params.get('chlPageData'):
                            task_payload['pagedata'] = turnstile_params['chlPageData']
                            logger.info(f"  Adding chlPageData: {turnstile_params['chlPageData'][:50]}...")
                    
                    # API v2 request payload
                    api_v2_payload = {
                        "clientKey": api_key,
                        "task": task_payload
                    }
                    
                    logger.info(f"  Task type: TurnstileTaskProxyless")
                    logger.info(f"  websiteURL: {base_url}")
                    logger.info(f"  websiteKey: {sitekey}")
                    logger.info(f"  Has challenge params: {bool(turnstile_params and (turnstile_params.get('action') or turnstile_params.get('cData')))}")
                    
                    # Step 1: Create task using API v2
                    create_task_url = "https://api.2captcha.com/createTask"
                    logger.info(f"Submitting to API v2: {create_task_url}")
                    
                    submit_response = requests.post(
                        create_task_url,
                        json=api_v2_payload,
                        headers={'Content-Type': 'application/json'},
                        timeout=30
                    )
                    submit_response.raise_for_status()
                    
                    submit_result = submit_response.json()
                    logger.info(f"CreateTask response: {submit_result}")
                    
                    if submit_result.get('errorId') != 0:
                        error_code = submit_result.get('errorCode', 'Unknown')
                        error_description = submit_result.get('errorDescription', 'No description')
                        raise Exception(f"2captcha createTask failed: {error_code} - {error_description}")
                    
                    task_id = submit_result.get('taskId')
                    if not task_id:
                        raise Exception("No taskId returned from 2captcha")
                    
                    logger.info(f"✅ Task created successfully. Task ID: {task_id}")
                    print(f"📝 Task ID: {task_id}")
                    print(f"⏳ Waiting for solution (this may take 15-60 seconds)...")
                    
                    # Step 2: Poll for result using API v2
                    get_result_url = "https://api.2captcha.com/getTaskResult"
                    max_attempts = 30  # Poll for up to 30 attempts (2.5 minutes)
                    poll_interval = 5  # Wait 5 seconds between polls
                    
                    for attempt in range(max_attempts):
                        time.sleep(poll_interval)
                        
                        result_payload = {
                            "clientKey": api_key,
                            "taskId": task_id
                        }
                        
                        result_response = requests.post(
                            get_result_url,
                            json=result_payload,
                            headers={'Content-Type': 'application/json'},
                            timeout=30
                        )
                        result_response.raise_for_status()
                        
                        result_data = result_response.json()
                        logger.debug(f"Poll attempt {attempt + 1}/{max_attempts}: {result_data}")
                        
                        status = result_data.get('status')
                        if status == 'ready':
                            solution = result_data.get('solution', {})
                            captured_token = solution.get('token')
                            if captured_token:
                                print(f"\n✅ CAPTCHA solved! Token: {captured_token[:50]}...")
                                logger.info(f"✅ CAPTCHA token captured: {captured_token[:50]}...")
                                
                                # Also capture userAgent if provided (for challenge pages)
                                user_agent = solution.get('userAgent')
                                if user_agent:
                                    logger.info(f"  userAgent: {user_agent}")
                                
                                # Inject token immediately after receiving it
                                logger.info("🔧 Injecting token into Cloudflare challenge page...")
                                try:
                                    # User-Agent consistency check
                                    # Since we sent our browser's User-Agent to 2captcha, they should return the same one
                                    if user_agent:
                                        logger.info(f"  2captcha returned User-Agent: {user_agent[:50]}...")
                                        current_ua = await page.evaluate("() => navigator.userAgent")
                                        
                                        if current_ua != user_agent:
                                            logger.warning(f"  ⚠ User-Agent mismatch! This may cause Cloudflare to reject the token.")
                                            logger.warning(f"     Browser: {current_ua}")
                                            logger.warning(f"     2captcha: {user_agent}")
                                            logger.info("  Attempting to override navigator.userAgent...")
                                            # Try to override navigator.userAgent (limited effectiveness but worth trying)
                                            await page.evaluate("""(ua) => {
                                                try {
                                                    Object.defineProperty(navigator, 'userAgent', {
                                                        get: function() { return ua; },
                                                        configurable: true
                                                    });
                                                    console.log('✅ navigator.userAgent overridden');
                                                } catch(e) {
                                                    console.error('❌ Failed to override userAgent:', e);
                                                }
                                            }""", user_agent)
                                        else:
                                            logger.info("  ✅ User-Agent matches - perfect!")
                                    
                                    # Inject token via callback function (recommended method for Cloudflare Challenge pages)
                                    # Pass token as argument to avoid escaping issues
                                    injection_result = await page.evaluate("""(token) => {
                                        try {
                                            // Get the callback function from captured turnstile params
                                            if (window.turnstileParams && window.turnstileParams.callback) {
                                                const callback = window.turnstileParams.callback;
                                                if (typeof callback === 'function') {
                                                    // Call the callback with the token
                                                    callback(token);
                                                    console.log('✅ Token injected via callback function');
                                                    return { success: true, method: 'callback' };
                                                } else {
                                                    console.error('❌ Callback is not a function');
                                                    return { success: false, error: 'Callback is not a function' };
                                                }
                                            } else {
                                                // Fallback: try to find and use turnstile.execute if available
                                                if (window.turnstile && typeof window.turnstile.execute === 'function') {
                                                    // Try to find widget ID (might be stored in a variable or DOM)
                                                    console.log('⚠ Callback not found, trying turnstile.execute...');
                                                    return { success: false, method: 'execute', note: 'Callback not found, trying execute method' };
                                                } else {
                                                    console.error('❌ No callback or execute method available');
                                                    return { success: false, error: 'No callback or execute method available' };
                                                }
                                            }
                                        } catch (error) {
                                            console.error('❌ Error injecting token:', error);
                                            return { success: false, error: error.toString() };
                                        }
                                    }""", captured_token)
                                    
                                    if injection_result.get('success'):
                                        logger.info(f"✅ Token successfully injected via {injection_result.get('method', 'unknown')} method")
                                        print(f"✅ Token injected successfully!")
                                        
                                        # Wait for Cloudflare to process the token and redirect/clear challenge
                                        logger.info("⏳ Waiting for Cloudflare to process token (3-5 seconds)...")
                                        await page.wait_for_timeout(4000)
                                        
                                        # Check if we're still on challenge page or if we've been redirected
                                        current_url = page.url
                                        logger.info(f"  Current URL after injection: {current_url}")
                                        
                                        # Check if challenge was cleared (page content changed or redirected)
                                        challenge_cleared = False
                                        try:
                                            # Wait for navigation or content change
                                            await page.wait_for_load_state("networkidle", timeout=5000)
                                            logger.info("✅ Page loaded after token injection")
                                            
                                            # Verify challenge is actually cleared
                                            if await is_session_valid(page):
                                                challenge_cleared = True
                                                logger.info("✅ Cloudflare challenge successfully bypassed!")
                                                print("✅ Challenge cleared! Saving session...")
                                                
                                                # Save session for future use
                                                if await save_cloudflare_session(context, domain):
                                                    print(f"💾 Session saved for {domain}")
                                                else:
                                                    logger.warning("Failed to save session, but challenge was cleared")
                                            else:
                                                logger.warning("⚠️ Challenge may not be fully cleared")
                                        except Exception as e:
                                            logger.debug(f"Error checking challenge status: {str(e)}")
                                            # Try to save session anyway (might still be valid)
                                            try:
                                                if await is_session_valid(page):
                                                    challenge_cleared = True
                                                    await save_cloudflare_session(context, domain)
                                            except:
                                                pass
                                            
                                    else:
                                        error_msg = injection_result.get('error', 'Unknown error')
                                        logger.warning(f"⚠ Token injection issue: {error_msg}")
                                        print(f"⚠ Warning: Token injection reported issue: {error_msg}")
                                        
                                        # Try fallback method if callback didn't work
                                        if injection_result.get('method') == 'execute':
                                            logger.info("🔄 Attempting fallback: turnstile.execute method...")
                                            # Try to find widget ID and execute
                                            execute_result = await page.evaluate("""(token) => {
                                                try {
                                                    if (window.turnstile && typeof window.turnstile.execute === 'function') {
                                                        // Try to find any turnstile widget IDs
                                                        const widgets = document.querySelectorAll('[data-sitekey]');
                                                        if (widgets.length > 0) {
                                                            // Execute on first widget found
                                                            const widgetId = window.turnstile.render(widgets[0]);
                                                            window.turnstile.execute(widgetId, token);
                                                            return { success: true, method: 'execute' };
                                                        }
                                                    }
                                                    return { success: false, error: 'No widgets found for execute' };
                                                } catch (error) {
                                                    return { success: false, error: error.toString() };
                                                }
                                            }""", captured_token)
                                            
                                            if execute_result.get('success'):
                                                logger.info("✅ Token injected via execute method")
                                                await page.wait_for_timeout(4000)
                                            else:
                                                logger.warning(f"⚠ Execute method also failed: {execute_result.get('error')}")
                                                print(f"⚠ Warning: Could not inject token automatically. You may need to inject it manually.")
                                
                                except Exception as injection_error:
                                    logger.error(f"❌ Error during token injection: {str(injection_error)}")
                                    logger.exception(injection_error)
                                    print(f"❌ Error injecting token: {str(injection_error)}")
                                
                                break
                            else:
                                raise Exception("No token in solution")
                        elif status == 'processing':
                            # Still processing
                            if (attempt + 1) % 3 == 0:  # Log every 3rd attempt
                                logger.info(f"Still processing... ({attempt + 1}/{max_attempts})")
                            continue
                        else:
                            error_code = result_data.get('errorCode', 'Unknown')
                            error_description = result_data.get('errorDescription', 'Unknown error')
                            raise Exception(f"2captcha polling failed: {error_code} - {error_description}")
                    else:
                        # Loop completed without break (timeout)
                        raise Exception(f"Timeout waiting for CAPTCHA solution after {max_attempts * poll_interval} seconds")
                        
                except Exception as e:
                    error_msg = str(e)
                    error_type = type(e).__name__
                    
                    logger.error("=" * 70)
                    # Get base URL for error logging
                    parsed_url = urlparse(page.url)
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"  # Base domain only
                    
                    logger.error("2CAPTCHA ERROR DETAILS:")
                    logger.error(f"  Error Type: {error_type}")
                    logger.error(f"  Error Message: {error_msg}")
                    logger.error(f"  Sitekey: {sitekey}")
                    logger.error(f"  Current page URL: {page.url}")
                    logger.error(f"  Base URL sent to 2captcha: {base_url}")
                    logger.error("=" * 70)
                    
                    if hasattr(e, 'args') and e.args:
                        logger.error(f"  Exception args: {e.args}")
                    if hasattr(e, '__dict__'):
                        logger.error(f"  Exception attributes: {e.__dict__}")
                    
                    print(f"\n❌ Error solving CAPTCHA: {error_msg}")
                    print(f"   Error Type: {error_type}")
                    print(f"\n📋 Details logged. Check the logs above for full error information.")
                    
                    # Try direct API call to get raw error
                    try:
                        import requests
                        # Extract base URL again (domain only, no path)
                        parsed_url = urlparse(page.url)
                        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"  # Base domain only
                        
                        logger.info("\n🔍 Making direct API call to check exact error...")
                        logger.info(f"  Parameters for direct API call:")
                        logger.info(f"    sitekey: {sitekey}")
                        logger.info(f"    pageurl: {base_url}  <-- Base domain only")
                        submit_response = requests.post(
                            "https://2captcha.com/in.php",
                            data={
                                'key': api_key,
                                'method': 'turnstile',
                                'sitekey': sitekey,
                                'pageurl': base_url,  # Base domain only: https://ecorp.sos.ga.gov/
                                'json': 1
                            },
                            timeout=30
                        )
                        logger.info(f"Direct API response status: {submit_response.status_code}")
                        logger.info(f"Direct API response text: {submit_response.text}")
                        direct_result = submit_response.json()
                        logger.info(f"Direct API JSON response: {direct_result}")
                        
                        if direct_result.get('status') == 0:
                            error_text = direct_result.get('error_text', 'No error text provided')
                            request_msg = direct_result.get('request', 'Unknown error')
                            print(f"\n🔍 Direct API Error:")
                            print(f"   Error: {request_msg}")
                            print(f"   Details: {error_text}")
                            logger.error(f"Direct API error: {request_msg}")
                            logger.error(f"Direct API error text: {error_text}")
                    except Exception as direct_error:
                        logger.error(f"Could not make direct API call: {str(direct_error)}")
            else:
                print("\n⚠ Skipping CAPTCHA solving (no API key)")
        elif not need_to_solve:
            # Valid session, no challenge to solve
            logger.info("Session is valid, no challenge detected")
            print("\n✅ No challenge detected - using saved session")
        else:
            print("\n❌ Could not extract sitekey")
            
        # Show captured network requests
        if 'extractor' in locals() and extractor.captured_requests:
            print(f"\n📡 Captured {len(extractor.captured_requests)} network requests:")
            for i, req in enumerate(extractor.captured_requests[:10]):  # Show first 10
                print(f"  Request #{i+1}: {req['method']} {req['url'][:150]}...")
        
        # Close context if we created one
        if context:
            await context.close()
        
        # Keep browser open for inspection
        input("\nPress Enter to close browser...")
        
        await browser.close()


async def solve_cloudflare_challenge(page: Page, context: BrowserContext, domain: str, sitekey: str, turnstile_params: Optional[Dict] = None) -> bool:
    """
    Solve Cloudflare challenge using 2captcha API
    
    Returns:
        bool: True if challenge was solved successfully, False otherwise
    """
    api_key = os.getenv('TWOCAPTCHA_API_KEY')
    if not api_key or not TWOCAPTCHA_AVAILABLE:
        logger.warning("2captcha not available - cannot solve challenge")
        return False
    
    import requests
    
    try:
        parsed_url = urlparse(page.url)
        # Use the full page URL, not just base URL (2captcha may need the exact page)
        website_url = page.url
        
        browser_user_agent = await page.evaluate("() => navigator.userAgent")
        
        task_payload = {
            "type": "TurnstileTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": sitekey
        }
        
        if browser_user_agent:
            task_payload['userAgent'] = browser_user_agent
        
        # Add optional parameters only if they exist and are not None/null
        if turnstile_params:
            action = turnstile_params.get('action')
            if action and action not in [None, 'null', '']:
                task_payload['action'] = action
            
            c_data = turnstile_params.get('cData')
            if c_data and c_data not in [None, 'null', '']:
                task_payload['data'] = c_data
            
            chl_page_data = turnstile_params.get('chlPageData')
            if chl_page_data and chl_page_data not in [None, 'null', '']:
                task_payload['pagedata'] = chl_page_data
        
        logger.debug(f"Task payload: {task_payload}")
        logger.info(f"Sending to 2captcha: websiteURL={website_url}, websiteKey={sitekey}")
        
        # Create task
        request_payload = {"clientKey": api_key, "task": task_payload}
        logger.debug(f"Full request payload: {request_payload}")
        
        create_response = requests.post(
            "https://api.2captcha.com/createTask",
            json=request_payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        create_response.raise_for_status()
        create_result = create_response.json()
        
        logger.debug(f"2captcha response: {create_result}")
        
        if create_result.get('errorId') != 0:
            error_desc = create_result.get('errorDescription', 'Unknown error')
            error_code = create_result.get('errorCode')
            logger.error(f"2captcha API error - Code: {error_code}, Description: {error_desc}")
            logger.error(f"Request payload sent: {request_payload}")
            raise Exception(f"2captcha createTask failed: {error_desc}")
        
        task_id = create_result.get('taskId')
        logger.info(f"✅ Task created: {task_id}")
        
        # Poll for result
        for attempt in range(30):
            await asyncio.sleep(5)
            result_response = requests.post(
                "https://api.2captcha.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            result_data = result_response.json()
            status = result_data.get('status')
            
            if status == 'ready':
                solution = result_data.get('solution', {})
                token = solution.get('token')
                if token:
                    # Inject token
                    user_agent = solution.get('userAgent')
                    if user_agent:
                        current_ua = await page.evaluate("() => navigator.userAgent")
                        if current_ua != user_agent:
                            await page.evaluate("""(ua) => {
                                Object.defineProperty(navigator, 'userAgent', {
                                    get: function() { return ua; },
                                    configurable: true
                                });
                            }""", user_agent)
                    
                    # Inject via callback
                    injection_result = await page.evaluate("""(token) => {
                        if (window.turnstileParams && window.turnstileParams.callback) {
                            const callback = window.turnstileParams.callback;
                            if (typeof callback === 'function') {
                                callback(token);
                                return { success: true };
                            }
                        }
                        return { success: false };
                    }""", token)
                    
                    if injection_result.get('success'):
                        await page.wait_for_timeout(4000)
                        if await is_session_valid(page):
                            await save_cloudflare_session(context, domain)
                            logger.info("✅ Challenge solved and session saved")
                            return True
            elif status == 'processing':
                continue
            else:
                raise Exception(f"2captcha error: {result_data.get('errorDescription')}")
        
        raise Exception("Timeout waiting for CAPTCHA solution")
        
    except Exception as e:
        logger.error(f"Error solving challenge: {str(e)}")
        return False


async def get_bypassed_page(
    target_url: str = "https://ecorp.sos.ga.gov/BusinessSearch",
    headless: bool = False,
    playwright_instance = None
) -> tuple:
    """
    Get a Playwright page after bypassing Cloudflare challenge.
    Returns browser, context, and page objects for continued use.
    
    Args:
        target_url: URL to navigate to
        headless: Whether to run browser in headless mode
        playwright_instance: Optional playwright instance (if None, creates new)
        
    Returns:
        tuple: (playwright, browser, context, page) - All ready for scraping
    """
    from playwright.async_api import async_playwright
    
    # Get or create playwright instance
    if playwright_instance is None:
        playwright_instance = await async_playwright().start()
    
    browser = await playwright_instance.chromium.launch(headless=headless)
    
    # Extract domain from target URL for session management
    parsed_url = urlparse(target_url)
    domain = parsed_url.netloc
    
    # Try to load existing session
    logger.info(f"🔍 Checking for saved Cloudflare session for {domain}...")
    context = await load_cloudflare_session(browser, domain)
    
    if context:
        page = await context.new_page()
        await page.goto(target_url)
        await page.wait_for_load_state("domcontentloaded")
        
        if await is_session_valid(page):
            logger.info("✅ Saved session is still valid!")
            return (playwright_instance, browser, context, page)
        else:
            await context.close()
            context = None
    
    if not context:
        context = await browser.new_context()
        page = await context.new_page()
        
        extractor = CloudflareTurnstileExtractor()
        await extractor.setup_network_monitoring(page)
        
        await page.goto(target_url)
        await page.wait_for_load_state("domcontentloaded")
        
        # Inject turnstile interceptor
        await page.evaluate("""
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
        """)
        
        await page.wait_for_timeout(10000)
        
        sitekey = await extractor.get_sitekey(page)
        turnstile_params = await page.evaluate("() => window.turnstileParams")
        
        if sitekey:
            logger.info("🔧 Solving Cloudflare challenge...")
            await solve_cloudflare_challenge(page, context, domain, sitekey, turnstile_params)
    
    return (playwright_instance, browser, context, page)


if __name__ == "__main__":
    import asyncio
    
    # Run sitekey extraction test
    asyncio.run(test_sitekey_extraction())
