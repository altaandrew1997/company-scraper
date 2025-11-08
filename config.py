"""
Alta Data Collection System
===========================

A scalable infrastructure for collecting and cleaning company data from public registries.
Starting with Georgia Secretary of State business registry.

Author: Anupam Srivastava
Client: Alta (sourcealta.com)
"""

import os
import sys
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Project configuration
PROJECT_NAME = "alta_data_collection"
VERSION = "1.0.0"

# Data sources configuration
DATA_SOURCES = {
    "georgia_sos": {
        "name": "Georgia Secretary of State Business Registry",
        "base_url": "https://ecorp.sos.ga.gov/BusinessSearch",
        "search_endpoint": "/BusinessSearch/SearchResults",
        "enabled": True
    }
}

# Snowflake configuration
SNOWFLAKE_CONFIG = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT"),
    "user": os.getenv("SNOWFLAKE_USER"),
    "password": os.getenv("SNOWFLAKE_PASSWORD"),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    "database": os.getenv("SNOWFLAKE_DATABASE", "ALTA_DATA"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA", "COMPANY_DATA")
}

# Salesforce configuration
SALESFORCE_CONFIG = {
    "username": os.getenv("SALESFORCE_USERNAME"),
    "password": os.getenv("SALESFORCE_PASSWORD"),
    "security_token": os.getenv("SALESFORCE_SECURITY_TOKEN"),
    "domain": os.getenv("SALESFORCE_DOMAIN", "login")
}

# Scraping configuration
SCRAPING_CONFIG = {
    "rate_limit_delay": 1.0,  # seconds between requests
    "max_retries": 3,
    "timeout": 30,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "concurrent_requests": 5
}

# Data enrichment configuration
ENRICHMENT_CONFIG = {
    "google_search_enabled": True,
    "website_detection_enabled": True,
    "email_extraction_enabled": True,
    "naics_classification_enabled": True,
    "linkedin_enrichment_enabled": False  # Disabled initially
}

# Logging configuration
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    "rotation": "1 week",
    "retention": "4 weeks"
}



