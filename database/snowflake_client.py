"""
Snowflake Database Integration
==============================

Provides integration with Snowflake for storing and querying company data.
Supports connection management, table operations, and data insertion/querying.

Author: Anupam Srivastava
Client: Alta (sourcealta.com)
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import snowflake.connector
    from snowflake.connector import DictCursor
    from snowflake.connector.errors import ProgrammingError, DatabaseError
except ImportError:
    raise ImportError(
        "snowflake-connector-python is required. Install it with: pip install snowflake-connector-python"
    )

from loguru import logger
from config import SNOWFLAKE_CONFIG
from models import EnrichedCompanyRecord, BusinessRegistryRecord, ScrapingJob


class SnowflakeClient:
    """Client for interacting with Snowflake database"""
    
    @staticmethod
    def _normalize_azure_account(account: str) -> str:
        """
        Normalize Azure Snowflake account identifier format
        
        For Azure accounts, converts region format from AZURE_WESTUS2 to west-us-2.azure
        Example: VC44044.AZURE_WESTUS2 -> VC44044.west-us-2.azure
        
        Args:
            account: Account identifier string
            
        Returns:
            Normalized account identifier
        """
        if not account:
            return account
        
        # Check if it's already in the correct format
        if account.endswith('.azure'):
            return account
        
        # Check if it contains AZURE_ region format
        if 'AZURE_' in account.upper():
            parts = account.split('.')
            if len(parts) >= 2:
                account_locator = parts[0]
                region_part = parts[1]
                
                # Convert AZURE_WESTUS2 -> west-us-2
                if region_part.startswith('AZURE_'):
                    region = region_part.replace('AZURE_', '').lower()
                    # Convert WESTUS2 -> west-us-2 (add hyphens)
                    # Handle common Azure region formats
                    if 'WEST' in region.upper() and 'US' in region.upper():
                        # Extract number if present (e.g., WESTUS2 -> west-us-2)
                        import re
                        match = re.match(r'(\w+)US(\d+)', region.upper())
                        if match:
                            direction = match.group(1).lower()
                            number = match.group(2)
                            region = f"{direction}-us-{number}"
                        else:
                            # Fallback: convert underscores to hyphens and lowercase
                            region = region.replace('_', '-').lower()
                    else:
                        # General conversion: lowercase and replace underscores with hyphens
                        region = region.replace('_', '-').lower()
                    
                    return f"{account_locator}.{region}.azure"
        
        return account
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Snowflake client with configuration
        
        Args:
            config: Optional configuration dict. If not provided, uses SNOWFLAKE_CONFIG from config.py
        """
        self.config = config or SNOWFLAKE_CONFIG.copy()
        
        # Normalize Azure account identifier format
        if self.config.get("account"):
            self.config["account"] = self._normalize_azure_account(self.config["account"])
        
        self.connection: Optional[snowflake.connector.SnowflakeConnection] = None
        self.cursor: Optional[snowflake.connector.cursor.SnowflakeCursor] = None
        
        # Validate required configuration
        required_keys = ["account", "user", "password", "warehouse", "database", "schema"]
        missing_keys = [key for key in required_keys if not self.config.get(key)]
        
        if missing_keys:
            raise ValueError(
                f"Missing required Snowflake configuration keys: {', '.join(missing_keys)}. "
                f"Set them as environment variables or in config."
            )
    
    def connect(self) -> bool:
        """
        Establish connection to Snowflake
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info("Connecting to Snowflake...")
            
            self.connection = snowflake.connector.connect(
                account=self.config["account"],
                user=self.config["user"],
                password=self.config["password"],
                warehouse=self.config["warehouse"],
                database=self.config["database"],
                schema=self.config["schema"],
                autocommit=False
            )
            
            self.cursor = self.connection.cursor()
            logger.info(f"✅ Connected to Snowflake: {self.config['database']}.{self.config['schema']}")
            
            # Verify connection
            self.cursor.execute("SELECT CURRENT_VERSION()")
            version = self.cursor.fetchone()[0]
            logger.info(f"Snowflake version: {version}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Snowflake: {str(e)}")
            logger.exception(e)
            return False
    
    def disconnect(self):
        """Close Snowflake connection"""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
            logger.info("Disconnected from Snowflake")
        except Exception as e:
            logger.error(f"Error disconnecting from Snowflake: {str(e)}")
        finally:
            self.cursor = None
            self.connection = None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
    
    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[tuple]:
        """
        Execute a SQL query and return results
        
        Args:
            query: SQL query string
            params: Optional parameters for parameterized query
            
        Returns:
            List of result tuples
        """
        if not self.connection:
            raise RuntimeError("Not connected to Snowflake. Call connect() first.")
        
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            
            return self.cursor.fetchall()
            
        except ProgrammingError as e:
            logger.error(f"SQL Error: {str(e)}")
            logger.error(f"Query: {query}")
            raise
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            raise
    
    def execute_update(self, query: str, params: Optional[tuple] = None) -> int:
        """
        Execute an update/insert/delete query
        
        Args:
            query: SQL query string
            params: Optional parameters for parameterized query
            
        Returns:
            Number of rows affected
        """
        if not self.connection:
            raise RuntimeError("Not connected to Snowflake. Call connect() first.")
        
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            
            self.connection.commit()
            return self.cursor.rowcount
            
        except ProgrammingError as e:
            logger.error(f"SQL Error: {str(e)}")
            logger.error(f"Query: {query}")
            self.connection.rollback()
            raise
        except Exception as e:
            logger.error(f"Error executing update: {str(e)}")
            self.connection.rollback()
            raise
    
    def create_tables(self):
        """Create required tables if they don't exist"""
        if not self.connection:
            raise RuntimeError("Not connected to Snowflake. Call connect() first.")
        
        try:
            logger.info("Creating tables if they don't exist...")
            
            # Table for enriched company records
            companies_table = """
            CREATE TABLE IF NOT EXISTS enriched_companies (
                entity_name VARCHAR(500) NOT NULL,
                entity_type VARCHAR(100),
                registration_number VARCHAR(100),
                registration_date TIMESTAMP_NTZ,
                status VARCHAR(50),
                registered_agent VARCHAR(500),
                registered_agent_address_street VARCHAR(500),
                registered_agent_address_city VARCHAR(100),
                registered_agent_address_state VARCHAR(50),
                registered_agent_address_zip_code VARCHAR(20),
                registered_agent_address_country VARCHAR(50) DEFAULT 'US',
                principal_address_street VARCHAR(500),
                principal_address_city VARCHAR(100),
                principal_address_state VARCHAR(50),
                principal_address_zip_code VARCHAR(20),
                principal_address_country VARCHAR(50) DEFAULT 'US',
                mailing_address_street VARCHAR(500),
                mailing_address_city VARCHAR(100),
                mailing_address_state VARCHAR(50),
                mailing_address_zip_code VARCHAR(20),
                mailing_address_country VARCHAR(50) DEFAULT 'US',
                website VARCHAR(500),
                contact_email VARCHAR(255),
                contact_phone VARCHAR(50),
                contact_linkedin_url VARCHAR(500),
                naics_code VARCHAR(10),
                naics_description VARCHAR(500),
                industry_keywords VARIANT,
                data_quality_score FLOAT,
                enrichment_status VARCHAR(50) DEFAULT 'pending',
                enrichment_errors VARIANT,
                jurisdiction VARCHAR(10) DEFAULT 'GA',
                source_url VARCHAR(1000),
                scraped_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                enriched_at TIMESTAMP_NTZ,
                last_updated TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                PRIMARY KEY (entity_name, registration_number, jurisdiction)
            )
            """
            
            # Table for scraping jobs
            jobs_table = """
            CREATE TABLE IF NOT EXISTS scraping_jobs (
                job_id VARCHAR(100) PRIMARY KEY,
                source VARCHAR(100) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                started_at TIMESTAMP_NTZ,
                completed_at TIMESTAMP_NTZ,
                records_scraped INTEGER DEFAULT 0,
                records_enriched INTEGER DEFAULT 0,
                errors VARIANT,
                created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
            """
            
            self.cursor.execute(companies_table)
            self.cursor.execute(jobs_table)
            self.connection.commit()
            
            logger.info("✅ Tables created successfully")
            
        except Exception as e:
            logger.error(f"❌ Error creating tables: {str(e)}")
            if self.connection:
                self.connection.rollback()
            raise
    
    def insert_company_record(self, record: Union[EnrichedCompanyRecord, BusinessRegistryRecord]) -> bool:
        """
        Insert a single company record into Snowflake
        
        Args:
            record: EnrichedCompanyRecord or BusinessRegistryRecord instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert Pydantic model to dict
            if isinstance(record, EnrichedCompanyRecord):
                data = self._enriched_record_to_dict(record)
            elif isinstance(record, BusinessRegistryRecord):
                data = self._business_record_to_dict(record)
            else:
                raise ValueError(f"Unsupported record type: {type(record)}")
            
            # Build INSERT query
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            
            query = f"""
            INSERT INTO enriched_companies ({columns})
            VALUES ({placeholders})
            """
            
            self.execute_update(query, tuple(data.values()))
            logger.debug(f"Inserted company record: {data.get('entity_name', 'Unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Error inserting company record: {str(e)}")
            logger.exception(e)
            return False
    
    def upsert_company_record(self, record: Union[EnrichedCompanyRecord, BusinessRegistryRecord]) -> bool:
        """
        Insert or update a company record (upsert)
        
        Args:
            record: EnrichedCompanyRecord or BusinessRegistryRecord instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert Pydantic model to dict
            if isinstance(record, EnrichedCompanyRecord):
                data = self._enriched_record_to_dict(record)
            elif isinstance(record, BusinessRegistryRecord):
                data = self._business_record_to_dict(record)
            else:
                raise ValueError(f"Unsupported record type: {type(record)}")
            
            # Build MERGE query for upsert
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            
            # Build update clause excluding primary key fields
            update_fields = [k for k in data.keys() if k not in ['entity_name', 'registration_number', 'jurisdiction']]
            update_clause = ", ".join([f"target.{k} = source.{k}" for k in update_fields])
            
            # Build VALUES clause for USING with column aliases
            col_list = list(data.keys())
            using_select = ", ".join([f"%s AS {col}" for col in col_list])
            
            query = f"""
            MERGE INTO enriched_companies AS target
            USING (SELECT {using_select}) AS source
            ON target.entity_name = source.entity_name 
               AND COALESCE(target.registration_number, '') = COALESCE(source.registration_number, '')
               AND target.jurisdiction = source.jurisdiction
            WHEN MATCHED THEN
                UPDATE SET {update_clause}, last_updated = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN
                INSERT ({columns}) VALUES ({placeholders})
            """
            
            # For USING clause, we need all values
            # For INSERT VALUES, we need all values again  
            all_values = tuple(data.values()) * 2
            
            self.execute_update(query, all_values)
            logger.debug(f"Upserted company record: {data.get('entity_name', 'Unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Error upserting company record: {str(e)}")
            logger.exception(e)
            return False
    
    def insert_company_records_batch(self, records: List[Union[EnrichedCompanyRecord, BusinessRegistryRecord]]) -> int:
        """
        Insert multiple company records in a batch
        
        Args:
            records: List of EnrichedCompanyRecord or BusinessRegistryRecord instances
            
        Returns:
            Number of records successfully inserted
        """
        if not records:
            return 0
        
        success_count = 0
        for record in records:
            if self.insert_company_record(record):
                success_count += 1
        
        logger.info(f"Inserted {success_count}/{len(records)} company records")
        return success_count
    
    def query_companies(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Query company records from Snowflake
        
        Args:
            filters: Optional dict of column: value filters
            limit: Optional limit on number of results
            offset: Offset for pagination
            
        Returns:
            List of company records as dictionaries
        """
        query = "SELECT * FROM enriched_companies WHERE 1=1"
        params = []
        
        if filters:
            for key, value in filters.items():
                query += f" AND {key} = %s"
                params.append(value)
        
        query += " ORDER BY last_updated DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        if offset:
            query += f" OFFSET {offset}"
        
        try:
            results = self.execute_query(query, tuple(params) if params else None)
            
            # Convert to list of dicts
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in results]
            
        except Exception as e:
            logger.error(f"Error querying companies: {str(e)}")
            raise
    
    def insert_scraping_job(self, job: ScrapingJob) -> bool:
        """
        Insert a scraping job record
        
        Args:
            job: ScrapingJob instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                'job_id': job.job_id,
                'source': job.source,
                'status': job.status,
                'started_at': job.started_at,
                'completed_at': job.completed_at,
                'records_scraped': job.records_scraped,
                'records_enriched': job.records_enriched,
                'errors': json.dumps(job.errors) if job.errors else None
            }
            
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            
            query = f"""
            INSERT INTO scraping_jobs ({columns})
            VALUES ({placeholders})
            """
            
            self.execute_update(query, tuple(data.values()))
            logger.info(f"Inserted scraping job: {job.job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error inserting scraping job: {str(e)}")
            logger.exception(e)
            return False
    
    def update_scraping_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a scraping job record
        
        Args:
            job_id: Job ID to update
            updates: Dict of fields to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if 'errors' in updates and isinstance(updates['errors'], list):
                updates['errors'] = json.dumps(updates['errors'])
            
            set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
            query = f"UPDATE scraping_jobs SET {set_clause} WHERE job_id = %s"
            
            params = tuple(list(updates.values()) + [job_id])
            self.execute_update(query, params)
            
            logger.debug(f"Updated scraping job: {job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating scraping job: {str(e)}")
            logger.exception(e)
            return False
    
    def _enriched_record_to_dict(self, record: EnrichedCompanyRecord) -> Dict[str, Any]:
        """Convert EnrichedCompanyRecord to dictionary for database insertion"""
        data = {
            'entity_name': record.entity_name,
            'entity_type': record.entity_type,
            'registration_number': record.registration_number,
            'registration_date': record.registration_date,
            'status': record.status,
            'registered_agent': record.registered_agent,
            'website': record.website,
            'naics_code': record.naics_code,
            'naics_description': record.naics_description,
            'industry_keywords': json.dumps(record.industry_keywords) if record.industry_keywords else None,
            'data_quality_score': record.data_quality_score,
            'enrichment_status': record.enrichment_status,
            'enrichment_errors': json.dumps(record.enrichment_errors) if record.enrichment_errors else None,
            'jurisdiction': record.jurisdiction,
            'source_url': record.source_url,
            'scraped_at': record.scraped_at,
            'enriched_at': record.enriched_at,
        }
        
        # Address fields
        if record.registered_agent_address:
            data['registered_agent_address_street'] = record.registered_agent_address.street
            data['registered_agent_address_city'] = record.registered_agent_address.city
            data['registered_agent_address_state'] = record.registered_agent_address.state
            data['registered_agent_address_zip_code'] = record.registered_agent_address.zip_code
            data['registered_agent_address_country'] = record.registered_agent_address.country
        
        if record.principal_address:
            data['principal_address_street'] = record.principal_address.street
            data['principal_address_city'] = record.principal_address.city
            data['principal_address_state'] = record.principal_address.state
            data['principal_address_zip_code'] = record.principal_address.zip_code
            data['principal_address_country'] = record.principal_address.country
        
        if record.mailing_address:
            data['mailing_address_street'] = record.mailing_address.street
            data['mailing_address_city'] = record.mailing_address.city
            data['mailing_address_state'] = record.mailing_address.state
            data['mailing_address_zip_code'] = record.mailing_address.zip_code
            data['mailing_address_country'] = record.mailing_address.country
        
        # Contact info
        if record.contact_info:
            data['contact_email'] = record.contact_info.email
            data['contact_phone'] = record.contact_info.phone
            data['contact_linkedin_url'] = record.contact_info.linkedin_url
        
        return data
    
    def _business_record_to_dict(self, record: BusinessRegistryRecord) -> Dict[str, Any]:
        """Convert BusinessRegistryRecord to dictionary for database insertion"""
        data = {
            'entity_name': record.entity_name,
            'entity_type': record.entity_type,
            'registration_number': record.registration_number,
            'registration_date': record.registration_date,
            'status': record.status,
            'registered_agent': record.registered_agent,
            'jurisdiction': record.jurisdiction or 'GA',
            'source_url': record.source_url,
            'scraped_at': record.scraped_at,
            'enrichment_status': 'pending',
        }
        
        # Address fields
        if record.registered_agent_address:
            data['registered_agent_address_street'] = record.registered_agent_address.street
            data['registered_agent_address_city'] = record.registered_agent_address.city
            data['registered_agent_address_state'] = record.registered_agent_address.state
            data['registered_agent_address_zip_code'] = record.registered_agent_address.zip_code
            data['registered_agent_address_country'] = record.registered_agent_address.country
        
        if record.principal_address:
            data['principal_address_street'] = record.principal_address.street
            data['principal_address_city'] = record.principal_address.city
            data['principal_address_state'] = record.principal_address.state
            data['principal_address_zip_code'] = record.principal_address.zip_code
            data['principal_address_country'] = record.principal_address.country
        
        if record.mailing_address:
            data['mailing_address_street'] = record.mailing_address.street
            data['mailing_address_city'] = record.mailing_address.city
            data['mailing_address_state'] = record.mailing_address.state
            data['mailing_address_zip_code'] = record.mailing_address.zip_code
            data['mailing_address_country'] = record.mailing_address.country
        
        return data


# Convenience function for quick usage
def get_snowflake_client(config: Optional[Dict[str, Any]] = None) -> SnowflakeClient:
    """
    Get a Snowflake client instance
    
    Args:
        config: Optional configuration dict
        
    Returns:
        SnowflakeClient instance
    """
    return SnowflakeClient(config)

