"""
Manta Business Directory Scraper
Scrapes business data from Manta.com including owner names, phone, address, NAICS, etc.
Uses the same Cloudflare bypass as Georgia SOS scraper
"""

import asyncio
import random
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from pathlib import Path
from loguru import logger
from playwright.async_api import Page, Browser, BrowserContext
from urllib.parse import urlparse, quote_plus
import json
import re

from cloudflareSolver import get_bypassed_page, solve_cloudflare_challenge, CloudflareTurnstileExtractor
from cloudflare_utils import is_session_valid
from scrapers import human_delay, simulate_human_behavior, human_like_type, check_and_solve_cloudflare
from utils.business_utils import normalize_business_name



async def check_autocomplete_for_match(
    page: Page,
    business_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None
) -> bool:
    """
    Check autocomplete dropdown for a business listing match and click it if found.
    Only clicks on actual business listings (store-alt icon) which go directly to detail page.
    
    Args:
        page: Playwright page object
        business_name: Business name to match
        city: Optional city (not used for matching - just logged)
        state: Optional state (not used for matching)
        
    Returns:
        True if found and clicked, False otherwise
    """
    try:
        # Look for autocomplete suggestions - ONLY business listings (store-alt icon)
        suggestions = await page.evaluate("""
            () => {
                const results = [];
                const items = document.querySelectorAll('li.cursor-pointer');
                
                items.forEach((item, idx) => {
                    // ONLY include items with store-alt icon (actual business listings)
                    const hasStoreIcon = item.querySelector('.fa-store-alt');
                    if (!hasStoreIcon) return;
                    
                    // Find the text-small span container for business listings
                    const textSmall = item.querySelector('.text-small');
                    if (!textSmall) return;
                    
                    // Get name from first span inside text-small (before the br)
                    const nameSpan = textSmall.querySelector('span:first-child');
                    const addressSpan = textSmall.querySelector('span.text-xs, span.text-gray');
                    
                    const name = nameSpan ? nameSpan.textContent.trim() : '';
                    const address = addressSpan ? addressSpan.textContent.trim() : '';
                    
                    if (name) {
                        results.push({
                            name: name,
                            address: address,
                            index: idx
                        });
                    }
                });
                return results;
            }
        """)
        
        if not suggestions:
            logger.debug("   ℹ️ No business listings in autocomplete")
            return False
        
        logger.debug(f"   📋 Found {len(suggestions)} business listings in autocomplete")
        for s in suggestions[:3]:
            logger.debug(f"      - '{s['name']}' at {s.get('address', 'no address')}")
        
        # Normalize for comparison
        search_normalized = normalize_business_name(business_name).lower()
        
        for suggestion in suggestions:
            sugg_normalized = normalize_business_name(suggestion['name']).lower()
            
            # Check for exact match - DON'T check city, just match on name
            if search_normalized == sugg_normalized:
                logger.info(f"   ✅ Found exact match in autocomplete: '{suggestion['name']}' at {suggestion.get('address', 'N/A')}")
                
                # Click on this suggestion
                autocomplete_items = await page.query_selector_all('li.cursor-pointer')
                if suggestion['index'] < len(autocomplete_items):
                    await autocomplete_items[suggestion['index']].click()
                    await human_delay(2.0, 3.0)
                    return True
        
        # No exact match found
        logger.debug("   ℹ️ No exact match in autocomplete, will proceed with search")
        return False
        
    except Exception as e:
        logger.debug(f"   ⚠️ Error checking autocomplete: {str(e)}")
        return False


