"""
Company Size Filter
Determines if a company is large enough to be enriched with Apollo.io
"""

from typing import Dict, Tuple, Optional
from datetime import datetime
from loguru import logger
from config import APOLLO_FILTERING


def should_enrich_with_apollo(company_record: Dict, config: Optional[Dict] = None) -> Tuple[bool, float, str]:
    """
    Determine if company should be enriched with Apollo
    
    Apollo is more likely to have data on larger, established companies.
    This function scores companies based on various indicators.
    
    Args:
        company_record: Dictionary with company data
        config: Optional configuration dict (defaults to APOLLO_FILTERING from config)
        
    Returns:
        Tuple of (should_enrich, confidence_score, reason)
    """
    if config is None:
        config = APOLLO_FILTERING
    
    score = 0.0
    reasons = []
    required_checks = []
    
    # 1. Website validation (30 points) - Most important indicator
    website_confidence = company_record.get('Website_Confidence', 0)
    if website_confidence and website_confidence >= 0.8:
        score += 30
        reasons.append("High website confidence")
    elif website_confidence and website_confidence >= 0.5:
        score += 15
        reasons.append("Medium website confidence")
    
    # 2. Has validated website (20 points)
    website = company_record.get('Website') or company_record.get('website')
    if website and website_confidence:
        score += 20
        reasons.append("Has validated website")
        required_checks.append(("website", True))
    elif config.get("require_website", True):
        # If website is required but missing, this is a blocker
        required_checks.append(("website", False))
    
    # 3. LinkedIn presence (15 points)
    linkedin = company_record.get('LinkedIn') or company_record.get('linkedin_url')
    if linkedin:
        score += 15
        reasons.append("Has LinkedIn page")
    
    # 4. Google Business Profile (15 points)
    has_gbp_phone = bool(company_record.get('Google_Business_Phone'))
    has_gbp_address = bool(company_record.get('Google_Business_Address'))
    has_gbp_rating = bool(company_record.get('Google_Business_Rating'))
    
    if has_gbp_phone or has_gbp_address or has_gbp_rating:
        score += 15
        reasons.append("Has Google Business Profile")
    
    # 5. Multiple officers (10 points)
    officer_count = company_record.get('Officer_Count', 0)
    if not officer_count:
        # Try alternative field names
        officers = company_record.get('Officers') or company_record.get('Officers_Formatted')
        if officers:
            if isinstance(officers, str):
                # Count officers in formatted string
                officer_count = len([o for o in officers.split(';') if o.strip()])
            else:
                officer_count = len(officers) if isinstance(officers, list) else 1
    
    min_officers = config.get("min_officers", 0)
    if officer_count and officer_count > 1:
        score += 10
        reasons.append(f"{officer_count} officers")
    elif officer_count == 1:
        score += 5
        reasons.append("Has officers")
    
    if min_officers > 0 and officer_count < min_officers:
        required_checks.append(("officers", False))
    
    # 6. Entity type (10 points)
    entity_type = str(company_record.get('Entity Type', '') or company_record.get('entity_type', '')).upper()
    if any(term in entity_type for term in ['CORP', 'CORPORATION', 'INC', 'INCORPORATED']):
        score += 10
        reasons.append("Corporation entity type")
    elif 'LLC' in entity_type:
        score += 5
        reasons.append("LLC entity type")
    
    # 7. Company age (10 points)
    registration_date = (
        company_record.get('Date of Formation') or 
        company_record.get('registration_date') or
        company_record.get('Registration Date')
    )
    
    min_years = config.get("min_years_old", 0)
    years_old = None
    
    if registration_date:
        try:
            if isinstance(registration_date, str):
                # Try to parse various date formats
                date_str = registration_date.split()[0] if ' ' in registration_date else registration_date
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%m-%d-%Y']:
                    try:
                        reg_date = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
                else:
                    # Try to extract year if full date parsing fails
                    year_match = None
                    import re
                    year_match = re.search(r'(\d{4})', registration_date)
                    if year_match:
                        year = int(year_match.group(1))
                        reg_date = datetime(year, 1, 1)
                    else:
                        raise ValueError("Could not parse date")
            else:
                reg_date = registration_date
            
            years_old = (datetime.now() - reg_date).days / 365.25
            
            if years_old >= 5:
                score += 10
                reasons.append(f"{int(years_old)} years old")
            elif years_old >= 3:
                score += 5
                reasons.append(f"{int(years_old)} years old")
        except Exception as e:
            logger.debug(f"Could not parse registration date '{registration_date}': {str(e)}")
    
    if min_years > 0 and (years_old is None or years_old < min_years):
        required_checks.append(("age", False))
    
    # 8. Active status (5 points)
    status = str(company_record.get('Status', '') or company_record.get('status', '')).upper()
    if 'ACTIVE' in status:
        score += 5
        reasons.append("Active status")
    elif 'INACTIVE' in status or 'DISSOLVED' in status:
        score -= 10  # Penalty for inactive companies
        reasons.append("Inactive/Dissolved status")
    
    # 9. Data completeness (5 points)
    has_phone = bool(
        company_record.get('Google_Business_Phone') or 
        company_record.get('Phone') or 
        company_record.get('contact_phone')
    )
    has_email = bool(
        company_record.get('Email') or 
        company_record.get('contact_email')
    )
    has_address = bool(
        company_record.get('Google_Business_Address') or 
        company_record.get('Principal Address') or 
        company_record.get('principal_address')
    )
    
    data_points = sum([has_phone, has_email, has_address])
    if data_points >= 2:
        score += 5
        reasons.append("Good data completeness")
    
    # 10. Industry/NAICS (bonus points)
    naics_code = (
        str(company_record.get('naics_code', '') or 
        company_record.get('NAICS Code', '') or '')
    )
    if naics_code and naics_code.isdigit():
        naics_int = int(naics_code[:2]) if len(naics_code) >= 2 else 0
        # Certain industries more likely in Apollo
        # 51-55: Professional services, finance, real estate, etc.
        if naics_int in [51, 52, 53, 54, 55]:
            score += 5
            reasons.append("Professional services industry")
        # 54: Professional, Scientific, and Technical Services
        elif naics_int == 54:
            score += 3
            reasons.append("Technical services industry")
    
    # Check required conditions
    all_required_met = all(check[1] for check in required_checks)
    
    # Get threshold
    threshold = config.get("min_score", 50)
    
    # Final decision
    should_enrich = all_required_met and score >= threshold
    
    # Build reason string
    if not all_required_met:
        missing = [check[0] for check in required_checks if not check[1]]
        reason_str = f"Score: {score}/100 - Missing required: {', '.join(missing)}"
    else:
        reason_str = f"Score: {score}/100 ({', '.join(reasons)})"
    
    return should_enrich, score, reason_str


