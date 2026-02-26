#!/usr/bin/env python3
"""
Run Gemini NAICS enrichment on existing Snowflake records
Updates only the NAICS-related fields after each Gemini response
"""

import asyncio
import sys
from pathlib import Path
import pandas as pd
from loguru import logger

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from database import SnowflakeClient
from naics_classifier_ai import enrich_naics_codes_ai


async def main():
    """Run Gemini NAICS enrichment on Snowflake data"""
    
    logger.info("\n" + "="*60)
    logger.info("🤖 GEMINI NAICS ENRICHMENT")
    logger.info("="*60)
    
    # Initialize Snowflake client
    client = SnowflakeClient()
    
    try:
        client.connect()
        
        # Load all records from Snowflake that need NAICS enrichment
        logger.info("\n📥 Loading records from Snowflake...")
        cursor = client.connection.cursor()
        
        # Get records that don't have NAICS codes or have low confidence
        cursor.execute(f"""
            SELECT 
                CONTROL_NUMBER,
                BUSINESS_NAME,
                BUSINESS_TYPE,
                GEORGIA_SOS_NAICS,
                GEORGIA_SOS_NAICS_SUB,
                PRINCIPAL_OFFICE_ADDRESS,
                NAICS_CODE,
                NAICS_CONFIDENCE
            FROM {client.table_name}
            WHERE CONTROL_NUMBER IS NOT NULL
            ORDER BY CREATED_AT DESC
        """)
        
        columns = [desc[0] for desc in cursor.description]
        data = cursor.fetchall()
        df = pd.DataFrame(data, columns=columns)
        cursor.close()
        
        logger.info(f"✅ Loaded {len(df)} records")
        logger.info(f"   - Records with NAICS: {df['NAICS_CODE'].notna().sum()}")
        logger.info(f"   - Records without NAICS: {df['NAICS_CODE'].isna().sum()}")
        
        # Map Snowflake column names to expected format for enrichment
        column_mapping = {
            'BUSINESS_NAME': 'Business Name',
            'BUSINESS_TYPE': 'Business Type',
            'GEORGIA_SOS_NAICS': 'Georgia_SOS_NAICS',
            'GEORGIA_SOS_NAICS_SUB': 'Georgia_SOS_NAICS_Sub',
            'PRINCIPAL_OFFICE_ADDRESS': 'Principal Office Address',
            'CONTROL_NUMBER': 'Control Number',
            'NAICS_CODE': 'NAICS Code',
            'NAICS_CONFIDENCE': 'NAICS Confidence'
        }
        df = df.rename(columns=column_mapping)
        
        # Run Gemini enrichment
        # gemini-2.5-flash-lite: BEST free tier! 30 RPM, 1500 RPD
        logger.info(f"\n🤖 Running Gemini NAICS enrichment...")
        logger.info(f"   🏷️  Model: gemini-2.5-flash-lite (best free tier: 30 RPM, 1500 RPD)")
        logger.info(f"   ⏱️  API delay: 2.5s (24 RPM - safely under 30 RPM limit)")
        logger.info(f"   📊 Estimated time: ~{len(df) * 2.5 / 60:.0f} minutes for {len(df)} records")
        enriched_df = enrich_naics_codes_ai(
            df,
            excel_file_path=str(PROJECT_ROOT / "2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx"),
            use_ai=True,
            gemini_model="gemini-2.5-flash-lite",  # Best free tier: 30 RPM, 1500 RPD
            min_confidence=0.50,
            api_delay=2.5,  # 2.5 seconds = 24 RPM (safely under 30 RPM limit)
            save_progress_every=10,
            output_file_path=None
        )
        
        logger.info(f"✅ Gemini enrichment complete")
        
        # Update Snowflake with NAICS data only
        logger.info(f"\n💾 Updating NAICS fields in Snowflake...")
        
        cursor = client.connection.cursor()
        updated = 0
        
        for idx, row in enriched_df.iterrows():
            control_number = row.get('Control Number')  # Use mapped column name
            if not control_number:
                continue
            
            # Update only NAICS-related fields
            naics_code = row.get('NAICS Code')
            naics_title = row.get('NAICS Title')
            naics_confidence = row.get('NAICS Confidence')
            naics_method = row.get('NAICS Classification Method')
            naics_source = row.get('NAICS_Source')
            
            # Build update SQL for NAICS fields only
            update_sql = f"""
                UPDATE {client.table_name}
                SET 
                    NAICS_CODE = %s,
                    NAICS_TITLE = %s,
                    NAICS_CONFIDENCE = %s,
                    NAICS_CLASSIFICATION_METHOD = %s,
                    NAICS_SOURCE = %s,
                    UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE CONTROL_NUMBER = %s
            """
            
            try:
                cursor.execute(update_sql, [
                    naics_code,
                    naics_title,
                    naics_confidence,
                    naics_method,
                    naics_source,
                    str(control_number)
                ])
                updated += 1
                
                # Log progress
                if updated % 10 == 0:
                    logger.info(f"   Updated {updated} records...")
                    
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to update {control_number}: {e}")
        
        client.connection.commit()
        logger.info(f"✅ Updated {updated} records in Snowflake")
        
        # Final stats
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN NAICS_CODE IS NOT NULL THEN 1 ELSE 0 END) as with_naics,
                AVG(NAICS_CONFIDENCE) as avg_confidence
            FROM {client.table_name}
        """)
        stats = cursor.fetchone()
        
        logger.info(f"\n📊 Final Statistics:")
        logger.info(f"   Total records: {stats[0]}")
        logger.info(f"   With NAICS: {stats[1]} ({stats[1]/stats[0]*100:.1f}%)")
        logger.info(f"   Avg confidence: {stats[2]:.2f}" if stats[2] else "   Avg confidence: N/A")
        
        cursor.close()
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise
    finally:
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