async def search_manta_business(
    business_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    page: Optional[Page] = None
) -> Optional[Page]:
    """
    Search for a business on Manta.com using form-based search
    
    Args:
        business_name: Business name to search for
        city: Optional city name
        state: Optional state (default: 'GA')
        page: Optional page instance (if already bypassed Cloudflare)
        
    Returns:
        Page object with search results, or None if not found
    """
    target_url = "https://www.manta.com"
    
    # Get bypassed page if not provided
    if not page:
        logger.info("🔐 Bypassing Cloudflare challenge for Manta...")
        playwright, browser, context, page = await get_bypassed_page(target_url, headless=False)
    
    # Default state
    if not state:
        state = 'GA'
    
    # Normalize business name for search
    clean_name = normalize_business_name(business_name)
    
    logger.info(f"🔍 Searching Manta for: {clean_name} (orig: {business_name}) in {city or ''}, {state}")
    
    try:
        # Navigate to Manta homepage
        await page.goto(target_url, wait_until="domcontentloaded")
        await human_delay(1.0, 2.0)
        
        # Check for Cloudflare challenge
        await check_and_solve_cloudflare(page, page.context)
        await human_delay(1.0, 2.0)
        
        # Find and fill the search form
        # Manta has search fields - try to find them
        logger.info("   Looking for search form...")
        
        # Try multiple selectors for the search input
        search_selectors = [
            'input[name="search"]',
            'input[placeholder*="business"]',
            'input[placeholder*="I\'m looking for"]',
            'input[type="text"]',
            '.search-input',
            '#search'
        ]
        
        search_input = None
        for selector in search_selectors:
            try:
                search_input = page.locator(selector).first
                if await search_input.count() > 0:
                    logger.info(f"   ✅ Found search input with selector: {selector}")
                    break
            except:
                continue
        
        if not search_input or await search_input.count() == 0:
            # Fallback: try to find any input field and fill it
            logger.warning("   ⚠️ Could not find search input, trying alternative approach...")
            # Try URL-based search as fallback
            search_url = f"https://www.manta.com/search?search={quote_plus(business_name)}"
            if city and state:
                search_url += f"&location={quote_plus(f'{city}, {state}')}"
            elif state:
                search_url += f"&location={quote_plus(state)}"
            
            logger.info(f"   Using URL-based search: {search_url}")
            await page.goto(search_url, wait_until="domcontentloaded")
            await human_delay(2.0, 3.0)
            await check_and_solve_cloudflare(page, page.context)
        else:
            # Get the selector for the found input
            search_selector = None
            for selector in search_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        search_selector = selector
                        break
                except:
                    continue
            
            if search_selector:
                # Clear and fill in business name
                search_el = page.locator(search_selector).first
                await search_el.click()
                await human_delay(0.2, 0.3)
                # Select all and clear
                await page.keyboard.press('Control+a')
                await page.keyboard.press('Backspace')
                await human_delay(0.2, 0.3)
                await human_like_type(page, search_selector, clean_name)
                await human_delay(1.0, 1.5)  # Wait for autocomplete dropdown
                
                # Check for autocomplete suggestions
                autocomplete_match = await check_autocomplete_for_match(page, business_name, city, state)
                if autocomplete_match:
                    logger.info(f"   ✅ Found exact match in autocomplete, navigating directly...")
                    # Return page - caller should check if we're on detail page
                    return page
                
                # Find and fill location field
                location_selectors = [
                    'input[name="location"]',
                    'input[name="near"]',
                    'input[placeholder*="City"]',
                    'input[placeholder*="location"]',
                    'input[type="text"]:nth-of-type(2)'
                ]
                
                location_selector = None
                for selector in location_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            location_selector = selector
                            logger.info(f"   ✅ Found location input with selector: {selector}")
                            break
                    except:
                        continue
                
                if location_selector:
                    location_text = f"{city}, {state}" if city else state
                    location_el = page.locator(location_selector).first
                    await location_el.click()
                    await human_delay(0.2, 0.3)
                    # Select all and clear
                    await page.keyboard.press('Control+a')
                    await page.keyboard.press('Backspace')
                    await human_delay(0.2, 0.3)
                    await human_like_type(page, location_selector, location_text)
                    await human_delay(0.5, 1.0)
            
            # Find and click search button
            search_button_selectors = [
                'button[type="submit"]',
                'button:has-text("Search")',
                'input[type="submit"]',
                '.search-button',
                'button.search',
                '[aria-label*="Search"]'
            ]
            
            search_button = None
            for selector in search_button_selectors:
                try:
                    search_button = page.locator(selector).first
                    if await search_button.count() > 0:
                        logger.info(f"   ✅ Found search button with selector: {selector}")
                        break
                except:
                    continue
            
            if search_button and await search_button.count() > 0:
                await search_button.click()
                logger.info("   ✅ Search button clicked")
            else:
                # Try pressing Enter
                await page.keyboard.press("Enter")
                logger.info("   ✅ Pressed Enter to submit search")
            
            # Wait for search results
            await human_delay(2.0, 3.0)
            await check_and_solve_cloudflare(page, page.context)
        
        # Wait for search results to load - use domcontentloaded instead of networkidle
        # as Manta has continuous network activity that prevents networkidle
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except:
            pass  # Continue even if timeout - page might still be usable
        await human_delay(3.0, 4.0)  # Give time for results to render
        
        logger.info("✅ Manta search page loaded")
        return page
        
    except Exception as e:
        logger.error(f"❌ Error searching Manta: {str(e)}")
        logger.exception(e)
        return None


