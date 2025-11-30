"""
Apollo.io Enricher Module
Enriches company data with executive-level contacts from Apollo.io
Optimized for minimal credit usage with website validation

CREDIT OPTIMIZATION:
- Uses 1 credit per company (instead of 2)
- Extracts organization data from people search response
- No separate organization search needed
- Expected: ~49 credits for 49 companies (50% savings)
"""

import os
import json
import asyncio
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from loguru import logger
import aiohttp
import pandas as pd
from website_validator import (
    extract_domain, validate_domain, calculate_name_similarity,
    extract_domain_from_email
)

# Executive-level titles to filter for (case-insensitive)
EXECUTIVE_TITLES = [
    'ceo', 'chief executive officer',
    'president', 'coo', 'chief operating officer',
    'cfo', 'chief financial officer',
    'cto', 'chief technology officer',
    'founder', 'co-founder',
    'owner', 'proprietor',
    'vp', 'vice president', 'vice-president',
    'director', 'managing director',
    'chairman', 'chairwoman', 'chair',
    'partner', 'managing partner',
    'head of', 'head',
    'executive', 'exec',
    'principal', 'president & ceo'
]

# Apollo API configuration
APOLLO_API_BASE = "https://api.apollo.io/v1"
APOLLO_SEARCH_PEOPLE_ENDPOINT = f"{APOLLO_API_BASE}/mixed_people/search"
APOLLO_SEARCH_ORGANIZATIONS_ENDPOINT = f"{APOLLO_API_BASE}/organizations/search"


