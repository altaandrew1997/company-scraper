"""
Data Aggregator
Merges and selects best data from multiple sources (Google, Facebook, etc.)
"""

from typing import Dict, List, Optional, Any
from loguru import logger
from website_validator import select_best_website, extract_domain


def merge_google_facebook_data(
    company_record: Dict,
    google_data: Optional[Dict] = None,
    facebook_data: Optional[Dict] = None
) -> Dict:
    """
    Merge Google and Facebook data, selecting best values based on source priority
    
    Source Priority:
    1. Apollo (highest - if available)
    2. Google Business Profile
    3. Facebook About page
    4. Google Search results
    5. Other sources
    
    Args:
        company_record: Base company record from Georgia SOS
        google_data: Dictionary with Google-scraped data
        facebook_data: Dictionary with Facebook-scraped data
        
    Returns:
        Merged company record with best data selected
    """
    merged = company_record.copy()
    
    # Source priority scores (higher = more trusted)
    # Note: For WEBSITE, google_search is prioritized over facebook because
    # Facebook often extracts invalid links like messenger.com
    SOURCE_PRIORITY = {
        'apollo': 100,
        'google_business': 90,
        'google_search': 70,  # Prioritize over facebook for websites
        'facebook': 50,  # Facebook data less reliable for websites
        'email': 40,
        'other': 20
    }
    
    # Fields to merge with priority (Google Business Profile disabled - using DuckDuckGo)
    fields_to_merge = {
        'website': ['Website', 'website'],
        'phone': ['Phone', 'phone', 'contact_phone'],
        'email': ['Email', 'email', 'contact_email'],
        'address': ['address', 'Principal Address', 'principal_address'],
        'linkedin': ['LinkedIn'],
        'facebook': ['Facebook'],
        'description': ['description', 'Description'],
        'category': ['category', 'Category'],
    }
    
    # Collect all values for each field with their sources
    field_candidates = {}
    
    # Process Google data
    if google_data:
        for field_type, field_names in fields_to_merge.items():
            for field_name in field_names:
                value = google_data.get(field_name)
                if value and str(value).strip():
                    source = 'google_business' if 'Google_Business' in field_name else 'google_search'
                    if field_type not in field_candidates:
                        field_candidates[field_type] = []
                    field_candidates[field_type].append({
                        'value': value,
                        'source': source,
                        'priority': SOURCE_PRIORITY.get(source, 20),
                        'field_name': field_name
                    })
    
    # Process Facebook data
    if facebook_data:
        for field_type, field_names in fields_to_merge.items():
            for field_name in field_names:
                value = facebook_data.get(field_name)
                if value and str(value).strip():
                    source = 'facebook'
                    if field_type not in field_candidates:
                        field_candidates[field_type] = []
                    field_candidates[field_type].append({
                        'value': value,
                        'source': source,
                        'priority': SOURCE_PRIORITY.get(source, 20),
                        'field_name': field_name
                    })
    
    # Select best value for each field
    for field_type, candidates in field_candidates.items():
        if not candidates:
            continue
        
        # Sort by priority (highest first)
        candidates.sort(key=lambda x: x['priority'], reverse=True)
        
        # Check for conflicts (multiple different values)
        top_priority = candidates[0]['priority']
        top_candidates = [c for c in candidates if c['priority'] == top_priority]
        
        if len(top_candidates) == 1:
            # Single top candidate - use it
            best = top_candidates[0]
            merged[best['field_name']] = best['value']
            logger.debug(f"   Selected {field_type} from {best['source']}: {best['value'][:50]}")
        else:
            # Multiple candidates with same priority - check for agreement
            values = [c['value'] for c in top_candidates]
            unique_values = list(set(str(v).lower().strip() for v in values))
            
            if len(unique_values) == 1:
                # All agree - use any
                best = top_candidates[0]
                merged[best['field_name']] = best['value']
                logger.debug(f"   Selected {field_type} from {best['source']} (agreement): {best['value'][:50]}")
            else:
                # Conflict - use highest priority source
                best = top_candidates[0]
                merged[best['field_name']] = best['value']
                logger.warning(f"   ⚠️  Conflict in {field_type}: {len(unique_values)} different values, using {best['source']}")
    
    # Special handling for website - use website_validator
    website_sources = []
    if google_data:
        if google_data.get('Website'):
            website_sources.append({
                'url': google_data['Website'],
                'source': 'google_search'
            })
        if google_data.get('Google_Business_Website'):
            website_sources.append({
                'url': google_data['Google_Business_Website'],
                'source': 'google_business'
            })
    
    if facebook_data and facebook_data.get('website'):
        website_sources.append({
            'url': facebook_data['website'],
            'source': 'facebook'
        })
    
    if website_sources:
        company_name = merged.get('Entity Name') or merged.get('Business Name', '')
        best_website = select_best_website(website_sources, company_name)
        if best_website:
            merged['Website'] = best_website['url']
            merged['Website_Confidence'] = best_website['combined_confidence']
            merged['Website_Source'] = best_website['source']
            merged['Website_Validation_Reason'] = best_website['validation']['reason']
    
    # Calculate data quality score
    data_quality_score = _calculate_data_quality_score(merged)
    merged['data_quality_score'] = data_quality_score
    
    return merged


