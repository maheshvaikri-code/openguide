"""Customer data comes from the customer API."""
from app import config, http_client


def lookup_customer(customer_id):
    return http_client.get_json(f"{config.CUSTOMER_API}/customers/{customer_id}")
