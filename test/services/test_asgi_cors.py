import unittest
from unittest.mock import Mock

from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from app import asgi


class TestASGICORS(unittest.TestCase):
    """验证浏览器跨域默认值和显式兼容配置，避免重新引入开放 CORS。"""

    @staticmethod
    def _create_client(allowed_origins: list[str]) -> TestClient:
        """构造只包含探针路由的应用，隔离业务任务和外部 API 调用。"""

        application = FastAPI()

        @application.get("/probe")
        def probe():
            return {"status": "ok"}

        asgi.configure_browser_access(application, allowed_origins)
        return TestClient(application, base_url="http://localhost")

    def test_origin_parser_trims_values_and_ignores_empty_items(self):
        """环境变量中的空格和尾随逗号不应破坏合法来源匹配。"""

        origins = asgi.parse_cors_allowed_origins(
            " https://a.example,https://b.example, ,"
        )

        self.assertEqual(
            origins,
            ["https://a.example", "https://b.example"],
        )
        self.assertEqual(asgi.parse_cors_allowed_origins(""), [])
        self.assertEqual(asgi.parse_cors_allowed_origins(None), [])

    def test_empty_configuration_keeps_browser_same_origin_policy(self):
        """未配置白名单时，第三方网页不能读取响应或通过预检。"""

        client = self._create_client([])
        origin = "https://evil.attacker.example"

        response = client.get("/probe", headers={"Origin": origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(preflight.status_code, 403)
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    def test_same_origin_and_server_clients_remain_compatible(self):
        """同源浏览器和不发送 Origin 的服务端客户端必须继续正常访问。"""

        client = self._create_client([])

        same_origin = client.get(
            "/probe",
            headers={"Origin": "http://localhost"},
        )
        server_client = client.get("/probe")

        self.assertEqual(same_origin.status_code, 200)
        self.assertEqual(server_client.status_code, 200)

    def test_untrusted_host_is_rejected_without_api_key(self):
        """未配置 api_key 时，局域网 Host 和 DNS 重绑定域名都必须被拒绝。"""

        from app.config import config

        original_key = config.app.get("api_key", "")
        config.app["api_key"] = ""
        try:
            application = FastAPI()

            @application.get("/probe")
            def probe():
                return {"status": "ok"}

            asgi.configure_browser_access(application, [], {"mpt.lan"})

            for base_url in ("http://localhost", "http://127.0.0.1:8080",
                             "http://mpt.lan:8080"):
                with self.subTest(base_url=base_url):
                    client = TestClient(application, base_url=base_url)
                    self.assertEqual(client.get("/probe").status_code, 200)

            for base_url in ("http://192.168.1.20:8080", "http://evil.example:8080"):
                with self.subTest(base_url=base_url):
                    client = TestClient(application, base_url=base_url)
                    # 重绑定场景下 Origin 与 Host 相同，旧的同源比较会放行。
                    response = client.get(
                        "/probe", headers={"Origin": base_url}
                    )
                    self.assertEqual(response.status_code, 403)

            # TestClient 无法解析 IPv6 base_url，直接构造请求验证 [::1]。
            from starlette.requests import Request

            ipv6_request = Request(
                {
                    "type": "http",
                    "scheme": "http",
                    "path": "/probe",
                    "query_string": b"",
                    "headers": [(b"host", b"[::1]:8080")],
                    "server": ("::1", 8080),
                }
            )
            self.assertTrue(asgi.is_request_host_allowed(ipv6_request, set()))

            config.app["api_key"] = "host-secret"
            client = TestClient(application, base_url="http://192.168.1.20:8080")
            self.assertEqual(client.get("/probe").status_code, 200)
        finally:
            config.app["api_key"] = original_key

    def test_allowed_hosts_parser_accepts_strings_and_lists(self):
        self.assertEqual(
            asgi.parse_allowed_hosts(" A.example, ,b.example "),
            {"a.example", "b.example"},
        )
        self.assertEqual(asgi.parse_allowed_hosts(["x.lan", 3, ""]), {"x.lan"})
        self.assertEqual(asgi.parse_allowed_hosts(None), set())

    def test_explicit_origin_allows_only_the_trusted_frontend(self):
        """独立网页前端显式配置后可以访问，其他来源仍必须被拒绝。"""

        trusted_origin = "https://frontend.example"
        untrusted_origin = "https://evil.attacker.example"
        client = self._create_client([trusted_origin])

        trusted = client.get("/probe", headers={"Origin": trusted_origin})
        untrusted = client.get("/probe", headers={"Origin": untrusted_origin})
        trusted_preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        untrusted_preflight = client.options(
            "/probe",
            headers={
                "Origin": untrusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(trusted.headers["access-control-allow-origin"], trusted_origin)
        self.assertEqual(trusted.headers["access-control-allow-credentials"], "true")
        self.assertNotIn("access-control-allow-origin", untrusted.headers)
        self.assertEqual(trusted_preflight.status_code, 200)
        self.assertEqual(untrusted_preflight.status_code, 400)

    def test_trusted_origin_can_request_private_network_access(self):
        """精确白名单应支持远程网页访问本机或局域网 API 的额外预检。"""

        trusted_origin = "https://frontend.example"
        client = self._create_client([trusted_origin])

        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )

        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-private-network"],
            "true",
        )

    def test_explicit_wildcard_does_not_enable_credentials(self):
        """显式通配符保留兼容能力，但不得再次形成反射 Origin 的组合。"""

        client = self._create_client(["*"])
        origin = "https://frontend.example"

        response = client.get("/probe", headers={"Origin": origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", preflight.headers)

    def test_untrusted_multipart_request_is_rejected_before_side_effect(self):
        """无需预检的 multipart 请求也必须在进入上传处理函数前返回 403。"""

        application = FastAPI()
        save_upload = Mock(return_value="stored.mp3")

        @application.post("/upload")
        def upload(file: UploadFile = File(...)):
            return {"file": save_upload(file.filename)}

        asgi.configure_browser_access(application, [])
        client = TestClient(application, base_url="http://localhost")

        response = client.post(
            "/upload",
            headers={"Origin": "https://evil.attacker.example"},
            files={
                "file": (
                    "attack.mp3",
                    b"attacker-controlled",
                    "audio/mpeg",
                )
            },
        )

        self.assertEqual(response.status_code, 403)
        save_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
