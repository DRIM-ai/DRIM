from typing import List, Optional, Any # [Source: 678]
from pydantic import BaseModel, Field, ConfigDict # [Source: 678]

class SearchItem(BaseModel): # [Source: 678]
    """Represents a single search result item"""
    title: str = Field(description="The title of the search result") # [Source: 678]
    url: str = Field(description="The URL of the search result") # [Source: 678]
    description: Optional[str] = Field(
        default=None, description="A description or snippet of the search result" # [Source: 678]
    )
    # Add any other common fields you might get from Brave or Google CSE, e.g., displayUrl

    model_config = ConfigDict(extra="allow") # Allow extra fields if APIs return more

    def __str__(self) -> str: # [Source: 678]
        """String representation of a search result item."""
        return f"{self.title} - {self.url}"

class WebSearchEngine(BaseModel): # [Source: 678]
    """Base class for web search engines."""
    model_config = ConfigDict(arbitrary_types_allowed=True) # [Source: 678]

    engine_name: str = "Unknown"

    async def perform_search( # Changed to async as API calls will be I/O bound
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any # For engine-specific params like lang, country, etc. [Source: 681]
    ) -> List[SearchItem]:
        """
        Perform a web search and return a list of search items.
        Args:
            query (str): The search query to submit to the search engine. [Source: 680]
            num_results (int, optional): The number of search results to return. Default is 10. [Source: 681]
            kwargs: Additional keyword arguments specific to the search engine (e.g., lang, country).
        Returns:
            List[SearchItem]: A list of SearchItem objects matching the search query. [Source: 682]
        """
        raise NotImplementedError # [Source: 683]

# Role in the System (Updated for DRIM AI)
# As part of the tool subsystem, this script provides the foundational structures
# for web search capabilities within DRIM AI. [Source: 678] It ensures consistency
# across different search engine implementations.