async def extract_manta_business_details(page: Page, business_name: str) -> Optional[Dict]:
    """
    Extract business details from Manta business listing page
    
    Args:
        page: Playwright page object (should be on Manta business detail page)
        business_name: Business name for verification
        
    Returns:
        Dictionary with business details or None if not found
    """
    try:
        await page.wait_for_load_state("domcontentloaded")
        await human_delay(1.0, 2.0)
        
        # Check for Cloudflare challenge
        await check_and_solve_cloudflare(page, page.context)
        
        # Extract data from page using specific selectors for Manta's HTML structure
        data = await page.evaluate("""
            () => {
                const result = {};
                
                // Extract phone number from tel: link
                const phoneLink = document.querySelector('a[href^="tel:"]');
                if (phoneLink) {
                    let phone = phoneLink.textContent.trim();
                    if (!phone) {
                        phone = phoneLink.getAttribute('href').replace('tel:', '');
                    }
                    // Format phone number
                    if (phone) {
                        result['Phone'] = phone.replace(/[^0-9()-\s]/g, '').trim();
                    }
                }
                
                // Extract address from contact section - look for the address list specifically
                const contactSection = document.querySelector('#contactContent');
                if (contactSection) {
                    // The address is in the first div with class lg:w-3/5
                    const addressContainer = contactSection.querySelector('.lg\\\\:w-3\\\\/5, div.mr-2');
                    if (addressContainer) {
                        const addressLines = addressContainer.querySelectorAll('ul.text-gray-800 li');
                        if (addressLines.length > 0) {
                            const addressParts = [];
                            addressLines.forEach(li => {
                                const text = li.textContent.trim();
                                // Skip empty lines and business name
                                if (text && !text.match(/^\\(\\d{3}\\)/) && text.length > 2) {
                                    addressParts.push(text);
                                }
                            });
                            if (addressParts.length > 0) {
                                // Remove business name if it's the first item
                                if (addressParts[0].toLowerCase().includes('landscaping') || 
                                    addressParts[0].toLowerCase().includes('llc')) {
                                    addressParts.shift();
                                }
                                result['Address'] = addressParts.join(', ').replace(/\\s+/g, ' ').trim();
                            }
                        }
                    }
                    
                    // Extract Google Maps URL
                    const mapLink = contactSection.querySelector('a[href*="maps.google.com"]');
                    if (mapLink) {
                        result['Manta_Map_Url'] = mapLink.getAttribute('href');
                    }
                }
                
                // Fallback: get address from hero section
                if (!result['Address']) {
                    const heroAddress = document.querySelector('a[href*="maps.google.com"]');
                    if (heroAddress) {
                        const text = heroAddress.textContent.trim();
                        if (text && text.includes(',')) {
                            result['Address'] = text.replace(/\\s+/g, ' ').trim();
                        }
                    }
                }
                
                // Extract details from Detailed Information section
                const detailsSection = document.querySelector('#detailsContent');
                if (detailsSection) {
                    const detailItems = detailsSection.querySelectorAll('li');
                    detailItems.forEach(item => {
                        const label = item.querySelector('span.text-gray-600, span.text-gray-700');
                        const values = item.querySelectorAll('span.text-gray-800');
                        
                        if (label && values.length > 0) {
                            const labelText = label.textContent.trim().toLowerCase();
                            // Get the last span with text-gray-800 (visible value) or hidden one
                            let value = '';
                            values.forEach(v => {
                                const txt = v.textContent.trim();
                                if (txt) value = txt;
                            });
                            
                            if (labelText.includes('location type') && value) {
                                result['Manta_Location_Type'] = value;
                            } else if (labelText.includes('opening date') && value) {
                                result['Manta_Opening_Date'] = value;
                            } else if (labelText.includes('annual revenue') && value) {
                                result['Manta_Annual_Revenue'] = value.replace(/[^0-9]/g, '');
                            } else if (labelText.includes('sic code') && value) {
                                // SIC might be hidden, check for hidden span
                                const hiddenSpan = item.querySelector('span.hidden');
                                if (hiddenSpan) {
                                    const sicText = hiddenSpan.textContent.trim();
                                    const sicMatch = sicText.match(/^(\\d+)/);
                                    if (sicMatch) {
                                        result['Manta_SIC'] = sicMatch[1];
                                    }
                                } else {
                                    const sicMatch = value.match(/^(\\d+)/);
                                    if (sicMatch) {
                                        result['Manta_SIC'] = sicMatch[1];
                                    }
                                }
                            } else if (labelText.includes('naics code') && value) {
                                // NAICS might be hidden, check for hidden span
                                const hiddenSpan = item.querySelector('span.hidden');
                                if (hiddenSpan) {
                                    const naicsText = hiddenSpan.textContent.trim();
                                    const naicsMatch = naicsText.match(/^(\\d+)/);
                                    if (naicsMatch) {
                                        result['NAICS Code'] = naicsMatch[1];
                                        result['NAICS_Source'] = 'Manta';
                                    }
                                } else {
                                    const naicsMatch = value.match(/^(\\d+)/);
                                    if (naicsMatch) {
                                        result['NAICS Code'] = naicsMatch[1];
                                        result['NAICS_Source'] = 'Manta';
                                    }
                                }
                            } else if (labelText.includes('employees') && value) {
                                result['Manta_Employees'] = value.replace(/[^0-9]/g, '');
                            } else if (labelText.includes('principal') && value) {
                                result['Manta_Owner_Name'] = value;
                            }
                        }
                    });
                    
                    // Check for Principal in nested ul (Contacts section)
                    const nestedLists = detailsSection.querySelectorAll('ul.hidden li');
                    nestedLists.forEach(item => {
                        const label = item.querySelector('span.text-gray-600, span.text-gray-700');
                        const value = item.querySelector('span.text-gray-800');
                        if (label && value) {
                            const labelText = label.textContent.trim().toLowerCase();
                            if (labelText.includes('principal') && !result['Manta_Owner_Name']) {
                                result['Manta_Owner_Name'] = value.textContent.trim();
                            }
                        }
                    });
                }
                
                // Extract website if available (look for external links)
                const allLinks = document.querySelectorAll('a[href^="http"]');
                allLinks.forEach(link => {
                    const href = link.getAttribute('href');
                    if (href && 
                        !href.includes('manta.com') && 
                        !href.includes('facebook.com') && 
                        !href.includes('linkedin.com') &&
                        !href.includes('google.com') &&
                        !href.includes('twitter.com') &&
                        !result['Website']) {
                        result['Website'] = href;
                        result['Website_Source'] = 'Manta';
                    }
                });
                
                // Mark that data came from Manta
                if (Object.keys(result).length > 0) {
                    result['Manta_Found'] = true;
                }
                
                return result;
            }
        """)
        
        if data and any(data.values()):
            logger.info(f"   ✅ Extracted Manta data: {len([k for k, v in data.items() if v])} fields")
            for key, value in data.items():
                if value:
                    logger.debug(f"      {key}: {value}")
            return data
        else:
            logger.debug(f"   ⚠️ No Manta data extracted")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error extracting Manta details: {str(e)}")
        return None


