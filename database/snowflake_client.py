"""
Snowflake Client for storing scraped company data
"""
import os
import pandas as pd
from loguru import logger
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Singleton instance
_snowflake_client = None

def get_snowflake_client() -> 'SnowflakeClient':
    """Get or create singleton SnowflakeClient instance"""
    global _snowflake_client
    if _snowflake_client is None:
        _snowflake_client = SnowflakeClient()
    return _snowflake_client


class SnowflakeClient:
    """Client for interacting with Snowflake database"""
    
    def __init__(self):
        """Initialize Snowflake connection using environment variables"""
        self.account = os.getenv('SNOWFLAKE_ACCOUNT')
        self.user = os.getenv('SNOWFLAKE_USER')
        self.password = os.getenv('SNOWFLAKE_PASSWORD')
        self.warehouse = os.getenv('SNOWFLAKE_WAREHOUSE')
        self.database = os.getenv('SNOWFLAKE_DATABASE')
        self.schema = os.getenv('SNOWFLAKE_SCHEMA')
        self.table_name = 'SCRAPED_COMPANIES'  # Default table name
        
        self.connection = None
        self._validate_config()
    
    def _validate_config(self):
        """Validate that all required config is present"""
        required = ['account', 'user', 'password', 'warehouse', 'database', 'schema']
        missing = [k for k in required if not getattr(self, k)]
        if missing:
            raise ValueError(f"Missing Snowflake configuration: {missing}")
        logger.info(f"✅ Snowflake config validated: {self.database}.{self.schema}")
    
    def connect(self):
        """Establish connection to Snowflake"""
        try:
            import snowflake.connector
            
            self.connection = snowflake.connector.connect(
                account=self.account,
                user=self.user,
                password=self.password,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema
            )
            logger.info(f"✅ Connected to Snowflake: {self.database}.{self.schema}")
            
            # Set warehouse context immediately after connecting
            cursor = self.connection.cursor()
            try:
                cursor.execute(f"USE WAREHOUSE {self.warehouse}")
                cursor.execute(f"USE DATABASE {self.database}")
                cursor.execute(f"USE SCHEMA {self.schema}")
            finally:
                cursor.close()
            
            return self.connection
        except Exception as e:
            logger.error(f"❌ Failed to connect to Snowflake: {e}")
            raise
    
    def reconnect(self):
        """Reconnect to Snowflake (useful for long-running pipelines where token expires)"""
        logger.info("🔄 Reconnecting to Snowflake...")
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
        return self.connect()
    
    def ensure_connection(self):
        """Ensure connection is active, reconnect if needed"""
        if not self.connection:
            return self.connect()
        
        # Test if connection is still valid
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return self.connection
        except Exception as e:
            logger.warning(f"⚠️ Connection test failed, reconnecting: {e}")
            return self.reconnect()
    
    def disconnect(self):
        """Close Snowflake connection"""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("✅ Disconnected from Snowflake")
    
    def create_tables(self):
        """Alias for create_table_if_not_exists - for pipeline compatibility"""
        return self.create_table_if_not_exists()
    
    def create_table_if_not_exists(self):
        """Create the scraped companies table if it doesn't exist"""
        if not self.connection:
            self.connect()
        
        cursor = self.connection.cursor()
        
        # Set database and schema context first
        try:
            cursor.execute(f"USE DATABASE {self.database}")
            cursor.execute(f"USE SCHEMA {self.schema}")
            logger.info(f"✅ Set context: {self.database}.{self.schema}")
        except Exception as e:
            logger.warning(f"⚠️ Could not set context: {e}")
        finally:
            cursor.close()
        
        # Fully qualified table name
        full_table_name = f"{self.database}.{self.schema}.{self.table_name}"
        
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {full_table_name} (
            -- Primary identifiers
            ID NUMBER AUTOINCREMENT PRIMARY KEY,
            JOB_ID VARCHAR(50),
            CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            
            -- Georgia SOS Basic Info
            BUSINESS_NAME VARCHAR(500),
            CONTROL_NUMBER VARCHAR(50),
            BUSINESS_TYPE VARCHAR(200),
            STATUS VARCHAR(100),
            BUSINESS_LINK VARCHAR(1000),
            
            -- Address Information
            PRINCIPAL_OFFICE_ADDRESS VARCHAR(500),
            REGISTERED_AGENT_NAME VARCHAR(300),
            REGISTERED_AGENT_ADDRESS VARCHAR(500),
            REGISTERED_AGENT_COUNTY VARCHAR(100),
            
            -- Date Information
            DATE_OF_FORMATION DATE,
            STATE_OF_FORMATION VARCHAR(100),
            LAST_ANNUAL_REGISTRATION_YEAR INTEGER,
            DISSOLVED_DATE DATE,
            
            -- Officers
            OFFICERS TEXT,
            OFFICERS_FORMATTED TEXT,
            OFFICER_COUNT INTEGER,
            
            -- Georgia SOS NAICS (original from website)
            GEORGIA_SOS_NAICS VARCHAR(500),
            GEORGIA_SOS_NAICS_SUB VARCHAR(500),
            
            -- Gemini AI NAICS (enriched)
            NAICS_CODE VARCHAR(10),
            NAICS_TITLE VARCHAR(500),
            NAICS_DESCRIPTION VARCHAR(500),
            NAICS_CONFIDENCE FLOAT,
            NAICS_CLASSIFICATION_METHOD VARCHAR(50),
            NAICS_SOURCE VARCHAR(100),
            
            -- Contact Information (from Google/DuckDuckGo search)
            WEBSITE VARCHAR(1000),
            WEBSITE_CONFIDENCE FLOAT,
            WEBSITE_SOURCE VARCHAR(100),
            WEBSITE_VALIDATION_REASON VARCHAR(500),
            LINKEDIN VARCHAR(500),
            FACEBOOK VARCHAR(500),
            EMAIL VARCHAR(300),
            PHONE VARCHAR(50),
            
            -- Facebook Data
            FB_CATEGORY VARCHAR(300),
            FB_DESCRIPTION TEXT,
            FB_ADDRESS VARCHAR(500),
            FB_CITY VARCHAR(100),
            FB_STATE VARCHAR(50),
            FB_ZIP VARCHAR(20),
            FB_HOURS TEXT,
            FB_PRICE_RANGE VARCHAR(50),
            FB_REVIEWS VARCHAR(200),
            
            -- Apollo Enrichment
            APOLLO_ENRICHED BOOLEAN DEFAULT FALSE,
            APOLLO_COMPANY_ID VARCHAR(100),
            APOLLO_EMPLOYEE_COUNT INTEGER,
            APOLLO_ESTIMATED_REVENUE VARCHAR(100),
            APOLLO_INDUSTRY VARCHAR(200),
            
            -- Manta Specific Data
            MANTA_MAP_URL VARCHAR(1000),
            
            -- Data Quality
            DATA_QUALITY_SCORE FLOAT,
            
            -- Metadata
            UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
        
        cursor = self.connection.cursor()
        try:
            cursor.execute(create_table_sql)
            logger.info(f"✅ Table {self.table_name} created/verified")
        finally:
            cursor.close()
    
    def save_dataframe(self, df: pd.DataFrame, job_id: str = None) -> int:
        """
        Save a DataFrame to Snowflake
        
        Args:
            df: DataFrame with company data
            job_id: Optional job identifier
            
        Returns:
            Number of rows inserted
        """
        if not self.connection:
            self.connect()
        
        # Ensure table exists
        self.create_table_if_not_exists()
        
        # Map DataFrame columns to Snowflake columns
        column_mapping = {
            'Business Name': 'BUSINESS_NAME',
            'Entity Name': 'BUSINESS_NAME',
            'Control Number': 'CONTROL_NUMBER',
            'Business Type': 'BUSINESS_TYPE',
            'Status': 'STATUS',
            'Business Link': 'BUSINESS_LINK',
            'Principal Office Address': 'PRINCIPAL_OFFICE_ADDRESS',
            'Registered / Designated Agent Name': 'REGISTERED_AGENT_NAME',
            'Registered Agent Physical Address': 'REGISTERED_AGENT_ADDRESS',
            'Registered Agent County': 'REGISTERED_AGENT_COUNTY',
            'Date of Formation': 'DATE_OF_FORMATION',
            'State of Formation': 'STATE_OF_FORMATION',
            'Last Annual Registration Year': 'LAST_ANNUAL_REGISTRATION_YEAR',
            'Dissolved Date': 'DISSOLVED_DATE',
            'Officers': 'OFFICERS',
            'Officers_Formatted': 'OFFICERS_FORMATTED',
            'Officer_Count': 'OFFICER_COUNT',
            'Georgia_SOS_NAICS': 'GEORGIA_SOS_NAICS',
            'Georgia_SOS_NAICS_Sub': 'GEORGIA_SOS_NAICS_SUB',
            'NAICS Code': 'NAICS_CODE',
            'NAICS Title': 'NAICS_TITLE',
            'NAICS Description': 'NAICS_DESCRIPTION',
            'NAICS Confidence': 'NAICS_CONFIDENCE',
            'NAICS Classification Method': 'NAICS_CLASSIFICATION_METHOD',
            'NAICS_Source': 'NAICS_SOURCE',
            'Website': 'WEBSITE',
            'Website_Confidence': 'WEBSITE_CONFIDENCE',
            'Website_Source': 'WEBSITE_SOURCE',
            'Website_Validation_Reason': 'WEBSITE_VALIDATION_REASON',
            'LinkedIn': 'LINKEDIN',
            'Facebook': 'FACEBOOK',
            'Email': 'EMAIL',
            'email': 'EMAIL',
            'Phone': 'PHONE',
            'phone': 'PHONE',
            'category': 'FB_CATEGORY',
            'description': 'FB_DESCRIPTION',
            'address': 'FB_ADDRESS',
            'city': 'FB_CITY',
            'state': 'FB_STATE',
            'zip': 'FB_ZIP',
            'hours': 'FB_HOURS',
            'price_range': 'FB_PRICE_RANGE',
            'reviews': 'FB_REVIEWS',
            'Manta_Map_Url': 'MANTA_MAP_URL',
            'data_quality_score': 'DATA_QUALITY_SCORE',
        }
        
        # Rename columns to Snowflake format
        df_snowflake = df.copy()
        for old_col, new_col in column_mapping.items():
            if old_col in df_snowflake.columns:
                df_snowflake = df_snowflake.rename(columns={old_col: new_col})
        
        # Add job_id if provided
        if job_id:
            df_snowflake['JOB_ID'] = job_id
        
        # Keep only columns that exist in table
        valid_columns = [
            'JOB_ID', 'BUSINESS_NAME', 'CONTROL_NUMBER', 'BUSINESS_TYPE', 'STATUS',
            'BUSINESS_LINK', 'PRINCIPAL_OFFICE_ADDRESS', 'REGISTERED_AGENT_NAME',
            'REGISTERED_AGENT_ADDRESS', 'REGISTERED_AGENT_COUNTY', 'DATE_OF_FORMATION',
            'STATE_OF_FORMATION', 'LAST_ANNUAL_REGISTRATION_YEAR', 'DISSOLVED_DATE',
            'OFFICERS', 'OFFICERS_FORMATTED', 'OFFICER_COUNT',
            'GEORGIA_SOS_NAICS', 'GEORGIA_SOS_NAICS_SUB',
            'NAICS_CODE', 'NAICS_TITLE', 'NAICS_DESCRIPTION', 'NAICS_CONFIDENCE',
            'NAICS_CLASSIFICATION_METHOD', 'NAICS_SOURCE',
            'WEBSITE', 'WEBSITE_CONFIDENCE', 'WEBSITE_SOURCE', 'WEBSITE_VALIDATION_REASON',
            'LINKEDIN', 'FACEBOOK', 'EMAIL', 'PHONE',
            'FB_CATEGORY', 'FB_DESCRIPTION', 'FB_ADDRESS', 'FB_CITY', 'FB_STATE',
            'FB_ZIP', 'FB_HOURS', 'FB_PRICE_RANGE', 'FB_REVIEWS',
            'MANTA_MAP_URL',
            'DATA_QUALITY_SCORE'
        ]
        
        existing_cols = [c for c in valid_columns if c in df_snowflake.columns]
        df_snowflake = df_snowflake[existing_cols]
        
        # Replace NaN with None for Snowflake
        df_snowflake = df_snowflake.where(pd.notnull(df_snowflake), None)
        
        # Use write_pandas for efficient bulk insert
        from snowflake.connector.pandas_tools import write_pandas
        
        try:
            success, nchunks, nrows, _ = write_pandas(
                self.connection,
                df_snowflake,
                self.table_name,
                auto_create_table=False,
                overwrite=False
            )
            logger.info(f"✅ Saved {nrows} records to Snowflake table {self.table_name}")
            return nrows
        except Exception as e:
            logger.error(f"❌ Failed to save to Snowflake: {e}")
            # Fallback to row-by-row insert
            return self._insert_rows(df_snowflake)
    
    def _insert_rows(self, df: pd.DataFrame) -> int:
        """Fallback row-by-row insert"""
        cursor = self.connection.cursor()
        inserted = 0
        
        try:
            for _, row in df.iterrows():
                cols = [c for c in row.index if pd.notna(row[c])]
                vals = [row[c] for c in cols]
                
                placeholders = ', '.join(['%s'] * len(cols))
                col_names = ', '.join(cols)
                
                sql = f"INSERT INTO {self.table_name} ({col_names}) VALUES ({placeholders})"
                
                try:
                    cursor.execute(sql, vals)
                    inserted += 1
                except Exception as e:
                    logger.warning(f"⚠️ Failed to insert row: {e}")
            
            logger.info(f"✅ Inserted {inserted} rows via fallback method")
            return inserted
        finally:
            cursor.close()
    
    def load_companies(self, limit: int = None, where_clause: str = None) -> pd.DataFrame:
        """
        Load companies from Snowflake
        
        Args:
            limit: Maximum number of records to load
            where_clause: Optional WHERE clause (without 'WHERE' keyword)
            
        Returns:
            DataFrame with company data
        """
        if not self.connection:
            self.connect()
        
        sql = f"SELECT * FROM {self.table_name}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        sql += " ORDER BY CREATED_AT DESC"
        if limit:
            sql += f" LIMIT {limit}"
        
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()
            df = pd.DataFrame(data, columns=columns)
            logger.info(f"✅ Loaded {len(df)} records from Snowflake")
            return df
        finally:
            cursor.close()
    
    def upsert_dataframe(self, df: pd.DataFrame, job_id: str = None) -> int:
        """
        Upsert (insert or update) a DataFrame to Snowflake.
        Uses CONTROL_NUMBER as the unique key - inserts new records and updates existing ones.
        
        Args:
            df: DataFrame with company data
            job_id: Optional job identifier
            
        Returns:
            Number of rows affected (inserted + updated)
        """
        # Ensure connection is active (auto-reconnect if token expired)
        self.ensure_connection()
        
        # Ensure table exists
        self.create_table_if_not_exists()
        
        # Map DataFrame columns to Snowflake columns
        column_mapping = {
            'Business Name': 'BUSINESS_NAME',
            'Entity Name': 'BUSINESS_NAME',
            'Control Number': 'CONTROL_NUMBER',
            'Business Type': 'BUSINESS_TYPE',
            'Status': 'STATUS',
            'Business Link': 'BUSINESS_LINK',
            'Principal Office Address': 'PRINCIPAL_OFFICE_ADDRESS',
            'Registered / Designated Agent Name': 'REGISTERED_AGENT_NAME',
            'Registered Agent Physical Address': 'REGISTERED_AGENT_ADDRESS',
            'Registered Agent County': 'REGISTERED_AGENT_COUNTY',
            'Date of Formation': 'DATE_OF_FORMATION',
            'State of Formation': 'STATE_OF_FORMATION',
            'Last Annual Registration Year': 'LAST_ANNUAL_REGISTRATION_YEAR',
            'Dissolved Date': 'DISSOLVED_DATE',
            'Officers': 'OFFICERS',
            'Officers_Formatted': 'OFFICERS_FORMATTED',
            'Officer_Count': 'OFFICER_COUNT',
            'Georgia_SOS_NAICS': 'GEORGIA_SOS_NAICS',
            'Georgia_SOS_NAICS_Sub': 'GEORGIA_SOS_NAICS_SUB',
            'NAICS Code': 'NAICS_CODE',
            'NAICS Title': 'NAICS_TITLE',
            'NAICS Description': 'NAICS_DESCRIPTION',
            'NAICS Confidence': 'NAICS_CONFIDENCE',
            'NAICS Classification Method': 'NAICS_CLASSIFICATION_METHOD',
            'NAICS_Source': 'NAICS_SOURCE',
            'Website': 'WEBSITE',
            'Website_Confidence': 'WEBSITE_CONFIDENCE',
            'Website_Source': 'WEBSITE_SOURCE',
            'Website_Validation_Reason': 'WEBSITE_VALIDATION_REASON',
            'LinkedIn': 'LINKEDIN',
            'Facebook': 'FACEBOOK',
            'Email': 'EMAIL',
            'email': 'EMAIL',
            'Phone': 'PHONE',
            'phone': 'PHONE',
            'category': 'FB_CATEGORY',
            'description': 'FB_DESCRIPTION',
            'address': 'FB_ADDRESS',
            'city': 'FB_CITY',
            'state': 'FB_STATE',
            'zip': 'FB_ZIP',
            'hours': 'FB_HOURS',
            'price_range': 'FB_PRICE_RANGE',
            'reviews': 'FB_REVIEWS',
            'Manta_Map_Url': 'MANTA_MAP_URL',
            'data_quality_score': 'DATA_QUALITY_SCORE',
        }
        
        # Rename columns to Snowflake format
        df_snowflake = df.copy()
        for old_col, new_col in column_mapping.items():
            if old_col in df_snowflake.columns:
                df_snowflake = df_snowflake.rename(columns={old_col: new_col})
        
        # Add job_id if provided
        if job_id:
            df_snowflake['JOB_ID'] = job_id
        
        # Keep only columns that exist in table
        valid_columns = [
            'JOB_ID', 'BUSINESS_NAME', 'CONTROL_NUMBER', 'BUSINESS_TYPE', 'STATUS',
            'BUSINESS_LINK', 'PRINCIPAL_OFFICE_ADDRESS', 'REGISTERED_AGENT_NAME',
            'REGISTERED_AGENT_ADDRESS', 'REGISTERED_AGENT_COUNTY', 'DATE_OF_FORMATION',
            'STATE_OF_FORMATION', 'LAST_ANNUAL_REGISTRATION_YEAR', 'DISSOLVED_DATE',
            'OFFICERS', 'OFFICERS_FORMATTED', 'OFFICER_COUNT',
            'GEORGIA_SOS_NAICS', 'GEORGIA_SOS_NAICS_SUB',
            'NAICS_CODE', 'NAICS_TITLE', 'NAICS_DESCRIPTION', 'NAICS_CONFIDENCE',
            'NAICS_CLASSIFICATION_METHOD', 'NAICS_SOURCE',
            'WEBSITE', 'WEBSITE_CONFIDENCE', 'WEBSITE_SOURCE', 'WEBSITE_VALIDATION_REASON',
            'LINKEDIN', 'FACEBOOK', 'EMAIL', 'PHONE',
            'FB_CATEGORY', 'FB_DESCRIPTION', 'FB_ADDRESS', 'FB_CITY', 'FB_STATE',
            'FB_ZIP', 'FB_HOURS', 'FB_PRICE_RANGE', 'FB_REVIEWS',
            'MANTA_MAP_URL',
            'DATA_QUALITY_SCORE'
        ]
        
        existing_cols = [c for c in valid_columns if c in df_snowflake.columns]
        df_snowflake = df_snowflake[existing_cols]
        
        # Replace NaN with None for Snowflake
        df_snowflake = df_snowflake.where(pd.notnull(df_snowflake), None)
        
        # Check for CONTROL_NUMBER - required for upsert
        if 'CONTROL_NUMBER' not in df_snowflake.columns:
            logger.warning("⚠️ CONTROL_NUMBER not found, falling back to regular insert")
            return self.save_dataframe(df, job_id)
        
        # Create temporary staging table
        staging_table = f"STAGING_{self.table_name}_{job_id or 'temp'}".replace('-', '_')
        
        cursor = self.connection.cursor()
        inserted = 0
        updated = 0
        
        try:
            # Drop staging table if exists
            cursor.execute(f"DROP TABLE IF EXISTS {staging_table}")
            
            # Create staging table with same structure
            cursor.execute(f"""
                CREATE TEMPORARY TABLE {staging_table} LIKE {self.table_name}
            """)
            logger.debug(f"Created staging table: {staging_table}")
            
            # Insert data into staging table using write_pandas
            try:
                from snowflake.connector.pandas_tools import write_pandas
                
                # Ensure pandas is properly available
                success, nchunks, nrows, _ = write_pandas(
                    self.connection,
                    df_snowflake,
                    staging_table,
                    auto_create_table=False,
                    overwrite=False,
                    quote_identifiers=False
                )
                logger.debug(f"Loaded {nrows} rows into staging table")
            except ImportError as e:
                logger.warning(f"⚠️ write_pandas not available: {e}, using fallback INSERT")
                # Fallback: insert rows directly into staging table
                nrows = self._insert_to_staging(cursor, staging_table, df_snowflake, existing_cols)
                logger.debug(f"Inserted {nrows} rows into staging table via fallback")
            
            # Build MERGE statement
            update_cols = [c for c in existing_cols if c != 'CONTROL_NUMBER']
            
            # Update clause - update all columns except CONTROL_NUMBER
            update_clause = ', '.join([f"target.{c} = source.{c}" for c in update_cols])
            update_clause += ", target.UPDATED_AT = CURRENT_TIMESTAMP()"
            
            # Insert columns and values
            insert_cols = ', '.join(existing_cols)
            insert_vals = ', '.join([f"source.{c}" for c in existing_cols])
            
            merge_sql = f"""
                MERGE INTO {self.table_name} AS target
                USING {staging_table} AS source
                ON target.CONTROL_NUMBER = source.CONTROL_NUMBER
                WHEN MATCHED THEN
                    UPDATE SET {update_clause}
                WHEN NOT MATCHED THEN
                    INSERT ({insert_cols})
                    VALUES ({insert_vals})
            """
            
            cursor.execute(merge_sql)
            
            # Get merge results
            result = cursor.fetchone()
            if result:
                # Snowflake returns number of rows inserted
                total_affected = cursor.rowcount
                logger.info(f"✅ MERGE completed: {total_affected} rows affected")
            
            # Clean up staging table
            cursor.execute(f"DROP TABLE IF EXISTS {staging_table}")
            
            # Count actual inserted vs updated for logging
            cursor.execute(f"""
                SELECT COUNT(*) FROM {self.table_name} 
                WHERE CONTROL_NUMBER IN (
                    SELECT CONTROL_NUMBER FROM {staging_table}
                )
            """)
            
            logger.info(f"✅ Upserted {nrows} records to Snowflake (new + updated)")
            return nrows
            
        except Exception as e:
            logger.error(f"❌ Failed to upsert to Snowflake: {e}")
            # Fallback to row-by-row upsert
            return self._upsert_rows(df_snowflake)
        finally:
            cursor.close()
    
    def _insert_to_staging(self, cursor, staging_table: str, df: pd.DataFrame, columns: list) -> int:
        """Insert rows into staging table when write_pandas fails"""
        inserted = 0
        for _, row in df.iterrows():
            # Get values for columns that exist
            vals = []
            valid_cols = []
            for col in columns:
                val = row.get(col)
                if pd.notna(val):
                    vals.append(val)
                    valid_cols.append(col)
            
            if vals:
                placeholders = ', '.join(['%s'] * len(vals))
                col_names = ', '.join(valid_cols)
                sql = f"INSERT INTO {staging_table} ({col_names}) VALUES ({placeholders})"
                try:
                    cursor.execute(sql, vals)
                    inserted += 1
                except Exception as e:
                    logger.debug(f"Failed to insert row: {e}")
        return inserted
    
    def _upsert_rows(self, df: pd.DataFrame) -> int:
        """Fallback row-by-row upsert using INSERT with ON CONFLICT simulation"""
        # Ensure connection is active
        self.ensure_connection()
        
        cursor = self.connection.cursor()
        affected = 0
        
        try:
            # Set context first
            cursor.execute(f"USE WAREHOUSE {self.warehouse}")
            cursor.execute(f"USE DATABASE {self.database}")
            cursor.execute(f"USE SCHEMA {self.schema}")
            
            for idx, row in df.iterrows():
                try:
                    control_number = row.get('CONTROL_NUMBER')
                    # Handle pandas NA/None properly
                    if control_number is None or (isinstance(control_number, float) and pd.isna(control_number)):
                        continue
                    if hasattr(control_number, 'item'):
                        control_number = control_number.item()
                    
                    
                    # Build column/value lists, properly handling pandas types
                    # Use dict to avoid duplicate column names
                    col_val_dict = {}
                    for c in row.index:
                        # Skip if column already processed (handles duplicates)
                        if c in col_val_dict:
                            continue
                            
                        val = row[c]
                        # Check if value is valid (not NA/NaN/None)
                        try:
                            is_valid = val is not None and not pd.isna(val)
                        except (ValueError, TypeError):
                            is_valid = val is not None
                        
                        # Also check for string representations of None/NA
                        if is_valid and isinstance(val, str):
                            val_upper = val.strip().upper()
                            if val_upper in ('NONE', 'N/A', 'NA', 'NULL', ''):
                                is_valid = False
                        
                        if is_valid:
                            # Convert pandas/numpy types to Python native types
                            import numpy as np
                            if isinstance(val, np.ndarray):
                                # Handle numpy arrays - take first element if single, or convert to string
                                if val.size == 1:
                                    val = val.item()
                                else:
                                    val = str(val.tolist())
                            elif hasattr(val, 'item') and not isinstance(val, str):
                                try:
                                    val = val.item()
                                except ValueError:
                                    val = str(val)
                            elif isinstance(val, pd.Timestamp):
                                val = val.to_pydatetime()
                            elif isinstance(val, (np.integer, np.floating)):
                                val = val.item()
                            col_val_dict[c] = val
                    
                    if not col_val_dict:
                        continue
                    
                    cols = list(col_val_dict.keys())
                    vals = list(col_val_dict.values())
                    
                    # Check if record exists
                    cursor.execute(
                        f"SELECT 1 FROM {self.table_name} WHERE CONTROL_NUMBER = %s",
                        [str(control_number)]
                    )
                    exists = cursor.fetchone() is not None
                    
                    if exists:
                        # Update existing record
                        update_parts = [f"{c} = %s" for c in cols if c != 'CONTROL_NUMBER']
                        update_vals = [v for c, v in zip(cols, vals) if c != 'CONTROL_NUMBER']
                        update_vals.append(str(control_number))
                        
                        if update_parts:
                            sql = f"""
                                UPDATE {self.table_name} 
                                SET {', '.join(update_parts)}, UPDATED_AT = CURRENT_TIMESTAMP()
                                WHERE CONTROL_NUMBER = %s
                            """
                            cursor.execute(sql, update_vals)
                    else:
                        # Insert new record
                        placeholders = ', '.join(['%s'] * len(cols))
                        col_names = ', '.join(cols)
                        sql = f"INSERT INTO {self.table_name} ({col_names}) VALUES ({placeholders})"
                        cursor.execute(sql, vals)
                    
                    affected += 1
                    
                    # Log progress
                    if affected % 50 == 0:
                        logger.debug(f"Upserted {affected} rows...")
                        
                except Exception as row_e:
                    logger.debug(f"Error processing row {idx}: {row_e}")
                    continue
            
            logger.info(f"✅ Upserted {affected} rows via fallback method")
            return affected
        except Exception as e:
            logger.error(f"❌ Row-by-row upsert failed: {e}")
            return 0
        finally:
            cursor.close()
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
