"""
Cloudflare Session Management Utilities
Helper functions for saving and loading Cloudflare bypass sessions
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger
from playwright.async_api import BrowserContext, Page


SESSION_DIR = Path(".sessions")
SESSION_DIR.mkdir(exist_ok=True)


def get_session_path(domain: str) -> Path:
    """Get the session file path for a given domain"""
    safe_domain = domain.replace(".", "_")
    return SESSION_DIR / f"cloudflare_{safe_domain}.json"


async def save_cloudflare_session(context: BrowserContext, domain: str) -> bool:
    """
    Save Cloudflare bypass session (cookies and storage) to file
    
    Args:
        context: Playwright browser context with active session
        domain: Domain name (e.g., 'ecorp.sos.ga.gov') for session filename
        
    Returns:
        bool: True if saved successfully, False otherwise
    """
    try:
        session_path = get_session_path(domain)
        
        # Save storage state (cookies, localStorage, etc.)
        await context.storage_state(path=str(session_path))
        
        logger.info(f"✅ Cloudflare session saved to: {session_path}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save Cloudflare session: {str(e)}")
        logger.exception(e)
        return False


async def load_cloudflare_session(browser, domain: str) -> Optional[BrowserContext]:
    """
    Load Cloudflare bypass session and create a new context with it
    
    Args:
        browser: Playwright browser instance
        domain: Domain name (e.g., 'ecorp.sos.ga.gov')
        
    Returns:
        BrowserContext if session exists and loaded, None otherwise
    """
    try:
        session_path = get_session_path(domain)
        
        if not session_path.exists():
            logger.debug(f"No saved session found for {domain}")
            return None
        
        # Check if session file is valid JSON
        try:
            with open(session_path, 'r') as f:
                session_data = json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Session file corrupted, removing: {session_path}")
            session_path.unlink()
            return None
        
        # Check if session has cookies (especially cf_clearance)
        cookies = session_data.get('cookies', [])
        has_cf_clearance = any(c.get('name') == 'cf_clearance' for c in cookies)
        
        if not has_cf_clearance:
            logger.debug(f"Session file exists but no cf_clearance cookie found")
            return None
        
        # Create context with saved storage state
        context = await browser.new_context(storage_state=str(session_path))
        logger.info(f"✅ Loaded Cloudflare session from: {session_path}")
        logger.info(f"   Found {len(cookies)} cookies")
        
        return context
        
    except Exception as e:
        logger.error(f"❌ Failed to load Cloudflare session: {str(e)}")
        logger.exception(e)
        return None


async def is_session_valid(page: Page, challenge_url_pattern: str = "challenges.cloudflare.com") -> bool:
    """
    Check if the current session is still valid (no Cloudflare challenge)
    
    Args:
        page: Playwright page object
        challenge_url_pattern: Pattern to detect challenge pages (default: challenges.cloudflare.com)
        
    Returns:
        bool: True if session is valid (no challenge), False if challenge detected
    """
    try:
        current_url = page.url
        
        # Check if we're on a Cloudflare challenge page
        if challenge_url_pattern in current_url:
            logger.debug(f"Challenge detected in URL: {current_url}")
            return False
        
        # Check for challenge indicators in page content
        try:
            # Wait a bit for any redirects/challenges to appear
            await page.wait_for_timeout(2000)
            
            # Check for common Cloudflare challenge indicators
            challenge_indicators = [
                "checking your browser",
                "just a moment",
                "cf-challenge",
                "cf-browser-verification",
                "turnstile"
            ]
            
            page_content = await page.content()
            page_text = (await page.evaluate("() => document.body.innerText")).lower()
            
            for indicator in challenge_indicators:
                if indicator in page_text.lower() or indicator in page_content.lower():
                    logger.debug(f"Challenge indicator found: {indicator}")
                    return False
                    
        except Exception as e:
            logger.debug(f"Error checking page content: {str(e)}")
            # If we can't check, assume valid (better to be permissive)
        
        # Check current URL again after wait
        final_url = page.url
        if challenge_url_pattern in final_url:
            logger.debug(f"Challenge detected after wait: {final_url}")
            return False
        
        logger.debug("Session appears valid (no challenge detected)")
        return True
        
    except Exception as e:
        logger.error(f"Error validating session: {str(e)}")
        # On error, assume invalid to be safe
        return False


async def clear_session(domain: str) -> bool:
    """
    Clear (delete) saved session for a domain
    
    Args:
        domain: Domain name
        
    Returns:
        bool: True if cleared successfully, False otherwise
    """
    try:
        session_path = get_session_path(domain)
        
        if session_path.exists():
            session_path.unlink()
            logger.info(f"✅ Cleared session file: {session_path}")
            return True
        else:
            logger.debug(f"No session file to clear: {session_path}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to clear session: {str(e)}")
        return False


def get_session_info(domain: str) -> Optional[Dict[str, Any]]:
    """
    Get information about saved session (without loading it)
    
    Args:
        domain: Domain name
        
    Returns:
        Dict with session info or None if no session exists
    """
    try:
        session_path = get_session_path(domain)
        
        if not session_path.exists():
            return None
        
        with open(session_path, 'r') as f:
            session_data = json.load(f)
        
        cookies = session_data.get('cookies', [])
        cf_cookie = next((c for c in cookies if c.get('name') == 'cf_clearance'), None)
        
        info = {
            'path': str(session_path),
            'exists': True,
            'cookie_count': len(cookies),
            'has_cf_clearance': cf_cookie is not None,
            'file_size': session_path.stat().st_size,
            'modified': session_path.stat().st_mtime
        }
        
        if cf_cookie:
            info['cf_clearance_expires'] = cf_cookie.get('expires', 'session')
        
        return info
        
    except Exception as e:
        logger.error(f"Error getting session info: {str(e)}")
        return None



