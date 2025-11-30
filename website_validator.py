"""
Website Validation Module
Validates and scores websites from multiple sources to ensure accuracy
"""

import re
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from loguru import logger
from difflib import SequenceMatcher


# Known directory/government sites to reject
SKIP_DOMAINS = [
    'transportation.gov',
    'sos.ga.gov',
    'ecorp.sos.ga.gov',
    'bbb.org',
    'yellowpages.com',
    'superpages.com',
    'manta.com',
    'bizapedia.com',
    'zoominfo.com',
    'dnb.com',
    'bloomberg.com',
    'crunchbase.com',
    'mapquest.com',
    'facebook.com',
    'linkedin.com',
    'instagram.com',
    'twitter.com',
    'yelp.com',
]


def extract_domain(url: str) -> Optional[str]:
    """
    Extract clean domain from URL
    
    Args:
        url: Website URL
        
    Returns:
        Clean domain (e.g., 'example.com') or None
    """
    if not url:
        return None
    
    try:
        # Add protocol if missing
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Remove port if present
        if ':' in domain:
            domain = domain.split(':')[0]
        
        return domain.lower().strip() if domain else None
    except Exception as e:
        logger.debug(f"Error extracting domain from '{url}': {str(e)}")
        return None


def extract_company_keywords(company_name: str) -> List[str]:
    """
    Extract meaningful keywords from company name
    
    Args:
        company_name: Company name (e.g., "BIG BREEZE LANDSCAPING, LLC")
        
    Returns:
        List of keywords (e.g., ['big', 'breeze', 'landscaping'])
    """
    if not company_name:
        return []
    
    suffixes = [
        ' llc', ' l.l.c.', ' inc', ' inc.', ' corp', ' corporation',
        ' ltd', ' ltd.', ' co', ' co.', ' limited', ' lp', ' llp',
        ' pc', ' p.c.', ' pa', ' p.a.'
    ]
    
    clean_name = company_name.lower()
    for suffix in suffixes:
        clean_name = clean_name.replace(suffix, '')
    
    # Remove special characters and split
    clean_name = re.sub(r'[^\w\s]', ' ', clean_name)
    keywords = [kw.strip() for kw in clean_name.split() if len(kw.strip()) > 2]
    
    # Remove common words
    stop_words = {'the', 'and', 'of', 'for', 'in', 'on', 'at', 'to', 'a', 'an'}
    keywords = [kw for kw in keywords if kw not in stop_words]
    
    return keywords


def calculate_name_similarity(name1: str, name2: str) -> float:
    """
    Calculate similarity between two company names (0-1)
    
    Args:
        name1: First company name
        name2: Second company name
        
    Returns:
        Similarity score (0-1)
    """
    if not name1 or not name2:
        return 0.0
    
    # Normalize names
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    
    # Exact match
    if n1 == n2:
        return 1.0
    
    # Use SequenceMatcher for similarity
    similarity = SequenceMatcher(None, n1, n2).ratio()
    
    # Check if one name contains the other
    if n1 in n2 or n2 in n1:
        similarity = max(similarity, 0.8)
    
    return similarity


