import httpx 
from typing import List, Dict, Any, Optional

from app.tool.search.base import SearchItem, WebSearchEngine
from app.config import config as app_main_config 
from app.logger import logger
# from pydantic import Field # Not strictly needed here if api_key/cse_id use simple '= None'

class GoogleCustomSearchEngine(WebSearchEngine):
    engine_name: str = "GoogleCustomSearch"
    api_key: Optional[str] = None
    cse_id: Optional[str] = None
    # MODIFIED: Corrected base_url
    base_url: str = "www.googleapis.com/customsearch/v1" 

    def __init__(self, use_fallback: bool = False, **data: Any):
        super().__init__(**data) 
        if use_fallback:
            self.api_key = app_main_config.search.fallback_google_api_key
            self.cse_id = app_main_config.search.fallback_google_cse_id
            self.engine_name = "GoogleCustomSearch_Fallback"
        else:
            self.api_key = app_main_config.search.google_api_key
            self.cse_id = app_main_config.search.google_cse_id
        
        if not self.api_key or not self.cse_id:
            logger.warning(f"{self.engine_name} API key or CSE ID not configured (api_key: {'set' if self.api_key else 'None'}, cse_id: {'set' if self.cse_id else 'None'}). This engine may not be available.")

    async def perform_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any 
    ) -> List[SearchItem]:
        if not self.api_key or not self.cse_id:
            logger.error(f"{self.engine_name} API key or CSE ID is missing. Cannot perform search.")
            return []

        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(num_results, 10), 
        }
        if kwargs.get("lang"): params["hl"] = kwargs["lang"]
        if kwargs.get("country"): params["cr"] = "country" + kwargs["country"].upper() 

        try:
            # Ensure full_url includes https:// correctly
            full_url = f"https://{self.base_url}" 
            async with httpx.AsyncClient() as client:
                response = await client.get(full_url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            results: List[SearchItem] = []
            if "items" in data:
                for item in data["items"]:
                    results.append(
                        SearchItem(
                            title=item.get("title", "Google Search Result"),
                            url=item.get("link", ""),
                            description=item.get("snippet"),
                        )
                    )
                    if len(results) >= num_results:
                        break
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"{self.engine_name} API request failed with status {e.response.status_code}: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Error performing {self.engine_name} search for '{query}': {e}")
            return []