class ApolloEnricher:
    """Apollo.io enricher for finding executive-level contacts"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        max_executives_per_company: int = 5,
        cache_file: Optional[str] = "data/apollo_cache.json",
        delay_between_requests: float = 0.5
    ):
        """
        Initialize Apollo enricher
        
        Args:
            api_key: Apollo API key (defaults to APOLLO_API_KEY env var)
            max_executives_per_company: Maximum executives to fetch per company
            cache_file: Path to cache file for API responses
            delay_between_requests: Delay in seconds between API requests
        """
        self.api_key = api_key or os.getenv("APOLLO_API_KEY")
        if not self.api_key:
            raise ValueError("APOLLO_API_KEY not found. Set it in .env file or pass as parameter.")
        
        self.max_executives_per_company = max_executives_per_company
        self.cache_file = Path(cache_file) if cache_file else None
        self.cache = {}
        self.delay = delay_between_requests
        
        # Load cache if exists
        if self.cache_file:
            self._load_cache()
    
    def _load_cache(self):
        """Load API response cache"""
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
                logger.info(f"✅ Loaded {len(self.cache)} cached Apollo responses")
            except Exception as e:
                logger.warning(f"Could not load cache: {str(e)}")
                self.cache = {}
    
    def _save_cache(self):
        """Save API response cache"""
        if self.cache_file:
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.cache_file, 'w') as f:
                    json.dump(self.cache, f, indent=2)
            except Exception as e:
                logger.warning(f"Could not save cache: {str(e)}")
    
    def _get_cache_key(self, search_type: str, identifier: str) -> str:
        """Generate cache key"""
        return f"{search_type}:{identifier.lower().strip()}"
    
    def _is_executive_title(self, title: str) -> bool:
        """Check if job title is executive-level"""
        if not title:
            return False
        
        title_lower = title.lower()
        return any(exec_title in title_lower for exec_title in EXECUTIVE_TITLES)
    
    def _sort_by_seniority(self, executives: List[Dict]) -> List[Dict]:
        """Sort executives by title seniority"""
        seniority_order = {
            'ceo': 1, 'chief executive': 1,
            'founder': 2, 'co-founder': 2,
            'president': 3,
            'coo': 4, 'chief operating': 4,
            'cfo': 5, 'chief financial': 5,
            'cto': 6, 'chief technology': 6,
            'owner': 7,
            'chairman': 8, 'chairwoman': 8, 'chair': 8,
            'vp': 9, 'vice president': 9,
            'director': 10,
            'head': 11,
        }
        
        def get_seniority_score(title: str) -> int:
            title_lower = title.lower()
            for key, score in seniority_order.items():
                if key in title_lower:
                    return score
            return 99
        
        return sorted(executives, key=lambda x: get_seniority_score(x.get("title", "")))
    
    async def _search_organizations_by_domain(
        self,
        domain: str,
        company_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Search for organization by domain (FALLBACK ONLY - 1 credit)
        
        NOTE: This method is kept as a fallback but should NOT be used in normal flow.
        Use _search_executives_and_org_by_domain() instead which gets both in 1 credit.
        This is only for cases where people search doesn't return org data.
        
        Returns:
            Organization data or None
        """
        cache_key = self._get_cache_key("org_domain", domain)
        if cache_key in self.cache:
            logger.debug(f"📦 Using cached organization for {domain}")
            return self.cache[cache_key]
        
        await asyncio.sleep(self.delay)
        
        try:
            payload = {
                "api_key": self.api_key,
                "q_organization_domains": domain,
                "per_page": 1,
                "page": 1
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    APOLLO_SEARCH_ORGANIZATIONS_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        organizations = data.get("organizations", [])
                        
                        if organizations:
                            org = organizations[0]
                            # Cache result
                            self.cache[cache_key] = org
                            self._save_cache()
                            return org
                    else:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Apollo org search error for {domain}: {response.status}")
        
        except Exception as e:
            logger.error(f"❌ Error searching Apollo org for {domain}: {str(e)}")
        
        return None
    
    async def _search_executives_by_domain(
        self,
        domain: str,
        company_name: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for executives at a company by domain (1 credit)
        
        Returns:
            List of executive contact dictionaries
        """
        cache_key = self._get_cache_key("exec_domain", domain)
        if cache_key in self.cache:
            logger.debug(f"📦 Using cached executives for {domain}")
            return self.cache[cache_key]
        
        await asyncio.sleep(self.delay)
        
        try:
            payload = {
                "api_key": self.api_key,
                "q_organization_domains": domain,
                "per_page": 25,
                "page": 1,
            }
            
            if company_name:
                payload["q_organization_name"] = company_name
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    APOLLO_SEARCH_PEOPLE_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        people = data.get("people", [])
                        
                        # Filter for executives only
                        executives = []
                        for person in people:
                            title = person.get("title", "")
                            if self._is_executive_title(title):
                                executives.append({
                                    "first_name": person.get("first_name", ""),
                                    "last_name": person.get("last_name", ""),
                                    "full_name": person.get("name", ""),
                                    "title": title,
                                    "email": person.get("email", ""),
                                    "linkedin_url": person.get("linkedin_url", ""),
                                    "phone_number": person.get("phone_numbers", [{}])[0].get("raw_number", "") if person.get("phone_numbers") else "",
                                    "apollo_id": person.get("id", ""),
                                })
                        
                        # Sort by seniority and limit
                        executives = self._sort_by_seniority(executives)
                        executives = executives[:self.max_executives_per_company]
                        
                        # Cache results
                        self.cache[cache_key] = executives
                        self._save_cache()
                        
                        logger.info(f"✅ Found {len(executives)} executives at {domain}")
                        return executives
                    else:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Apollo API error for {domain}: {response.status}")
                        return []
        
        except Exception as e:
            logger.error(f"❌ Error searching Apollo for {domain}: {str(e)}")
            return []
    
    async def _search_executives_and_org_by_domain(
        self,
        domain: str,
        company_name: Optional[str] = None
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """
        Search for executives at a company by domain (OPTIMIZED - 1 credit)
        Also extracts organization data from people response to avoid separate org search
        
        Returns:
            Tuple of (executives list, organization dict)
        """
        cache_key = self._get_cache_key("exec_domain", domain)
        org_cache_key = self._get_cache_key("org_domain", domain)
        
        # Check cache for both
        if cache_key in self.cache and org_cache_key in self.cache:
            logger.debug(f"📦 Using cached data for {domain}")
            return self.cache[cache_key], self.cache[org_cache_key]
        
        await asyncio.sleep(self.delay)
        
        try:
            payload = {
                "api_key": self.api_key,
                "q_organization_domains": domain,
                "per_page": 50,  # Increased to get more people to filter from
                "page": 1,
            }
            
            if company_name:
                payload["q_organization_name"] = company_name
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    APOLLO_SEARCH_PEOPLE_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        people = data.get("people", [])
                        
                        # Extract organization data from any person (if available)
                        # Try to get from any person, not just executives
                        organization = None
                        if people:
                            # Try to find organization data from any person
                            for person in people:
                                org_data = person.get("organization", {})
                                if org_data and org_data.get("name"):
                                    organization = {
                                        "id": org_data.get("id"),
                                        "name": org_data.get("name", ""),
                                        "website_url": org_data.get("website_url", ""),
                                        "linkedin_url": org_data.get("linkedin_url", ""),
                                        "primary_phone": org_data.get("primary_phone", {}),
                                        "phone": org_data.get("phone", ""),
                                        "industry": org_data.get("industry", ""),
                                        "estimated_num_employees": org_data.get("estimated_num_employees"),
                                        "raw_address": org_data.get("raw_address", ""),
                                        "city": org_data.get("city", ""),
                                        "state": org_data.get("state", ""),
                                        "country": org_data.get("country", ""),
                                    }
                                    break  # Use first valid organization found
                        
                        # Filter for executives only
                        executives = []
                        for person in people:
                            title = person.get("title", "")
                            if self._is_executive_title(title):
                                executives.append({
                                    "first_name": person.get("first_name", ""),
                                    "last_name": person.get("last_name", ""),
                                    "full_name": person.get("name", ""),
                                    "title": title,
                                    "email": person.get("email", ""),
                                    "linkedin_url": person.get("linkedin_url", ""),
                                    "phone_number": person.get("phone_numbers", [{}])[0].get("raw_number", "") if person.get("phone_numbers") else "",
                                    "apollo_id": person.get("id", ""),
                                })
                        
                        # Sort by seniority and limit
                        executives = self._sort_by_seniority(executives)
                        executives = executives[:self.max_executives_per_company]
                        
                        # Cache both results
                        self.cache[cache_key] = executives
                        if organization:
                            self.cache[org_cache_key] = organization
                        self._save_cache()
                        
                        logger.info(f"✅ Found {len(executives)} executives at {domain}")
                        if organization:
                            logger.debug(f"   Organization data extracted from people response")
                        return executives, organization
                    else:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Apollo API error for {domain}: {response.status}")
                        return [], None
        
        except Exception as e:
            logger.error(f"❌ Error searching Apollo for {domain}: {str(e)}")
            return [], None
    
    async def _search_executives_and_org_by_name(
        self,
        company_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """
        Search for executives by company name and location (OPTIMIZED - 1 credit)
        Also extracts organization data from people response
        
        Returns:
            Tuple of (executives list, organization dict)
        """
        cache_key = self._get_cache_key("exec_name", f"{company_name}_{city}_{state}")
        org_cache_key = self._get_cache_key("org_name", f"{company_name}_{city}_{state}")
        
        # Check cache
        if cache_key in self.cache and org_cache_key in self.cache:
            logger.debug(f"📦 Using cached data for {company_name}")
            return self.cache[cache_key], self.cache[org_cache_key]
        
        await asyncio.sleep(self.delay)
        
        try:
            payload = {
                "api_key": self.api_key,
                "q_organization_name": company_name,
                "per_page": 50,  # Increased to get more people to filter from
                "page": 1,
            }
            
            if city:
                payload["q_organization_locations"] = city
            if state:
                payload["q_organization_locations"] = f"{city}, {state}" if city else state
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    APOLLO_SEARCH_PEOPLE_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        people = data.get("people", [])
                        
                        # Extract organization data from any person (if available)
                        # Try to get from any person, not just executives
                        organization = None
                        if people:
                            # Try to find organization data from any person
                            for person in people:
                                org_data = person.get("organization", {})
                                if org_data and org_data.get("name"):
                                    organization = {
                                        "id": org_data.get("id"),
                                        "name": org_data.get("name", ""),
                                        "website_url": org_data.get("website_url", ""),
                                        "linkedin_url": org_data.get("linkedin_url", ""),
                                        "primary_phone": org_data.get("primary_phone", {}),
                                        "phone": org_data.get("phone", ""),
                                        "industry": org_data.get("industry", ""),
                                        "estimated_num_employees": org_data.get("estimated_num_employees"),
                                        "raw_address": org_data.get("raw_address", ""),
                                        "city": org_data.get("city", ""),
                                        "state": org_data.get("state", ""),
                                        "country": org_data.get("country", ""),
                                    }
                                    break  # Use first valid organization found
                        
                        # Filter for executives only
                        executives = []
                        for person in people:
                            title = person.get("title", "")
                            if self._is_executive_title(title):
                                executives.append({
                                    "first_name": person.get("first_name", ""),
                                    "last_name": person.get("last_name", ""),
                                    "full_name": person.get("name", ""),
                                    "title": title,
                                    "email": person.get("email", ""),
                                    "linkedin_url": person.get("linkedin_url", ""),
                                    "phone_number": person.get("phone_numbers", [{}])[0].get("raw_number", "") if person.get("phone_numbers") else "",
                                    "apollo_id": person.get("id", ""),
                                })
                        
                        # Sort by seniority and limit
                        executives = self._sort_by_seniority(executives)
                        executives = executives[:self.max_executives_per_company]
                        
                        # Cache both results
                        self.cache[cache_key] = executives
                        if organization:
                            self.cache[org_cache_key] = organization
                        self._save_cache()
                        
                        logger.info(f"✅ Found {len(executives)} executives for {company_name}")
                        if organization:
                            logger.debug(f"   Organization data extracted from people response")
                        return executives, organization
                    else:
                        return [], None
        
        except Exception as e:
            logger.error(f"❌ Error searching Apollo by name for {company_name}: {str(e)}")
            return [], None
    
    def verify_apollo_results(
        self,
        apollo_company_name: Optional[str],
        our_company_name: str,
        apollo_website: Optional[str],
        our_website: Optional[str],
        executives: List[Dict]
    ) -> Dict:
        """
        Verify Apollo results match our company
        
        Returns:
            Verification result dictionary
        """
        verification = {
            'is_verified': False,
            'confidence': 0.0,
            'name_similarity': 0.0,
            'website_match': False,
            'email_domains': [],
            'needs_review': False,
            'reason': ''
        }
        
        # Name similarity check
        if apollo_company_name:
            name_similarity = calculate_name_similarity(apollo_company_name, our_company_name)
            verification['name_similarity'] = name_similarity
        else:
            name_similarity = 0.0
        
        # Website match check
        if apollo_website and our_website:
            apollo_domain = extract_domain(apollo_website)
            our_domain = extract_domain(our_website)
            verification['website_match'] = (apollo_domain == our_domain)
        
        # Email domain check
        email_domains = []
        for exec in executives:
            if exec.get('email'):
                domain = extract_domain_from_email(exec['email'])
                if domain:
                    email_domains.append(domain)
        
        verification['email_domains'] = list(set(email_domains))
        
        # Calculate overall confidence
        confidence = 0.0
        reasons = []
        
        if name_similarity >= 0.8:
            confidence += 0.5
            reasons.append("Strong name match")
        elif name_similarity >= 0.6:
            confidence += 0.3
            reasons.append("Good name match")
        else:
            reasons.append("Weak name match")
        
        if verification['website_match']:
            confidence += 0.3
            reasons.append("Website matches")
        
        if email_domains:
            confidence += 0.2
            reasons.append("Email domains found")
        
        verification['confidence'] = min(confidence, 1.0)
        verification['is_verified'] = confidence >= 0.6
        verification['needs_review'] = confidence < 0.6
        verification['reason'] = "; ".join(reasons)
        
        return verification
    
    async def _search_person_by_name(
        self,
        person_name: str,
        company_name: Optional[str] = None,
        domain: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Search for a specific person by name in Apollo (1 credit)
        
        Args:
            person_name: Full name of the person to search (can be "First Last" or "Last, First")
            company_name: Company name for filtering
            domain: Company domain for filtering
            city: City for filtering
            state: State for filtering
            
        Returns:
            Person data dictionary or None
        """
        # Parse name - handle both "First Last" and "Last, First" formats
        person_name = person_name.strip()
        
        # Check if it's in "Last, First" format
        if ',' in person_name:
            parts = [p.strip() for p in person_name.split(',', 1)]
            if len(parts) == 2:
                last_name = parts[0]
                first_name = parts[1].split()[0]  # Take first word after comma as first name
            else:
                # Fallback: split by space
                name_parts = person_name.replace(',', '').split()
                if len(name_parts) < 2:
                    logger.debug(f"   ⚠️ Cannot parse name '{person_name}' - need first and last name")
                    return None
                first_name = name_parts[0]
                last_name = " ".join(name_parts[1:])
        else:
            # Standard "First Last" format
            name_parts = person_name.split()
            if len(name_parts) < 2:
                logger.debug(f"   ⚠️ Cannot search for person '{person_name}' - need first and last name")
                return None
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:])
        
        logger.debug(f"   Parsed name: first_name='{first_name}', last_name='{last_name}'")
        
        cache_key = self._get_cache_key("person", f"{person_name}_{company_name}_{domain}")
        if cache_key in self.cache:
            logger.debug(f"📦 Using cached person data for {person_name}")
            return self.cache[cache_key]
        
        await asyncio.sleep(self.delay)
        
        try:
            # Try with company/domain filters first (more targeted)
            payload = {
                "api_key": self.api_key,
                "first_name": first_name,
                "last_name": last_name,
                "per_page": 10,
                "page": 1,
            }
            
            # Add company filters only if available
            if company_name:
                payload["q_organization_name"] = company_name
            if domain:
                payload["q_organization_domains"] = domain
            # Location filters - only add if we have both city and state
            if city and state:
                payload["q_organization_locations"] = f"{city}, {state}"
            elif state:
                payload["q_organization_locations"] = state
            
            logger.debug(f"   Apollo search payload: first_name='{first_name}', last_name='{last_name}', company='{company_name}', domain='{domain}'")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    APOLLO_SEARCH_PEOPLE_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        people = data.get("people", [])
                        
                        # If no results with filters, try without company name (broader search)
                        if not people and company_name:
                            logger.debug(f"   No results with company filter, trying broader search...")
                            payload_broad = {
                                "api_key": self.api_key,
                                "first_name": first_name,
                                "last_name": last_name,
                                "per_page": 10,
                                "page": 1,
                            }
                            if state:
                                payload_broad["q_organization_locations"] = state
                            
                            async with session.post(
                                APOLLO_SEARCH_PEOPLE_ENDPOINT,
                                json=payload_broad,
                                headers={"Content-Type": "application/json"}
                            ) as response2:
                                if response2.status == 200:
                                    data2 = await response2.json()
                                    people = data2.get("people", [])
                        
                        if people:
                            # Filter to find exact name match first
                            exact_match = None
                            for person in people:
                                person_first = person.get("first_name", "").lower().strip()
                                person_last = person.get("last_name", "").lower().strip()
                                
                                # Check if first and last name match (case-insensitive)
                                if (person_first == first_name.lower().strip() and 
                                    person_last == last_name.lower().strip()):
                                    exact_match = person
                                    break
                            
                            # Use exact match if found, otherwise use first result
                            person = exact_match if exact_match else people[0]
                            
                            person_data = {
                                "first_name": person.get("first_name", ""),
                                "last_name": person.get("last_name", ""),
                                "full_name": person.get("name", ""),
                                "title": person.get("title", ""),
                                "email": person.get("email", ""),
                                "linkedin_url": person.get("linkedin_url", ""),
                                "phone_number": person.get("phone_numbers", [{}])[0].get("raw_number", "") if person.get("phone_numbers") else "",
                                "apollo_id": person.get("id", ""),
                                "organization": person.get("organization", {})
                            }
                            
                            # Only return if name matches
                            if (person_data['first_name'].lower().strip() == first_name.lower().strip() and
                                person_data['last_name'].lower().strip() == last_name.lower().strip()):
                                # Cache result
                                self.cache[cache_key] = person_data
                                self._save_cache()
                                
                                logger.info(f"   ✅ Found person: {person_data['full_name']} ({person_data.get('title', 'N/A')})")
                                return person_data
                            else:
                                logger.debug(f"   ⚠️ Found person '{person_data['full_name']}' but name doesn't match '{first_name} {last_name}'")
                                return None
                        else:
                            logger.debug(f"   ⚠️ No person found for '{person_name}'")
                            return None
                    else:
                        logger.warning(f"⚠️ Apollo API error for person search: {response.status}")
                        return None
        
        except Exception as e:
            logger.error(f"❌ Error searching Apollo for person '{person_name}': {str(e)}")
            return None
    
    async def enrich_company(
        self,
        company_name: str,
        website: Optional[str] = None,
        website_confidence: Optional[float] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        registered_agent: Optional[str] = None,
        officers: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Enrich a single company with executive contacts
        
        Returns:
            Dictionary with enrichment results:
            {
                'executives': [...],
                'apollo_company_name': str,
                'apollo_website': str,
                'verification': {...},
                'website_updated': bool
            }
        """
        result = {
            'executives': [],
            'apollo_company_name': None,
            'apollo_website': None,
            'verification': None,
            'website_updated': False
        }
        
        # Determine search method based on website validation
        use_domain_search = False
        domain = None
        
        if website and (website_confidence is None or website_confidence >= 0.5):
            domain = extract_domain(website)
            if domain:
                # Validate domain one more time
                validation = validate_domain(domain, company_name)
                if validation['is_valid']:
                    use_domain_search = True
        
        if use_domain_search:
            # Method 1: Domain search - Get executives AND organization (1 credit - OPTIMIZED)
            logger.info(f"🔍 Searching Apollo by domain: {domain} (executives + org search - 1 credit)")
            
            # Search for executives AND organization in one call
            executives, org = await self._search_executives_and_org_by_domain(domain, company_name)
            
            # Start with executives from domain search (even if org is None)
            all_executives = executives.copy() if executives else []
            existing_ids = {e.get('apollo_id') for e in all_executives if e.get('apollo_id')}
            
            if org:
                result['apollo_company_name'] = org.get("name", "")
                result['apollo_website'] = org.get("website_url", "")
                
                # Verify match
                verification = self.verify_apollo_results(
                    result['apollo_company_name'],
                    company_name,
                    result['apollo_website'],
                    website,
                    executives  # Pass executives for email domain checking
                )
                result['verification'] = verification
                
                # Check if Apollo website is better
                if result['apollo_website'] and result['apollo_website'] != website:
                    result['website_updated'] = True
                    logger.info(f"✅ Apollo found better website: {result['apollo_website']}")
                
                logger.info(f"✅ Organization found (verification: {verification.get('confidence', 0.0):.0%})")
            else:
                # Even if no org found, we might have executives
                result['verification'] = {
                    'is_verified': False,
                    'confidence': 0.0,
                    'name_similarity': 0.0,
                    'website_match': False,
                    'email_domains': [],
                    'needs_review': True,
                    'reason': 'No organization found in Apollo'
                }
                if executives:
                    logger.info(f"✅ Found {len(executives)} executives (but no organization data)")
                else:
                    logger.warning(f"⚠️ No organization or executives found for {domain}")
            
            # Search for officers/registered agent if provided (to supplement)
            if officers:
                logger.info(f"   Searching for {len(officers)} officers from sheet...")
                for officer in officers[:5]:  # Limit to 5 officers
                    officer_name = officer.get('name', '').strip()
                    if officer_name:
                        person = await self._search_person_by_name(
                            person_name=officer_name,
                            company_name=company_name,
                            domain=domain,
                            city=city,
                            state=state
                        )
                        if person and person.get('apollo_id') not in existing_ids:
                            all_executives.append(person)
                            existing_ids.add(person.get('apollo_id'))
            
            # Also search for registered agent if provided
            if registered_agent and registered_agent.strip():
                logger.info(f"   Searching for registered agent: {registered_agent}")
                person = await self._search_person_by_name(
                    person_name=registered_agent.strip(),
                    company_name=company_name,
                    domain=domain,
                    city=city,
                    state=state
                )
                if person and person.get('apollo_id') not in existing_ids:
                    all_executives.append(person)
            
            # Sort by seniority and limit
            all_executives = self._sort_by_seniority(all_executives)
            result['executives'] = all_executives[:self.max_executives_per_company]
            
            if result['executives']:
                logger.info(f"   ✅ Found {len(result['executives'])} total executives ({len(executives)} from domain search, {len(all_executives) - len(executives)} from officers/agent)")
        else:
            # Method 2: Company name search - Get executives AND organization (1 credit)
            if not website or (website_confidence and website_confidence < 0.5):
                logger.info(f"🔄 Searching Apollo by company name (website not validated, executives + org search - 1 credit)")
            else:
                logger.info(f"🔄 Searching Apollo by company name (fallback, executives + org search - 1 credit)")
            
            executives, org = await self._search_executives_and_org_by_name(
                company_name=company_name,
                city=city,
                state=state
            )
            
            if org:
                result['apollo_company_name'] = org.get("name", "")
                result['apollo_website'] = org.get("website_url", "")
                
                # Verify match
                verification = self.verify_apollo_results(
                    result['apollo_company_name'],
                    company_name,
                    result['apollo_website'],
                    website,
                    executives
                )
                result['verification'] = verification
                
                if result['apollo_website'] and result['apollo_website'] != website:
                    result['website_updated'] = True
                    logger.info(f"✅ Apollo found better website: {result['apollo_website']}")
                
                logger.info(f"✅ Organization found (verification: {verification.get('confidence', 0.0):.0%})")
                
                # Combine with officers/agent search
                all_executives = executives.copy() if executives else []
                existing_ids = {e.get('apollo_id') for e in all_executives if e.get('apollo_id')}
                
                # Search for officers/registered agent
                if officers:
                    logger.info(f"   Searching for {len(officers)} officers from sheet...")
                    for officer in officers[:5]:
                        officer_name = officer.get('name', '').strip()
                        if officer_name:
                            person = await self._search_person_by_name(
                                person_name=officer_name,
                                company_name=company_name,
                                city=city,
                                state=state
                            )
                            if person and person.get('apollo_id') not in existing_ids:
                                all_executives.append(person)
                                existing_ids.add(person.get('apollo_id'))
                
                if registered_agent and registered_agent.strip():
                    logger.info(f"   Searching for registered agent: {registered_agent}")
                    person = await self._search_person_by_name(
                        person_name=registered_agent.strip(),
                        company_name=company_name,
                        city=city,
                        state=state
                    )
                    if person and person.get('apollo_id') not in existing_ids:
                        all_executives.append(person)
                
                # Sort and limit
                all_executives = self._sort_by_seniority(all_executives)
                result['executives'] = all_executives[:self.max_executives_per_company]
                
                if result['executives']:
                    logger.info(f"   ✅ Found {len(result['executives'])} total executives")
            else:
                result['executives'] = []
                result['verification'] = {
                    'is_verified': False,
                    'confidence': 0.0,
                    'name_similarity': 0.0,
                    'website_match': False,
                    'email_domains': [],
                    'needs_review': True,
                    'reason': 'No organization found in Apollo'
                }
                logger.warning(f"⚠️ No organization found for {company_name}")
        
        return result


async def enrich_excel_with_person_search_only(
    excel_file_path: str,
    output_file_path: Optional[str] = None,
    save_progress_every: int = 50
) -> pd.DataFrame:
    """
    Enrich Excel file with Apollo person search only (for officers/registered agents)
    Skips organization search - only searches for people by name
    
    Args:
        excel_file_path: Path to input Excel file
        output_file_path: Path to output Excel file (defaults to input file)
        save_progress_every: Save progress every N records
        
    Returns:
        Enriched DataFrame
    """
    import json
    
    # Load Excel file
    logger.info(f"📂 Loading Excel file: {excel_file_path}")
    df = pd.read_excel(excel_file_path, engine='openpyxl')
    logger.info(f"✅ Loaded {len(df)} records")
    
    # Initialize Apollo enricher
    enricher = ApolloEnricher(max_executives_per_company=10)
    
    # Add Apollo enrichment columns
    apollo_columns = [
        'Apollo_Executives_Count',
        'Apollo_Executives_Names',
        'Apollo_Executives_Titles',
        'Apollo_Executives_Emails',
        'Apollo_Executives_LinkedIn',
        'Apollo_Executives_Phones',
        'Apollo_Executives_JSON',
        'Apollo_Company_Name',
        'Apollo_Website'
    ]
    
    for col in apollo_columns:
        if col not in df.columns:
            df[col] = None
    
    total_records = len(df)
    processed = 0
    found_people = 0
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting Person-Only Apollo search for {total_records} companies")
    logger.info(f"{'='*60}")
    
    for idx, row in df.iterrows():
        processed += 1
        
        business_name = row.get('Business Name', '')
        if not business_name:
            continue
        
        website = row.get('Website', '')
        domain = None
        if website:
            domain = extract_domain(website)
        
        city = row.get('City', '')
        state = row.get('State', 'GA')
        
        logger.info(f"\n📄 [{processed}/{total_records}] Processing: {business_name[:50]}...")
        
        # Parse officers from Excel
        officers = []
        officers_json = row.get('Officers', '')
        if pd.notna(officers_json) and officers_json != '':
            try:
                if isinstance(officers_json, str):
                    officers = json.loads(officers_json)
                elif isinstance(officers_json, list):
                    officers = officers_json
            except:
                logger.debug(f"   ⚠️ Could not parse officers JSON")
                officers = []
        
        # Get registered agent
        registered_agent = row.get('Registered / Designated Agent Name', '')
        if pd.isna(registered_agent) or registered_agent == '':
            registered_agent = None
        
        if not officers and not registered_agent:
            logger.debug(f"   ⏭️  Skipping (no officers or registered agent)")
            continue
        
        executives = []
        
        # Search for officers
        if officers:
            logger.info(f"   🔍 Searching for {len(officers)} officers...")
            for officer in officers[:5]:  # Limit to 5 officers
                officer_name = officer.get('name', '').strip()
                if officer_name:
                    person = await enricher._search_person_by_name(
                        person_name=officer_name,
                        company_name=business_name,
                        domain=domain,
                        city=city,
                        state=state
                    )
                    if person:
                        executives.append(person)
        
        # Search for registered agent
        if registered_agent and registered_agent.strip():
            logger.info(f"   🔍 Searching for registered agent: {registered_agent}")
            person = await enricher._search_person_by_name(
                person_name=registered_agent.strip(),
                company_name=business_name,
                domain=domain,
                city=city,
                state=state
            )
            if person:
                # Avoid duplicates
                if not any(e.get('apollo_id') == person.get('apollo_id') for e in executives):
                    executives.append(person)
        
        if executives:
            found_people += len(executives)
            df.at[idx, 'Apollo_Executives_Count'] = len(executives)
            df.at[idx, 'Apollo_Executives_Names'] = '; '.join([e.get('full_name', '') for e in executives])
            df.at[idx, 'Apollo_Executives_Titles'] = '; '.join([e.get('title', '') for e in executives])
            df.at[idx, 'Apollo_Executives_Emails'] = '; '.join([e.get('email', '') for e in executives if e.get('email')])
            df.at[idx, 'Apollo_Executives_LinkedIn'] = '; '.join([e.get('linkedin_url', '') for e in executives if e.get('linkedin_url')])
            df.at[idx, 'Apollo_Executives_Phones'] = '; '.join([e.get('phone_number', '') for e in executives if e.get('phone_number')])
            df.at[idx, 'Apollo_Executives_JSON'] = json.dumps(executives)
            
            # Extract organization data from first person
            first_person = executives[0]
            org_data = first_person.get('organization', {})
            if org_data and org_data.get('name'):
                df.at[idx, 'Apollo_Company_Name'] = org_data.get('name', '')
                df.at[idx, 'Apollo_Website'] = org_data.get('website_url', '')
            
            logger.info(f"   ✅ Found {len(executives)} people")
        
        # Save progress periodically
        if processed % save_progress_every == 0:
            output = output_file_path or excel_file_path
            df.to_excel(output, index=False, engine='openpyxl')
            logger.info(f"   💾 Progress saved: {processed}/{total_records} processed")
    
    # Final save
    output = output_file_path or excel_file_path
    df.to_excel(output, index=False, engine='openpyxl')
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Person search complete!")
    logger.info(f"   Total processed: {processed}/{total_records}")
    logger.info(f"   People found: {found_people}")
    logger.info(f"{'='*60}")
    
    return df


async def enrich_excel_with_apollo(
    excel_file_path: str,
    output_file_path: Optional[str] = None,
    max_executives_per_company: int = 5,
    save_progress_every: int = 50,
    only_companies_with_website: bool = True,
    min_website_confidence: float = 0.5
) -> pd.DataFrame:
    """
    Enrich Excel file with Apollo executive data
    
    Args:
        excel_file_path: Path to input Excel file
        output_file_path: Path to output Excel file (defaults to input file)
        max_executives_per_company: Maximum executives per company
        save_progress_every: Save progress every N records
        only_companies_with_website: Only process companies with websites
        min_website_confidence: Minimum website confidence to use domain search
        
    Returns:
        Enriched DataFrame
    """
    # Load Excel file
    logger.info(f"📂 Loading Excel file: {excel_file_path}")
    df = pd.read_excel(excel_file_path, engine='openpyxl')
    logger.info(f"✅ Loaded {len(df)} records")
    
    # Initialize Apollo enricher
    enricher = ApolloEnricher(max_executives_per_company=max_executives_per_company)
    
    # Add Apollo enrichment columns
    apollo_columns = [
        'Apollo_Executives_Count',
        'Apollo_Executives_Names',
        'Apollo_Executives_Titles',
        'Apollo_Executives_Emails',
        'Apollo_Executives_LinkedIn',
        'Apollo_Executives_Phones',
        'Apollo_Company_Name',
        'Apollo_Website',
        'Apollo_Website_Updated',
        'Apollo_Verification_Confidence',
        'Apollo_Verification_Status',
        'Apollo_Needs_Review',
        'Apollo_Executives_JSON'
    ]
    
    for col in apollo_columns:
        if col not in df.columns:
            df[col] = ''
    
    total_records = len(df)
    processed = 0
    found_executives = 0
    skipped_no_website = 0
    website_updates = 0
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Starting Apollo enrichment for {total_records} companies")
    logger.info(f"{'='*60}")
    
    # Helper function to extract city/state from address (to avoid circular import)
    def extract_city_state_from_address(address: str):
        """Extract city and state from address string"""
        if not address:
            return None, None
        try:
            import re
            # Pattern: "City, ST ZIP" or "City, State ZIP"
            pattern = r',\s*([A-Za-z\s]+?),\s*([A-Z]{2})(?:\s+\d{5})?$'
            match = re.search(pattern, address)
            if match:
                return match.group(1).strip(), match.group(2).strip()
            # Pattern 2: Last two words before ZIP
            pattern2 = r'([A-Za-z\s]+?),\s*([A-Z]{2})\s+\d{5}'
            match = re.search(pattern2, address)
            if match:
                return match.group(1).strip(), match.group(2).strip()
            # Pattern 3: Split by comma
            parts = [p.strip() for p in address.split(',')]
            if len(parts) >= 2:
                last_part = parts[-1]
                state_match = re.search(r'\b([A-Z]{2})\b', last_part)
                if state_match:
                    state = state_match.group(1)
                    if len(parts) >= 2:
                        city = parts[-2]
                        return city, state
            return None, None
        except:
            return None, None
    
    for idx, row in df.iterrows():
        processed += 1
        
        business_name = row.get('Business Name', '')
        if not business_name:
            continue
        
        website = row.get('Website', '')
        website_confidence = row.get('Website_Confidence', None)
        if pd.notna(website_confidence):
            website_confidence = float(website_confidence)
        else:
            website_confidence = None
        
        # Extract city/state
        principal_address = row.get('Principal Office Address', '')
        city, state = extract_city_state_from_address(principal_address)
        if not city and 'City' in row and row.get('City'):
            city = row.get('City')
        if not state:
            state = 'GA'
        
        # Skip if no website and only_companies_with_website is True
        if only_companies_with_website and not website:
            skipped_no_website += 1
            logger.debug(f"⏭️  [{processed}/{total_records}] Skipping {business_name[:50]}... (no website)")
            continue
        
        logger.info(f"\n📄 [{processed}/{total_records}] Processing: {business_name[:50]}...")
        
        # Parse officers from Excel
        officers = []
        officers_json = row.get('Officers', '')
        if pd.notna(officers_json) and officers_json != '':
            try:
                if isinstance(officers_json, str):
                    officers = json.loads(officers_json)
                elif isinstance(officers_json, list):
                    officers = officers_json
            except:
                logger.debug(f"   ⚠️ Could not parse officers JSON for {business_name}")
                officers = []
        
        # Get registered agent
        registered_agent = row.get('Registered / Designated Agent Name', '')
        if pd.isna(registered_agent) or registered_agent == '':
            registered_agent = None
        
        if officers:
            logger.info(f"   📋 Found {len(officers)} officers from sheet")
        if registered_agent:
            logger.info(f"   📋 Registered Agent: {registered_agent}")
        
        try:
            # Enrich with Apollo
            enrichment_result = await enricher.enrich_company(
                company_name=business_name,
                website=website,
                website_confidence=website_confidence,
                city=city,
                state=state,
                registered_agent=registered_agent,
                officers=officers
            )
            
            executives = enrichment_result.get('executives', [])
            verification = enrichment_result.get('verification', {})
            
            if executives:
                found_executives += len(executives)
                
                # Store executive data
                df.at[idx, 'Apollo_Executives_Count'] = len(executives)
                df.at[idx, 'Apollo_Executives_Names'] = '; '.join([e.get('full_name', '') for e in executives])
                df.at[idx, 'Apollo_Executives_Titles'] = '; '.join([e.get('title', '') for e in executives])
                df.at[idx, 'Apollo_Executives_Emails'] = '; '.join([e.get('email', '') for e in executives if e.get('email')])
                df.at[idx, 'Apollo_Executives_LinkedIn'] = '; '.join([e.get('linkedin_url', '') for e in executives if e.get('linkedin_url')])
                df.at[idx, 'Apollo_Executives_Phones'] = '; '.join([e.get('phone_number', '') for e in executives if e.get('phone_number')])
                df.at[idx, 'Apollo_Executives_JSON'] = json.dumps(executives)
                
                logger.info(f"   ✅ Found {len(executives)} executives")
                for exec in executives[:3]:
                    logger.info(f"      - {exec.get('full_name', 'N/A')} ({exec.get('title', 'N/A')})")
            
            # Store Apollo company info
            if enrichment_result.get('apollo_company_name'):
                df.at[idx, 'Apollo_Company_Name'] = enrichment_result['apollo_company_name']
            
            if enrichment_result.get('apollo_website'):
                df.at[idx, 'Apollo_Website'] = enrichment_result['apollo_website']
                
                # Update website if Apollo has better one
                if enrichment_result.get('website_updated'):
                    df.at[idx, 'Website'] = enrichment_result['apollo_website']
                    df.at[idx, 'Website_Source'] = 'apollo'
                    df.at[idx, 'Website_Confidence'] = 0.95
                    df.at[idx, 'Apollo_Website_Updated'] = True
                    website_updates += 1
                    logger.info(f"   ✅ Updated website to Apollo's verified website")
            
            # Store verification data
            if verification:
                df.at[idx, 'Apollo_Verification_Confidence'] = verification.get('confidence', 0.0)
                df.at[idx, 'Apollo_Verification_Status'] = 'Verified' if verification.get('is_verified') else 'Needs Review'
                df.at[idx, 'Apollo_Needs_Review'] = verification.get('needs_review', False)
            
            # Save progress periodically
            if processed % save_progress_every == 0:
                output = output_file_path or excel_file_path
                df.to_excel(output, index=False, engine='openpyxl')
                logger.info(f"   💾 Progress saved: {processed}/{total_records} processed")
        
        except Exception as e:
            logger.error(f"   ❌ Error processing {business_name}: {str(e)}")
            continue
    
    # Final save
    output = output_file_path or excel_file_path
    df.to_excel(output, index=False, engine='openpyxl')
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Apollo enrichment complete!")
    logger.info(f"   Total processed: {processed}/{total_records}")
    logger.info(f"   Companies with executives: {found_executives}")
    logger.info(f"   Websites updated by Apollo: {website_updates}")
    logger.info(f"   Skipped (no website): {skipped_no_website}")
    logger.info(f"{'='*60}")
    
    return df


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python apollo_enricher.py <excel_file_path> [output_file_path] [--person-only]")
        print("  --person-only: Only search for officers/registered agents (skip organization search)")
        sys.exit(1)
    
    excel_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None
    person_only = '--person-only' in sys.argv
    
    if person_only:
        logger.info("🔍 Running Person-Only Search Mode")
        asyncio.run(enrich_excel_with_person_search_only(
            excel_file_path=excel_file,
            output_file_path=output_file
        ))
    else:
        logger.info("🔍 Running Full Apollo Enrichment (Organization + Person Search)")
        asyncio.run(enrich_excel_with_apollo(
            excel_file_path=excel_file,
            output_file_path=output_file,
            max_executives_per_company=5,
            only_companies_with_website=True,
            min_website_confidence=0.5
        ))

