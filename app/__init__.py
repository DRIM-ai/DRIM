# Python version check: 3.11-3.13
import sys

if sys.version_info < (3, 11) or sys.version_info >= (3, 14): # Adjusted upper bound slightly
    print(
        "Warning: Unsupported Python version {ver}, please use Python 3.11, 3.12, or 3.13. DRIM AI is optimized for these versions.".format(
            ver=".".join(map(str, sys.version_info[:3]))
        )
    )

# This file can also be used to make submodules easily importable, e.g.:
# from .agent import BaseAgent
# from .tool import BaseTool
# from .config import config
# from .logger import logger