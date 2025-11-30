#!/usr/bin/env python3
"""
Facebook About Section Scraper
Extracts company details from Facebook About pages
"""

import asyncio
import pandas as pd
from pathlib import Path
from loguru import logger
from typing import Optional, Dict, List
from datetime import datetime
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
import time
import random

from scrapers import setup_logging


async def human_delay(min_seconds: float = 1.0, max_seconds: float = 3.0):
    """Add human-like delay"""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


async def extract_facebook_about_details(page: Page, facebook_url: str) -> Dict:
    """
    Extract details from Facebook About section
    
    Args:
        page: Playwright page object
        facebook_url: URL of the Facebook page
        
    Returns:
        Dictionary with extracted details
    """
    result = {
        'facebook_url': facebook_url,
        'page_name': None,
        'category': None,
        'description': None,
        'phone': None,
        'email': None,
        'website': None,
        'address': None,
        'city': None,
        'state': None,
        'zip': None,
        'hours': None,
        'founded': None,
        'price_range': None,
        'reviews': None,
        'error': None
    }
    
    try:
        logger.info(f"   🌐 Opening Facebook page: {facebook_url}")
        
        # Navigate to the page
        await page.goto(facebook_url, wait_until='networkidle', timeout=30000)
        await human_delay(2, 4)
        
        # Check if we were redirected to Meta's corporate page
        current_url = page.url
        if 'meta.com' in current_url.lower() or 'about.facebook.com' in current_url.lower():
            logger.warning(f"   ⚠️ Redirected to Meta corporate page: {current_url}")
            logger.info(f"   🔄 Going back to original Facebook URL")
            
            # Try to construct a direct About URL
            # Extract profile ID or page name from original URL
            profile_id = None
            page_name = None
            
            if 'profile.php?id=' in facebook_url:
                import re
                match = re.search(r'profile\.php\?id=(\d+)', facebook_url)
                if match:
                    profile_id = match.group(1)
            elif '/p/' in facebook_url:
                # Extract page name from /p/PageName-123456/ format
                import re
                match = re.search(r'/p/([^/]+)', facebook_url)
                if match:
                    page_name = match.group(1)
            
            # Try direct About URL
            if profile_id:
                about_url = f"https://www.facebook.com/profile.php?id={profile_id}&sk=about"
            elif page_name:
                about_url = f"https://www.facebook.com/{page_name}/about/"
            else:
                # Fallback: try appending /about/ to original URL
                about_url = facebook_url.rstrip('/') + '/about/'
            
            logger.info(f"   🔄 Trying direct About URL: {about_url}")
            try:
                await page.goto(about_url, wait_until='networkidle', timeout=30000)
                await human_delay(3, 5)
                current_url = page.url
                
                # Check if still redirected
                if 'meta.com' in current_url.lower():
                    logger.warning(f"   ⚠️ Still redirected. Facebook may require login or page doesn't exist.")
                    result['error'] = "Redirected to Meta corporate page - may require login"
                    return result
            except Exception as e:
                logger.warning(f"   ⚠️ Could not navigate to About URL: {str(e)}")
        
        # Close login popup if it appears (check multiple times - before and after navigation)
        async def close_login_popup():
            """Helper function to close login popup"""
            try:
                # First, check if login form is visible
                login_form_selectors = [
                    'form[id*="login"]',
                    'form[action*="login"]',
                    '//form[contains(@action, "login")]',
                    '//div[contains(@class, "xod5an3")]//form',
                    '//span[contains(text(), "See more on Facebook")]/ancestor::form',
                    '//span[contains(text(), "Log in to Facebook")]/ancestor::form'
                ]
                
                login_form_visible = False
                for selector in login_form_selectors:
                    try:
                        if selector.startswith('//'):
                            element = page.locator(selector).first
                        else:
                            element = page.locator(selector).first
                        
                        if await element.is_visible(timeout=2000):
                            login_form_visible = True
                            logger.debug(f"   🔍 Login form detected")
                            break
                    except:
                        continue
                
                if not login_form_visible:
                    return False
                
                # Look for close buttons (X buttons, close icons, etc.)
                close_selectors = [
                    # Close buttons with aria-label
                    '//button[@aria-label="Close"]',
                    '//div[@role="button" and contains(@aria-label, "Close")]',
                    '//div[@role="button" and contains(@aria-label, "close")]',
                    # Close icons
                    '//div[contains(@class, "x1ey2m1c")]//button',
                    '//div[contains(@class, "xod5an3")]//button',
                    '//div[@role="dialog"]//button[contains(@aria-label, "Close")]',
                    # Text-based close
                    '//span[contains(text(), "Close")]/ancestor::button',
                    '//span[contains(text(), "✕")]/ancestor::button',
                    # Generic close buttons
                    '[aria-label*="Close"]',
                    '[aria-label*="close"]',
                    # Try clicking outside the form (on overlay)
                    '//div[contains(@class, "x5yr21d")]//div[contains(@class, "x4l50q0")]',
                    # Escape key alternative - click on backdrop
                    '//div[@class="x5yr21d x4l50q0"]'
                ]
                
                for selector in close_selectors:
                    try:
                        if selector.startswith('//'):
                            elements = await page.locator(selector).all()
                        else:
                            elements = [page.locator(selector).first]
                        
                        for element in elements[:5]:
                            try:
                                if await element.is_visible(timeout=2000):
                                    # Check if it's a close button
                                    text = await element.inner_text() or ''
                                    aria_label = await element.get_attribute('aria-label') or ''
                                    role = await element.get_attribute('role') or ''
                                    
                                    # If it's the backdrop/overlay, click it to close
                                    if 'x5yr21d' in selector or 'x4l50q0' in selector:
                                        await element.click()
                                        logger.debug(f"   ✅ Clicked backdrop to close login popup")
                                        await human_delay(1, 2)
                                        return True
                                    
                                    # If it's a close button
                                    if ('close' in text.lower() or 
                                        'close' in aria_label.lower() or 
                                        '✕' in text or
                                        '×' in text or
                                        role == 'button'):
                                        await element.click()
                                        logger.debug(f"   ✅ Closed login popup using: {selector}")
                                        await human_delay(1, 2)
                                        return True
                            except Exception as e:
                                continue
                    except:
                        continue
                
                # If no close button found, try pressing Escape key
                try:
                    await page.keyboard.press('Escape')
                    logger.debug(f"   ✅ Pressed Escape to close login popup")
                    await human_delay(1, 2)
                    return True
                except:
                    pass
                
                return False
            except Exception as e:
                logger.debug(f"   ⚠️ Error closing popup: {str(e)}")
                return False
        
        # Close login popup after initial page load
        await close_login_popup()
        
        # Verify we're on the correct page (not Meta corporate)
        current_url = page.url
        if 'meta.com' in current_url.lower():
            logger.warning(f"   ⚠️ Still on Meta corporate page. Page may require login or be unavailable.")
            result['error'] = "Page redirected to Meta corporate site - may require login"
            return result
        
        # If we're already on About page, continue; otherwise navigate to it
        if 'sk=about' not in current_url and '/about' not in current_url:
            # Try to extract profile ID from URL to construct About URL
            profile_id = None
            page_name = None
            
            if 'profile.php?id=' in current_url or 'profile.php?id=' in facebook_url:
                import re
                match = re.search(r'profile\.php\?id=(\d+)', current_url or facebook_url)
                if match:
                    profile_id = match.group(1)
            elif '/p/' in current_url or '/p/' in facebook_url:
                # Extract from /p/ format
                import re
                match = re.search(r'/p/([^/]+)', current_url or facebook_url)
                if match:
                    page_name = match.group(1)
            
            # Navigate directly to About page (more reliable)
            about_url = None
            if profile_id:
                about_url = f"https://www.facebook.com/profile.php?id={profile_id}&sk=about"
            elif page_name:
                about_url = f"https://www.facebook.com/{page_name}/about/"
            else:
                # Fallback: try appending /about/
                about_url = (current_url or facebook_url).rstrip('/') + '/about/'
            
            logger.info(f"   🔄 Navigating to About page: {about_url}")
            try:
                await page.goto(about_url, wait_until='networkidle', timeout=30000)
                await human_delay(3, 5)
                
                # Close login popup again after navigation to About page
                closed = await close_login_popup()
                if closed:
                    logger.debug(f"   ✅ Closed login popup after navigation")
                
                # Wait a bit more for page to fully load after closing popup
                await human_delay(2, 3)
                
                # Check again if redirected
                current_url = page.url
                if 'meta.com' in current_url.lower():
                    logger.warning(f"   ⚠️ Redirected again. Page may require login.")
                    result['error'] = "Page redirected to Meta corporate site - may require login"
                    return result
                
                # Wait for About page content to load (look for Categories or Contact information heading)
                try:
                    await page.wait_for_selector('//h2[contains(text(), "Categories")]', timeout=10000)
                    logger.debug(f"   ✅ About page content loaded")
                except:
                    try:
                        await page.wait_for_selector('//h2[contains(text(), "Contact information")]', timeout=5000)
                        logger.debug(f"   ✅ About page content loaded (Contact section)")
                    except:
                        logger.debug(f"   ⚠️ About page content may not be fully loaded")
                
                # Scroll down on About page to load all content
                logger.info(f"   📜 Scrolling down on About page to load all content...")
                try:
                    # Scroll gradually to trigger lazy loading
                    for i in range(8):
                        await page.evaluate('window.scrollBy(0, 600)')
                        await human_delay(0.8, 1.5)
                    
                    # Scroll to bottom to ensure all content is loaded
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await human_delay(2, 3)
                    
                    # Scroll back to top to ensure all sections are accessible
                    await page.evaluate('window.scrollTo(0, 0)')
                    await human_delay(1, 2)
                    
                    logger.debug(f"   ✅ Finished scrolling - all content should be visible")
                except Exception as e:
                    logger.debug(f"   ⚠️ Error scrolling: {str(e)}")
            except Exception as e:
                logger.warning(f"   ⚠️ Could not navigate to About page: {str(e)}")
                # Try clicking About tab instead
                about_selectors = [
                    '//a[contains(@href, "sk=about")]',
                    '//a[contains(@href, "/about")]',
                    '//span[contains(text(), "About")]/ancestor::a',
                    '//a[@role="tab" and contains(@href, "about")]'
                ]
                
                for selector in about_selectors:
                    try:
                        element = page.locator(selector).first
                        if await element.is_visible(timeout=3000):
                            await element.click()
                            logger.debug(f"   ✅ Clicked About tab")
                            await human_delay(2, 4)
                            # Close login popup after clicking About tab
                            await close_login_popup()
                            
                            # Wait for About content to load
                            await human_delay(2, 3)
                            
                            # Scroll down on About page to load all content
                            logger.info(f"   📜 Scrolling down on About page to load all content...")
                            try:
                                # Scroll gradually to trigger lazy loading
                                for i in range(8):
                                    await page.evaluate('window.scrollBy(0, 600)')
                                    await human_delay(0.8, 1.5)
                                
                                # Scroll to bottom to ensure all content is loaded
                                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                                await human_delay(2, 3)
                                
                                # Scroll back to top to ensure all sections are accessible
                                await page.evaluate('window.scrollTo(0, 0)')
                                await human_delay(1, 2)
                                
                                logger.debug(f"   ✅ Finished scrolling - all content should be visible")
                            except Exception as e:
                                logger.debug(f"   ⚠️ Error scrolling: {str(e)}")
                            
                            break
                    except:
                        continue
        
        # Extract page name
        try:
            # Try multiple selectors for page name
            name_selectors = [
                'h1',
                '[data-testid="page_name"]',
                '//h1',
                '//span[@dir="auto"]//span[contains(@class, "x1heor9g")]',
                '//div[contains(@class, "x1i10hfl")]//span[contains(@dir, "auto")]'
            ]
            
            for selector in name_selectors:
                try:
                    if selector.startswith('//'):
                        element = page.locator(selector).first
                    else:
                        element = page.locator(selector).first
                    
                    if await element.is_visible(timeout=2000):
                        name_text = await element.inner_text()
                        if name_text and len(name_text.strip()) > 0:
                            result['page_name'] = name_text.strip()
                            logger.debug(f"   ✅ Found page name: {result['page_name']}")
                            break
                except:
                    continue
        except Exception as e:
            logger.debug(f"   ⚠️ Could not extract page name: {str(e)}")
        
        # Extract category (look for "Categories" heading)
        try:
            # Based on actual HTML: h2 "Categories" -> span with class "xzsf02u x6prxxf xvq8zen x126k92a"
            category_selectors = [
                '//h2[contains(text(), "Categories")]/following::span[contains(@class, "xzsf02u") and contains(@class, "x126k92a")]',
                '//h2[contains(text(), "Categories")]/following::span[@dir="auto"]',
                '//span[contains(text(), "Categories")]/following::span[@dir="auto"]'
            ]
            
            for selector in category_selectors:
                try:
                    elements = await page.locator(selector).all()
                    for element in elements[:5]:
                        if await element.is_visible(timeout=2000):
                            category_text = await element.inner_text()
                            if category_text and len(category_text.strip()) > 0 and 'Categor' not in category_text.lower():
                                result['category'] = category_text.strip()
                                logger.debug(f"   ✅ Found category: {result['category']}")
                                break
                    if result['category']:
                        break
                except:
                    continue
        except Exception as e:
            logger.debug(f"   ⚠️ Could not extract category: {str(e)}")
        
        # Extract description
        try:
            desc_selectors = [
                '//div[contains(@data-testid, "about")]//div[contains(@dir, "auto")]',
                '//div[contains(@class, "x1y1aw1k")]//div[contains(@dir, "auto")]',
                '[data-testid="about"]',
                '//span[contains(text(), "About")]/following::div[1]'
            ]
            
            # Filter out login-related text
            login_keywords = ['log in', 'sign up', 'facebook', 'connect with friends', 'password', 'email address', 'contact and basic info']
            
            for selector in desc_selectors:
                try:
                    if selector.startswith('//'):
                        elements = await page.locator(selector).all()
                    else:
                        elements = [page.locator(selector).first]
                    
                    for element in elements[:5]:  # Check first 5 matches
                        if await element.is_visible(timeout=2000):
                            desc_text = await element.inner_text()
                            # Validate it's not login text and is meaningful
                            if desc_text and len(desc_text.strip()) > 20:
                                if not any(keyword in desc_text.lower() for keyword in login_keywords):
                                    result['description'] = desc_text.strip()
                                    logger.debug(f"   ✅ Found description ({len(result['description'])} chars)")
                                    break
                    if result['description']:
                        break
                except:
                    continue
        except Exception as e:
            logger.debug(f"   ⚠️ Could not extract description: {str(e)}")
        
        # Extract contact information (phone, email, website, address)
        try:
            # Wait for Contact information section to be visible
            try:
                await page.wait_for_selector('//h2[contains(text(), "Contact information")]', timeout=5000)
                logger.debug(f"   ✅ Contact information section is visible")
            except:
                logger.debug(f"   ⚠️ Contact information section not found, continuing anyway")
            
            # Extract phone from Contact information section
            # Based on HTML: In ul.x1e56ztr > li > span.x1yc453h containing "+1 770-873-9114", followed by "Mobile"
            phone_selectors = [
                '//h2[contains(text(), "Contact information")]/following::ul[@class="x1e56ztr"]//span[contains(@class, "x1yc453h") and contains(text(), "+")]',
                '//h2[contains(text(), "Contact information")]/following::ul[@class="x1e56ztr"]//span[contains(@class, "x1yc453h")]',
                '//span[contains(text(), "Mobile")]/ancestor::ul//span[contains(@class, "x1yc453h")]',
                '//h2[contains(text(), "Contact information")]/following::div[contains(@class, "xat24cr")]//span[contains(@class, "x1yc453h")]'
            ]
            
            login_keywords = ['log in', 'sign up', 'facebook', 'password', 'email address', 'connect with friends']
            
            for selector in phone_selectors:
                try:
                    elements = await page.locator(selector).all()
                    logger.debug(f"   🔍 Trying phone selector: {selector}, found {len(elements)} elements")
                    for element in elements[:15]:
                        try:
                            if await element.is_visible(timeout=2000):
                                phone_text = await element.inner_text()
                                logger.debug(f"   🔍 Phone candidate: '{phone_text[:50]}'")
                                # Filter out login text
                                if any(kw in phone_text.lower() for kw in login_keywords):
                                    logger.debug(f"   ⚠️ Skipping (login text): {phone_text[:50]}")
                                    continue
                                # Check if it looks like a phone number (must have digits and proper format)
                                import re
                                # More strict pattern: must start with + or digit, have proper phone format
                                phone_pattern = r'\+?1?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}'
                                if re.search(phone_pattern, phone_text) and len(phone_text.strip()) >= 10:
                                    result['phone'] = phone_text.strip()
                                    logger.debug(f"   ✅ Found phone: {result['phone']}")
                                    break
                        except Exception as e:
                            logger.debug(f"   ⚠️ Error checking element: {str(e)}")
                            continue
                    if result['phone']:
                        break
                except Exception as e:
                    logger.debug(f"   ⚠️ Error with selector {selector}: {str(e)}")
                    continue
            
            if not result['phone']:
                logger.debug(f"   ⚠️ Phone not found - trying alternative method")
                # Try searching all text on page for phone pattern
                try:
                    page_text = await page.content()
                    import re
                    phone_pattern = r'\+1[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{4}'
                    matches = re.findall(phone_pattern, page_text)
                    if matches:
                        # Filter out matches that are in login forms
                        for match in matches:
                            # Check if match is near login keywords
                            match_index = page_text.find(match)
                            context = page_text[max(0, match_index-100):match_index+100].lower()
                            if not any(kw in context for kw in login_keywords):
                                result['phone'] = match.strip()
                                logger.debug(f"   ✅ Found phone via text search: {result['phone']}")
                                break
                except Exception as e:
                    logger.debug(f"   ⚠️ Alternative phone search failed: {str(e)}")
            
            # Extract address from Contact information section
            # Based on HTML: span with class "xzsf02u x6prxxf xvq8zen x126k92a x12nagc" containing address
            # Must be after the map image and not be login text
            address_selectors = [
                '//h2[contains(text(), "Contact information")]/following::div[contains(@class, "x1i5p2am")]/following::span[contains(@class, "x12nagc")]',
                '//img[contains(@src, "static_map")]/following::span[contains(@class, "x12nagc")]',
                '//div[contains(@class, "x1i5p2am")]//span[contains(@class, "x12nagc")]',
                '//h2[contains(text(), "Contact information")]/following::span[contains(@class, "x12nagc")]'
            ]
            
            # Filter out login-related text
            login_keywords = ['log in', 'sign up', 'facebook', 'connect with friends', 'password', 'email address']
            
            for selector in address_selectors:
                try:
                    elements = await page.locator(selector).all()
                    logger.debug(f"   🔍 Trying address selector: {selector}, found {len(elements)} elements")
                    for element in elements[:10]:
                        try:
                            if await element.is_visible(timeout=2000):
                                address_text = await element.inner_text()
                                logger.debug(f"   🔍 Address candidate: '{address_text[:80]}'")
                                # Validate it's not login text
                                if any(keyword in address_text.lower() for keyword in login_keywords):
                                    logger.debug(f"   ⚠️ Skipping (login text): {address_text[:50]}")
                                    continue
                                # Check if it looks like an address (contains comma and state/zip)
                                if ',' in address_text and len(address_text.strip()) > 10:
                                    # Must contain a state abbreviation or country
                                    import re
                                    if re.search(r'[A-Z]{2}|United States|USA', address_text):
                                        result['address'] = address_text.strip()
                                        logger.debug(f"   ✅ Found address: {result['address']}")
                                        
                                        # Try to parse city, state, zip
                                        # Pattern: City, State, Country, ZIP
                                        city_state_match = re.search(r'([A-Za-z\s]+?),\s*([A-Z]{2})(?:\s*,\s*[^,]+)?(?:\s+(\d{5}))?', address_text)
                                        if city_state_match:
                                            result['city'] = city_state_match.group(1).strip()
                                            result['state'] = city_state_match.group(2).strip()
                                            if city_state_match.group(3):
                                                result['zip'] = city_state_match.group(3).strip()
                                        break
                        except Exception as e:
                            logger.debug(f"   ⚠️ Error checking address element: {str(e)}")
                            continue
                    if result['address']:
                        break
                except Exception as e:
                    logger.debug(f"   ⚠️ Error with address selector {selector}: {str(e)}")
                    continue
            
            if not result['address']:
                logger.debug(f"   ⚠️ Address not found - trying alternative method")
                # Try searching for address pattern in page text
                try:
                    # Look for address after "Contact information" heading
                    page_text = await page.content()
                    import re
                    # Find Contact information section
                    contact_section_match = re.search(r'Contact information.*?<span[^>]*class="[^"]*x12nagc[^"]*"[^>]*>([^<]+)</span>', page_text, re.DOTALL)
                    if contact_section_match:
                        address_candidate = contact_section_match.group(1).strip()
                        if ',' in address_candidate and not any(kw in address_candidate.lower() for kw in login_keywords):
                            if re.search(r'[A-Z]{2}|United States|USA', address_candidate):
                                result['address'] = address_candidate
                                logger.debug(f"   ✅ Found address via text search: {result['address']}")
                except Exception as e:
                    logger.debug(f"   ⚠️ Alternative address search failed: {str(e)}")
            
            # Extract email (from page content)
            try:
                page_text = await page.content()
                import re
                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                email_matches = re.findall(email_pattern, page_text)
                if email_matches:
                    # Filter out Facebook emails
                    for email in email_matches:
                        if 'facebook.com' not in email.lower():
                            result['email'] = email.strip()
                            logger.debug(f"   ✅ Found email: {result['email']}")
                            break
            except:
                pass
            
            # Extract website
            website_selectors = [
                '//a[contains(@href, "http") and not(contains(@href, "facebook.com")) and not(contains(@href, "maps"))]',
                '//span[contains(text(), "Website")]/following::a',
                '//div[contains(text(), "Website")]/following::a'
            ]
            
            for selector in website_selectors:
                try:
                    elements = await page.locator(selector).all()
                    for element in elements[:10]:
                        try:
                            href = await element.get_attribute('href')
                            if href and 'facebook.com' not in href and 'maps' not in href and ('http' in href or 'www.' in href):
                                result['website'] = href.strip()
                                logger.debug(f"   ✅ Found website: {result['website']}")
                                break
                        except:
                            continue
                    if result['website']:
                        break
                except:
                    continue
        except Exception as e:
            logger.debug(f"   ⚠️ Could not extract contact info: {str(e)}")
        
        # Extract price range and reviews from Basic information
        try:
            # Price range - Based on HTML: span with class "x1yc453h" containing "Price range · $$"
            price_selectors = [
                '//h2[contains(text(), "Basic information")]/following::span[contains(@class, "x1yc453h") and contains(text(), "Price range")]',
                '//h2[contains(text(), "Basic information")]/following::span[contains(@class, "x1yc453h") and contains(text(), "$")]',
                '//span[contains(text(), "Price range")]'
            ]
            
            for selector in price_selectors:
                try:
                    elements = await page.locator(selector).all()
                    for element in elements[:5]:
                        if await element.is_visible(timeout=2000):
                            price_text = await element.inner_text()
                            if 'Price range' in price_text or '$' in price_text:
                                result['price_range'] = price_text.strip()
                                logger.debug(f"   ✅ Found price range: {result['price_range']}")
                                break
                    if result['price_range']:
                        break
                except:
                    continue
            
            # Reviews - Based on HTML: span with class "x1yc453h" containing "Not rated yet (0 reviews)"
            review_selectors = [
                '//h2[contains(text(), "Basic information")]/following::span[contains(@class, "x1yc453h") and contains(text(), "review")]',
                '//h2[contains(text(), "Basic information")]/following::span[contains(@class, "x1yc453h") and contains(text(), "rated")]',
                '//span[contains(text(), "review") and contains(@dir, "auto")]'
            ]
            
            for selector in review_selectors:
                try:
                    elements = await page.locator(selector).all()
                    for element in elements[:5]:
                        if await element.is_visible(timeout=2000):
                            review_text = await element.inner_text()
                            if 'review' in review_text.lower() or 'rated' in review_text.lower():
                                result['reviews'] = review_text.strip()
                                logger.debug(f"   ✅ Found reviews: {result['reviews']}")
                                break
                    if result['reviews']:
                        break
                except:
                    continue
        except Exception as e:
            logger.debug(f"   ⚠️ Could not extract basic info: {str(e)}")
        
        # Extract hours
        try:
            hours_selectors = [
                '//span[contains(text(), "Hours")]/following-sibling::div',
                '//div[contains(text(), "Hours")]/following-sibling::div',
                '//h2[contains(text(), "Hours")]/following::div',
                '[data-testid="hours"]'
            ]
            
            for selector in hours_selectors:
                try:
                    if selector.startswith('//'):
                        element = page.locator(selector).first
                    else:
                        element = page.locator(selector).first
                    
                    if await element.is_visible(timeout=2000):
                        hours_text = await element.inner_text()
                        if hours_text:
                            result['hours'] = hours_text.strip()
                            logger.debug(f"   ✅ Found hours")
                            break
                except:
                    continue
        except Exception as e:
            logger.debug(f"   ⚠️ Could not extract hours: {str(e)}")
        
        # Print all extracted data
        logger.info(f"\n   📊 EXTRACTED FACEBOOK DATA:")
        logger.info(f"   {'='*60}")
        if result['page_name']:
            logger.info(f"   Page Name: {result['page_name']}")
        if result['category']:
            logger.info(f"   Category: {result['category']}")
        if result['description']:
            logger.info(f"   Description: {result['description'][:100]}..." if len(result['description']) > 100 else f"   Description: {result['description']}")
        if result['phone']:
            logger.info(f"   Phone: {result['phone']}")
        if result['email']:
            logger.info(f"   Email: {result['email']}")
        if result['website']:
            logger.info(f"   Website: {result['website']}")
        if result['address']:
            logger.info(f"   Address: {result['address']}")
            if result['city']:
                logger.info(f"   City: {result['city']}")
            if result['state']:
                logger.info(f"   State: {result['state']}")
            if result['zip']:
                logger.info(f"   ZIP: {result['zip']}")
        if result['hours']:
            logger.info(f"   Hours: {result['hours']}")
        if result['price_range']:
            logger.info(f"   Price Range: {result['price_range']}")
        if result['reviews']:
            logger.info(f"   Reviews: {result['reviews']}")
        if result['founded']:
            logger.info(f"   Founded: {result['founded']}")
        if result.get('error'):
            logger.warning(f"   Error: {result['error']}")
        
        # Count extracted fields
        extracted_count = sum(1 for k, v in result.items() if v and k != 'error' and k != 'facebook_url')
        logger.info(f"   {'='*60}")
        logger.info(f"   ✅ Extracted {extracted_count} fields successfully")
        
    except Exception as e:
        error_msg = str(e)
        result['error'] = error_msg
        logger.error(f"   ❌ Error extracting Facebook details: {error_msg}")
    
    return result


