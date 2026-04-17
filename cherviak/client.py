import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from cherviak.config import Config
from cherviak.models import Arena


class GameClient:
    def __init__(self, config: Config, timeout: float = 0.5):
        self._client = httpx.Client(
            base_url=config.base_url,
            headers={"X-Auth-Token": config.token},
            timeout=timeout,
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def get_arena(self) -> Arena:
        r = self._client.get("/api/arena")
        r.raise_for_status()
        return Arena.model_validate(r.json())

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def post_command(self, body: dict) -> dict:
        r = self._client.post("/api/command", json=body)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