async def find_manta_business_listing(
    page: Page,
    business_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None
) -> Optional[str]:
    """
    Find the Manta listing URL for a business from search results
    
    Args:
        page: Playwright page object (should be on Manta search results page)
        business_name: Business name to match
        city: Optional city for verification
        state: Optional state for verification
        
    Returns:
        URL of business listing page, or None if not found
    """
    try:
        await page.wait_for_load_state("domcontentloaded")
        await human_delay(1.0, 2.0)
        
        # Extract business listing cards with more details
        listings = await page.evaluate("""
            () => {
                const results = [];
                // Look for business listing cards (each card has the business info)
                const cards = document.querySelectorAll('.md\\\\:rounded.bg-white');
                cards.forEach(card => {
                    // Get the business name link
                    const nameLink = card.querySelector('a[href*="/c/"]');
                    if (nameLink) {
                        const href = nameLink.getAttribute('href');
                        const name = nameLink.textContent.trim();
                        
                        // Try to get location info
                        let location = '';
                        const locationDiv = card.querySelector('div.ml-4');
                        if (locationDiv) {
                            location = locationDiv.textContent.trim();
                        }
                        
                        // Get phone if available
                        let phone = '';
                        const phoneDiv = card.querySelector('div:has(> i.fa-phone) + div, a[href^="tel:"]');
                        if (phoneDiv) {
                            phone = phoneDiv.textContent.trim();
                        }
                        
                        if (href && href.includes('/c/')) {
                            results.push({
                                url: href.startsWith('http') ? href : 'https://www.manta.com' + href,
                                name: name,
                                location: location,
                                phone: phone
                            });
                        }
                    }
                });
                return results;
            }
        """)
        
        if not listings:
            logger.debug(f"   ⚠️ No Manta listings found in search results")
            return None
        
        logger.info(f"   📋 Found {len(listings)} listings in search results")
        
        # Normalize names for comparison
        search_name_normalized = normalize_business_name(business_name).lower()
        city_lower = city.lower() if city else ''
        
        best_match = None
        best_score = 0
        
        for listing in listings[:15]:  # Check first 15 results
            listing_name_normalized = normalize_business_name(listing['name']).lower()
            location_lower = listing.get('location', '').lower()
            
            score = 0
            
            # Exact match (after normalization) - highest priority
            if search_name_normalized == listing_name_normalized:
                score = 100
                logger.info(f"   ✅ EXACT match found: {listing['name']}")
            # Search name contained in listing name
            elif search_name_normalized in listing_name_normalized:
                score = 80
            # Listing name contained in search name
            elif listing_name_normalized in search_name_normalized:
                score = 70
            else:
                # Check word overlap
                search_words = set(search_name_normalized.split())
                listing_words = set(listing_name_normalized.split())
                # Remove small words
                search_words = {w for w in search_words if len(w) > 2}
                listing_words = {w for w in listing_words if len(w) > 2}
                
                if search_words and listing_words:
                    overlap = len(search_words & listing_words)
                    total = len(search_words | listing_words)
                    if overlap > 0:
                        score = int(60 * (overlap / total))
            
            # Bonus for matching city
            if city_lower and city_lower in location_lower:
                score += 10
            
            if score > best_score:
                best_score = score
                best_match = listing
                
            # If we found an exact match with location, use it immediately
            if score >= 100:
                break
        
        if best_match and best_score >= 80:
            logger.info(f"   ✅ Best match (score={best_score}): {best_match['name']} - {best_match.get('location', 'N/A')}")
            return best_match['url']
        
        # If no good match found, return None - don't pick a wrong business
        if listings:
            logger.warning(f"   ⚠️ No match found for '{business_name}' (best score was {best_score})")
            logger.debug(f"   Available listings: {[l['name'] for l in listings[:5]]}")
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Error finding Manta listing: {str(e)}")
        return None


