"""
Main Data Collection Pipeline
Orchestrates the complete data collection and enrichment process

Steps:
1. Scrape Georgia SOS data
2. Google scraping (with validation)
3. Facebook URL scraping
4. Aggregate Google/Facebook data (select best values)
5. Fix NAICS codes with Gemini
6. Apollo enrichment (only for larger companies)
"""

import asyncio
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import modules
from scrapers import (
    setup_logging, search_business, scrape_all_pages, enrich_business_data
)
from cloudflareSolver import get_bypassed_page
from google_scraper import (
    setup_google_search_context, search_google_for_website,
    search_google_for_linkedin, search_google_for_facebook,
    get_google_business_profile
)
from facebook_scraper import extract_facebook_about_details
from naics_classifier_ai import enrich_naics_codes_ai
from apollo_enricher import ApolloEnricher
import json
from filters import CompanySizeFilter, should_enrich_with_apollo
from utils import DataAggregator, merge_google_facebook_data
from database import SnowflakeClient
from models import ScrapingJob
from config import APOLLO_FILTERING


class DataCollectionPipeline:
    """Main pipeline orchestrator for data collection and enrichment"""
    
    def __init__(
        self,
        output_dir: str = "output",
        save_to_snowflake: bool = True,
        save_to_excel: bool = True
    ):
        """
        Initialize pipeline
        
        Args:
            output_dir: Directory for output files
            save_to_snowflake: Whether to save to Snowflake
            save_to_excel: Whether to save to Excel
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.save_to_snowflake = save_to_snowflake
        self.save_to_excel = save_to_excel
        
        self.snowflake_client = None
        if save_to_snowflake:
            try:
                self.snowflake_client = SnowflakeClient()
                self.snowflake_client.connect()
                self.snowflake_client.create_tables()
            except Exception as e:
                logger.warning(f"Could not connect to Snowflake: {str(e)}")
                self.save_to_snowflake = False
        
        self.job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.job = ScrapingJob(
            job_id=self.job_id,
            source="georgia_sos",
            status="pending",
            started_at=datetime.utcnow()
        )
    
    async def step1_scrape_georgia_data(
        self,
        search_term: str = "landscap",
        max_pages: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Step 1: Scrape Georgia SOS data
        
        Args:
            search_term: Search term for Georgia SOS
            max_pages: Maximum pages to scrape (None = all)
            
        Returns:
            DataFrame with scraped data
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 1: Scraping Georgia SOS Data")
        logger.info("="*60)
        
        self.job.status = "running"
        self.job.started_at = datetime.utcnow()
        
        try:
            # Get bypassed page
            target_url = "https://ecorp.sos.ga.gov/BusinessSearch"
            logger.info("🔐 Bypassing Cloudflare challenge...")
            playwright, browser, context, page = await get_bypassed_page(target_url, headless=False)
            
            # Search for businesses
            logger.info(f"🔍 Searching for: '{search_term}'")
            page = await search_business(search_term, page)
            
            # Scrape all pages
            logger.info("📊 Scraping business listings...")
            all_data = await scrape_all_pages(page, max_pages=max_pages)
            
            if not all_data:
                logger.warning("⚠️ No data scraped")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame(all_data)
            logger.info(f"✅ Scraped {len(df)} records from Georgia SOS")
            
            self.job.records_scraped = len(df)
            
            # Save to Snowflake
            if self.save_to_snowflake and self.snowflake_client:
                logger.info("💾 Saving to Snowflake...")
                for _, row in df.iterrows():
                    # Convert to BusinessRegistryRecord and save
                    # (Implementation depends on your data structure)
                    pass
            
            # Save to Excel
            if self.save_to_excel:
                output_file = self.output_dir / f"georgia_sos_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                df.to_excel(output_file, index=False, engine='openpyxl')
                logger.info(f"💾 Saved to: {output_file}")
            
            return df
            
        except Exception as e:
            logger.error(f"❌ Error in Step 1: {str(e)}")
            self.job.status = "failed"
            if not self.job.errors:
                self.job.errors = []
            self.job.errors.append(f"Step 1 error: {str(e)}")
            raise
    
    async def step2_google_scraping(
        self,
        df: pd.DataFrame,
        page: Optional = None
    ) -> pd.DataFrame:
        """
        Step 2: Google scraping with validation
        
        Args:
            df: DataFrame with company data
            page: Optional Playwright page (will create if None)
            
        Returns:
            DataFrame with Google-scraped data
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 2: Google Scraping (with Validation)")
        logger.info("="*60)
        
        if df.empty:
            logger.warning("⚠️ No data to enrich")
            return df
        
        try:
            # Setup Google search context if needed
            if not page:
                from playwright.async_api import async_playwright
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(headless=False)
                context = await setup_google_search_context(browser)
                page = await context.new_page()
            
            # Enrich with Google data
            enriched_df = await enrich_business_data(
                page,
                df,
                save_progress_every=50,
                enrich_contact_info=True
            )
            
            logger.info(f"✅ Google scraping complete for {len(enriched_df)} records")
            
            # Save progress
            if self.save_to_excel:
                output_file = self.output_dir / f"enriched_google_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                enriched_df.to_excel(output_file, index=False, engine='openpyxl')
                logger.info(f"💾 Saved to: {output_file}")
            
            return enriched_df
            
        except Exception as e:
            logger.error(f"❌ Error in Step 2: {str(e)}")
            raise
    
    async def step3_facebook_scraping(
        self,
        df: pd.DataFrame,
        page: Optional = None
    ) -> Dict[str, Dict]:
        """
        Step 3: Facebook URL scraping
        
        Args:
            df: DataFrame with company data (should have Facebook URLs)
            page: Optional Playwright page
            
        Returns:
            Dictionary mapping company names to Facebook data
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 3: Facebook URL Scraping")
        logger.info("="*60)
        
        if df.empty:
            logger.warning("⚠️ No data to scrape")
            return {}
        
        try:
            # Setup page if needed
            if not page:
                from playwright.async_api import async_playwright
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(headless=False)
                page = await browser.new_page()
            
            facebook_data = {}
            companies_with_facebook = df[df['Facebook'].notna() & (df['Facebook'] != '')]
            
            logger.info(f"📊 Found {len(companies_with_facebook)} companies with Facebook URLs")
            
            for idx, row in companies_with_facebook.iterrows():
                company_name = row.get('Entity Name') or row.get('Business Name', f"Company_{idx}")
                facebook_url = row.get('Facebook')
                
                if not facebook_url:
                    continue
                
                try:
                    logger.info(f"   🌐 Scraping Facebook for: {company_name}")
                    fb_data = await extract_facebook_about_details(page, facebook_url)
                    facebook_data[company_name] = fb_data
                    
                    # Small delay between requests
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.warning(f"   ⚠️ Error scraping Facebook for {company_name}: {str(e)}")
                    continue
            
            logger.info(f"✅ Facebook scraping complete: {len(facebook_data)} companies")
            return facebook_data
            
        except Exception as e:
            logger.error(f"❌ Error in Step 3: {str(e)}")
            raise
    
    def step4_aggregate_data(
        self,
        df: pd.DataFrame,
        facebook_data: Dict[str, Dict]
    ) -> pd.DataFrame:
        """
        Step 4: Aggregate Google and Facebook data
        
        Args:
            df: DataFrame with Google-scraped data
            facebook_data: Dictionary with Facebook data
            
        Returns:
            DataFrame with aggregated data
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 4: Aggregating Google & Facebook Data")
        logger.info("="*60)
        
        if df.empty:
            logger.warning("⚠️ No data to aggregate")
            return df
        
        try:
            aggregator = DataAggregator()
            aggregated_records = []
            
            for idx, row in df.iterrows():
                company_name = row.get('Entity Name') or row.get('Business Name', f"Company_{idx}")
                
                # Get Facebook data for this company
                fb_data = facebook_data.get(company_name)
                
                # Merge Google (from row) and Facebook data
                merged = merge_google_facebook_data(
                    row.to_dict(),
                    google_data=row.to_dict(),  # Row already has Google data
                    facebook_data=fb_data
                )
                
                aggregated_records.append(merged)
            
            aggregated_df = pd.DataFrame(aggregated_records)
            logger.info(f"✅ Data aggregation complete: {len(aggregated_df)} records")
            
            # Save progress
            if self.save_to_excel:
                output_file = self.output_dir / f"aggregated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                aggregated_df.to_excel(output_file, index=False, engine='openpyxl')
                logger.info(f"💾 Saved to: {output_file}")
            
            return aggregated_df
            
        except Exception as e:
            logger.error(f"❌ Error in Step 4: {str(e)}")
            raise
    
    def step5_fix_naics_codes(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Step 5: Fix NAICS codes with Gemini
        
        Args:
            df: DataFrame with company data
            
        Returns:
            DataFrame with NAICS codes fixed/enriched
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 5: Fixing NAICS Codes with Gemini")
        logger.info("="*60)
        
        if df.empty:
            logger.warning("⚠️ No data to process")
            return df
        
        try:
            enriched_df = enrich_naics_codes_ai(
                df,
                excel_file_path="2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
                use_ai=True,
                gemini_model="gemini-2.5-flash",
                min_confidence=0.50,
                api_delay=1.5,
                save_progress_every=25,
                output_file_path=None  # Will save at end
            )
            
            logger.info(f"✅ NAICS code enrichment complete")
            
            # Save progress
            if self.save_to_excel:
                output_file = self.output_dir / f"naics_enriched_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                enriched_df.to_excel(output_file, index=False, engine='openpyxl')
                logger.info(f"💾 Saved to: {output_file}")
            
            return enriched_df
            
        except Exception as e:
            logger.error(f"❌ Error in Step 5: {str(e)}")
            raise
    
    async def step6_apollo_enrichment(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Step 6: Apollo enrichment (only for larger companies)
        
        Args:
            df: DataFrame with company data
            
        Returns:
            DataFrame with Apollo enrichment data
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 6: Apollo Enrichment (Filtered for Larger Companies)")
        logger.info("="*60)
        
        if df.empty:
            logger.warning("⚠️ No data to enrich")
            return df
        
        try:
            # Filter companies for Apollo
            filter_obj = CompanySizeFilter(APOLLO_FILTERING)
            candidates, skipped = filter_obj.filter_companies(df, company_name_col='Entity Name')
            
            logger.info(f"📊 Apollo Enrichment Summary:")
            logger.info(f"   ✅ Candidates: {len(candidates)}")
            logger.info(f"   ⏭️  Skipped: {len(skipped)}")
            
            if not candidates:
                logger.info("   ℹ️  No companies qualify for Apollo enrichment")
                return df
            
            # Get candidates DataFrame
            apollo_df = df.loc[candidates].copy()
            
            # Initialize Apollo enricher
            enricher = ApolloEnricher()
            
            # Enrich candidates one by one
            apollo_columns = [
                'Apollo_Executives_Count', 'Apollo_Executives_Names', 'Apollo_Executives_Titles',
                'Apollo_Executives_Emails', 'Apollo_Executives_LinkedIn', 'Apollo_Executives_Phones',
                'Apollo_Company_Name', 'Apollo_Website', 'Apollo_Website_Updated',
                'Apollo_Verification_Confidence', 'Apollo_Verification_Status',
                'Apollo_Needs_Review', 'Apollo_Executives_JSON'
            ]
            
            # Initialize Apollo columns if they don't exist
            for col in apollo_columns:
                if col not in df.columns:
                    df[col] = None
            
            for idx in candidates:
                row = df.loc[idx]
                company_name = row.get('Entity Name') or row.get('Business Name', '')
                website = row.get('Website')
                website_confidence = row.get('Website_Confidence', 0)
                
                try:
                    logger.info(f"   🔍 Enriching with Apollo: {company_name}")
                    
                    # Parse officers if available
                    officers = None
                    if row.get('Officers'):
                        import json
                        try:
                            officers = json.loads(row['Officers']) if isinstance(row['Officers'], str) else row['Officers']
                        except:
                            pass
                    
                    # Enrich company
                    result = await enricher.enrich_company(
                        company_name=company_name,
                        website=website,
                        website_confidence=website_confidence,
                        city=row.get('City'),
                        state=row.get('State', 'GA'),
                        registered_agent=row.get('Registered Agent'),
                        officers=officers
                    )
                    
                    # Update DataFrame with Apollo data
                    executives = result.get('executives', [])
                    df.at[idx, 'Apollo_Executives_Count'] = len(executives)
                    df.at[idx, 'Apollo_Executives_Names'] = '; '.join([e.get('full_name', '') for e in executives])
                    df.at[idx, 'Apollo_Executives_Titles'] = '; '.join([e.get('title', '') for e in executives])
                    df.at[idx, 'Apollo_Executives_Emails'] = '; '.join([e.get('email', '') for e in executives if e.get('email')])
                    df.at[idx, 'Apollo_Executives_LinkedIn'] = '; '.join([e.get('linkedin_url', '') for e in executives if e.get('linkedin_url')])
                    df.at[idx, 'Apollo_Executives_Phones'] = '; '.join([e.get('phone_number', '') for e in executives if e.get('phone_number')])
                    df.at[idx, 'Apollo_Company_Name'] = result.get('apollo_company_name')
                    df.at[idx, 'Apollo_Website'] = result.get('apollo_website')
                    df.at[idx, 'Apollo_Website_Updated'] = result.get('website_updated', False)
                    
                    verification = result.get('verification', {})
                    df.at[idx, 'Apollo_Verification_Confidence'] = verification.get('confidence', 0)
                    df.at[idx, 'Apollo_Verification_Status'] = 'verified' if verification.get('is_verified') else 'unverified'
                    df.at[idx, 'Apollo_Needs_Review'] = verification.get('needs_review', False)
                    df.at[idx, 'Apollo_Executives_JSON'] = json.dumps(executives) if executives else None
                    
                    logger.info(f"   ✅ Found {len(executives)} executives for {company_name}")
                    
                    # Small delay between requests
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.warning(f"   ⚠️ Error enriching {company_name} with Apollo: {str(e)}")
                    continue
            
            logger.info(f"✅ Apollo enrichment complete: {len(candidates)} companies enriched")
            
            # Save progress
            if self.save_to_excel:
                output_file = self.output_dir / f"apollo_enriched_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                df.to_excel(output_file, index=False, engine='openpyxl')
                logger.info(f"💾 Saved to: {output_file}")
            
            return df
            
        except Exception as e:
            logger.error(f"❌ Error in Step 6: {str(e)}")
            raise
    
    async def run_full_pipeline(
        self,
        search_term: str = "landscap",
        max_pages: Optional[int] = None,
        skip_steps: Optional[List[int]] = None
    ) -> pd.DataFrame:
        """
        Run the complete pipeline
        
        Args:
            search_term: Search term for Georgia SOS
            max_pages: Maximum pages to scrape
            skip_steps: List of step numbers to skip (e.g., [6] to skip Apollo)
            
        Returns:
            Final enriched DataFrame
        """
        skip_steps = skip_steps or []
        
        logger.info("\n" + "="*80)
        logger.info("🚀 STARTING DATA COLLECTION PIPELINE")
        logger.info("="*80)
        logger.info(f"Job ID: {self.job_id}")
        logger.info(f"Output Directory: {self.output_dir}")
        logger.info(f"Save to Snowflake: {self.save_to_snowflake}")
        logger.info(f"Save to Excel: {self.save_to_excel}")
        
        try:
            # Step 1: Scrape Georgia data
            if 1 not in skip_steps:
                df = await self.step1_scrape_georgia_data(search_term, max_pages)
            else:
                logger.info("⏭️  Skipping Step 1")
                df = pd.DataFrame()
            
            if df.empty and 1 not in skip_steps:
                logger.error("❌ No data scraped. Stopping pipeline.")
                return df
            
            # Step 2: Google scraping
            if 2 not in skip_steps:
                df = await self.step2_google_scraping(df)
            else:
                logger.info("⏭️  Skipping Step 2")
            
            # Step 3: Facebook scraping
            facebook_data = {}
            if 3 not in skip_steps:
                facebook_data = await self.step3_facebook_scraping(df)
            else:
                logger.info("⏭️  Skipping Step 3")
            
            # Step 4: Aggregate data
            if 4 not in skip_steps:
                df = self.step4_aggregate_data(df, facebook_data)
            else:
                logger.info("⏭️  Skipping Step 4")
            
            # Step 5: Fix NAICS codes
            if 5 not in skip_steps:
                df = self.step5_fix_naics_codes(df)
            else:
                logger.info("⏭️  Skipping Step 5")
            
            # Step 6: Apollo enrichment
            if 6 not in skip_steps:
                df = await self.step6_apollo_enrichment(df)
            else:
                logger.info("⏭️  Skipping Step 6")
            
            # Final save
            if self.save_to_excel:
                final_file = self.output_dir / f"final_enriched_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                df.to_excel(final_file, index=False, engine='openpyxl')
                logger.info(f"💾 Final output saved to: {final_file}")
            
            # Update job status
            self.job.status = "completed"
            self.job.completed_at = datetime.utcnow()
            self.job.records_enriched = len(df)
            
            logger.info("\n" + "="*80)
            logger.info("✅ PIPELINE COMPLETE")
            logger.info("="*80)
            logger.info(f"Total records: {len(df)}")
            logger.info(f"Job ID: {self.job_id}")
            
            return df
            
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {str(e)}")
            self.job.status = "failed"
            self.job.completed_at = datetime.utcnow()
            if not self.job.errors:
                self.job.errors = []
            self.job.errors.append(f"Pipeline error: {str(e)}")
            raise
        finally:
            if self.snowflake_client:
                self.snowflake_client.disconnect()


async def main():
    """Main entry point"""
    # Setup logging
    setup_logging()
    
    # Create and run pipeline
    pipeline = DataCollectionPipeline(
        output_dir="output",
        save_to_snowflake=True,
        save_to_excel=True
    )
    
    # Run pipeline
    await pipeline.run_full_pipeline(
        search_term="landscap",
        max_pages=5,  # Limit for testing
        skip_steps=[]  # Run all steps
    )


if __name__ == "__main__":
    asyncio.run(main())

