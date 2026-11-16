import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

import loophaven.api.app as api_module
from loophaven.api.app import app as application
from loophaven.providers.looperman import auth, filters, scraper


ACAPELLA_FIXTURE = '''
<!-- Real order, verified on live pages: [data-mp3] marker -> card -> tag-wrapper -->
<div data-mp3="https://www.looperman.com/media/acapellas/42/test.mp3"></div>
<div class="card bg-player">
 <div class="flex-grow-1"><a class="player-title" href="https://www.looperman.com/acapellas/detail/1001/test-vocal">Test Vocal</a>
 <a href="https://www.looperman.com/users/profile/42"><img alt="Vocalist" src="avatar.jpg"></a>
 <span data-hash="abc123"></span></div>
 <div class="player-waveform-wrapper-list"><img class="player-waveform-image" src="https://www.looperman.com/media/acapellas/42/test.png"></div>
</div>
<div class="tag-wrapper">
 <a href="/acapellas?ftempo=90&amp;ttempo=90" data-bs-title="Find more acapellas at 90 bpm">90 bpm</a>
 <a href="/acapellas/genres/rap" data-bs-title="Genre : Rap Acapellas and Vocals">Rap</a>
 <a href="/acapellas?mf=1" data-bs-title="This acapella contains Male vocals">Male</a>
 <a href="/acapellas?style=1" data-bs-title="The vocal style of this acapella is Rapping">Rapping</a>
 <a href="/acapellas?ur=1" data-bs-title="Vocalist set this acapella as Free Commercial &amp; Non Commercial">Free Commercial &amp; Non Commercial</a>
</div>
'''


class ScraperTests(unittest.TestCase):
    def test_loop_filters_are_encoded(self):
        url = scraper.build_search_url(
            genre="Trap", category="Synth", key="Am", ftempo=140, ttempo=140,
            tsig="4x4", mid="123456", who=2, ppage=50, favs=True,
        )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(urlparse(url).path, "/loops")
        self.assertEqual(query["gid"], ["54"])
        self.assertEqual(query["cid"], ["4"])
        self.assertEqual(query["tsig"], ["4x4"])
        self.assertEqual(query["mid"], ["123456"])
        self.assertEqual(query["who"], ["2"])
        self.assertEqual(query["ppage"], ["50"])
        self.assertEqual(query["favs"], ["1"])

    def test_acapella_filter_url(self):
        url = scraper.build_acapella_search_url(
            genre="Boom Bap", ftempo=86, mf=1, style=1, ur=1,
        )
        query = parse_qs(urlparse(url).query)
        # Acapellas are filtered by gid on /acapellas, not by a guessed genre slug:
        # a wrong slug returns an empty page instead of an error.
        self.assertEqual(urlparse(url).path, "/acapellas")
        self.assertEqual(query["gid"], ["65"])
        self.assertEqual(query["ftempo"], ["86"])
        self.assertEqual(query["ttempo"], ["86"])
        self.assertEqual(query["mf"], ["1"])
        self.assertEqual(query["style"], ["1"])
        self.assertEqual(query["ur"], ["1"])

    def test_keywords_keep_their_plus_sign(self):
        # '+' means "must include" upstream; a raw '+' would decode as a space.
        url = scraper.build_search_url(keyword="+funky-techno")
        self.assertIn("keys=%2Bfunky-techno", url)
        self.assertEqual(parse_qs(urlparse(url).query)["keys"], ["+funky-techno"])

    def test_unknown_genre_lists_alternatives(self):
        with self.assertRaises(filters.UnknownFilter) as ctx:
            scraper.build_search_url(genre="Trapp")
        self.assertIn("Trap", ctx.exception.suggestions)

    def test_flat_keys_resolve_to_sharps(self):
        self.assertEqual(filters.resolve_key("Bb")[0], "a")
        self.assertEqual(filters.resolve_key("Bbm")[0], "am")
        self.assertEqual(filters.resolve_key("F#m")[0], "fsm")
        self.assertEqual(filters.resolve_key("A# minor")[0], "asm")

    def test_genre_and_category_accept_labels_ids_and_slugs(self):
        self.assertEqual(filters.resolve_genre("Trap")[0], "54")
        self.assertEqual(filters.resolve_genre("54")[0], "54")
        self.assertEqual(filters.resolve_genre("trap loops")[0], "54")
        self.assertEqual(filters.resolve_category("free-guitar-electric-loops-samples-sounds-wavs-download")[0], "3")

    def test_total_is_reported_as_capped(self):
        window = scraper._page_window("<p>Loops 1 - 25 of 5,000</p>")
        self.assertTrue(window["total_capped"])
        page = scraper._pagination(window, 25)
        self.assertIsNone(page["total_pages"])

    def test_small_result_set_uses_the_showing_counter(self):
        window = scraper._page_window(
            "<p>Showing 4 138 bpm 4x4 time Trap Guitar Electric loops In Key of Em</p>")
        self.assertEqual(window["total"], 4)
        self.assertFalse(window["total_capped"])

    def test_later_pages_do_not_invent_a_total(self):
        window = scraper._page_window("<p>no counter on page 3</p>")
        self.assertIsNone(window["total"])
        self.assertIsNone(scraper._pagination(window, 25)["total_pages"])

    def test_acapella_parser_returns_license_and_preview(self):
        class FakeResponse:
            text = ACAPELLA_FIXTURE
            def raise_for_status(self):
                pass
        with patch.object(scraper.requests, "get", return_value=FakeResponse()):
            result = scraper.scrape_acapellas("https://www.looperman.com/acapellas", limit=2)
        self.assertEqual(result["count"], 1)
        item = result["acapellas"][0]
        self.assertEqual(item["id"], "1001")
        self.assertEqual(item["author"], "Vocalist")
        self.assertEqual(item["gender"], "male")
        self.assertEqual(item["style"], "Rapping")
        self.assertEqual(item["license"], "Free Commercial & Non Commercial")
        self.assertEqual(item["favorite_hash"], "abc123")
        self.assertTrue(item["mp3_url"].endswith("test.mp3"))


