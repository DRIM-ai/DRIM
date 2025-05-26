# File: app/tool/search/google_scraper_search.py
from googlesearch import search as Google_Search_scrape
from typing import List, Dict, Any, Optional, Union # DRIM_AI_MODIFICATION: Added Union
import asyncio

from app.tool.search.base import SearchItem, WebSearchEngine
from app.logger import logger

class GoogleScraperSearchEngine(WebSearchEngine):
    engine_name: str = "GoogleScraper"

    def __init__(self, **data: Any):
        super().__init__(**data)
        logger.info(
            f"{self.engine_name} initialized. "
            "This engine scrapes Google search results and should be used sparingly "
            "to avoid potential IP blocks or CAPTCHAs. "
            "It primarily returns URLs; titles and descriptions are generic."
        )

    async def perform_search(
        self,
        query: str,
        num_results: Union[int, float] = 10, # DRIM_AI_MODIFICATION: Allow float input
        **kwargs: Any
    ) -> List[SearchItem]:
        num_results_int: int
        try:
            num_results_int = int(float(num_results)) # Robustly convert to int
            if num_results_int <= 0:
                num_results_int = 10 # Default if invalid
        except ValueError:
            logger.warning(f"{self.engine_name}: Invalid num_results '{num_results}', defaulting to 10.")
            num_results_int = 10
        
        logger.info(f"{self.engine_name}: Performing search for '{query}' for {num_results_int} results.")
        search_items: List[SearchItem] = []
        try:
            loop = asyncio.get_event_loop()
            
            lang_code = kwargs.get("lang", "en")

            def sync_search_operation():
                results = []
                processed_urls_count = 0
                max_urls_to_process = num_results_int * 3 

                try:
                    for url_result in Google_Search_scrape(
                        query,
                        lang=lang_code,
                        num_results=num_results_int, # Use the integer version
                    ):
                        processed_urls_count += 1
                        if isinstance(url_result, str) and \
                           (url_result.startswith("http://") or url_result.startswith("https://")):
                            results.append(
                                SearchItem(
                                    title=f"Search result for: {query}", 
                                    url=url_result,
                                    description="Content summary not available via this scraper. Visit URL for details."
                                )
                            )
                            if len(results) >= num_results_int:
                                break
                        else:
                            logger.warning(f"{self.engine_name}: Discarding invalid or relative URL: '{url_result}' for query '{query}'")
                        
                        if processed_urls_count >= max_urls_to_process and len(results) < num_results_int:
                            logger.warning(f"{self.engine_name}: Processed {max_urls_to_process} URLs but found less than {num_results_int} valid ones for '{query}'. Stopping to avoid excessive scraping.")
                            break
                                
                except TypeError as te: # Specifically catch TypeError for slice issues
                    logger.error(f"{self.engine_name}: TypeError during googlesearch iteration (possibly due to num_results type issue within the library for query '{query}'): {te}")
                    # Return empty list or re-raise depending on how critical this is
                    return [] 
                except Exception as e:
                    logger.error(f"{self.engine_name}: Error during search iteration for '{query}': {e}")
                return results

            search_items = await loop.run_in_executor(None, sync_search_operation)

            if not search_items:
                logger.warning(f"{self.engine_name}: No valid, absolute URLs returned for '{query}'. This might be due to rate limiting, CAPTCHA, or network issues.")

        except Exception as e:
            logger.error(f"{self.engine_name}: Unexpected error performing search for '{query}': {e}")
        
        return search_items[:num_results_int] # Ensure final slice uses int