def validate_domain(domain: str, company_name: str) -> Dict[str, any]:
    """
    Validate if domain belongs to company
    
    Args:
        domain: Domain to validate (e.g., 'example.com')
        company_name: Company name
        
    Returns:
        Validation result dictionary
    """
    if not domain:
        return {
            'is_valid': False,
            'confidence': 0.0,
            'reason': 'No domain provided'
        }
    
    domain_lower = domain.lower()
    
    # Check if domain is in skip list
    is_directory = any(skip_domain in domain_lower for skip_domain in SKIP_DOMAINS)
    if is_directory:
        return {
            'is_valid': False,
            'confidence': 0.1,
            'reason': 'Directory/government site'
        }
    
    # Extract company keywords
    keywords = extract_company_keywords(company_name)
    if not keywords:
        return {
            'is_valid': False,
            'confidence': 0.2,
            'reason': 'Could not extract company keywords'
        }
    
    # Check if domain contains company keywords
    keyword_matches = sum(1 for kw in keywords if kw in domain_lower)
    keyword_score = keyword_matches / len(keywords) if keywords else 0
    
    # Check domain structure
    domain_parts = domain_lower.split('.')
    main_domain = domain_parts[0] if domain_parts else ''
    
    # Very short domain = suspicious
    is_too_short = len(main_domain) < 3
    
    # Generic domains = suspicious
    generic_domains = ['example', 'test', 'demo', 'sample', 'company', 'business']
    is_generic = main_domain in generic_domains
    
    # Calculate confidence
    if is_generic:
        confidence = 0.2
        reason = 'Generic domain name'
    elif is_too_short:
        confidence = 0.2
        reason = 'Domain too short'
    elif keyword_score >= 0.7:
        confidence = 0.9
        reason = 'Strong domain match'
    elif keyword_score >= 0.5:
        confidence = 0.7
        reason = 'Good domain match'
    elif keyword_score >= 0.3:
        confidence = 0.5
        reason = 'Partial domain match'
    else:
        confidence = 0.3
        reason = 'Weak domain match'
    
    return {
        'is_valid': confidence >= 0.5,
        'confidence': confidence,
        'reason': reason,
        'keyword_score': keyword_score,
        'domain': domain
    }


def score_website_source(source: str) -> float:
    """
    Get confidence score for website source
    
    Args:
        source: Source name ('apollo', 'google_business', 'linkedin', 'email', 'google_search')
        
    Returns:
        Confidence score (0-1)
    """
    source_scores = {
        'apollo': 0.95,
        'google_business': 0.90,
        'linkedin': 0.80,
        'email': 0.70,
        'google_search': 0.50,
    }
    
    return source_scores.get(source.lower(), 0.5)


def select_best_website(
    websites: List[Dict[str, any]],
    company_name: str
) -> Optional[Dict[str, any]]:
    """
    Select best website from multiple sources
    
    Args:
        websites: List of website dictionaries with keys:
            - 'url': Website URL
            - 'source': Source name
            - 'domain': Domain (optional, will be extracted)
        company_name: Company name for validation
        
    Returns:
        Best website dictionary with validation info or None
    """
    if not websites:
        return None
    
    # Process and validate each website
    validated_websites = []
    
    for website in websites:
        url = website.get('url')
        if not url:
            continue
        
        source = website.get('source', 'unknown')
        domain = website.get('domain') or extract_domain(url)
        
        if not domain:
            continue
        
        # Validate domain
        validation = validate_domain(domain, company_name)
        
        # Get source confidence
        source_confidence = score_website_source(source)
        
        # Combined confidence (weighted average)
        combined_confidence = (validation['confidence'] * 0.6) + (source_confidence * 0.4)
        
        validated_websites.append({
            'url': url,
            'domain': domain,
            'source': source,
            'validation': validation,
            'source_confidence': source_confidence,
            'combined_confidence': combined_confidence,
            'is_valid': validation['is_valid'] and combined_confidence >= 0.5
        })
    
    if not validated_websites:
        return None
    
    # Sort by combined confidence (highest first)
    validated_websites.sort(key=lambda x: x['combined_confidence'], reverse=True)
    
    # Return best valid website, or best overall if none are valid
    best_valid = next((w for w in validated_websites if w['is_valid']), None)
    best_overall = validated_websites[0]
    
    return best_valid or best_overall


def extract_domain_from_email(email: str) -> Optional[str]:
    """
    Extract domain from email address
    
    Args:
        email: Email address
        
    Returns:
        Domain or None
    """
    if not email or '@' not in email:
        return None
    
    try:
        domain = email.split('@')[1].lower().strip()
        return domain
    except:
        return None


