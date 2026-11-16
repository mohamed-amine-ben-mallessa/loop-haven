"""The local rate limiter, and the guards it replaces.

The limiter exists because a retry loop inside a single-user install is
indistinguishable from abuse to Looperman, and a ban takes the account's WAV
downloads with it. These tests pin the behaviour that matters: the budget is
counted, cached reads are free, the state is readable without leaking
anything, and an over-budget call reaches the caller as 429 rather than 500.
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from loophaven.api import app as api_app
from loophaven.providers.looperman import scraper


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        scraper._rate_limit_reset()
        self._max = scraper._RATE_LIMIT_MAX

    def tearDown(self):
        scraper._RATE_LIMIT_MAX = self._max
        scraper._rate_limit_reset()
        scraper.clear_cache()

    def test_budget_is_exhausted_then_refused(self):
        scraper._RATE_LIMIT_MAX = 2
        scraper._rate_limit_check()
        scraper._rate_limit_check()
        with self.assertRaises(scraper.RateLimited) as caught:
            scraper._rate_limit_check()
        self.assertIn("local rate limit", str(caught.exception))

    def test_reset_restores_the_budget(self):
        scraper._RATE_LIMIT_MAX = 1
        scraper._rate_limit_check()
        scraper._rate_limit_reset()
        scraper._rate_limit_check()  # must not raise

    def test_cached_reads_do_not_consume_the_budget(self):
        scraper._RATE_LIMIT_MAX = 1

        class FakeResponse:
            text = "<html><body>cached</body></html>"

            def raise_for_status(self):
                pass

        with patch.object(scraper.requests, "get", return_value=FakeResponse()) as get:
            scraper.fetch_html("https://www.looperman.com/loops?fixture=cache")
            scraper.fetch_html("https://www.looperman.com/loops?fixture=cache")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(scraper.rate_limit_state()["recent_requests"], 1)

    def test_state_reports_remaining_without_leaking_urls(self):
        scraper._RATE_LIMIT_MAX = 3
        scraper._rate_limit_check()
        state = scraper.rate_limit_state()
        self.assertEqual(set(state), {"max_requests", "window_seconds",
                                      "recent_requests", "remaining"})
        self.assertEqual(state["recent_requests"], 1)
        self.assertEqual(state["remaining"], 2)

    def test_bad_environment_value_falls_back_instead_of_crashing(self):
        for raw in ("", "abc", "0", "-4"):
            with patch.dict("os.environ", {"LOOPHAVEN_RATE_LIMIT": raw}):
                self.assertEqual(scraper._configured_rate_limit(),
                                 scraper._RATE_LIMIT_DEFAULT, raw)
        with patch.dict("os.environ", {"LOOPHAVEN_RATE_LIMIT": "7"}):
            self.assertEqual(scraper._configured_rate_limit(), 7)


class RateLimitApiTests(unittest.TestCase):
    """HTTP shape: 429 for an exhausted budget, and the state on /api/health."""

    def setUp(self):
        scraper._rate_limit_reset()
        self.client = TestClient(api_app.app)

    def tearDown(self):
        scraper._rate_limit_reset()
        scraper.clear_cache()

    def test_health_exposes_the_rate_limit(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        state = response.json()["rate_limit"]
        self.assertEqual(state["window_seconds"], 60)
        self.assertGreater(state["max_requests"], 0)

    def test_exhausted_budget_answers_429_not_500(self):
        saved = scraper._RATE_LIMIT_MAX
        scraper._RATE_LIMIT_MAX = 0
        try:
            response = self.client.get("/api/search", params={"genre": "Trap", "limit": 1})
        finally:
            scraper._RATE_LIMIT_MAX = saved
        self.assertEqual(response.status_code, 429)
        self.assertIn("local rate limit", response.json()["detail"])


class AcapellaCategoryFilterTests(unittest.TestCase):
    """`?category=` never existed for acapellas; it must not look like it works."""

    def setUp(self):
        self.client = TestClient(api_app.app)

    def test_category_is_rejected_before_any_upstream_call(self):
        with patch.object(scraper.requests, "get") as get:
            response = self.client.get("/api/acapellas/search",
                                       params={"category": "Arpeggio"})
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail["filter"], "category")
        self.assertEqual(detail["catalogue"], "/api/filters")
        get.assert_not_called()

    def test_loops_still_accept_category(self):
        with patch.object(api_app, "scrape_loops",
                          return_value={"count": 0, "loops": [], "page": {}}) as scrape:
            response = self.client.get("/api/search", params={"category": "Arpeggio"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("cid=47", response.json()["looperman_url"])
        scrape.assert_called_once()


class UsernameTests(unittest.TestCase):
    """`/api/health` used to report `username: "My Profile"` for every account."""

    def test_name_comes_from_the_heading(self):
        from bs4 import BeautifulSoup

        from loophaven.providers.looperman.auth import _account_username

        soup = BeautifulSoup(
            '<html><head><title>Benmallessa - My Profile | Looperman</title></head>'
            '<body><h1>Benmallessa</h1>'
            '<a href="/users/profile/8655176">My Profile</a></body></html>',
            "lxml",
        )
        self.assertEqual(_account_username(soup), "Benmallessa")

    def test_falls_back_to_the_title_when_there_is_no_heading(self):
        from bs4 import BeautifulSoup

        from loophaven.providers.looperman.auth import _account_username

        soup = BeautifulSoup(
            "<html><head><title>Benmallessa - My Profile | Looperman</title></head>"
            "<body><a href='/users/profile/1'>My Profile</a></body></html>",
            "lxml",
        )
        self.assertEqual(_account_username(soup), "Benmallessa")

    def test_nav_label_is_never_taken_as_a_name(self):
        from bs4 import BeautifulSoup

        from loophaven.providers.looperman.auth import _account_username

        soup = BeautifulSoup(
            "<html><head><title>My Profile | Looperman</title></head>"
            "<body><a href='/users/profile/1'>My Profile</a></body></html>",
            "lxml",
        )
        self.assertIsNone(_account_username(soup))


if __name__ == "__main__":
    unittest.main()
