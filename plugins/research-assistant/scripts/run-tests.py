# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "semanticscholar==0.11.0",
#     "filelock==3.25.0",
#     "httpx==0.28.1",
#     "anyio==4.12.1",
#     "certifi==2026.2.25",
#     "h11==0.16.0",
#     "httpcore==1.0.9",
#     "idna==3.11",
#     "nest-asyncio==1.6.0",
#     "socksio==1.0.0",
#     "tenacity==9.1.4",
#     "typing_extensions==4.15.0",
#     "pytest==9.0.2",
#     "pytest-asyncio==1.3.0",
#     "iniconfig==2.3.0",
#     "packaging==26.0",
#     "pluggy==1.6.0",
# ]
# ///

import sys
from pathlib import Path

import pytest

tests_dir = str(Path(__file__).resolve().parent.parent / "tests")
sys.exit(pytest.main([tests_dir, *sys.argv[1:]]))
