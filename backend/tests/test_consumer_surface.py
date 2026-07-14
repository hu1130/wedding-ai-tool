import html
import re
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency guard for bare Python envs
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSUMER_SOURCE = PROJECT_ROOT / "frontend" / "src" / "ConsumerApp.tsx"

INTERNAL_TERMS = [
    "稳定演示模式",
    "保脸优先",
    "1K 高清",
    "后端在线",
    "进入测试台",
    "任务",
    "交付包",
    "API",
    "后台",
    "task_id",
    "队列",
    "可交付",
]

WORKS_FILTER_COPY = [
    "全部",
    "最近 7 天",
    "本月",
    "按婚纱或场景查找",
    "查看全部",
]


def read_consumer_source() -> str:
    return CONSUMER_SOURCE.read_text(encoding="utf-8")


def strip_consumer_guard_terms(source: str) -> str:
    """The guard list stores blocked terms for sanitizing old task names."""
    marker = "const consumerHiddenTerms = ["
    start = source.find(marker)
    if start == -1:
        return source
    end = source.find("];", start)
    if end == -1:
        return source
    return source[:start] + source[end + 2 :]


def visible_consumer_fragments(source: str) -> list[str]:
    source = strip_consumer_guard_terms(source)
    fragments: list[str] = []

    for match in re.finditer(r">([^<>{}][^<{}]*)<", source, flags=re.DOTALL):
        text = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
        if text:
            fragments.append(text)

    string_pattern = re.compile(r"(?P<quote>[\"'`])(?P<value>(?:\\.|(?!\1).)*?)(?P=quote)", re.DOTALL)
    for match in string_pattern.finditer(source):
        value = match.group("value").strip()
        if "/api/" in value or value.startswith("/api"):
            continue
        if value:
            fragments.append(value)

    return fragments


class ConsumerSurfaceTest(unittest.TestCase):
    def test_consumer_visible_copy_does_not_expose_internal_terms(self):
        surface_text = "\n".join(visible_consumer_fragments(read_consumer_source()))
        leaked_terms = [term for term in INTERNAL_TERMS if term in surface_text]
        self.assertEqual([], leaked_terms, f"C端可见文案含内部词: {leaked_terms}")

    def test_works_filter_copy_is_present(self):
        source = read_consumer_source()
        missing_copy = [text for text in WORKS_FILTER_COPY if text not in source]
        self.assertEqual([], missing_copy, f"作品页筛选文案缺失: {missing_copy}")


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class ConsumerSpaRouteTest(unittest.TestCase):
    def test_spa_routes_return_html(self):
        from backend.main import app

        client = TestClient(app)
        for route in ["/", "/works", "/help", "/studio", "/test"]:
            with self.subTest(route=route):
                response = client.get(route)
                self.assertEqual(200, response.status_code)
                self.assertIn("text/html", response.headers.get("content-type", ""))
                self.assertIn("<html", response.text.lower())


if __name__ == "__main__":
    unittest.main()