LOOP_FIXTURE = '''
<!-- Real order, verified on live pages (div.col-12 shared by every card):
     [data-mp3] marker -> card (title, author, stats, waveform, hash) -> tag-wrapper -->
<div class="col-12 col-lg-8">
 <div data-mp3="https://www.looperman.com/media/loops/3190338/x.mp3"></div>
 <div class="player-wrapper">
  <div class="card bg-player">
   <a class="player-title" href="https://www.looperman.com/loops/detail/436556/fall-on-me">FALL ON ME</a>
   <a href="https://www.looperman.com/users/profile/3190338">nickzbeatz</a>
   <span data-bs-title="0 favs">0</span>
   <span data-bs-title="14 downloads">14</span>
   <a data-bs-title="0 comments">0</a>
   <span data-bs-title="27 seconds">0:27</span>
   <img class="player-waveform-image" src="https://www.looperman.com/media/loops/3190338/x.png">
   <div data-hash="deadbeef"></div>
   <span>11th Nov 2026 11:42</span>
  </div>
 </div>
 <div class="tag-wrapper">
  <a href="/loops?ftempo=138" data-bs-title="Find more loops at 138 bpm ">138 bpm</a>
  <a href="/loops/genres/free-trap" data-bs-title="Genre : Free Trap Loops and Samples">Trap Loops</a>
  <a href="/loops/cats/free-guitar" data-bs-title="Category : Free Guitar Electric Loops">Guitar Electric Loops</a>
  <a href="/loops?tsig=4x4" data-bs-title="Time Signature : 4/4 ">4/4</a>
  <a href="/loops/detail/436556" data-bs-title="File Size : 4.68 MB ">4.68 MB</a>
  <a href="/loops?mkey=em" data-bs-title="This loop is in the key of Em">Key : Em</a>
  <a href="/loops?did=2" data-bs-title="This loop was created with FL Studio">FL Studio</a>
 </div>
</div>
<p>Loops 1 - 25 of 5,000</p>
'''


