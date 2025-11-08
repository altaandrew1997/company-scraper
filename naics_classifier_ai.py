"""
AI-Enhanced NAICS Code Classification Module using Google Gemini
Uses Gemini AI for intelligent classification with keyword fallback
"""

import re
import json
import os
import time
from typing import Optional, List, Dict
from pathlib import Path
from loguru import logger
import pandas as pd
from difflib import SequenceMatcher

# Import the existing keyword-based classifier
from naics_classifier import NAICSClassifier

# Gemini import
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("Google Gemini not installed. Install with: pip install google-generativeai")


class GeminiNAICSClassifier(NAICSClassifier):
    """Gemini AI-enhanced NAICS classifier with keyword fallback"""
    
    def __init__(
        self,
        excel_file_path: str = "2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
        use_ai: bool = True,
        cache_file: Optional[str] = "data/naics_gemini_cache.json",
        gemini_model: str = "gemini-2.5-flash"  # Fast and cost-effective
    ):
        """
        Initialize Gemini AI-enhanced NAICS classifier
        
        Args:
            excel_file_path: Path to NAICS Excel file
            use_ai: Whether to use AI (False = keyword matching only)
            cache_file: Path to cache file for AI responses
            gemini_model: Gemini model to use ("gemini-2.5-flash" or "gemini-1.5-pro")
        """
        # Initialize base classifier
        super().__init__(excel_file_path)
        
        self.use_ai = use_ai
        self.cache_file = Path(cache_file) if cache_file else None
        self.ai_cache = {}
        self.gemini_model_name = gemini_model
        self.gemini_model = None
        
        # Initialize Gemini if requested
        if self.use_ai:
            self._initialize_gemini()
            
        # Load cache if exists
        if self.cache_file:
            self._load_cache()
    
    def _initialize_gemini(self):
        """Initialize Gemini AI client"""
        if not GEMINI_AVAILABLE:
            logger.warning("Google Gemini not available, falling back to keyword matching")
            self.use_ai = False
            return
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found in environment. Falling back to keyword matching.")
            logger.info("Get your API key from: https://makersuite.google.com/app/apikey")
            self.use_ai = False
            return
        
        try:
            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel(self.gemini_model_name)
            logger.info(f"✅ Gemini AI client initialized (model: {self.gemini_model_name})")
        except Exception as e:
            logger.warning(f"Failed to initialize Gemini: {str(e)}. Falling back to keyword matching.")
            self.use_ai = False
    
    def _load_cache(self):
        """Load AI response cache from file"""
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.ai_cache = json.load(f)
                logger.info(f"✅ Loaded {len(self.ai_cache)} cached Gemini responses")
            except Exception as e:
                logger.warning(f"Could not load cache: {str(e)}")
                self.ai_cache = {}
    
    def _save_cache(self):
        """Save AI response cache to file"""
        if self.cache_file:
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.cache_file, 'w') as f:
                    json.dump(self.ai_cache, f, indent=2)
            except Exception as e:
                logger.warning(f"Could not save cache: {str(e)}")
    
    def _get_cache_key(self, business_name: str, business_type: Optional[str], business_description: Optional[str]) -> str:
        """Generate cache key for business"""
        key_parts = [business_name.lower().strip()]
        if business_type:
            key_parts.append(business_type.lower().strip())
        if business_description:
            # Use first 200 chars of description for cache key
            key_parts.append(business_description[:200].lower().strip())
        return "|".join(key_parts)
    
    def _classify_with_gemini(
        self,
        business_name: str,
        business_type: Optional[str] = None,
        business_description: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """
        Classify NAICS code using Gemini AI
        
        Args:
            business_name: Name of the business
            business_type: Business type (LLC, Corp, etc.)
            business_description: Additional business description/context
            
        Returns:
            Dictionary with NAICS classification or None
        """
        if not self.use_ai or not self.gemini_model:
            return None
        
        # Check cache first (no delay needed for cached responses)
        cache_key = self._get_cache_key(business_name, business_type, business_description)
        if cache_key in self.ai_cache:
            logger.debug(f"Using cached Gemini response for: {business_name}")
            return self.ai_cache[cache_key]
        
        # Prepare business context - keep it MINIMAL to avoid token limits
        # Don't include description as it can cause token overflow
        business_context = business_name
        if business_type:
            business_context += f" ({business_type})"
        # Skip business_description entirely to minimize tokens
        
        # Ultra-simple prompt - try even simpler format
        # Format: Just ask for the code directly
        prompt = f"What is the NAICS code for {business_context}? Answer with only the 6-digit code."
        
        # Log the prompt being sent for debugging
        logger.info(f"📤 Sending to Gemini for '{business_name}':")
        logger.info(f"   Prompt: {prompt}")
        logger.info(f"   Business context: {business_context}")

        try:
            # Import safety settings if available
            try:
                from google.generativeai.types import HarmCategory, HarmBlockThreshold
                safety_settings = [
                    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
                    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                ]
            except ImportError:
                # Fallback to string values if enum import fails
                safety_settings = [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]
            
            # Count tokens before sending (for debugging) - skip if it causes issues
            try:
                token_count = self.gemini_model.count_tokens(prompt)
                logger.info(f"   Token count: {token_count.total_tokens} tokens")
                if token_count.total_tokens > 100:
                    logger.warning(f"⚠️ Prompt token count is unexpectedly high: {token_count.total_tokens} tokens for '{business_name}'")
            except Exception as e:
                # Token counting is optional - just skip if it fails
                logger.debug(f"Token counting skipped (non-critical): {str(e)[:50]}")
            
            # Make API call with timeout and retry handling
            # Note: finish_reason=2 with 0 parts suggests output was cut before generation
            # Try with higher max_output_tokens - even though we only need 6 digits
            try:
                # Try without max_output_tokens limit first - let Gemini decide
                # finish_reason=2 with 0 parts might be caused by restrictive token limits
                generation_config = {
                    "temperature": 0.1,  # Low temperature for consistent results
                    "top_p": 0.95,
                }
                # Only set max_output_tokens if explicitly needed - try without first
                # generation_config["max_output_tokens"] = 50
                
                response = self.gemini_model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                    request_options={"timeout": 30}  # 30 second timeout
                )
            except Exception as api_error:
                # Handle API errors gracefully
                error_msg = str(api_error)
                if "quota" in error_msg.lower() or "rate" in error_msg.lower():
                    logger.warning(f"⚠️ Rate limit/quota exceeded for {business_name}, falling back to keyword matching")
                elif "timeout" in error_msg.lower():
                    logger.warning(f"⚠️ API timeout for {business_name}, falling back to keyword matching")
                else:
                    logger.warning(f"⚠️ Gemini API error for '{business_name}': {error_msg[:100]}... falling back to keyword matching")
                return None  # Fall back to keyword matching
            
            # Log response details for debugging
            logger.info(f"📥 Response received for '{business_name}':")
            logger.info(f"   Number of candidates: {len(response.candidates) if response.candidates else 0}")
            
            # Check if response was blocked
            if not response.candidates or len(response.candidates) == 0:
                logger.warning(f"⚠️ Gemini response blocked (no candidates) for: {business_name}")
                return None
            
            candidate = response.candidates[0]
            logger.info(f"   Candidate finish_reason: {candidate.finish_reason if hasattr(candidate, 'finish_reason') else 'N/A'}")
            logger.info(f"   Candidate has content: {hasattr(candidate, 'content') and candidate.content is not None}")
            if hasattr(candidate, 'content') and candidate.content:
                logger.info(f"   Content parts count: {len(candidate.content.parts) if hasattr(candidate.content, 'parts') else 0}")
            
            # Check finish reason and try to extract text
            finish_reason = candidate.finish_reason if hasattr(candidate, 'finish_reason') else None
            finish_reason_value = None
            
            # Try to extract text first, then check finish_reason
            ai_code = None
            
            # Method 1: Try response.text (simplest, but may fail if no parts)
            try:
                ai_code = response.text.strip()
            except (AttributeError, ValueError) as e:
                # response.text failed - try accessing parts directly
                logger.debug(f"response.text failed for {business_name}, trying parts: {str(e)}")
                pass
            
            # Method 2: Access parts directly if response.text failed
            if not ai_code:
                try:
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                            part = candidate.content.parts[0]
                            if hasattr(part, 'text'):
                                ai_code = part.text.strip()
                            elif hasattr(part, 'function_call'):
                                # Handle function calls if any
                                logger.debug(f"Gemini returned function call instead of text for: {business_name}")
                                return None
                except Exception as e:
                    logger.debug(f"Error accessing parts: {str(e)}")
            
            # Check finish reason for logging/debugging
            if finish_reason:
                # Convert to int if it's an enum
                if hasattr(finish_reason, 'value'):
                    finish_reason_value = finish_reason.value
                elif isinstance(finish_reason, str):
                    finish_reason_map = {
                        'STOP': 1,
                        'MAX_TOKENS': 2,
                        'SAFETY': 3,
                        'RECITATION': 4,
                        'OTHER': 5
                    }
                    finish_reason_value = finish_reason_map.get(finish_reason.upper(), 5)
                elif isinstance(finish_reason, int):
                    finish_reason_value = finish_reason
                
                # Log finish reason for debugging
                if finish_reason_value == 3:  # SAFETY
                    logger.warning(f"⚠️ Gemini response blocked by safety filters for: {business_name}")
                elif finish_reason_value == 4:  # RECITATION
                    logger.warning(f"⚠️ Gemini response blocked by recitation filter for: {business_name}")
                elif finish_reason_value == 2:  # MAX_TOKENS
                    # MAX_TOKENS with no parts usually means input token limit exceeded
                    logger.warning(f"⚠️ Gemini hit MAX_TOKENS limit (finish_reason=2) for: {business_name} - falling back to keyword matching")
            
            # If we couldn't extract text, return None (will fall back to keyword matching)
            if not ai_code:
                logger.debug(f"Could not extract text from Gemini response for: {business_name} (finish_reason: {finish_reason_value})")
                return None
            
            # Extract code from response
            code_match = re.search(r'(\d{2,6})', ai_code)
            if code_match:
                code = code_match.group(1)
                
                # Verify code exists in our data
                if code in self.naics_data:
                    result = {
                        'NAICS Code': code,
                        'NAICS Description': self.naics_data[code]['title'],
                        'NAICS Confidence': '0.95',  # High confidence for AI
                        'classification_method': 'Gemini AI'
                    }
                    
                    # Cache the result
                    self.ai_cache[cache_key] = result
                    self._save_cache()
                    
                    logger.info(f"🤖 Gemini classified '{business_name}' as NAICS {code} ({self.naics_data[code]['title']})")
                    return result
            
            # If Gemini returned "NONE" or invalid code, return None
            logger.debug(f"Gemini returned no valid code for: {business_name} (response: {ai_code[:50]}...)")
            return None
            
        except Exception as e:
            logger.warning(f"Gemini classification error for '{business_name}': {str(e)}")
            return None
    
    def _get_top_candidates(self, business_name: str, business_type: Optional[str], top_n: int = 20) -> List[Dict]:
        """Get top NAICS candidates using keyword matching (for Gemini prompt)"""
        search_text = f"{business_name} {business_type or ''}".strip()
        keywords = self._extract_keywords(search_text)
        
        if not keywords:
            return []
        
        scores = []
        for code, info in self.naics_data.items():
            title = self._normalize_text(info.get('title', ''))
            description = self._normalize_text(info.get('description', ''))
            
            score = 0.0
            for keyword in keywords:
                if keyword in title:
                    score += 0.5
                elif keyword in description:
                    score += 0.2
            
            if score > 0:
                scores.append({
                    'code': code,
                    'title': info.get('title', ''),
                    'score': score
                })
        
        scores.sort(key=lambda x: (x['score'], len(x['code'])), reverse=True)
        return scores[:top_n]
    
    def classify(
        self,
        business_name: str,
        business_type: Optional[str] = None,
        existing_naics: Optional[str] = None,
        business_description: Optional[str] = None,
        min_confidence: float = 0.50,
        use_ai_first: bool = True
    ) -> Optional[Dict[str, str]]:
        """
        Classify NAICS code using Gemini AI with keyword fallback
        
        Args:
            business_name: Name of the business
            business_type: Optional business type (LLC, Corp, etc.)
            existing_naics: Existing NAICS code (if any)
            business_description: Additional business description/context
            min_confidence: Minimum confidence threshold for keyword matching
            use_ai_first: Try AI first, then fall back to keywords
            
        Returns:
            Dictionary with NAICS classification or None
        """
        # If NAICS already exists, return it
        if existing_naics and str(existing_naics).strip():
            existing_code = str(existing_naics).strip()
            code_match = re.search(r'(\d{2,6})', existing_code)
            if code_match:
                existing_code = code_match.group(1)
                return {
                    'NAICS Code': existing_code,
                    'NAICS Description': 'From Georgia SOS Website',
                    'NAICS Confidence': '1.0',
                    'classification_method': 'website'
                }
        
        # Try Gemini AI first if enabled
        if use_ai_first and self.use_ai:
            gemini_result = self._classify_with_gemini(
                business_name=business_name,
                business_type=business_type,
                business_description=business_description
            )
            if gemini_result:
                return gemini_result
        
        # Fall back to keyword matching
        keyword_result = super().classify(
            business_name=business_name,
            business_type=business_type,
            existing_naics=existing_naics,
            min_confidence=min_confidence
        )
        
        if keyword_result:
            keyword_result['classification_method'] = 'keyword'
            return keyword_result
        
        return None


