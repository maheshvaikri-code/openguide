"""Settings, read from the environment so tests can override them."""
import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CUSTOMER_API = os.environ.get("CUSTOMER_API", "https://customers.example.invalid")
