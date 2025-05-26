from setuptools import find_packages, setup
import os
from pathlib import Path # Added Path

# Function to read dependencies from requirements.txt
def load_requirements(filename_req="requirements.txt"): # Renamed filename arg
    requirements_path = Path(__file__).resolve().parent / filename_req
    if not requirements_path.exists():
        print(f"Warning: '{filename_req}' not found at {requirements_path}. Using a fallback list of dependencies for setup.py.")
        # This fallback should ideally match your final requirements.txt
        return [
            "pydantic>=2.7,<2.8",
            "google-generativeai>=0.5,<0.6",
            "python-dotenv>=1.0,<1.1",
            "loguru>=0.7,<0.8",
            "PyYAML>=6.0,<6.1",
            "tomli>=2.0,<2.1; python_version < '3.11'", # tomllib is built-in for 3.11+
            "httpx>=0.27,<0.28",
            "requests>=2.31,<2.32", # Though httpx is preferred for async
            "beautifulsoup4>=4.12,<4.13",
            "tenacity>=8.2,<8.3",
            "docker>=7.0,<7.1",
            "browser-use>=0.1.40,<0.2.0", # Uses Playwright
            "pandas>=2.0,<2.3",
            # "mcp.py" # Placeholder for actual MCP library dependency if installable
            # If mcp is a local module, ensure it's included by find_packages
            # The PDF implies 'mcp' is an installed library (e.g. from mcp.server.fastmcp import FastMCP)
            # Add actual MCP dependency here if known (e.g., "fastmcp" or "mcp-sdk")
        ]
    with open(requirements_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

readme_path = Path(__file__).resolve().parent / "README.md"
if readme_path.exists():
    with open(readme_path, "r", encoding="utf-8") as fh:
        long_description = fh.read()
else:
    long_description = "DRIM AI - A versatile AI agent framework powered by Gemini, designed for complex task automation."

setup(
    name="drim_ai_agent", # [Source: 814]
    version="0.1.0", # Updated version slightly [Source: 814]
    author="DRIM AI Project (Adapted from OpenManus)", # Your Name/Team [Source: 814]
    author_email="your_drim_ai_contact@example.com", # Your contact [Source: 814]
    description="DRIM AI: A versatile and extensible AI agent framework using Google Gemini, capable of complex reasoning, tool use, and task automation.", # [Source: 814]
    long_description=long_description,
    long_description_content_type="text/markdown", # [Source: 814]
    url="https://github.com/your_username/DRIM_AI_Project", # Your project URL [Source: 814]
    
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests", "examples*", "config"]), # [Source: 814] Added config to exclude
    
    install_requires=load_requirements("requirements.txt"), # Ensure requirements.txt is correct [Source: 814]

    python_requires=">=3.11, <3.14", # Based on earlier discussions [Source: 815]
    
    entry_points={ # [Source: 815]
        "console_scripts": [
            "drim-ai=main:main_drim_ai_execution", # Updated function name [Source: 815]
            "drim-ai-flow=run_flow:run_drim_ai_planning_flow", # Updated
            "drim-ai-mcp-client=run_mcp:main_mcp_client_runner", # Updated
            "drim-ai-mcp-server=run_mcp_server:main_mcp_server", # Updated
        ],
    },
    
    classifiers=[ # [Source: 815]
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "License :: OSI Approved :: MIT License", # Confirm your license choice
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Operating System :: OS Independent", # [Source: 815]
    ],
    keywords="ai agent gemini llm framework drim automation tools planning",
    project_urls={
        "Bug Tracker": "https://github.com/your_username/DRIM_AI_Project/issues", # Update
        "Source Code": "https://github.com/your_username/DRIM_AI_Project/", # Update
        # "Documentation": "https://your_drim_ai_docs.com/", # If you have docs
    },
    include_package_data=True, # Important for MANIFEST.in or SCM-tracked data files
    # package_data={'app': ['py.typed']}, # Example if you add type hints marker
)