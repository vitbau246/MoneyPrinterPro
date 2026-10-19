import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests
import urllib3

from app.services import voice


def _response(status_code=200, content=b"", json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.text = "error"
    response.json.return_value = json_body or {}
    return response


def _connect_refused():
    reason = urllib3.exceptions.NewConnectionError(None, "connection refused")
    return requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(None, "/", reason=reason)
    )


class TestRetryClassification(unittest.TestCase):
    def test_only_connect_phase_errors_are_retryable(self):
        self.assertTrue(
            voice._is_tts_request_error_retryable(requests.exceptions.ConnectTimeout())
        )
        self.assertTrue(voice._is_tts_request_error_retryable(_connect_refused()))
        # 请求已发出后的失败可能已经计费，不能自动重试。
        self.assertFalse(
            voice._is_tts_request_error_retryable(requests.exceptions.ReadTimeout())
        )
        self.assertFalse(
            voice._is_tts_request_error_retryable(
                requests.exceptions.ConnectionError("connection reset by peer")
            )
        )
        self.assertFalse(
            voice._is_tts_request_error_retryable(
                requests.exceptions.ChunkedEncodingError()
            )
        )


class TestPaidTtsDoesNotRebuy(unittest.TestCase):
    """付费 TTS 在请求可能已被处理后不能重新提交，避免重复扣费。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.voice_file = os.path.join(self._tmp.name, "voice.mp3")

    def tearDown(self):
        self._tmp.cleanup()

    def _siliconflow(self):
        with patch.dict(voice.config.siliconflow, {"api_key": "sk-test"}):
            return voice.siliconflow_tts(
                text="hello",
                model="FunAudioLLM/CosyVoice2-0.5B",
                voice="FunAudioLLM/CosyVoice2-0.5B:alex",
                voice_rate=1.0,
                voice_file=self.voice_file,
            )

    def test_siliconflow_read_timeout_is_not_retried(self):
        with patch.object(
            voice.requests, "post", side_effect=requests.exceptions.ReadTimeout()
        ) as post:
            self.assertIsNone(self._siliconflow())
        self.assertEqual(post.call_count, 1)
        self.assertIsNotNone(post.call_args.kwargs.get("timeout"))

    def test_siliconflow_connect_failure_is_retried(self):
        with patch.object(
            voice.requests, "post", side_effect=_connect_refused()
        ) as post:
            self.assertIsNone(self._siliconflow())
        self.assertEqual(post.call_count, 3)

    def test_siliconflow_unreadable_audio_after_200_fails_without_retry(self):
        with (
            patch.object(
                voice.requests, "post", return_value=_response(200, b"not audio")
            ) as post,
            patch.object(voice, "AudioFileClip", side_effect=OSError("bad audio")),
        ):
            self.assertIsNone(self._siliconflow())
        self.assertEqual(post.call_count, 1)

    def test_siliconflow_client_error_is_not_retried_but_5xx_is(self):
        with patch.object(
            voice.requests, "post", return_value=_response(400)
        ) as post:
            self.assertIsNone(self._siliconflow())
        self.assertEqual(post.call_count, 1)

        with patch.object(
            voice.requests, "post", return_value=_response(503)
        ) as post:
            self.assertIsNone(self._siliconflow())
        self.assertEqual(post.call_count, 3)

    def test_elevenlabs_unreadable_audio_after_200_fails_without_retry(self):
        with (
            patch.object(voice, "get_elevenlabs_api_key", return_value="xi-test"),
            patch.object(
                voice.requests, "post", return_value=_response(200, b"not audio")
            ) as post,
            patch.object(voice, "AudioFileClip", side_effect=OSError("bad audio")),
        ):
            result = voice.elevenlabs_tts(
                text="hello", voice_id="voice", voice_file=self.voice_file
            )
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 1)


    def test_elevenlabs_402_library_voice_is_not_retried(self):
        body = {
            "detail": {
                "code": "paid_plan_required",
                "status": "payment_required",
            }
        }
        with (
            patch.object(voice, "get_elevenlabs_api_key", return_value="xi-test"),
            patch.object(
                voice.requests, "post", return_value=_response(402, json_body=body)
            ) as post,
        ):
            result = voice.elevenlabs_tts(
                text="hello", voice_id="voice", voice_file=self.voice_file
            )
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 1)


class TestEdgeTtsNetwork(unittest.TestCase):
    """企业代理网络下 Edge TTS 的 WebSocket 必须显式走代理。"""

    def test_proxy_prefers_config_then_environment(self):
        with patch.object(voice.config, "proxy", {"https": "http://cfg:1"}):
            self.assertEqual(voice._get_edge_tts_proxy(), "http://cfg:1")
        with (
            patch.object(voice.config, "proxy", {}),
            patch.object(
                voice.urllib.request,
                "getproxies",
                return_value={"https": "http://env:2"},
            ),
            patch.object(voice.urllib.request, "proxy_bypass", return_value=False),
        ):
            self.assertEqual(voice._get_edge_tts_proxy(), "http://env:2")
        with (
            patch.object(voice.config, "proxy", {}),
            patch.object(
                voice.urllib.request,
                "getproxies",
                return_value={"https": "http://env:2"},
            ),
            patch.object(voice.urllib.request, "proxy_bypass", return_value=True),
        ):
            self.assertIsNone(voice._get_edge_tts_proxy())

    def test_proxy_list_from_app_config(self):
        with patch.dict(voice.config.app, {"edge_tts_proxies": ["http://a:1", " ", "http://b:2"]}):
            self.assertEqual(voice._get_edge_tts_proxies(), ["http://a:1", "http://b:2"])
        with (
            patch.dict(voice.config.app, {"edge_tts_proxies": []}),
            patch.object(voice, "_get_edge_tts_proxy", return_value="http://p:3"),
        ):
            self.assertEqual(voice._get_edge_tts_proxies(), ["http://p:3"])

    def test_tts_rotates_proxies_three_tries_each(self):
        used = []

        def fake_communicate(text, voice_name, rate_str, proxy=None):
            used.append(proxy)
            raise TimeoutError("stalled")

        with (
            patch.object(voice, "_get_edge_tts_proxies", return_value=["http://a:1", "http://b:2"]),
            patch.object(voice, "create_edge_tts_communicate", side_effect=fake_communicate),
        ):
            result = voice.azure_tts_v1("xin chào", "vi-VN-HoaiMyNeural-Female", 1.0, os.devnull)
        self.assertIsNone(result)
        self.assertEqual(used, ["http://a:1"] * 3 + ["http://b:2"] * 3)

    def test_communicate_receives_proxy(self):
        with patch.object(voice, "_get_edge_tts_proxy", return_value="http://p:3"):
            communicate = voice.create_edge_tts_communicate(
                "xin chào", "vi-VN-HoaiMyNeural", "+0%"
            )
        self.assertEqual(communicate.proxy, "http://p:3")

    def test_timeout_resets_while_data_keeps_arriving(self):
        """总耗时超过超时值但持续有数据时不应失败；真正停滞时仍应超时。"""
        import time as real_time

        class SlowCommunicate:
            def __init__(self, stall_after=None):
                self.stall_after = stall_after

            def stream_sync(self):
                for index in range(6):
                    if self.stall_after is not None and index == self.stall_after:
                        real_time.sleep(5)
                    real_time.sleep(0.1)
                    yield {"type": "audio", "data": b"x"}

        chunks = []
        voice._stream_edge_tts_sync_with_timeout(
            SlowCommunicate(), chunks.append, timeout_seconds=0.3
        )
        self.assertEqual(len(chunks), 6)

        with self.assertRaises(TimeoutError):
            voice._stream_edge_tts_sync_with_timeout(
                SlowCommunicate(stall_after=2), lambda _chunk: None, timeout_seconds=0.3
            )


if __name__ == "__main__":
    unittest.main()
