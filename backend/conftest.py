import sys
import os
from dotenv import load_dotenv

# 1. load the test .env file BEFORE anything else happens
env_path = os.path.join(os.path.dirname(__file__), "tests", ".env")
load_dotenv(env_path)

# 2. safety net: If DATABASE_URL is still missing, set a default for tests
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite://:memory:"

# 3. add the backend folder to Python's path
sys.path.insert(0, os.path.dirname(__file__))