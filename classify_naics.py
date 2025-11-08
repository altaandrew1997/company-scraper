"""
Standalone script to classify NAICS codes for businesses missing them
Usage: python classify_naics.py <excel_file_path>
"""

import sys
import os
from pathlib import Path
from loguru import logger
import pandas as pd
from naics_classifier_ai import enrich_naics_codes_ai

def main():
    """Main function to classify NAICS codes for businesses missing them"""
    
    # Get Excel file path from command line argument
    if len(sys.argv) < 2:
        logger.error("❌ Please provide the path to the Excel file")
        logger.info("Usage: python classify_naics.py <excel_file_path>")
        logger.info("Example: python classify_naics.py output/georgia_sos_business_data_20251104_133631.xlsx")
        sys.exit(1)
    
    excel_file_path = sys.argv[1]
    
    # Check if file exists
    if not Path(excel_file_path).exists():
        logger.error(f"❌ File not found: {excel_file_path}")
        sys.exit(1)
    
    logger.info("="*60)
    logger.info("🏷️  NAICS Code Classification Tool")
    logger.info("="*60)
    logger.info(f"📂 Loading data from: {excel_file_path}")
    
    try:
        # Load the Excel file
        df = pd.read_excel(excel_file_path, engine='openpyxl')
        logger.info(f"✅ Loaded {len(df)} records from Excel file")
        
        # Check required columns
        if 'Business Name' not in df.columns:
            logger.error("❌ Excel file must contain 'Business Name' column")
            sys.exit(1)
        
        # Handle column structure: Check if NAICS Code column has text (titles) and needs renaming
        if 'NAICS Code' in df.columns:
            # Check if it contains numeric codes or text descriptions
            sample_values = df['NAICS Code'].dropna().head(20)
            has_numeric_codes = False
            if len(sample_values) > 0:
                import re
                for val in sample_values:
                    val_str = str(val).strip()
                    if re.match(r'^\d{2,6}$', val_str):  # Exact match for numeric code
                        has_numeric_codes = True
                        break
            
            # If column has text but no numeric codes, it will be renamed by enrich_naics_codes_ai
            if not has_numeric_codes:
                logger.info("📝 Detected 'NAICS Code' column contains titles/descriptions")
                logger.info("   Will be renamed to 'NAICS Title' and new 'NAICS Code' column will be added")
        
        # Count businesses without numeric NAICS codes
        def has_valid_naics_code(naics_value):
            """Check if a NAICS code value is a valid numeric code"""
            if pd.isna(naics_value):
                return False
            naics_str = str(naics_value).strip()
            if naics_str == '' or naics_str.lower() == 'nan':
                return False
            # Check if it's a valid numeric NAICS code (2-6 digits, exact match)
            import re
            if re.match(r'^\d{2,6}$', naics_str):
                return True
            return False
        
        # Check current state (will be updated after column renaming in enrich function)
        if 'NAICS Code' in df.columns:
            missing_naics = ~df['NAICS Code'].apply(has_valid_naics_code)
            missing_count = missing_naics.sum()
            existing_count = (~missing_naics).sum()
        else:
            missing_count = len(df)
            existing_count = 0
        
        logger.info(f"📊 Current Status:")
        logger.info(f"   ✅ Businesses with numeric NAICS codes: {existing_count}")
        logger.info(f"   ❌ Businesses missing numeric NAICS codes: {missing_count}")
        if 'NAICS Title' in df.columns or (existing_count == 0 and 'NAICS Code' in df.columns):
            logger.info(f"   📝 Note: Many businesses have NAICS titles but need numeric codes")
        
        if missing_count == 0:
            logger.info("✅ All businesses already have NAICS codes. Nothing to do!")
            return
        
        # Ask for confirmation
        logger.info("")
        logger.info("🔍 Ready to classify missing NAICS codes using Gemini AI")
        logger.info(f"   This will process {missing_count} businesses")
        
        # Check for Gemini API key
        if not os.getenv("GEMINI_API_KEY"):
            logger.warning("⚠️  GEMINI_API_KEY not found in environment")
            logger.warning("   The script will fall back to keyword matching only")
            logger.warning("   Get your API key from: https://makersuite.google.com/app/apikey")
            logger.warning("   Then set it: export GEMINI_API_KEY='your-key-here'")
        
        # Get user preferences (optional parameters)
        use_ai = True
        api_delay = 1.5
        
        # Check if user wants to proceed
        response = input("\n⚠️  Do you want to proceed? (yes/no) [yes]: ").strip().lower()
        if response and response not in ['yes', 'y', '']:
            logger.info("❌ Operation cancelled")
            return
        
        logger.info("")
        logger.info("="*60)
        logger.info("🚀 Starting NAICS classification...")
        logger.info("="*60)
        
        # Run NAICS classification
        enriched_df = enrich_naics_codes_ai(
            df,
            excel_file_path="2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
            use_ai=use_ai,
            gemini_model="gemini-2.5-flash",
            min_confidence=0.50,
            api_delay=api_delay,
            save_progress_every=25,
            output_file_path=excel_file_path  # Save progress to the same file
        )
        
        # Save results back to the Excel file
        logger.info("")
        logger.info("="*60)
        logger.info("💾 Saving results...")
        logger.info("="*60)
        enriched_df.to_excel(excel_file_path, index=False, engine='openpyxl')
        logger.info(f"✅ Results saved to: {excel_file_path}")
        
        # Final summary
        final_missing = ~enriched_df['NAICS Code'].apply(has_valid_naics_code)
        final_missing_count = final_missing.sum()
        final_existing_count = (~final_missing).sum()
        
        # Count how many have titles
        if 'NAICS Title' in enriched_df.columns:
            has_title_count = enriched_df['NAICS Title'].notna().sum()
            has_title_with_code = ((enriched_df['NAICS Code'].apply(has_valid_naics_code)) & 
                                   (enriched_df['NAICS Title'].notna())).sum()
        else:
            has_title_count = 0
            has_title_with_code = 0
        
        logger.info("")
        logger.info("="*60)
        logger.info("📊 Final Summary")
        logger.info("="*60)
        logger.info(f"   ✅ Businesses with numeric NAICS codes: {final_existing_count} (was {existing_count})")
        logger.info(f"   ❌ Businesses still missing numeric NAICS codes: {final_missing_count} (was {missing_count})")
        logger.info(f"   📈 Newly classified: {final_existing_count - existing_count}")
        if 'NAICS Title' in enriched_df.columns:
            logger.info(f"   📝 Businesses with NAICS titles: {has_title_count}")
            logger.info(f"   ✅ Businesses with both code and title: {has_title_with_code}")
        logger.info("")
        logger.info("📋 Column Structure:")
        logger.info("   - 'NAICS Code': Numeric codes (e.g., '561730')")
        logger.info("   - 'NAICS Title': Descriptions/titles (e.g., 'Landscaping Services')")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()

