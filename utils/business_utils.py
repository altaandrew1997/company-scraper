import re

def normalize_business_name(name: str) -> str:
    """
    Normalize business name for searching and storage:
    1. Remove all non-alphanumeric characters (keep spaces)
    2. Convert to Title Case
    3. Preserve uppercase for common company suffixes (LLC, INC, etc.)
    4. Trim and normalize whitespace
    """
    if not name:
        return ""
        
    # Remove all symbols (keep only letters, numbers, and spaces)
    # This also removes things like #, &, ,, .
    name = re.sub(r'[^a-zA-Z0-9\s]', ' ', name)
    
    # Normalize whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Convert to Title Case (e.g., "BIG BREEZE" -> "Big Breeze")
    name = name.title()
    
    # Preserve uppercase for common suffixes (convert "Llc" back to "LLC", etc.)
    # We use regex with word boundaries to ensure we only target the suffixes
    name = re.sub(r'\bLlc\b', 'LLC', name)
    name = re.sub(r'\bInc\b', 'INC', name)
    name = re.sub(r'\bCorp\b', 'CORP', name)
    name = re.sub(r'\bLtd\b', 'LTD', name)
    
    return name.strip()