def _loop_listing_fixture(records, counter):
    cards = [
        f'''
        <div data-mp3="https://fixtures.invalid/loops/{loop_id}.mp3"></div>
        <div class="player-wrapper"><div class="card bg-player">
         <a class="player-title" href="/loops/detail/{loop_id}/fixture-{loop_id}">Fixture {loop_id}</a>
        </div></div>
        <div class="tag-wrapper">
         <a data-bs-title="Find more loops at {bpm} bpm">{bpm} bpm</a>
         <a data-bs-title="This loop is in the key of {key}">Key : {key}</a>
        </div>
        '''
        for loop_id, bpm, key in records
    ]
    return '<div class="col-12">' + "".join(cards) + f"</div><p>{counter}</p>"


class LoopParseTests(unittest.TestCase):
    def test_loop_card_exposes_duration_stats_and_clean_author_url(self):
        class FakeResponse:
            text = LOOP_FIXTURE
            def raise_for_status(self):
                pass
        scraper.clear_cache()
        with patch.object(scraper.requests, "get", return_value=FakeResponse()):
            result = scraper.scrape_loops("https://www.looperman.com/loops?x=1", limit=5)
        item = result["loops"][0]
        self.assertEqual(item["duration_seconds"], 27)
        self.assertEqual(item["downloads"], 14)
        self.assertEqual(item["favorites"], 0)
        self.assertEqual(item["key"], "Em")
        self.assertEqual(item["genre"], "Trap")
        self.assertEqual(item["category"], "Guitar Electric")
        self.assertEqual(item["time_signature"], "4/4")
        self.assertEqual(item["daw"], "FL Studio")
        # Regression: the old code prepended BASE to an already absolute href.
        self.assertEqual(item["author_url"], "https://www.looperman.com/users/profile/3190338")
        self.assertEqual(len(item["tags"]), 7)
        self.assertEqual(result["page"]["total"], 5000)
        # 5,000 is Looperman's display cap, so a page count cannot be derived.
        self.assertTrue(result["page"]["total_capped"])
        self.assertIsNone(result["page"]["total_pages"])

    def test_two_items_in_one_shared_col12_do_not_share_data(self):
        """Regression: every card lives in the SAME div.col-12.

        Scoping by "the parent container" made card #2 inherit card #1's tags,
        bpm and mp3, so a 113bpm synth loop was reported as a 157bpm piano.
        """
        fixture = '''
        <div class="col-12 col-lg-8">
         <div data-mp3="https://cdn/1-first.mp3"></div>
         <div class="player-wrapper"><div class="card bg-player">
          <a class="player-title" href="/loops/detail/1/first">First Piano</a>
          <a href="/users/profile/11">Alice</a>
          <span data-hash="hash1"></span>
         </div></div>
         <div class="tag-wrapper">
          <a data-bs-title="Find more loops at 157 bpm">157 bpm</a>
          <a data-bs-title="Category : Free Piano Loops">Piano Loops</a>
         </div>

         <div data-mp3="https://cdn/2-second.mp3"></div>
         <div class="player-wrapper"><div class="card bg-player">
          <a class="player-title" href="/loops/detail/2/second">Second Synth</a>
          <a href="/users/profile/22">Bob</a>
          <span data-hash="hash2"></span>
         </div></div>
         <div class="tag-wrapper">
          <a data-bs-title="Find more loops at 113 bpm">113 bpm</a>
          <a data-bs-title="Category : Free Synth Loops">Synth Loops</a>
         </div>
        </div>
        '''

        class FakeResponse:
            text = fixture
            def raise_for_status(self):
                pass

        scraper.clear_cache()
        with patch.object(scraper.requests, "get", return_value=FakeResponse()):
            result = scraper.scrape_loops("https://www.looperman.com/loops?x=2", limit=5)

        first, second = result["loops"]
        self.assertEqual(first["title"], "First Piano")
        self.assertEqual(first["bpm"], 157)
        self.assertEqual(first["category"], "Piano")
        self.assertEqual(first["mp3_url"], "https://cdn/1-first.mp3")
        self.assertEqual(first["author"], "Alice")
        self.assertEqual(first["favorite_hash"], "hash1")

        self.assertEqual(second["title"], "Second Synth")
        self.assertEqual(second["bpm"], 113)
        self.assertEqual(second["category"], "Synth")
        self.assertEqual(second["mp3_url"], "https://cdn/2-second.mp3")
        self.assertEqual(second["author"], "Bob")
        self.assertEqual(second["favorite_hash"], "hash2")

    def test_full_page_in_one_column_keeps_first_and_last_loop_fields(self):
        middle = [(loop_id, 90 + loop_id, "Am") for loop_id in range(2, 25)]
        fixture = _loop_listing_fixture(
            [(1, 90, "C"), *middle, (25, 128, "Bm")], "Loops 1 - 25 of 50")

        class FakeResponse:
            text = fixture

            def raise_for_status(self):
                pass

        scraper.clear_cache()
        with patch.object(scraper.requests, "get", return_value=FakeResponse()):
            result = scraper.scrape_loops("https://www.looperman.com/loops?fixture=full", limit=25)

        self.assertEqual([item["id"] for item in result["loops"]], [str(i) for i in range(1, 26)])
        first, last = result["loops"][0], result["loops"][-1]
        self.assertEqual((first["bpm"], first["key"], first["mp3_url"]),
                         (90, "C", "https://fixtures.invalid/loops/1.mp3"))
        self.assertEqual((last["bpm"], last["key"], last["mp3_url"]),
                         (128, "Bm", "https://fixtures.invalid/loops/25.mp3"))

    def test_single_loop_uses_singular_showing_counter(self):
        fixture = _loop_listing_fixture([(1, 90, "C")], "Showing 1 90 bpm Piano loop")

        class FakeResponse:
            text = fixture

            def raise_for_status(self):
                pass

        scraper.clear_cache()
        with patch.object(scraper.requests, "get", return_value=FakeResponse()):
            result = scraper.scrape_loops("https://www.looperman.com/loops?fixture=single", limit=2)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["page"], {
            "from": 1, "to": 1, "per_page": 1,
            "total": 1, "total_pages": 1, "total_capped": False,
        })

    def test_two_acapellas_in_one_shared_col12_do_not_share_data(self):
        """Same regression test for acapellas: each item must get its own mp3, tags, etc."""
        fixture = '''
        <div class="col-12 col-lg-8">
         <div data-mp3="https://cdn/a-first.mp3"></div>
         <div class="card bg-player">
          <div class="flex-grow-1"><a class="player-title" href="/acapellas/detail/1/first">First Vocal</a>
          <a href="/users/profile/11"><img alt="Alice"></a>
          <span data-hash="hash1"></span></div>
          <div class="player-waveform-wrapper-list"><img class="player-waveform-image" src="https://cdn/w1.png"></div>
         </div>
         <div class="tag-wrapper">
          <a data-bs-title="Find more acapellas at 129 bpm">129 bpm</a>
          <a data-bs-title="This acapella is in the key of Dm">Key : Dm</a>
          <a data-bs-title="Genre : Trap Acapellas and Vocals">Trap</a>
          <a data-bs-title="This acapella contains Male vocals">Male</a>
          <a data-bs-title="The vocal style of this acapella is Rapping">Rapping</a>
          <a data-bs-title="Type : Full Song">Full Song</a>
          <a data-bs-title="Usage : Free Non Commercial Only">Free Non Commercial Only</a>
         </div>

         <div data-mp3="https://cdn/a-second.mp3"></div>
         <div class="card bg-player">
          <div class="flex-grow-1"><a class="player-title" href="/acapellas/detail/2/second">Second Vocal</a>
          <a href="/users/profile/22"><img alt="Bob"></a>
          <span data-hash="hash2"></span></div>
          <div class="player-waveform-wrapper-list"><img class="player-waveform-image" src="https://cdn/w2.png"></div>
         </div>
         <div class="tag-wrapper">
          <a data-bs-title="Find more acapellas at 165 bpm">165 bpm</a>
          <a data-bs-title="Genre : Trap Acapellas and Vocals">Trap</a>
          <a data-bs-title="This acapella contains Female vocals">Female</a>
          <a data-bs-title="The vocal style of this acapella is Singing">Singing</a>
          <a data-bs-title="Type : Hook">Hook</a>
          <a data-bs-title="Usage : Free Commercial & Non Commercial">Free Commercial & Non Commercial</a>
         </div>
        </div>
        '''

        class FakeResponse:
            text = fixture
            def raise_for_status(self):
                pass

        scraper.clear_cache()
        with patch.object(scraper.requests, "get", return_value=FakeResponse()):
            result = scraper.scrape_acapellas("https://www.looperman.com/acapellas?x=2", limit=5)

        first, second = result["acapellas"]
        self.assertEqual(first["title"], "First Vocal")
        self.assertEqual(first["bpm"], 129)
        self.assertEqual(first["key"], "Dm")
        self.assertEqual(first["gender"], "male")
        self.assertEqual(first["style"], "Rapping")
        self.assertEqual(first["type"], "Full Song")
        self.assertEqual(first["license"], "Free Non Commercial Only")
        self.assertEqual(first["mp3_url"], "https://cdn/a-first.mp3")
        self.assertEqual(first["waveform"], "https://cdn/w1.png")
        self.assertEqual(first["author"], "Alice")
        self.assertEqual(first["favorite_hash"], "hash1")

        self.assertEqual(second["title"], "Second Vocal")
        self.assertEqual(second["bpm"], 165)
        self.assertIsNone(second["key"])
        self.assertEqual(second["gender"], "female")
        self.assertEqual(second["style"], "Singing")
        self.assertEqual(second["type"], "Hook")
        self.assertEqual(second["license"], "Free Commercial & Non Commercial")
        self.assertEqual(second["mp3_url"], "https://cdn/a-second.mp3")
        self.assertEqual(second["waveform"], "https://cdn/w2.png")
        self.assertEqual(second["author"], "Bob")
        self.assertEqual(second["favorite_hash"], "hash2")