async def scrape_facebook_pages(
    excel_file_path: str,
    output_file_path: Optional[str] = None,
    max_pages: Optional[int] = None,
    headless: bool = False
) -> pd.DataFrame:
    """
    Scrape Facebook About sections for companies in Excel file
    
    Args:
        excel_file_path: Path to input Excel file
        output_file_path: Path to output Excel file (defaults to input file)
        max_pages: Maximum number of pages to scrape (None for all)
        headless: Run browser in headless mode
        
    Returns:
        DataFrame with Facebook details added
    """
    # Load Excel file
    logger.info(f"📂 Loading Excel file: {excel_file_path}")
    df = pd.read_excel(excel_file_path, engine='openpyxl')
    logger.info(f"✅ Loaded {len(df)} records")
    
    # Filter companies with Facebook URLs
    has_facebook = df['Facebook'].notna() & (df['Facebook'] != '') & (df['Facebook'].astype(str).str.strip() != '')
    companies_with_fb = df[has_facebook].copy()
    
    logger.info(f"📊 Found {len(companies_with_fb)} companies with Facebook pages")
    
    if len(companies_with_fb) == 0:
        logger.warning("⚠️ No companies with Facebook URLs found")
        return df
    
    # Limit if specified
    if max_pages:
        companies_with_fb = companies_with_fb.head(max_pages)
        logger.info(f"⚠️ Limiting to {max_pages} companies for testing")
    
    # Add single Facebook data column (JSON object)
    fb_column = 'Facebook_Data'
    if fb_column not in df.columns:
        df[fb_column] = None
    
    # Initialize Playwright
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = await context.new_page()
    
    total = len(companies_with_fb)
    processed = 0
    successful = 0
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting Facebook scraping for {total} companies")
    logger.info(f"{'='*60}\n")
    
    try:
        for idx, row in companies_with_fb.iterrows():
            processed += 1
            business_name = row.get('Business Name', 'N/A')
            facebook_url = row.get('Facebook', '')
            
            if not facebook_url or pd.isna(facebook_url):
                continue
            
            logger.info(f"\n📄 [{processed}/{total}] Processing: {business_name[:60]}...")
            logger.info(f"   Facebook URL: {facebook_url}")
            
            try:
                # Extract Facebook details
                fb_details = await extract_facebook_about_details(page, facebook_url)
                
                # Store all Facebook data as JSON object in single column
                import json
                # Remove error from main data if present, keep it separate
                error = fb_details.pop('error', None)
                if error:
                    fb_details['error'] = error
                
                # Save as JSON string
                df.at[idx, 'Facebook_Data'] = json.dumps(fb_details, ensure_ascii=False)
                
                if not error:
                    successful += 1
                    logger.info(f"   ✅ Successfully saved Facebook data to Excel")
                else:
                    logger.warning(f"   ⚠️ Saved with error: {error}")
                
                # Human-like delay between pages
                await human_delay(3, 6)
                
            except Exception as e:
                error_msg = str(e)
                # Save error in Facebook_Data column
                error_data = {'error': error_msg, 'facebook_url': facebook_url}
                df.at[idx, 'Facebook_Data'] = json.dumps(error_data, ensure_ascii=False)
                logger.error(f"   ❌ Error processing {business_name}: {error_msg}")
                await human_delay(2, 4)
    
    finally:
        # Cleanup
        await browser.close()
        await playwright.stop()
    
    # Save results
    output = output_file_path or excel_file_path
    df.to_excel(output, index=False, engine='openpyxl')
    logger.info(f"\n💾 Results saved to: {output}")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Facebook scraping complete!")
    logger.info(f"   Total processed: {processed}/{total}")
    logger.info(f"   Successful: {successful}")
    logger.info(f"   Failed: {processed - successful}")
    logger.info(f"{'='*60}")
    
    return df


async def main():
    """Main function"""
    import sys
    
    setup_logging()
    
    excel_file = "output/georgia_sos_business_data_20251104_133631.xlsx"
    
    if not Path(excel_file).exists():
        logger.error(f"❌ Excel file not found: {excel_file}")
        return
    
    # Check for command-line arguments
    max_pages = None
    if '--limit=' in ' '.join(sys.argv):
        for arg in sys.argv:
            if '--limit=' in arg:
                max_pages = int(arg.split('=')[1])
                break
    
    headless = '--headless' in sys.argv
    
    logger.info("="*80)
    logger.info("🔍 FACEBOOK ABOUT SECTION SCRAPER")
    logger.info("="*80)
    logger.info(f"Input file: {excel_file}")
    if max_pages:
        logger.info(f"Limiting to: {max_pages} companies")
    logger.info(f"Headless mode: {headless}")
    logger.info("="*80)
    
    await scrape_facebook_pages(
        excel_file_path=excel_file,
        max_pages=max_pages,
        headless=headless
    )


if __name__ == "__main__":
    asyncio.run(main())