class CompanySizeFilter:
    """Class-based filter for batch processing"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize company size filter
        
        Args:
            config: Optional configuration dict (defaults to APOLLO_FILTERING from config)
        """
        self.config = config or APOLLO_FILTERING
    
    def filter_companies(self, companies_df, company_name_col: str = 'Entity Name') -> Tuple[list, list]:
        """
        Filter companies into candidates and skipped lists
        
        Args:
            companies_df: DataFrame with company records
            company_name_col: Name of column containing company name
            
        Returns:
            Tuple of (candidate_indices, skipped_indices)
        """
        candidates = []
        skipped = []
        
        for idx, row in companies_df.iterrows():
            company_name = row.get(company_name_col, f"Company_{idx}")
            should_enrich, score, reason = should_enrich_with_apollo(row.to_dict(), self.config)
            
            if should_enrich:
                candidates.append(idx)
                logger.debug(f"✅ {company_name}: {reason}")
            else:
                skipped.append(idx)
                logger.debug(f"⏭️  {company_name}: {reason}")
        
        return candidates, skipped
    
    def get_candidates_df(self, companies_df, company_name_col: str = 'Entity Name'):
        """
        Get DataFrame with only Apollo candidate companies
        
        Args:
            companies_df: DataFrame with company records
            company_name_col: Name of column containing company name
            
        Returns:
            DataFrame with only candidate companies
        """
        candidates, _ = self.filter_companies(companies_df, company_name_col)
        return companies_df.loc[candidates] if candidates else companies_df.iloc[0:0]