def _calculate_data_quality_score(record: Dict) -> float:
    """
    Calculate data quality score (0-1) based on completeness and validation
    
    Args:
        record: Company record dictionary
        
    Returns:
        Data quality score (0.0-1.0)
    """
    score = 0.0
    max_score = 0.0
    
    # Website (25 points)
    max_score += 25
    if record.get('Website'):
        website_confidence = record.get('Website_Confidence', 0.5)
        score += 25 * website_confidence
    
    # Contact info (25 points)
    max_score += 25
    has_phone = bool(record.get('Google_Business_Phone') or record.get('Phone'))
    has_email = bool(record.get('Email'))
    contact_points = sum([has_phone, has_email])
    score += 25 * (contact_points / 2.0)
    
    # Address (15 points)
    max_score += 15
    if record.get('Google_Business_Address') or record.get('Principal Address'):
        score += 15
    
    # Social media (15 points)
    max_score += 15
    has_linkedin = bool(record.get('LinkedIn'))
    has_facebook = bool(record.get('Facebook'))
    social_points = sum([has_linkedin, has_facebook])
    score += 15 * (social_points / 2.0)
    
    # NAICS code (10 points)
    max_score += 10
    if record.get('naics_code') or record.get('NAICS Code'):
        score += 10
    
    # Officers (10 points)
    max_score += 10
    officer_count = record.get('Officer_Count', 0)
    # Convert to int if it's a string
    try:
        officer_count = int(officer_count) if officer_count else 0
    except (ValueError, TypeError):
        officer_count = 0
    if officer_count > 0:
        score += min(10, officer_count * 2)  # Up to 10 points
    
    # Normalize to 0-1
    if max_score > 0:
        return min(1.0, score / max_score)
    return 0.0


class DataAggregator:
    """Class-based aggregator for batch processing"""
    
    def __init__(self):
        """Initialize data aggregator"""
        pass
    
    def aggregate_batch(
        self,
        companies_df,
        google_data_dict: Optional[Dict] = None,
        facebook_data_dict: Optional[Dict] = None
    ):
        """
        Aggregate data for multiple companies
        
        Args:
            companies_df: DataFrame with company records
            google_data_dict: Dict mapping company_id/name to Google data
            facebook_data_dict: Dict mapping company_id/name to Facebook data
            
        Returns:
            DataFrame with aggregated data
        """
        aggregated_records = []
        
        for idx, row in companies_df.iterrows():
            company_name = row.get('Entity Name') or row.get('Business Name', f"Company_{idx}")
            
            google_data = google_data_dict.get(company_name) if google_data_dict else None
            facebook_data = facebook_data_dict.get(company_name) if facebook_data_dict else None
            
            merged = merge_google_facebook_data(
                row.to_dict(),
                google_data,
                facebook_data
            )
            
            aggregated_records.append(merged)
        
        import pandas as pd
        return pd.DataFrame(aggregated_records)












