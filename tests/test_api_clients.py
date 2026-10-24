import unittest

from services.fancytext import FancyTextAPI, FancyTextAPIError
from services.generatefancytext import (
    GenerateFancyTextAPI,
    GenerateFancyTextAPIError,
)


class FakeResponse:
    def __init__(
        self,
        status: int,
        payload: object = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
        self.payload = payload
        self.json_error = json_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self, **_kwargs: object) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    closed = False

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = 0

    def post(self, *_args: object, **_kwargs: object) -> FakeResponse:
        self.calls += 1
        return self.response

    def get(self, *_args: object, **_kwargs: object) -> FakeResponse:
        self.calls += 1
        return self.response


class APIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_thefancytext_handles_http_and_json_errors(self) -> None:
        for response in (
            FakeResponse(429),
            FakeResponse(200, json_error=ValueError("invalid JSON")),
        ):
            with self.subTest(status=response.status):
                client = FancyTextAPI()
                await client.start(FakeSession(response))
                with self.assertRaises(FancyTextAPIError):
                    await client.fetch_styles("Biozy")

    async def test_generatefancytext_validates_schema_and_rate_limit(self) -> None:
        for response in (
            FakeResponse(429),
            FakeResponse(200, {"success": False, "results": []}),
            FakeResponse(200, json_error=ValueError("invalid JSON")),
        ):
            with self.subTest(status=response.status):
                client = GenerateFancyTextAPI()
                await client.start(FakeSession(response))
                with self.assertRaises(GenerateFancyTextAPIError):
                    await client.fetch_styles("Biozy")

    async def test_successful_results_are_cached(self) -> None:
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "success": True,
                    "results": [{"result": "𝐁𝐢𝐨𝐳𝐲"}],
                },
            )
        )
        client = GenerateFancyTextAPI()
        await client.start(session)

        first = await client.fetch_styles("Biozy")
        second = await client.fetch_styles("Biozy")

        self.assertEqual(first, ["𝐁𝐢𝐨𝐳𝐲"])
        self.assertEqual(second, first)
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