async def enrich_business_with_manta(
    business_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    page: Optional[Page] = None
) -> Dict:
    """
    Enrich a single business with Manta data
    
    Args:
        business_name: Business name to search for
        city: Optional city name
        state: Optional state (default: 'GA')
        page: Optional page instance (if already bypassed Cloudflare)
        
    Returns:
        Dictionary with Manta enrichment data
    """
    result = {
        # Common fields (merge into existing columns)
        'Phone': None,
        'Address': None,
        'Email': None,
        'Website': None,
        'NAICS Code': None,
        'NAICS_Source': None,
        'Website_Source': None,
        # New fields (keep Manta_ prefix)
        'Manta_Owner_Name': None,
        'Manta_SIC': None,
        'Manta_Annual_Revenue': None,
        'Manta_Employees': None,
        'Manta_Opening_Date': None,
        'Manta_Location_Type': None,
        'Manta_Found': False
    }
    
    try:
        # Step 1: Search for business
        search_page = await search_manta_business(business_name, city, state, page)
        if not search_page:
            logger.debug(f"   ⚠️ Could not search Manta for {business_name}")
            return result
        
        # Check if we're already on a detail page (from autocomplete click)
        current_url = search_page.url
        if '/c/' in current_url:
            # Already on detail page from autocomplete
            logger.info(f"   ✅ Already on detail page from autocomplete")
        else:
            # Step 2: Find business listing URL from search results
            listing_url = await find_manta_business_listing(search_page, business_name, city, state)
            if not listing_url:
                logger.debug(f"   ⚠️ No Manta listing found for {business_name}")
                return result
            
            # Step 3: Navigate to business detail page
            logger.info(f"   📄 Navigating to Manta business page...")
            await search_page.goto(listing_url, wait_until="domcontentloaded")
            await human_delay(1.5, 2.5)
        
        # Check for Cloudflare challenge
        await check_and_solve_cloudflare(search_page, search_page.context)
        
        # Step 4: Extract business details
        details = await extract_manta_business_details(search_page, business_name)
        
        if details:
            result.update(details)
            result['Manta_Found'] = True
            logger.info(f"   ✅ Manta enrichment complete for {business_name}")
        else:
            logger.debug(f"   ⚠️ Could not extract Manta details for {business_name}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error enriching with Manta for {business_name}: {str(e)}")
        return result


