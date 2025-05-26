from app.tool.search.base import WebSearchEngine, SearchItem 
# Corrected import for GoogleCustomSearchEngine assuming the file is renamed
from app.tool.search.google_custom_search import GoogleCustomSearchEngine 
from app.tool.search.google_scraper_search import GoogleScraperSearchEngine 

__all__ = [ 
    "WebSearchEngine",
    "SearchItem", 
    "GoogleCustomSearchEngine",
    "GoogleScraperSearchEngine", 
]

# Role in the System (Updated for DRIM AI)
# This search-related tool enables DRIM AI to find information on the web,
# a critical capability for knowledge-intensive tasks. It provides interfaces
# to configured search engines like Google Custom Search and a Google scraping fallback.