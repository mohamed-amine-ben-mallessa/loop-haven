"""CLI tests: the download command must refuse early, and never retry a 429."""
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from loophaven import cli


class FakeResponse:
    """Minimal stand-in for the urlopen() response of the audio route."""

    def __init__(self, body=b"RIFF....WAVEfmt ", headers=None):
        self._body = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class DownloadCommandTests(unittest.TestCase):
    def test_refuses_without_a_session_and_never_calls_the_audio_route(self):
        info = {"id": "436799", "kind": "loop", "logged_in": False,
                "download_available": False, "expected_format": "wav",
                "title": "Lil Uzi Vert arp type loop", "size_hint": "2.31 MB",
                "bpm": 140, "key": "Cm"}
        with patch.object(cli, "request", return_value=info) as request, \
                patch.object(cli, "urlopen") as urlopen:
            code, out, err = run(["download", "--id", "436799"])

        self.assertEqual(code, 2)
        self.assertIn("haven login", err)
        self.assertIn("WAV", out)
        self.assertIn("2.31 MB", out)
        request.assert_called_once()
        urlopen.assert_not_called()

    def test_refuses_when_the_quota_is_spent_and_says_so(self):
        info = {"id": "436799", "kind": "loop", "logged_in": True,
                "download_available": False, "expected_format": "wav",
                "title": "Some loop", "size_hint": "1.00 MB", "bpm": 90, "key": "Am"}
        with patch.object(cli, "request", return_value=info), \
                patch.object(cli, "urlopen") as urlopen:
            code, _, err = run(["download", "--id", "436799"])

        self.assertEqual(code, 2)
        self.assertIn("quota", err)
        self.assertIn("do not retry", err)
        urlopen.assert_not_called()

    def test_a_429_is_reported_once_and_not_retried(self):
        info = {"id": "436799", "kind": "loop", "logged_in": True,
                "download_available": True, "expected_format": "wav",
                "title": "Some loop", "size_hint": "1.00 MB", "bpm": 90, "key": "Am"}
        error = HTTPError("http://127.0.0.1:8000/api/download/audio/loop/436799",
                          429, "Too Many Requests", {}, io.BytesIO(b"daily limit"))
        with patch.object(cli, "request", return_value=info), \
                patch.object(cli, "urlopen", side_effect=error) as urlopen:
            code, _, err = run(["download", "--id", "436799"])

        self.assertEqual(code, 2)
        self.assertIn("429", err)
        self.assertIn("do not retry", err)
        self.assertEqual(urlopen.call_count, 1)

    def test_writes_the_file_using_the_forwarded_name(self):
        info = {"id": "436799", "kind": "loop", "logged_in": True,
                "download_available": True, "expected_format": "wav",
                "title": "Some loop", "size_hint": "1.00 MB", "bpm": 90, "key": "Am"}
        body = b"RIFF" + b"\x00" * 60 + b"WAVE"
        response = FakeResponse(body, {
            "Content-Disposition": 'attachment; filename="looperman-l-1-2-title.wav"',
        })
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cli, "request", return_value=info), \
                    patch.object(cli, "urlopen", return_value=response):
                code, out, _ = run(["download", "--id", "436799", "--out",
                                    str(Path(tmp) / "picked.wav")])
            written = (Path(tmp) / "picked.wav").read_bytes()

        self.assertEqual(code, 0)
        self.assertEqual(written, body)
        self.assertIn("looperman-l-1-2-title.wav", out)

    def test_a_header_filename_cannot_escape_the_directory(self):
        info = {"id": "436799", "kind": "loop", "logged_in": True,
                "download_available": True, "expected_format": "wav",
                "title": "Some loop", "size_hint": "1.00 MB", "bpm": 90, "key": "Am"}
        response = FakeResponse(b"RIFF", {
            "Content-Disposition": 'attachment; filename="../../escaped.wav"',
        })
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            try:
                import os
                os.chdir(tmp)
                with patch.object(cli, "request", return_value=info), \
                        patch.object(cli, "urlopen", return_value=response):
                    code, _, _ = run(["download", "--id", "436799"])
                landed = sorted(p.name for p in Path(tmp).iterdir())
            finally:
                os.chdir(cwd)

        self.assertEqual(code, 0)
        self.assertEqual(landed, ["escaped.wav"])

    def test_a_non_numeric_id_is_rejected_before_any_request(self):
        with patch.object(cli, "request") as request:
            with self.assertRaises(SystemExit):
                run(["download", "--id", "not-an-id"])
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
