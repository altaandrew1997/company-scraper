#!/usr/bin/env python3
"""
Run direct NAICS mapping for landscaping businesses
Uses business name keywords to assign NAICS codes directly
Saves each result to Snowflake immediately
"""

import re
import sys
from pathlib import Path
from loguru import logger

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from database import SnowflakeClient


# Direct keyword to NAICS mapping for common business types
NAICS_MAPPINGS = {
    # Landscaping and Lawn Services - 561730
    ('landscaping', 'landscape', 'lawn', 'turf', 'grass', 'mowing', 'yard'): {
        'code': '561730',
        'title': 'Landscaping Services',
        'confidence': '0.85'
    },
    # Tree Services - also 561730
    ('tree service', 'tree removal', 'tree trimming', 'tree care', 'arborist'): {
        'code': '561730',
        'title': 'Landscaping Services',
        'confidence': '0.85'
    },
    # Construction - 236220
    ('construction', 'builder', 'building', 'contractor'): {
        'code': '236220',
        'title': 'Commercial and Institutional Building Construction',
        'confidence': '0.75'
    },
    # Electrical - 238210
    ('electrical', 'electrician', 'electric'): {
        'code': '238210',
        'title': 'Electrical Contractors and Other Wiring Installation Contractors',
        'confidence': '0.80'
    },
    # Plumbing - 238220
    ('plumbing', 'plumber'): {
        'code': '238220',
        'title': 'Plumbing, Heating, and Air-Conditioning Contractors',
        'confidence': '0.80'
    },
    # Roofing - 238160
    ('roofing', 'roof'): {
        'code': '238160',
        'title': 'Roofing Contractors',
        'confidence': '0.80'
    },
    # Painting - 238320
    ('painting', 'painter'): {
        'code': '238320',
        'title': 'Painting and Wall Covering Contractors',
        'confidence': '0.80'
    },
    # Flooring - 238330
    ('flooring', 'floor', 'carpet', 'tile'): {
        'code': '238330',
        'title': 'Flooring Contractors',
        'confidence': '0.75'
    },
}


def classify_by_keywords(business_name: str) -> dict | None:
    """Classify business using direct keyword mapping"""
    name_lower = business_name.lower()
    
    for keywords, naics_info in NAICS_MAPPINGS.items():
        for keyword in keywords:
            if keyword in name_lower:
                return {
                    'code': naics_info['code'],
                    'title': naics_info['title'],
                    'confidence': naics_info['confidence']
                }
    return None


def run_direct_mapping():
    """Run direct keyword mapping with incremental saves"""
    
    logger.info("\n" + "="*60)
    logger.info("🎯 DIRECT NAICS MAPPING (Keyword-based)")
    logger.info("="*60)
    
    # Initialize Snowflake client
    client = SnowflakeClient()
    
    try:
        client.connect()
        cursor = client.connection.cursor()
        
        # Set context
        cursor.execute(f"USE WAREHOUSE {client.warehouse}")
        cursor.execute(f"USE DATABASE {client.database}")
        cursor.execute(f"USE SCHEMA {client.schema}")
        
        # Get records without NAICS codes
        logger.info("\n📥 Loading records without NAICS codes...")
        cursor.execute(f"""
            SELECT 
                CONTROL_NUMBER,
                BUSINESS_NAME
            FROM {client.table_name}
            WHERE NAICS_CODE IS NULL OR NAICS_CODE = ''
            ORDER BY BUSINESS_NAME
        """)
        
        records = cursor.fetchall()
        total = len(records)
        
        logger.info(f"✅ Found {total} records needing NAICS enrichment")
        logger.info("\n🎯 Running direct keyword mapping...")
        logger.info("-" * 60)
        
        enriched = 0
        skipped = 0
        
        for i, (control_number, business_name) in enumerate(records, 1):
            if not business_name:
                skipped += 1
                continue
            
            # Run direct keyword classification
            classification = classify_by_keywords(business_name)
            
            if classification:
                naics_code = classification['code']
                naics_title = classification['title']
                naics_confidence = classification['confidence']
                
                # Update Snowflake immediately
                cursor.execute(f"""
                    UPDATE {client.table_name}
                    SET 
                        NAICS_CODE = %s,
                        NAICS_TITLE = %s,
                        NAICS_CONFIDENCE = %s,
                        NAICS_CLASSIFICATION_METHOD = 'keyword_mapping',
                        NAICS_SOURCE = 'Direct Keyword Mapping',
                        UPDATED_AT = CURRENT_TIMESTAMP()
                    WHERE CONTROL_NUMBER = %s
                """, [naics_code, naics_title, naics_confidence, control_number])
                
                # Commit after each update
                client.connection.commit()
                
                enriched += 1
                
                # Print each saved record
                name_display = business_name[:42] if len(business_name) > 42 else business_name
                logger.info(f"[{i}/{total}] ✅ {name_display}")
                logger.info(f"         → {naics_code}: {naics_title}")
            else:
                skipped += 1
                # Only log every 50 skipped or if it's an unusual business
                if skipped <= 5 or skipped % 50 == 0:
                    name_display = business_name[:42] if len(business_name) > 42 else business_name
                    logger.debug(f"[{i}/{total}] ⚠️ {name_display} - No keyword match")
        
        logger.info("-" * 60)
        logger.info(f"\n✅ Direct mapping complete!")
        logger.info(f"   Enriched: {enriched} records")
        logger.info(f"   Skipped (no match): {skipped} records")
        
        # Final stats
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN NAICS_CODE IS NOT NULL AND NAICS_CODE != '' THEN 1 ELSE 0 END) as with_naics,
                SUM(CASE WHEN NAICS_CLASSIFICATION_METHOD = 'Gemini AI' THEN 1 ELSE 0 END) as gemini,
                SUM(CASE WHEN NAICS_CLASSIFICATION_METHOD = 'keyword_mapping' THEN 1 ELSE 0 END) as keyword
            FROM {client.table_name}
        """)
        stats = cursor.fetchone()
        
        logger.info(f"\n📊 Final Snowflake Status:")
        logger.info(f"   Total records: {stats[0]}")
        logger.info(f"   With NAICS: {stats[1]} ({stats[1]/stats[0]*100:.1f}%)")
        logger.info(f"   - Gemini AI: {stats[2]}")
        logger.info(f"   - Keyword mapping: {stats[3]}")
        logger.info(f"   Missing: {stats[0] - stats[1]}")
        
        cursor.close()
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise
    finally:
        client.disconnect()


if __name__ == "__main__":
    run_direct_mapping()