class AuthVerifyTests(unittest.TestCase):
    """An expired cookie must not be reported as a live session."""

    def _session(self, url, status=200, body=""):
        class FakeResponse:
            status_code = status
            text = body
        FakeResponse.url = url
        class FakeSession:
            def get(self, *args, **kwargs):
                return FakeResponse()
        return FakeSession()

    def test_redirect_to_login_means_logged_out(self):
        # Regression: the HTML still contains /account/logout when logged out,
        # so the old check said "logged in" while downloads failed.
        session = self._session(
            "https://www.looperman.com/account/login",
            body='<a href="/account/logout">Logout</a><a href="/account/login">Login</a>')
        self.assertIs(auth._verify_session(session), False)

    def test_account_page_means_logged_in(self):
        session = self._session(
            "https://www.looperman.com/account/",
            body='<a href="/users/profile/8655176">My Profile</a>')
        self.assertIs(auth._verify_session(session), True)

    def test_network_failure_is_unknown_not_logged_out(self):
        class FakeSession:
            def get(self, *args, **kwargs):
                raise OSError("network down")
        self.assertIsNone(auth._verify_session(FakeSession()))


class DownloadTests(unittest.TestCase):
    def _response(self, status, content_type, extra=None):
        class FakeResponse:
            status_code = status
            headers = {"content-type": content_type, **(extra or {})}
            def close(self):
                pass
        return FakeResponse()

    def test_rate_limit_is_not_mistaken_for_audio(self):
        class FakeSession:
            def get(self, *args, **kwargs):
                return DownloadTests()._response(429, "text/plain")
        with self.assertRaises(scraper.RateLimited):
            scraper.download_media("https://www.looperman.com/getfiles/loops/v1-x", session=FakeSession())

    def test_success_status_quota_page_is_not_opened_as_a_file(self):
        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/html; charset=UTF-8"}
            closed = False

            def iter_content(self, size):
                yield b"<html><main><h1>Daily download quota reached</h1></main></html>"

            def close(self):
                self.closed = True

        response = FakeResponse()

        class FakeSession:
            def get(self, *args, **kwargs):
                return response

        with patch("builtins.open") as open_file, patch("io.open") as open_path:
            with self.assertRaisesRegex(scraper.NotAudio, "Daily download quota reached"):
                scraper.download_media("https://www.looperman.com/getfiles/loops/v1-x", session=FakeSession())
        self.assertTrue(response.closed)
        open_file.assert_not_called()
        open_path.assert_not_called()

    def test_upstream_filename_wins(self):
        response = self._response(200, "audio/wav", {
            "content-disposition": 'attachment; filename="looperman-l-1-2-title.wav"'})
        self.assertEqual(scraper.media_filename(response, "fallback.wav"), "looperman-l-1-2-title.wav")


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_acapella_search_route_passes_filters(self):
        with patch.object(api_module, "scrape_acapellas", return_value={"count": 0, "acapellas": []}) as scrape:
            response = await self.client.get(
                "/api/acapellas/search?genre=Boom%20Bap&bpm=86&mf=1&style=1&ur=1"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["query"]["bpm"], 86)
        args = scrape.call_args
        self.assertIn("ftempo=86", args.args[0])
        self.assertIn("mf=1", args.args[0])
        self.assertIn("ur=1", args.args[0])

    async def test_prototype_page_is_served_and_demo_mount_is_gone(self):
        home = await self.client.get("/")
        demo = await self.client.get("/dark-club/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("id=\"player\"", home.text)
        # The pilot demo and its bundled audio moved out of the public tree:
        # no third-party audio may be served from the repo.
        self.assertEqual(demo.status_code, 404)

    async def test_preview_stream_rejects_non_looperman_urls(self):
        response = await self.client.get(
            "/api/stream/preview",
            params={"url": "https://attacker.invalid/media/loops/a.mp3"},
        )
        self.assertEqual(response.status_code, 400)

    async def test_wav_route_maps_rate_limit_to_429(self):
        with patch.object(api_module.auth, "is_logged_in", return_value=True), \
             patch.object(api_module, "resolve_download", side_effect=api_module.RateLimited("quota")):
            response = await self.client.get("/api/download/wav/436556")
        self.assertEqual(response.status_code, 429)

    async def test_acapella_download_reports_mp3_not_wav(self):
        class FakeUpstream:
            headers = {
                "content-type": "audio/mpeg",
                "content-length": "3",
                "content-disposition": 'attachment; filename="looperman-a-1-24956-co-sings.mp3"',
            }
            url = "https://www.looperman.com/getfiles/acapellas/v1-x"
            def iter_content(self, chunk_size):
                yield b"ID3"
            def close(self):
                pass
        with patch.object(api_module.auth, "is_logged_in", return_value=True), \
             patch.object(api_module, "resolve_download", return_value=("https://www.looperman.com/getfiles/acapellas/v1-x", "https://www.looperman.com/acapellas/detail/24956")), \
             patch.object(api_module, "download_media", return_value=FakeUpstream()):
            response = await self.client.get("/api/download/audio/acapella/24956")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertEqual(response.headers["x-audio-format"], "mp3")
        self.assertIn("co-sings.mp3", response.headers["content-disposition"])

    async def test_zip_caps_selection_at_four(self):
        response = await self.client.post(
            "/api/download/zip", json={"ids": ["1", "2", "3", "4", "5"], "format": "mp3"}
        )
        self.assertEqual(response.status_code, 400)

    async def test_proxy_rejects_lookalike_host(self):
        response = await self.client.get(
            "/api/download/proxy",
            params={"url": "https://www.looperman.com.attacker.invalid/a.mp3"},
        )
        self.assertEqual(response.status_code, 400)

    async def test_favorite_action_requires_login(self):
        with patch.object(api_module.auth, "is_logged_in", return_value=False):
            response = await self.client.post(
                "/api/favorites/toggle", json={"item_hash": "abc123", "item_type": "loop"}
            )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
