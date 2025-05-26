import json
import threading
import tomllib # Python 3.11+
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).resolve().parent.parent

PROJECT_ROOT = get_project_root()
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

class GeminiSettings(BaseModel):
    api_key: str = Field(..., description="Gemini API Key")
    primary_model: str = Field("models/gemini-2.5-flash-preview-05-20", description="Primary Gemini model name for complex tasks.")
    small_model: Optional[str] = Field("models/gemini-2.0-flash-001", description="More capable Gemini model, intended for reliable tool calling and other focused tasks.")
    multimodal_model: str = Field("models/gemini-2.0-flash", description="Gemini multimodal model name for vision tasks.")
    max_output_tokens: int = Field(8192, description="Maximum number of output tokens per request for Gemini.")
    temperature: float = Field(0.5, description="Sampling temperature for Gemini.") # Changed from 0.3 to 0.5 based on last log, or keep your preferred
    top_p: Optional[float] = Field(None, description="Top-p (nucleus) sampling for Gemini.")
    top_k: Optional[int] = Field(None, description="Top-k sampling for Gemini.")

    fallback_primary_model: Optional[str] = Field("models/gemini-2.5-flash-preview-04-17", description="Fallback for primary_model if rate limited.")
    fallback_small_model: Optional[str] = Field("models/gemini-2.0-flash-lite-001", description="Fallback for small_model if rate limited.")
    fallback_multimodal_model: Optional[str] = Field("models/gemini-2.0-flash", description="Fallback for multimodal_model if rate limited (or None if no direct fallback).")


class ProxySettings(BaseModel):
    server: Optional[str] = Field(None, description="Proxy server address")
    username: Optional[str] = Field(None, description="Proxy username")
    password: Optional[str] = Field(None, description="Proxy password")

class SearchSettings(BaseModel):
    google_api_key: Optional[str] = Field(None, description="Google Custom Search API Key")
    google_cse_id: Optional[str] = Field(None, description="Google Custom Search Engine ID")
    fallback_google_api_key: Optional[str] = Field(None, description="Fallback Google Custom Search API Key (if using a different one for fallback)")
    fallback_google_cse_id: Optional[str] = Field(None, description="Fallback Google Custom Search Engine ID (if using a different one for fallback)")
    primary_engine: str = Field(default="Google", description="Primary search engine (e.g., Google, GoogleScraper)")
    fallback_engine: Optional[str] = Field(default="GoogleScraper", description="Fallback search engine (e.g., GoogleScraper, Google)")
    num_results: int = Field(default=5, description="Default number of search results to fetch")
    retry_delay: int = Field(default=60, description="Seconds to wait before retrying all engines")
    max_retries: int = Field(default=3, description="Maximum number of times to retry all engines")

class BrowserSettings(BaseModel):
    headless: bool = Field(False, description="Whether to run browser in headless mode")
    disable_security: bool = Field(True, description="Disable browser security features (use with caution)")
    extra_chromium_args: List[str] = Field(default_factory=list, description="Extra arguments to pass to the browser")
    chrome_instance_path: Optional[str] = Field(None, description="Path to a Chrome instance to use")
    wss_url: Optional[str] = Field(None, description="Connect to a browser instance via WebSocket")
    cdp_url: Optional[str] = Field(None, description="Connect to a browser instance via CDP")
    proxy: Optional[ProxySettings] = Field(None, description="Proxy settings for the browser")
    max_content_length: int = Field(150000, description="Maximum length for content retrieval operations")

class SandboxSettings(BaseModel):
    use_sandbox: bool = Field(False, description="Whether to use the sandbox")
    image: str = Field("python:3.12-slim", description="Base image for sandbox")
    work_dir: str = Field("/workspace", description="Container working directory for sandbox")
    memory_limit: str = Field("512m", description="Memory limit for sandbox")
    cpu_limit: float = Field(1.0, description="CPU limit for sandbox")
    timeout: int = Field(300, description="Default command timeout (seconds) for sandbox")
    network_enabled: bool = Field(False, description="Whether network access is allowed in sandbox")

class MCPServerConfig(BaseModel):
    type: str = Field(..., description="Server connection type (sse or stdio)")
    url: Optional[str] = Field(None, description="Server URL for SSE connections")
    command: Optional[str] = Field(None, description="Command for stdio connections")
    args: List[str] = Field(default_factory=list, description="Arguments for stdio command")

class MCPSettings(BaseModel):
    server_reference: str = Field("app.mcp.server", description="Module reference for the MCP server")
    servers: Dict[str, MCPServerConfig] = Field(default_factory=dict, description="MCP server configurations")

    @classmethod
    def load_server_config_from_json(cls) -> Dict[str, MCPServerConfig]:
        config_path = PROJECT_ROOT / "config" / "mcp.json"
        try:
            config_file = config_path if config_path.exists() else None
            if not config_file: return {}
            with config_file.open() as f: data = json.load(f)
            servers = {}
            for server_id, sc_data in data.get("mcpServers", {}).items():
                servers[server_id] = MCPServerConfig(type=sc_data["type"], url=sc_data.get("url"), command=sc_data.get("command"), args=sc_data.get("args", []))
            return servers
        except Exception as e:
            print(f"Warning: Failed to load MCP server config from mcp.json: {e}")
            return {}