def enrich_naics_codes_ai(
    df: pd.DataFrame,
    excel_file_path: str = "2022-NAICS-Codes-listed-numerically-2-Digit-through-6-Digit.xlsx",
    use_ai: bool = True,
    gemini_model: str = "gemini-2.5-flash",
    min_confidence: float = 0.50,
    api_delay: float = 1.0,
    save_progress_every: int = 50,
    output_file_path: Optional[str] = None
) -> pd.DataFrame:
    """
    Enrich DataFrame with NAICS codes using Gemini AI-enhanced classification
    
    Args:
        df: DataFrame with business data
        excel_file_path: Path to NAICS Excel file (for classification data)
        use_ai: Whether to use Gemini AI
        gemini_model: Gemini model to use ("gemini-1.5-flash" or "gemini-1.5-pro")
        min_confidence: Minimum confidence for keyword fallback
        api_delay: Delay in seconds between API calls (for rate limiting, default: 1.0)
        save_progress_every: Save progress every N classifications (default: 50)
        output_file_path: Optional path to save progress (if None, progress won't be saved to disk)
        
    Returns:
        DataFrame with enriched NAICS codes (has both 'NAICS Code' and 'NAICS Title' columns)
    """
    if df.empty:
        return df
    
    if 'Business Name' not in df.columns:
        logger.error("DataFrame must have 'Business Name' column")
        return df
    
    # Handle column renaming: If "NAICS Code" contains text (titles), rename it to "NAICS Title"
    if 'NAICS Code' in df.columns:
        # Check if the column contains mostly text (not numeric codes)
        sample_values = df['NAICS Code'].dropna().head(20)
        has_numeric_codes = False
        if len(sample_values) > 0:
            # Check if any value is a numeric code (2-6 digits, exact match)
            for val in sample_values:
                val_str = str(val).strip()
                if re.match(r'^\d{2,6}$', val_str):  # Exact match for numeric code
                    has_numeric_codes = True
                    break
        
        # If column has text descriptions but no numeric codes, rename it to NAICS Title
        if not has_numeric_codes and 'NAICS Title' not in df.columns:
            logger.info("📝 Renaming 'NAICS Code' column to 'NAICS Title' (contains descriptions, not numeric codes)")
            df['NAICS Title'] = df['NAICS Code']
            df = df.drop(columns=['NAICS Code'])
            # Create new empty NAICS Code column for numeric codes
            df['NAICS Code'] = ''
        elif has_numeric_codes and 'NAICS Title' not in df.columns:
            # Has numeric codes, create NAICS Title column if it doesn't exist
            df['NAICS Title'] = ''
    
    # Ensure both columns exist
    if 'NAICS Code' not in df.columns:
        df['NAICS Code'] = ''  # For numeric codes (e.g., "561730")
    if 'NAICS Title' not in df.columns:
        df['NAICS Title'] = ''  # For titles/descriptions (e.g., "Landscaping Services")
    
    # Add additional columns if they don't exist (for backward compatibility)
    if 'NAICS Description' not in df.columns:
        df['NAICS Description'] = ''  # Keep for backward compatibility
    if 'NAICS Confidence' not in df.columns:
        df['NAICS Confidence'] = ''
    if 'NAICS Classification Method' not in df.columns:
        df['NAICS Classification Method'] = ''
    
    try:
        classifier = GeminiNAICSClassifier(
            excel_file_path=excel_file_path,
            use_ai=use_ai,
            gemini_model=gemini_model
        )
    except Exception as e:
        logger.error(f"❌ Failed to initialize Gemini classifier: {str(e)}")
        return df
    
    # Find rows without valid NAICS codes
    # A valid NAICS code should be a numeric string with 2-6 digits (exact match)
    def has_valid_naics_code(naics_value):
        """Check if a NAICS code value is a valid numeric code"""
        if pd.isna(naics_value):
            return False
        naics_str = str(naics_value).strip()
        if naics_str == '' or naics_str.lower() == 'nan':
            return False
        # Check if it's a valid numeric NAICS code (2-6 digits, exact match)
        if re.match(r'^\d{2,6}$', naics_str):
            return True
        return False
    
    # Create mask for missing/invalid NAICS codes
    # We ONLY classify businesses that don't have a valid numeric NAICS code from the website
    # If a business already has a valid numeric code, we preserve it (don't update)
    missing_naics = ~df['NAICS Code'].apply(has_valid_naics_code)
    missing_count = missing_naics.sum()
    existing_count = (~missing_naics).sum()
    
    if missing_count == 0:
        logger.info(f"✅ All {len(df)} businesses already have valid NAICS codes")
        return df
    
    logger.info(f"📊 NAICS Code Status:")
    logger.info(f"   ✅ Businesses with existing numeric NAICS codes: {existing_count}")
    logger.info(f"   ❌ Businesses missing numeric NAICS codes: {missing_count}")
    logger.info(f"🔍 Classifying {missing_count} businesses using Gemini AI-enhanced classification...")
    logger.info(f"   📝 Will populate both 'NAICS Code' (numeric) and 'NAICS Title' (description) columns")
    if use_ai:
        logger.info(f"   ⏱️  API rate limiting: {api_delay}s delay between calls")
    
    enriched_count = 0
    ai_count = 0
    keyword_count = 0
    skipped_count = 0
    
    # Track API call times for rate limiting
    last_api_call_time = 0.0
    
    for idx in df[missing_naics].index:
        business_name = str(df.at[idx, 'Business Name'])
        
        # Double-check: Skip if somehow got a valid numeric code (shouldn't happen, but safety check)
        existing_naics_code = df.at[idx, 'NAICS Code']
        if has_valid_naics_code(existing_naics_code):
            skipped_count += 1
            logger.debug(f"Skipping {business_name} - already has NAICS code: {existing_naics_code}")
            continue
        
        # Get existing NAICS title if any (might have description but no code)
        existing_naics_title = df.at[idx, 'NAICS Title'] if 'NAICS Title' in df.columns else ''
        
        # IMPORTANT: We only process businesses WITHOUT valid numeric codes from the website
        # If a business already has a valid numeric NAICS code, it was skipped in the mask above
        # This ensures we preserve all existing website data - we only add codes where missing
        
        business_type = (
            str(df.at[idx, 'Business Type']) 
            if 'Business Type' in df.columns and pd.notna(df.at[idx, 'Business Type'])
            else None
        )
        business_description = (
            str(df.at[idx, 'Description']) 
            if 'Description' in df.columns and pd.notna(df.at[idx, 'Description'])
            else None
        )
        
        # Rate limiting: Ensure minimum delay between API calls
        if use_ai and api_delay > 0:
            current_time = time.time()
            time_since_last_call = current_time - last_api_call_time
            if time_since_last_call < api_delay:
                sleep_time = api_delay - time_since_last_call
                logger.debug(f"Rate limiting: waiting {sleep_time:.2f}s before next API call")
                time.sleep(sleep_time)
        
        classification = classifier.classify(
            business_name=business_name,
            business_type=business_type,
            business_description=business_description,
            existing_naics=None,  # Explicitly None since we know it's missing
            min_confidence=min_confidence
        )
        
        # Update last API call time if AI was used
        if use_ai and classification and classification.get('classification_method') == 'Gemini AI':
            last_api_call_time = time.time()
        
        if classification:
            # Add the numeric code we classified
            df.at[idx, 'NAICS Code'] = classification['NAICS Code']
            
            # Preserve original title if it's meaningful, otherwise use our classification
            # Check if existing title is meaningful (not generic)
            generic_titles = ['unknown', 'any legal purpose', '', 'nan']
            is_generic_title = False
            if pd.notna(existing_naics_title) and isinstance(existing_naics_title, str):
                title_lower = existing_naics_title.strip().lower()
                is_generic_title = (title_lower in generic_titles or 
                                   len(existing_naics_title.strip()) <= 5)
            
            if not is_generic_title and pd.notna(existing_naics_title) and isinstance(existing_naics_title, str) and existing_naics_title.strip():
                # Keep the original meaningful title from website, just add the numeric code
                df.at[idx, 'NAICS Title'] = existing_naics_title.strip()
                logger.debug(f"   Preserved original NAICS title: '{existing_naics_title.strip()}' (added code: {classification['NAICS Code']})")
            else:
                # Original title was generic or missing, use our classification
                df.at[idx, 'NAICS Title'] = classification['NAICS Description']
                if is_generic_title:
                    logger.debug(f"   Replaced generic title '{existing_naics_title}' with: '{classification['NAICS Description']}'")
            
            df.at[idx, 'NAICS Description'] = df.at[idx, 'NAICS Title']  # Keep for backward compatibility
            df.at[idx, 'NAICS Confidence'] = classification['NAICS Confidence']
            df.at[idx, 'NAICS Classification Method'] = classification.get('classification_method', 'unknown')
            
            enriched_count += 1
            if classification.get('classification_method') == 'Gemini AI':
                ai_count += 1
            elif classification.get('classification_method') == 'keyword':
                keyword_count += 1
            
            # Progress logging
            if enriched_count % 10 == 0:
                logger.info(f"   Progress: {enriched_count}/{missing_count} classified ({enriched_count*100/missing_count:.1f}%)")
            
            # Save progress periodically
            if save_progress_every > 0 and enriched_count % save_progress_every == 0:
                if output_file_path:
                    try:
                        df.to_excel(output_file_path, index=False, engine='openpyxl')
                        logger.info(f"   💾 Progress saved to: {output_file_path} ({enriched_count} businesses classified)")
                    except Exception as e:
                        logger.warning(f"   ⚠️  Could not save progress: {str(e)}")
                else:
                    logger.info(f"   ⏸️  Progress checkpoint: {enriched_count} businesses classified")
    
    logger.info(f"✅ Enrichment complete!")
    logger.info(f"   Total processed: {missing_count}")
    logger.info(f"   Successfully classified: {enriched_count}")
    logger.info(f"     - Gemini AI classifications: {ai_count}")
    logger.info(f"     - Keyword classifications: {keyword_count}")
    logger.info(f"   Skipped (already had codes): {skipped_count}")
    logger.info(f"   Remaining without NAICS: {missing_count - enriched_count - skipped_count}")
    
    return df

