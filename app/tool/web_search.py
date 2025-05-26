import asyncio
from typing import Any, Dict, List, Optional, Union 
import httpx 

from bs4 import BeautifulSoup 
from pydantic import BaseModel, ConfigDict, Field, model_validator 
from tenacity import retry, stop_after_attempt, wait_exponential 

from app.config import config as app_main_config 
from app.logger import logger 
from app.tool.base import BaseTool, ToolResult 
from app.tool.search import ( 
    GoogleCustomSearchEngine,
    GoogleScraperSearchEngine, 
    WebSearchEngine,
    SearchItem, 
)

class SearchResult(BaseModel): 
    model_config = ConfigDict(arbitrary_types_allowed=True)
    position: int = Field(description="Position in search results") 
    url: str = Field(description="URL of the search result") 
    title: str = Field(default="", description="Title of the search result") 
    description: Optional[str] = Field(default="", description="Description or snippet") 
    source: str = Field(description="The search engine that provided this result") 
    raw_content: Optional[str] = Field(default=None, description="Raw content from the page if fetched") 

    def __str__(self) -> str: 
        return f"{self.position}. {self.title} ({self.url}) - Source: {self.source}"

class SearchMetadata(BaseModel): 
    model_config = ConfigDict(arbitrary_types_allowed=True)
    query_used: str = Field(description="The actual query performed")
    total_results_returned: int = Field(description="Number of results returned in this response") 
    language: Optional[str] = Field(None, description="Language code used for the search") 
    country: Optional[str] = Field(None, description="Country code used for the search") 

class WebSearchResponse(ToolResult): 
    query: str = Field(description="The original search query provided by the agent") 
    results: List[SearchResult] = Field(default_factory=list, description="List of search results") 
    metadata: Optional[SearchMetadata] = Field(default=None, description="Metadata about the search operation") 

    @model_validator(mode="after")
    def populate_output_field(self) -> "WebSearchResponse": 
        if self.error: 
            self.output = self.error
            return self
        
        if not self.results:
            self.output = f"No search results found for query: '{self.query}'."
            if self.metadata:
                 self.output += f" (Query performed: {self.metadata.query_used if self.metadata else 'N/A'})" 
            return self

        result_texts = [f"Search results for '{self.query}':"]
        for res_item in self.results: 
            result_texts.append(f"\n{res_item.position}. {res_item.title or 'No Title'}")
            result_texts.append(f"   URL: {res_item.url}") 
            if res_item.description:
                result_texts.append(f"   Description: {res_item.description.strip()}") 
            if res_item.raw_content: 
                content_preview = res_item.raw_content[:300].replace("\n", " ").strip() 
                if len(res_item.raw_content) > 300: content_preview += "..."
                result_texts.append(f"   Content Preview: {content_preview}")
            result_texts.append(f"   Source Engine: {res_item.source}")
        
        if self.metadata: 
            result_texts.append("\nSearch Metadata:")
            result_texts.append(f"- Query Performed: {self.metadata.query_used}")
            result_texts.append(f"- Results in this response: {self.metadata.total_results_returned}")
            if self.metadata.language: result_texts.append(f"- Language: {self.metadata.language}")
            if self.metadata.country: result_texts.append(f"- Country: {self.metadata.country}")
        
        self.output = "\n".join(result_texts) 
        return self