class AppConfig(BaseModel):
    gemini: GeminiSettings
    search: SearchSettings
    browser: Optional[BrowserSettings] = Field(default_factory=BrowserSettings)
    sandbox: Optional[SandboxSettings] = Field(default_factory=SandboxSettings)
    mcp: Optional[MCPSettings] = Field(default_factory=MCPSettings)

    class Config:
        arbitrary_types_allowed = True

class Config:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._app_config: Optional[AppConfig] = None
                    self._load_initial_config()
                    self._initialized = True
    
    @staticmethod
    def _get_config_path() -> Path:
        root = PROJECT_ROOT
        config_path = root / "config" / "drim_ai_config.toml"
        if config_path.exists():
            return config_path
        
        print(f"Configuration file {config_path} not found. Creating a default one.")
        
        gs_defaults_for_template = GeminiSettings(api_key="DUMMY_FOR_TEMPLATE")
        bs_defaults_for_template = BrowserSettings()

        default_config_content = f"""
[gemini]
primary_model = "{os.getenv("PRIMARY_MODEL", gs_defaults_for_template.primary_model)}"
small_model = "{os.getenv("SMALL_MODEL", gs_defaults_for_template.small_model)}" 
multimodal_model = "{os.getenv("MULTIMODAL_MODEL", gs_defaults_for_template.multimodal_model)}"
fallback_primary_model = "{os.getenv("FALLBACK_PRIMARY_MODEL", gs_defaults_for_template.fallback_primary_model)}"
fallback_small_model = "{os.getenv("FALLBACK_SMALL_MODEL", gs_defaults_for_template.fallback_small_model)}" 
fallback_multimodal_model = "{os.getenv("FALLBACK_MULTIMODAL_MODEL", gs_defaults_for_template.fallback_multimodal_model)}"
max_output_tokens = {gs_defaults_for_template.max_output_tokens}
temperature = {gs_defaults_for_template.temperature}

[search]
primary_engine = "Google" 
fallback_engine = "GoogleScraper" 
num_results = 5

[browser]
headless = {str(bs_defaults_for_template.headless).lower()}
disable_security = {str(bs_defaults_for_template.disable_security).lower()}
max_content_length = {bs_defaults_for_template.max_content_length}

[sandbox]
use_sandbox = false
"""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f: f.write(default_config_content)
        return config_path

    def _load_toml_config(self) -> dict:
        config_path = self._get_config_path()
        with config_path.open("rb") as f: return tomllib.load(f)

    def _load_initial_config(self):
        raw_config = self._load_toml_config()
        
        gemini_conf = raw_config.get("gemini", {})
        gemini_settings = GeminiSettings(
            api_key=os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE"),
            primary_model=gemini_conf.get("primary_model", os.getenv("PRIMARY_MODEL", GeminiSettings.model_fields['primary_model'].default)),
            small_model=gemini_conf.get("small_model", os.getenv("SMALL_MODEL", GeminiSettings.model_fields['small_model'].default)),
            multimodal_model=gemini_conf.get("multimodal_model", os.getenv("MULTIMODAL_MODEL", GeminiSettings.model_fields['multimodal_model'].default)),
            max_output_tokens=gemini_conf.get("max_output_tokens", GeminiSettings.model_fields['max_output_tokens'].default),
            temperature=gemini_conf.get("temperature", GeminiSettings.model_fields['temperature'].default),
            top_p=gemini_conf.get("top_p", GeminiSettings.model_fields['top_p'].default),
            top_k=gemini_conf.get("top_k", GeminiSettings.model_fields['top_k'].default),
            fallback_primary_model=gemini_conf.get("fallback_primary_model", os.getenv("FALLBACK_PRIMARY_MODEL", GeminiSettings.model_fields['fallback_primary_model'].default)),
            fallback_small_model=gemini_conf.get("fallback_small_model", os.getenv("FALLBACK_SMALL_MODEL", GeminiSettings.model_fields['fallback_small_model'].default)),
            fallback_multimodal_model=gemini_conf.get("fallback_multimodal_model", os.getenv("FALLBACK_MULTIMODAL_MODEL", GeminiSettings.model_fields['fallback_multimodal_model'].default)),
        )
        if not gemini_settings.api_key or gemini_settings.api_key == "YOUR_GEMINI_API_KEY_HERE":
            # Allowing this to pass for now if user wants to only use scraper, but it will limit functionality.
            # Will rely on individual tools/LLM class to error out if API key is strictly needed and missing.
            print("Warning: GEMINI_API_KEY not found or is a placeholder. Gemini-dependent features will fail.")


        search_conf = raw_config.get("search", {})
        default_search_pydantic = SearchSettings()
        search_settings = SearchSettings(
            google_api_key=os.getenv("GOOGLE_SEARCH_API_KEY"), # Corrected env var name from your .env example
            google_cse_id=os.getenv("GOOGLE_CSE_ID"),
            fallback_google_api_key=os.getenv("FALLBACK_Google_Search_API_KEY"), # Corrected env var name
            fallback_google_cse_id=os.getenv("FALLBACK_GOOGLE_CSE_ID"),
            primary_engine=search_conf.get("primary_engine", default_search_pydantic.primary_engine),
            fallback_engine=search_conf.get("fallback_engine", default_search_pydantic.fallback_engine),
            num_results=search_conf.get("num_results", default_search_pydantic.num_results),
            retry_delay=search_conf.get("retry_delay", default_search_pydantic.retry_delay),
            max_retries=search_conf.get("max_retries", default_search_pydantic.max_retries),
        )
        
        # --- TEMPORARY DEBUG LOGGING START ---
        print(f"DEBUG [config.py]: Loaded google_api_key: '{search_settings.google_api_key}' (Type: {type(search_settings.google_api_key)})")
        print(f"DEBUG [config.py]: Loaded google_cse_id: '{search_settings.google_cse_id}' (Type: {type(search_settings.google_cse_id)})")
        print(f"DEBUG [config.py]: Loaded fallback_google_api_key: '{search_settings.fallback_google_api_key}' (Type: {type(search_settings.fallback_google_api_key)})")
        print(f"DEBUG [config.py]: Loaded fallback_google_cse_id: '{search_settings.fallback_google_cse_id}' (Type: {type(search_settings.fallback_google_cse_id)})")
        # --- TEMPORARY DEBUG LOGGING END ---
        
        browser_conf = raw_config.get("browser", {})
        default_browser_pydantic = BrowserSettings()
        proxy_conf = browser_conf.get("proxy", {})
        proxy_settings = None
        if proxy_conf.get("server") or os.getenv("PROXY_SERVER"):
            proxy_settings = ProxySettings(
                server=proxy_conf.get("server", os.getenv("PROXY_SERVER")),
                username=proxy_conf.get("username", os.getenv("PROXY_USERNAME")),
                password=proxy_conf.get("password", os.getenv("PROXY_PASSWORD")),
            )
        
        browser_settings_data = default_browser_pydantic.model_dump()
        if isinstance(browser_conf, dict):
            for k, v in browser_conf.items():
                if hasattr(BrowserSettings, k) and v is not None and k != "proxy": # Check if attribute exists
                    browser_settings_data[k] = v
        
        if proxy_settings: browser_settings_data["proxy"] = proxy_settings
        else: browser_settings_data["proxy"] = None 

        browser_settings = BrowserSettings(**browser_settings_data)

        sandbox_conf = raw_config.get("sandbox", {})
        default_sandbox_pydantic = SandboxSettings()
        sandbox_settings = SandboxSettings(**{**default_sandbox_pydantic.model_dump(), **sandbox_conf}) if sandbox_conf else default_sandbox_pydantic

        mcp_conf = raw_config.get("mcp", {})
        default_mcp_pydantic = MCPSettings()
        mcp_servers_from_json = MCPSettings.load_server_config_from_json()
        
        toml_mcp_servers = {}
        if "servers" in mcp_conf and isinstance(mcp_conf["servers"], dict):
            for server_id, server_data in mcp_conf["servers"].items():
                if isinstance(server_data, dict):
                    try: toml_mcp_servers[server_id] = MCPServerConfig(**server_data)
                    except Exception as e: print(f"Warning: Invalid MCP server config for '{server_id}' in TOML: {e}")
        
        merged_mcp_servers = {**mcp_servers_from_json, **toml_mcp_servers} 
        
        mcp_settings = MCPSettings(
            server_reference=mcp_conf.get("server_reference", default_mcp_pydantic.server_reference), 
            servers=merged_mcp_servers if merged_mcp_servers else default_mcp_pydantic.servers
        )

        self._app_config = AppConfig(
            gemini=gemini_settings, search=search_settings, browser=browser_settings,
            sandbox=sandbox_settings, mcp=mcp_settings,
        )

    @property
    def gemini(self) -> GeminiSettings:
        if self._app_config is None: self._load_initial_config()
        assert self._app_config is not None # Should be initialized
        return self._app_config.gemini
    
    @property
    def search(self) -> SearchSettings:
        if self._app_config is None: self._load_initial_config()
        assert self._app_config is not None
        return self._app_config.search

    @property
    def browser(self) -> BrowserSettings: 
        if self._app_config is None: self._load_initial_config()
        assert self._app_config is not None
        return self._app_config.browser if self._app_config.browser is not None else BrowserSettings()

    @property
    def sandbox(self) -> SandboxSettings:
        if self._app_config is None: self._load_initial_config()
        assert self._app_config is not None
        return self._app_config.sandbox if self._app_config.sandbox is not None else SandboxSettings()

    @property
    def mcp(self) -> MCPSettings:
        if self._app_config is None: self._load_initial_config()
        assert self._app_config is not None
        return self._app_config.mcp if self._app_config.mcp is not None else MCPSettings()

    @property
    def workspace_root(self) -> Path: return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path: return PROJECT_ROOT

config = Config()