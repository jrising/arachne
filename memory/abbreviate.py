import re
from collections import Counter

# A basic list of English stopwords to remove
STOPWORDS = set([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", 
    "is", "was", "were", "be", "been", "this", "that", "these", "those", "i", 
    "you", "he", "she", "it", "they", "we", "my", "your", "his", "her", "their"
])

def extract_keywords(text: str, max_keywords: int = 20) -> str:
    # 1. Lowercase and find all words
    words = re.findall(r'\b\w+\b', text.lower())
    
    # 2. Filter out stopwords and short/numeric words
    filtered_words = [w for w in words if w not in STOPWORDS and len(w) > 2 and not w.isdigit()]
    
    # 3. Count frequencies and take the top unique keywords
    most_common = Counter(filtered_words).most_common(max_keywords)
    
    # 4. Join back into a clean query string
    return " ".join([word for word, count in most_common])