class WebContentFetcher: 
    @staticmethod
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def fetch_content(url: str, timeout: int = 10) -> Optional[str]: 
        headers = { 
            "User-Agent": "DRIM-AI-Agent/1.0 (WebScraper; +https://github.com/your-repo)", 
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                response = await client.get(url, headers=headers)
            response.raise_for_status() 

            soup = BeautifulSoup(response.text, "html.parser") 
            
            for SCRIPTORSTYLE in soup(["script", "style", "header", "footer", "nav", "aside"]): 
                SCRIPTORSTYLE.extract()
            
            text_content = soup.get_text(separator="\n", strip=True) 
            text_content = " ".join(text_content.split()) 
            
            return text_content[:10000] if text_content else None 
        except Exception as e:
            logger.warning(f"Error fetching content from {url}: {e}") 
            return None

class WebSearch(BaseTool): 
    name: str = "web_search" 
    description: str = """Performs a web search using configured search engines (DRIM AI: Google API, GoogleScraper).
This tool returns a list of search results including titles, URLs, snippets, and optionally, fetched page content.
It will try the primary engine first, then fall back to another if the primary fails.""" 
    
    parameters: Dict[str, Any] = { 
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "(Required) The search query."}, 
            "num_results": {"type": "integer", "description": "(Optional) Number of results per engine. Default: 3-5.", "default": 5}, 
            "lang": {"type": "string", "description": "(Optional) Language code (e.g., 'en', 'de')."}, 
            "country": {"type": "string", "description": "(Optional) Country code (e.g., 'US', 'GB')."}, 
            "fetch_content": {"type": "boolean", "description": "(Optional) Fetch content from result URLs. Default: False.", "default": False}, 
        },
        "required": ["query"],
    }

    _search_engines: Dict[str, WebSearchEngine]
    _engine_order: List[str]
    _content_fetcher: WebContentFetcher

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._search_engines = {}
        
        # --- TEMPORARY DEBUG LOGGING START ---
        print(f"DEBUG [web_search.py]: app_main_config.search.google_api_key = '{app_main_config.search.google_api_key}'")
        print(f"DEBUG [web_search.py]: app_main_config.search.google_cse_id = '{app_main_config.search.google_cse_id}'")
        print(f"DEBUG [web_search.py]: app_main_config.search.fallback_google_api_key = '{app_main_config.search.fallback_google_api_key}'")
        print(f"DEBUG [web_search.py]: app_main_config.search.fallback_google_cse_id = '{app_main_config.search.fallback_google_cse_id}'")
        # --- TEMPORARY DEBUG LOGGING END ---

        if app_main_config.search.google_api_key and app_main_config.search.google_cse_id:
            self._search_engines["Google"] = GoogleCustomSearchEngine(use_fallback=False)
            print("DEBUG [web_search.py]: Initialized GoogleCustomSearchEngine (Primary)") 
        else:
            print(f"DEBUG [web_search.py]: NOT Initializing GoogleCustomSearchEngine (Primary due to missing key/id).")
        
        if app_main_config.search.fallback_google_api_key and app_main_config.search.fallback_google_cse_id:
            # Add fallback only if it's distinct or primary Google API is not set
            if not self._search_engines.get("Google") or \
               (app_main_config.search.google_api_key != app_main_config.search.fallback_google_api_key or \
                app_main_config.search.google_cse_id != app_main_config.search.fallback_google_cse_id):
                
                # If primary Google is not set, use fallback as "Google"
                if not self._search_engines.get("Google"):
                    self._search_engines["Google"] = GoogleCustomSearchEngine(use_fallback=True)
                    print("DEBUG [web_search.py]: Initialized GoogleCustomSearchEngine (using Fallback config as 'Google')")
                # Else, if primary is set and fallback is different, add it as "Google_Fallback"
                elif self._search_engines.get("Google") and not getattr(self._search_engines["Google"], 'is_fallback_config', False): # Check if primary is already fallback
                    self._search_engines["Google_Fallback"] = GoogleCustomSearchEngine(use_fallback=True)
                    print("DEBUG [web_search.py]: Initialized GoogleCustomSearchEngine (as 'Google_Fallback')")
        else:
            print(f"DEBUG [web_search.py]: Fallback Google API Key/CSE ID not configured or primary already uses it.")


        self._search_engines["GoogleScraper"] = GoogleScraperSearchEngine()
        print("DEBUG [web_search.py]: Initialized GoogleScraperSearchEngine") 

        self._engine_order = self._get_engine_order()
        self._content_fetcher = WebContentFetcher()
        if not self._search_engines: 
            logger.error("DRIM AI WebSearch: No search engines configured correctly. Web search will fail.")
        print(f"DEBUG [web_search.py]: ToolCollection _search_engines keys: {list(self._search_engines.keys())}")


    def _get_engine_order(self) -> List[str]: 
        order: List[str] = []
        primary_conf = app_main_config.search.primary_engine 
        fallback_conf = app_main_config.search.fallback_engine 

        print(f"DEBUG [web_search.py/_get_engine_order]: Configured primary: {primary_conf}, fallback: {fallback_conf}")
        print(f"DEBUG [web_search.py/_get_engine_order]: Available engines in _search_engines: {list(self._search_engines.keys())}")

        if primary_conf and primary_conf in self._search_engines:
            order.append(primary_conf)
            print(f"DEBUG [web_search.py/_get_engine_order]: Added primary '{primary_conf}' to order.")
        
        # Ensure Google_Fallback is considered if available and different from primary
        if "Google_Fallback" in self._search_engines and "Google_Fallback" not in order:
            # If primary_conf is "Google" and "Google_Fallback" exists, it should be the fallback
            # Or if fallback_conf is "Google_Fallback"
            if fallback_conf == "Google_Fallback" or (primary_conf == "Google" and fallback_conf != "Google_Fallback"):
                 if "Google_Fallback" not in order : order.append("Google_Fallback")
                 print(f"DEBUG [web_search.py/_get_engine_order]: Added 'Google_Fallback' to order based on fallback_conf or distinctness.")


        if fallback_conf and fallback_conf in self._search_engines and fallback_conf not in order:
            order.append(fallback_conf)
            print(f"DEBUG [web_search.py/_get_engine_order]: Added configured fallback '{fallback_conf}' to order.")
        
        for engine_name in self._search_engines.keys():
            if engine_name not in order:
                order.append(engine_name)
                print(f"DEBUG [web_search.py/_get_engine_order]: Added other available engine '{engine_name}' to order.")
        
        if not order and self._search_engines: 
             order = list(self._search_engines.keys())
             print(f"DEBUG [web_search.py/_get_engine_order]: No specific order, using available: {order}")
        elif not self._search_engines:
            print(f"DEBUG [web_search.py/_get_engine_order]: No engines available at all.")


        logger.info(f"DRIM AI WebSearch engine order: {order}")
        return order

    async def _perform_search_with_engine_retry( 
        self, engine: WebSearchEngine, query: str, num_results: int, search_params: Dict[str, Any]
    ) -> List[SearchItem]:
        max_retries = app_main_config.search.max_retries if app_main_config.search.max_retries is not None else 1
        retry_delay_base = (app_main_config.search.retry_delay if app_main_config.search.retry_delay is not None else 60)
        
        for attempt in range(max_retries):
            try:
                return await engine.perform_search(query, num_results=num_results, **search_params)
            except Exception as e:
                logger.warning(f"Engine {engine.engine_name} attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt + 1 == max_retries:
                    logger.error(f"Engine {engine.engine_name} failed after all retries for query: {query}")
                    return [] 
                # Use a shorter, fixed delay for inter-engine retries, not exponential backoff for the *same* engine within one _perform_search_with_engine_retry call
                await asyncio.sleep(max(1, retry_delay_base // 10)) # e.g. 6s if retry_delay is 60s
        return []

    async def execute( 
        self,
        query: str,
        num_results: int = 5,
        lang: Optional[str] = None,
        country: Optional[str] = None,
        fetch_content: bool = False,
    ) -> WebSearchResponse:
        if not self._engine_order and not self._search_engines: 
            logger.error("DRIM AI WebSearch: No search engines available to perform search.")
            return WebSearchResponse(query=query, error="No search engines configured or available.")
        
        current_engine_order = self._engine_order
        if not current_engine_order and self._search_engines:
            current_engine_order = self._get_engine_order() # Try to get order again if it was empty
            logger.warning(f"DRIM AI WebSearch: Engine order was empty, re-evaluated to: {current_engine_order}")
        if not current_engine_order: 
            logger.error("DRIM AI WebSearch: No search engines available after trying to determine order.")
            return WebSearchResponse(query=query, error="No search engines available.")

        search_params = {}
        if lang: search_params["lang"] = lang
        if country: search_params["country"] = country 
        
        all_search_items: List[SearchItem] = []
        final_engine_used = "None"
        # Use a potentially longer overall retry delay for trying *different* engines after one fails completely
        overall_retry_delay = app_main_config.search.retry_delay if app_main_config.search.retry_delay is not None else 60


        for engine_name in current_engine_order: 
            engine = self._search_engines.get(engine_name)
            if not engine: 
                logger.warning(f"DRIM AI WebSearch: Configured engine '{engine_name}' not found in loaded engines.")
                continue
            
            # Check if the engine is GoogleCustomSearchEngine and if it's properly configured
            if isinstance(engine, GoogleCustomSearchEngine):
                if not engine.api_key or not engine.cse_id:
                    logger.warning(f"DRIM AI WebSearch: Skipping {engine.engine_name} because API key or CSE ID is missing.")
                    continue

            logger.info(f"DRIM AI WebSearch: Attempting search with {engine.engine_name} for query: '{query}'")
            specific_params_for_engine = {}
            if lang: specific_params_for_engine["lang"] = lang
            if country: specific_params_for_engine["country"] = country 

            current_engine_items = await self._perform_search_with_engine_retry(
                engine, query, num_results, specific_params_for_engine 
            )
            if current_engine_items:
                all_search_items = current_engine_items 
                final_engine_used = engine.engine_name
                logger.info(f"DRIM AI WebSearch: Successfully found {len(all_search_items)} results with {engine.engine_name}.")
                break 
            else:
                logger.warning(f"DRIM AI WebSearch: Engine {engine.engine_name} returned no results for '{query}'. Trying next engine if available after delay.")
                if engine_name != current_engine_order[-1]: # If not the last engine
                    await asyncio.sleep(overall_retry_delay // len(current_engine_order) if len(current_engine_order) > 0 else overall_retry_delay)


        if not all_search_items:
            logger.error(f"DRIM AI WebSearch: All configured search engines failed to return results for query: '{query}'.")
            return WebSearchResponse(query=query, error="All search engines failed to return results.", results=[])

        structured_results: List[SearchResult] = []
        for i, item in enumerate(all_search_items):
            search_res = SearchResult(
                position=i + 1,
                url=item.url,
                title=item.title or f"Result {i+1}",
                description=item.description or "",
                source=final_engine_used, 
                raw_content=None
            )
            if fetch_content and item.url: 
                logger.debug(f"Fetching content for URL: {item.url}")
                search_res.raw_content = await self._content_fetcher.fetch_content(item.url)
            structured_results.append(search_res)
            if len(structured_results) >= num_results : 
                break

        return WebSearchResponse( 
            query=query,
            results=structured_results,
            metadata=SearchMetadata(
                query_used=query, 
                total_results_returned=len(structured_results),
                language=lang,
                country=country,
            )
        )

async def main_test(): 
    logger.info("Testing DRIM AI WebSearch tool...")
    # Ensure .env has Google Search_API_KEY and GOOGLE_CSE_ID for this test to use Google Custom Search
    app_main_config.search.primary_engine = "Google" # Force Google for test if keys are there
    # app_main_config.search.fallback_engine = "GoogleScraper" # Keep scraper as fallback

    web_search_tool = WebSearch() # Re-initialize to pick up any config changes
    
    if not web_search_tool._engine_order or not web_search_tool._search_engines:
        logger.error("No search engines configured in WebSearch after re-init. Test cannot run effectively.")
        return

    test_query = "latest news on AI advancements May 2025"
    logger.info(f"Executing test query: '{test_query}' with engine order: {web_search_tool._engine_order}")
    
    response = await web_search_tool.execute(query=test_query, num_results=2, fetch_content=False, lang="en")
    
    if response.error:
        print(f"Error: {response.error}")
    elif response.output:
        print(response.output) 
    else:
        print("No output or error from WebSearch tool.")

if __name__ == "__main__": 
    from app.logger import define_log_level
    define_log_level(print_level="DEBUG") # Set to DEBUG to see more logs
    # Create a dummy .env if it doesn't exist for testing, or ensure your actual .env is loaded
    if not (PROJECT_ROOT / ".env").exists():
        with open(PROJECT_ROOT / ".env", "w") as f:
            f.write("# Google Search_API_KEY=YOUR_KEY_HERE\n")
            f.write("# GOOGLE_CSE_ID=YOUR_CSE_ID_HERE\n")
        print("Created a dummy .env file. Please populate it with API keys for full Google search testing.")
    
    asyncio.run(main_test())