import unittest
from backend.gateway.image_tool_feedback import classify_error

class ErrorCategories(unittest.TestCase):
    def test_long_policy_code_survives_truncation(self):
        raw="ImageProviderError: image API HTTP 400: " + "echoed prompt " * 250 + " (type=invalid_request_error, code=content_policy_violation)"
        category,detail=classify_error(raw)
        self.assertEqual(category,"moderation_block")
        self.assertIn("content_policy_violation",detail)
    def test_echo_is_not_moderation(self):
        for text in ("nsfw", "sexual content", "content_policy_violation", "quota", "timeout"):
            self.assertEqual(classify_error("image API HTTP 400: prompt="+text+" (type=invalid_request_error, code=invalid_value)")[0],"unknown_provider_error")
    def test_status(self):
        for n,expected in [(400,"unknown_provider_error"),(401,"auth_error"),(403,"auth_error"),(429,"quota_error"),(500,"service_unavailable"),(503,"service_unavailable"),(504,"timeout")]:
            self.assertEqual(classify_error(f"image API HTTP {n}: error")[0],expected)