async def enrich_dataframe_with_manta(
    df: pd.DataFrame,
    page: Optional[Page] = None,
    save_progress_every: int = 50,
    output_file: Optional[str] = None
) -> pd.DataFrame:
    """
    Enrich DataFrame with Manta data
    
    Args:
        df: DataFrame with business data (must have 'Business Name' or 'Entity Name' column)
        page: Optional Playwright page instance (if already bypassed Cloudflare)
        save_progress_every: Save progress every N records
        output_file: Optional path to save progress Excel file
        
    Returns:
        DataFrame with Manta enrichment columns added
    """
    if df.empty:
        logger.warning("⚠️ No data to enrich with Manta")
        return df
    
    # Add Manta-specific columns if they don't exist (only new fields)
    manta_new_columns = [
        'Manta_Owner_Name',
        'Manta_SIC',
        'Manta_Annual_Revenue',
        'Manta_Employees',
        'Manta_Opening_Date',
        'Manta_Location_Type',
        'Manta_Map_Url',
        'Manta_Found'
    ]
    
    # Common columns should already exist, but add if missing
    common_columns = [
        'Phone',
        'Address',
        'Email',
        'Website',
        'NAICS Code',
        'NAICS_Source',
        'Website_Source'
    ]
    
    for col in manta_new_columns + common_columns:
        if col not in df.columns:
            df[col] = None
    
    # Get or create page instance
    if not page:
        logger.info("🔐 Creating Manta browser session...")
        target_url = "https://www.manta.com"
        playwright, browser, context, page = await get_bypassed_page(target_url, headless=False)
    
    total_records = len(df)
    processed = 0
    found = 0
    failed = 0
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting Manta enrichment for {total_records} businesses")
    logger.info(f"{'='*60}")
    
    for idx, row in df.iterrows():
        processed += 1
        
        # Get business name
        business_name = row.get('Business Name') or row.get('Entity Name', '')
        if not business_name:
            logger.debug(f"⏭️  [{processed}/{total_records}] Skipping (no business name)")
            continue
        
        # Get location info
        city = row.get('City')
        state = row.get('State', 'GA')
        
        # Extract city from address if not in City column
        if not city:
            address = row.get('Principal Office Address') or row.get('Address', '')
            if address:
                # Simple extraction: look for city before state
                match = re.search(r',\s*([^,]+),\s*([A-Z]{2})', address)
                if match:
                    city = match.group(1).strip()
                    if not state:
                        state = match.group(2).strip()
        
        logger.info(f"\n📄 [{processed}/{total_records}] Enriching: {business_name[:50]}...")
        if city:
            logger.info(f"   Location: {city}, {state}")
        
        try:
            # Enrich with Manta
            manta_data = await enrich_business_with_manta(
                business_name=business_name,
                city=city,
                state=state,
                page=page
            )
            
            # Update DataFrame - merge into existing columns or add new ones
            for key, value in manta_data.items():
                if value:  # Only update if we have a value from Manta
                    if key in df.columns:
                        # For common fields, Manta is considered higher quality, so we update
                        if key in ['Phone', 'Address', 'Email', 'Website', 'NAICS Code']:
                            df.at[idx, key] = value
                            # Update source if provided
                            if key == 'NAICS Code' and 'NAICS_Source' in manta_data:
                                df.at[idx, 'NAICS_Source'] = manta_data.get('NAICS_Source')
                            elif key == 'Website' and 'Website_Source' in manta_data:
                                df.at[idx, 'Website_Source'] = manta_data.get('Website_Source')
                        else:
                            # For new fields, always update
                            df.at[idx, key] = value
                    else:
                        # Column doesn't exist, add it
                        df[key] = None
                        df.at[idx, key] = value
            
            if manta_data.get('Manta_Found'):
                found += 1
                logger.info(f"   ✅ Manta data found")
            else:
                logger.debug(f"   ⚠️ No Manta data found")
            
            # Human-like delay between searches
            await human_delay(2.0, 4.0)
            
            # Save progress periodically
            if processed % save_progress_every == 0:
                if output_file:
                    df.to_excel(output_file, index=False, engine='openpyxl')
                    logger.info(f"   💾 Progress saved: {processed}/{total_records} processed")
            
        except Exception as e:
            logger.warning(f"   ⚠️ Error enriching {business_name} with Manta: {str(e)}")
            failed += 1
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Manta enrichment complete!")
    logger.info(f"   Total processed: {processed}/{total_records}")
    logger.info(f"   Found: {found}")
    logger.info(f"   Not found: {processed - found - failed}")
    logger.info(f"   Failed: {failed}")
    logger.info(f"{'='*60}")
    
    return df


if __name__ == "__main__":
    # Test function
    async def test():
        business_name = "101 Landscaping LLC"
        city = "Lawrenceville"
        state = "GA"
        
        logger.info(f"Testing Manta scraper for: {business_name}")
        result = await enrich_business_with_manta(business_name, city, state)
        logger.info(f"Result: {json.dumps(result, indent=2)}")
    
    asyncio.run(test())

