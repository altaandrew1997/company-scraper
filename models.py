"""
Data models for company information and business registry records.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
import re


class Address(BaseModel):
    """Standardized address model"""
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: str = "US"
    
    @validator('zip_code')
    def validate_zip_code(cls, v):
        if v and not re.match(r'^\d{5}(-\d{4})?$', v):
            raise ValueError('Invalid ZIP code format')
        return v


class ContactInfo(BaseModel):
    """Contact information model"""
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    
    @validator('email')
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v


class BusinessRegistryRecord(BaseModel):
    """Raw business registry record from Secretary of State"""
    entity_name: str
    entity_type: Optional[str] = None  # LLC, Corp, etc.
    registration_number: Optional[str] = None
    registration_date: Optional[datetime] = None
    status: Optional[str] = None  # Active, Inactive, etc.
    registered_agent: Optional[str] = None
    registered_agent_address: Optional[Address] = None
    principal_address: Optional[Address] = None
    mailing_address: Optional[Address] = None
    jurisdiction: Optional[str] = None
    source_url: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class EnrichedCompanyRecord(BaseModel):
    """Enriched company record with additional data"""
    # Core registry data
    entity_name: str
    entity_type: Optional[str] = None
    registration_number: Optional[str] = None
    registration_date: Optional[datetime] = None
    status: Optional[str] = None
    
    # Address information
    registered_agent: Optional[str] = None
    registered_agent_address: Optional[Address] = None
    principal_address: Optional[Address] = None
    mailing_address: Optional[Address] = None
    
    # Enriched data
    website: Optional[str] = None
    contact_info: Optional[ContactInfo] = None
    
    # Industry classification
    naics_code: Optional[str] = None
    naics_description: Optional[str] = None
    industry_keywords: Optional[List[str]] = None
    
    # Data quality metrics
    data_quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    enrichment_status: str = "pending"  # pending, completed, failed
    enrichment_errors: Optional[List[str]] = None
    
    # Metadata
    jurisdiction: str = "GA"  # Starting with Georgia
    source_url: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    enriched_at: Optional[datetime] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ScrapingJob(BaseModel):
    """Scraping job metadata"""
    job_id: str
    source: str  # e.g., "georgia_sos"
    status: str = "pending"  # pending, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    records_scraped: int = 0
    records_enriched: int = 0
    errors: Optional[List[str]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class NAICSClassification(BaseModel):
    """NAICS code classification"""
    code: str
    title: str
    description: Optional[str] = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    keywords_matched: List[str] = []
    
    @validator('code')
    def validate_naics_code(cls, v):
        if not re.match(r'^\d{2,6}$', v):
            raise ValueError('Invalid NAICS code format')
        return v



