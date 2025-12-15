"""
Example script to run pipeline starting from Google scraping step (Step 2)

Usage:
    python run_from_google_scraping.py
"""

import asyncio
from pathlib import Path
from loguru import logger
from scrapers import setup_logging
from pipeline.main_pipeline import DataCollectionPipeline


async def main():
    """Run pipeline from Google scraping step"""
    # Setup logging
    setup_logging()
    
    # Create pipeline
    pipeline = DataCollectionPipeline(
        output_dir="output",
        save_to_snowflake=True,
        save_to_excel=True
    )
    
    # Find the most recent Excel file in output directories
    # Check multiple possible locations
    search_dirs = [
        Path("output"),
        Path("pipeline/output"),
        Path(".")  # Also check root directory
    ]
    
    all_excel_files = []
    for output_dir in search_dirs:
        if output_dir.exists():
            # Look for files with detail page data
            patterns = [
                "georgia_sos_with_details_*.xlsx",
                "georgia_sos_data_*.xlsx",
                "*_with_details_*.xlsx"
            ]
            for pattern in patterns:
                files = list(output_dir.glob(pattern))
                all_excel_files.extend(files)
    
    if all_excel_files:
        # Remove duplicates and get most recent file
        unique_files = list(set(all_excel_files))
        latest_file = max(unique_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"📂 Found {len(unique_files)} Excel file(s)")
        logger.info(f"📂 Using latest file: {latest_file}")
        
        # Run pipeline from Google scraping step
        await pipeline.run_full_pipeline(
            input_file=str(latest_file),
            skip_steps=[1, 6]  # Skip Step 1 (already done) and Step 6 (Apollo)
        )
    else:
        logger.error("❌ No Excel files found")
        logger.info("   Searched in: output/, pipeline/output/, and current directory")
        logger.info("   Please run the full pipeline first (Step 1) to generate data files")


if __name__ == "__main__":
    asyncio.run(main())

