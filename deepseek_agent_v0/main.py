#!/usr/bin/env python3
# Backward compatibility stub for DeepSeek Agent
# This file is deprecated - use the package directly: localuser-agent or python -m localuser_agent

import warnings
import sys
import os

# Add parent directory to path to import the new package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

warnings.warn(
    "deepseek_agent_v0/main.py is deprecated and will be removed in a future version. "
    "Use 'localuser-agent' command or 'python -m localuser_agent' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Import and run the actual main function
from main import main

if __name__ == "__main__":
    main()