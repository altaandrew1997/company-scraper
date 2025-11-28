# Data Collection Pipeline

Main pipeline for orchestrating the complete data collection and enrichment process.

## Pipeline Steps

1. **Scrape Georgia SOS Data** - Scrapes business data from Georgia Secretary of State
2. **Google Scraping** - Searches Google for websites, LinkedIn, Facebook, and business profiles (with validation)
3. **Facebook URL Scraping** - Extracts detailed information from Facebook About pages
4. **Aggregate Data** - Merges Google and Facebook data, selecting best values based on source priority
5. **Fix NAICS Codes** - Uses Gemini AI to classify and fix NAICS codes
6. **Apollo Enrichment** - Enriches larger companies with executive contacts (filtered by company size)

## Usage

### Basic Usage

```python
import asyncio
from pipeline import DataCollectionPipeline

async def main():
    pipeline = DataCollectionPipeline(
        output_dir="output",
        save_to_snowflake=True,
        save_to_excel=True
    )
    
    # Run full pipeline
    df = await pipeline.run_full_pipeline(
        search_term="landscap",
        max_pages=10,
        skip_steps=[]  # Run all steps
    )
    
    print(f"Processed {len(df)} companies")

asyncio.run(main())
```

### Skip Specific Steps

```python
# Skip Apollo enrichment (Step 6)
df = await pipeline.run_full_pipeline(
    search_term="landscap",
    skip_steps=[6]
)
```

### Run Individual Steps

```python
# Step 1: Scrape Georgia data
df = await pipeline.step1_scrape_georgia_data("landscap", max_pages=5)

# Step 2: Google scraping
df = await pipeline.step2_google_scraping(df)

# Step 3: Facebook scraping
facebook_data = await pipeline.step3_facebook_scraping(df)

# Step 4: Aggregate data
df = pipeline.step4_aggregate_data(df, facebook_data)

# Step 5: Fix NAICS codes
df = pipeline.step5_fix_naics_codes(df)

# Step 6: Apollo enrichment (only for larger companies)
df = await pipeline.step6_apollo_enrichment(df)
```

## Apollo Filtering

Apollo enrichment (Step 6) only runs for larger companies to save credits. The filtering is configured in `config.py`:

```python
APOLLO_FILTERING = {
    "min_score": 50,  # Minimum score (0-100) to qualify
    "require_website": True,  # Must have validated website
    "min_officers": 0,  # Minimum officers required
    "min_years_old": 0,  # Minimum years in business
}
```

### Scoring Criteria

Companies are scored based on:
- Website validation (30 points)
- Has validated website (20 points)
- LinkedIn presence (15 points)
- Google Business Profile (15 points)
- Multiple officers (10 points)
- Entity type (10 points)
- Company age (10 points)
- Active status (5 points)
- Data completeness (5 points)
- Industry/NAICS (bonus points)

## Output Files

The pipeline saves progress at each step:
- `georgia_sos_data_*.xlsx` - Raw Georgia SOS data
- `enriched_google_*.xlsx` - After Google scraping
- `aggregated_*.xlsx` - After data aggregation
- `naics_enriched_*.xlsx` - After NAICS classification
- `apollo_enriched_*.xlsx` - After Apollo enrichment
- `final_enriched_*.xlsx` - Final output

## Configuration

Set environment variables in `.env`:
- `SNOWFLAKE_ACCOUNT` - Snowflake account identifier
- `SNOWFLAKE_USER` - Snowflake username
- `SNOWFLAKE_PASSWORD` - Snowflake password
- `APOLLO_API_KEY` - Apollo.io API key
- `GEMINI_API_KEY` - Google Gemini API key
- `TWOCAPTCHA_API_KEY` - 2Captcha API key (for Cloudflare)


