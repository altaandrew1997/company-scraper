"""
NAICS Code Classification Module
Uses the official 2022 NAICS Excel file for keyword-based classification
"""

import re
import json
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from loguru import logger
import pandas as pd
from difflib import SequenceMatcher

class NAICSClassifier:
    """NAICS code classifier using official Excel data"""
    
    def __init__(self, excel_file_path: str = "2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx"):
        """
        Initialize NAICS classifier
        
        Args:
            excel_file_path: Path to the NAICS Excel file
        """
        self.excel_file = Path(excel_file_path)
        self.naics_data = {}
        self._load_naics_data()
    
    def _load_naics_data(self):
        """Load NAICS data from all sheets in Excel file"""
        try:
            logger.info(f"📂 Loading NAICS data from: {self.excel_file}")
            
            # Define sheet priority (most specific first)
            # We'll load from most specific (6-digit) to least specific (2-digit)
            # and use the most specific match available
            sheet_priority = [
                'Six Digit NAICS',      # Most specific (1012 rows)
                'Five Digit NAICS',     # 689 rows
                'Four Digit NAICS',     # 308 rows
                'Three Digit NAICS',    # 96 rows
                'Two-Six Digit NAICS',  # All codes (2125 rows) - fallback
            ]
            
            xl_file = pd.ExcelFile(self.excel_file, engine='openpyxl')
            
            # Load sheets in priority order
            for sheet_name in sheet_priority:
                if sheet_name not in xl_file.sheet_names:
                    continue
                
                try:
                    df = pd.read_excel(xl_file, sheet_name=sheet_name, engine='openpyxl')
                    logger.info(f"   Loading sheet: {sheet_name} ({len(df)} rows)")
                    
                    # Column names are consistent across sheets
                    code_col = '2022 NAICS US   Code'
                    title_col = '2022 NAICS US Title'
                    desc_col = 'Description'
                    
                    if code_col not in df.columns or title_col not in df.columns:
                        logger.warning(f"   ⚠️  Sheet {sheet_name} missing required columns, skipping")
                        continue
                    
                    # Process each row
                    for _, row in df.iterrows():
                        code = str(row[code_col]).strip() if pd.notna(row[code_col]) else None
                        
                        # Skip if code is invalid
                        if not code or code == 'nan':
                            continue
                        
                        # Remove trailing 'T' that appears in some sheets
                        code = code.rstrip('T').strip()
                        
                        # Only process if code contains digits
                        if not re.search(r'\d', code):
                            continue
                        
                        # Extract numeric code (remove dashes, spaces, etc.)
                        code_match = re.search(r'(\d{2,6})', code)
                        if not code_match:
                            continue
                        
                        numeric_code = code_match.group(1)
                        
                        # Get title and description
                        title = str(row[title_col]).strip() if pd.notna(row[title_col]) else ""
                        # Remove trailing 'T' from title
                        title = title.rstrip('T').strip()
                        
                        desc = str(row[desc_col]).strip() if pd.notna(row[desc_col]) else ""
                        
                        # Only store if we don't have a more specific code already
                        # (6-digit codes override 5-digit, etc.)
                        if numeric_code not in self.naics_data or len(numeric_code) >= len(self.naics_data[numeric_code]['code']):
                            self.naics_data[numeric_code] = {
                                'code': numeric_code,
                                'title': title,
                                'description': desc or title,
                                'sheet_source': sheet_name
                            }
                    
                except Exception as e:
                    logger.warning(f"   ⚠️  Error loading sheet {sheet_name}: {str(e)}")
                    continue
            
            logger.info(f"✅ Loaded {len(self.naics_data)} unique NAICS codes")
            logger.info(f"   Codes by length: {self._count_by_length()}")
            
        except Exception as e:
            logger.error(f"❌ Error loading NAICS data: {str(e)}")
            raise
    
    def _count_by_length(self) -> Dict[str, int]:
        """Count codes by digit length"""
        counts = {}
        for code in self.naics_data.keys():
            length = len(code)
            counts[length] = counts.get(length, 0) + 1
        return counts
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching"""
        if not text:
            return ""
        return text.lower().strip()
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from business name"""
        if not text:
            return []
        
        # Remove common business suffixes
        text = re.sub(
            r'\b(LLC|Inc|Corp|Corporation|Ltd|Limited|LLP|LP|PA|PC|Co|Company|Enterprises|Enterprise|Group|Holdings|Holdings LLC|Services|Service)\b',
            '',
            text,
            flags=re.IGNORECASE
        )
        
        # First, extract common compound phrases (2-word phrases)
        compound_phrases = [
            'lawn care', 'tree removal', 'tree service', 'tree trimming', 'tree cutting',
            'landscape design', 'garden design', 'snow removal', 'snow plowing',
            'lawn maintenance', 'yard care', 'property management', 'real estate',
            'home improvement', 'construction', 'general contractor', 'plumbing',
            'electrical', 'heating', 'cooling', 'hvac', 'painting', 'roofing'
        ]
        
        keywords = []
        text_lower = text.lower()
        
        # Add compound phrases found (keep with spaces for better matching)
        for phrase in compound_phrases:
            if phrase in text_lower:
                keywords.append(phrase)  # Keep with space for matching
        
        # Extract individual words (3+ characters)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text_lower)
        
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'her',
            'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how',
            'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy',
            'did', 'let', 'put', 'say', 'she', 'too', 'use', 'with', 'from', 'this',
            'that', 'have', 'been', 'what', 'when', 'where', 'which', 'there', 'their'
        }
        words = [w for w in words if w not in stop_words]
        
        # Combine compound phrases and individual words
        keywords.extend(words)
        
        return keywords
    
    def _similarity_score(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts"""
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    
    def classify(
        self,
        business_name: str,
        business_type: Optional[str] = None,
        existing_naics: Optional[str] = None,
        min_confidence: float = 0.50,
        max_results: int = 5
    ) -> Optional[Dict[str, str]]:
        """
        Classify NAICS code using keyword matching
        
        Args:
            business_name: Name of the business
            business_type: Optional business type (LLC, Corp, etc.)
            existing_naics: Existing NAICS code (if any)
            min_confidence: Minimum confidence threshold (0.0-1.0)
            max_results: Maximum number of results to consider
            
        Returns:
            Dictionary with NAICS classification or None
        """
        # If NAICS already exists, return it
        if existing_naics and str(existing_naics).strip():
            existing_code = str(existing_naics).strip()
            # Extract numeric code if it has extra characters
            code_match = re.search(r'(\d{2,6})', existing_code)
            if code_match:
                existing_code = code_match.group(1)
                return {
                    'NAICS Code': existing_code,
                    'NAICS Description': 'From Georgia SOS Website',
                    'NAICS Confidence': '1.0'
                }
        
        if not self.naics_data:
            logger.warning("No NAICS data available")
            return None
        
        # Extract keywords from business name
        search_text = f"{business_name} {business_type or ''}".strip()
        keywords = self._extract_keywords(search_text)
        
        if not keywords:
            return None
        
        # Score each NAICS code
        scores = []
        for code, info in self.naics_data.items():
            title = self._normalize_text(info.get('title', ''))
            description = self._normalize_text(info.get('description', ''))
            combined_text = f"{title} {description}"
            
            # Calculate match score
            score = 0.0
            matches = []
            
            # Check keyword matches in title (higher weight)
            for keyword in keywords:
                # Check if keyword appears in title (exact match or as part of word)
                if keyword in title:
                    # Bonus for exact word match (space-separated)
                    if f" {keyword} " in f" {title} " or f" {keyword} " in f" {combined_text} ":
                        score += 0.5  # Higher weight for exact word match
                    else:
                        score += 0.4  # Lower weight for substring match
                    matches.append(keyword)
                elif keyword in description:
                    if f" {keyword} " in f" {description} ":
                        score += 0.25  # Bonus for exact word match in description
                    else:
                        score += 0.2  # Lower weight for description substring matches
                    matches.append(keyword)
            
            # Check overall similarity
            similarity = self._similarity_score(search_text, combined_text)
            score += similarity * 0.3
            
            # Bonus for multiple keyword matches (indicates strong relevance)
            if len(matches) > 1:
                score += 0.1 * (len(matches) - 1)  # 0.1 bonus per additional match
            
            # Prefer longer (more specific) codes if scores are similar
            code_length_bonus = len(code) / 100  # Small bonus for 6-digit codes
            score += code_length_bonus
            
            # Normalize score to 0-1 range
            # Max theoretical score is around 0.4 * num_keywords + 0.3 + 0.1 * num_keywords + 0.06
            normalized_score = min(1.0, score / max(len(keywords) * 0.5 + 0.4, 1))
            
            if normalized_score >= min_confidence:
                scores.append({
                    'code': code,
                    'title': info.get('title', ''),
                    'description': info.get('description', ''),
                    'score': normalized_score,
                    'matches': matches
                })
        
        if not scores:
            return None
        
        # Sort by score (highest first), then by code length (longer = more specific)
        scores.sort(key=lambda x: (x['score'], len(x['code'])), reverse=True)
        
        # Get best match
        best_match = scores[0]
        
        logger.debug(
            f"Classified '{business_name}' as NAICS {best_match['code']} "
            f"({best_match['title']}) - Confidence: {best_match['score']:.2f}"
        )
        
        return {
            'NAICS Code': best_match['code'],
            'NAICS Description': best_match['title'],
            'NAICS Confidence': f"{best_match['score']:.2f}"
        }


def enrich_naics_codes(
    df: pd.DataFrame,
    excel_file_path: str = "2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
    min_confidence: float = 0.50
) -> pd.DataFrame:
    """
    Enrich DataFrame with NAICS codes for businesses missing them
    
    Args:
        df: DataFrame with business data (must have 'Business Name' column)
        excel_file_path: Path to NAICS Excel file
        min_confidence: Minimum confidence threshold for classification
        
    Returns:
        DataFrame with enriched NAICS codes
    """
    if df.empty:
        return df
    
    # Ensure required columns exist
    if 'Business Name' not in df.columns:
        logger.error("DataFrame must have 'Business Name' column")
        return df
    
    # Add new columns if they don't exist
    if 'NAICS Code' not in df.columns:
        df['NAICS Code'] = ''
    if 'NAICS Description' not in df.columns:
        df['NAICS Description'] = ''
    if 'NAICS Confidence' not in df.columns:
        df['NAICS Confidence'] = ''
    
    # Initialize classifier (loads data once)
    try:
        classifier = NAICSClassifier(excel_file_path)
    except Exception as e:
        logger.error(f"❌ Failed to initialize NAICS classifier: {str(e)}")
        return df
    
    # Find rows without NAICS codes
    missing_naics = (
        df['NAICS Code'].isna() | 
        (df['NAICS Code'].astype(str).str.strip() == '') |
        (df['NAICS Code'].astype(str).str.strip() == 'nan')
    )
    missing_count = missing_naics.sum()
    
    if missing_count == 0:
        logger.info("✅ All businesses already have NAICS codes")
        return df
    
    logger.info(f"🔍 Classifying NAICS codes for {missing_count} businesses...")
    
    enriched_count = 0
    for idx in df[missing_naics].index:
        business_name = str(df.at[idx, 'Business Name'])
        business_type = (
            str(df.at[idx, 'Business Type']) 
            if 'Business Type' in df.columns and pd.notna(df.at[idx, 'Business Type'])
            else None
        )
        existing_naics = (
            str(df.at[idx, 'NAICS Code'])
            if pd.notna(df.at[idx, 'NAICS Code'])
            else None
        )
        
        classification = classifier.classify(
            business_name=business_name,
            business_type=business_type,
            existing_naics=existing_naics,
            min_confidence=min_confidence
        )
        
        if classification:
            df.at[idx, 'NAICS Code'] = classification['NAICS Code']
            df.at[idx, 'NAICS Description'] = classification['NAICS Description']
            df.at[idx, 'NAICS Confidence'] = classification['NAICS Confidence']
            enriched_count += 1
    
    logger.info(f"✅ Enriched {enriched_count} businesses with NAICS codes")
    logger.info(f"   Remaining without NAICS: {missing_count - enriched_count}")
    
    return df

