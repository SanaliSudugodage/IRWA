import httpx

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

def get_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
