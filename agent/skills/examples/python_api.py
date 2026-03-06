"""
Example skill: Python API documentation.

Provides knowledge about Python standard library and common packages.
"""

from typing import Optional
import os

from ..base import Skill, SkillMetadata, SkillType, StaticSkill


class PythonAPISkill(StaticSkill):
    """Skill providing Python API documentation."""

    def __init__(self, metadata: Optional[SkillMetadata] = None):
        if metadata is None:
            metadata = SkillMetadata(
                name="python_api",
                description="Python standard library and common packages documentation",
                skill_type=SkillType.DOCUMENTATION,
                tags=["python", "programming", "api", "code"],
                size_estimate=5000,  # Rough estimate
                cache_ttl=86400,  # 24 hours
                dependencies=[],
            )

        # Static content with Python documentation
        content = """# Python API Documentation

## Core Language Features

### Data Types
- **int**: Arbitrary precision integers
- **float**: Double-precision floating point numbers
- **str**: Immutable Unicode strings
- **list**: Mutable sequence type
- **tuple**: Immutable sequence type
- **dict**: Hash map / associative array
- **set**: Unordered collection of unique elements
- **bool**: Boolean values (True/False)

### Control Flow
- `if`/`elif`/`else`: Conditional execution
- `for`/`while`: Loops with `break`, `continue`
- `try`/`except`/`finally`: Exception handling
- `with`: Context managers for resource management

### Functions
- `def`: Function definition
- `lambda`: Anonymous functions
- `*args`, `**kwargs`: Variable arguments
- Decorators: `@decorator` syntax

## Standard Library Highlights

### os module - Operating system interface
```python
import os
os.path.join()  # Join path components
os.listdir()    # List directory contents
os.makedirs()   # Create directories recursively
os.environ      # Environment variables
```

### sys module - System-specific parameters
```python
import sys
sys.argv        # Command line arguments
sys.path        # Module search path
sys.exit()      # Exit interpreter
```

### json module - JSON encoding/decoding
```python
import json
json.dumps()    # Convert Python object to JSON string
json.loads()    # Parse JSON string to Python object
json.dump()     # Write JSON to file
json.load()     # Read JSON from file
```

### datetime module - Date and time
```python
from datetime import datetime, date, timedelta
datetime.now()           # Current date and time
date.today()            # Current date
timedelta(days=1)       # Time difference
```

### collections module - Container datatypes
```python
from collections import defaultdict, Counter, namedtuple, deque
defaultdict(list)       # Dict with default factory
Counter('hello')        # Count hashable objects
namedtuple('Point', ['x', 'y'])  # Lightweight object
deque()                 # Double-ended queue
```

### re module - Regular expressions
```python
import re
re.search(pattern, string)    # Search for pattern
re.match(pattern, string)     # Match at beginning
re.findall(pattern, string)   # Find all matches
re.sub(pattern, repl, string) # Substitute matches
```

## Common Packages

### requests - HTTP for Humans
```python
import requests
response = requests.get(url)
response.json()     # Parse JSON response
response.text       # Text response
response.status_code # HTTP status
```

### numpy - Numerical computing
```python
import numpy as np
np.array([1, 2, 3])    # Create array
np.zeros((3, 3))       # Zero matrix
np.linspace(0, 1, 5)   # Linear spacing
```

### pandas - Data analysis
```python
import pandas as pd
pd.DataFrame(data)     # Create DataFrame
df.read_csv('file.csv') # Read CSV
df.groupby('column')   # Group operations
```

### flask - Web framework
```python
from flask import Flask
app = Flask(__name__)
@app.route('/')
def hello(): return "Hello"
app.run()
```

## Best Practices

1. **Use virtual environments** (`venv`, `conda`)
2. **Follow PEP 8** style guide
3. **Write docstrings** for functions and classes
4. **Use type hints** (Python 3.5+)
5. **Handle exceptions** gracefully
6. **Write unit tests** (`unittest`, `pytest`)

## Common Patterns

### List comprehension
```python
squares = [x**2 for x in range(10) if x % 2 == 0]
```

### Dictionary comprehension
```python
square_dict = {x: x**2 for x in range(5)}
```

### Context manager pattern
```python
with open('file.txt', 'r') as f:
    content = f.read()
```

### Decorator pattern
```python
def log_calls(func):
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper
```

This documentation provides essential Python knowledge for coding tasks.
"""
        super().__init__(content, metadata)


# Convenience function to create and register the skill
def create_python_api_skill() -> PythonAPISkill:
    """Create and return a Python API skill instance."""
    return PythonAPISkill()