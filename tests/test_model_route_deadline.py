import os
import threading
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
for flag in ("PROACTIVE_ENABLED", "PROACTIVE_BACKGROUND_ENABLED", "GIST_HISTORY_IO_ENABLED", "MEMORY_RECALL_ENABLED"):
    os.environ[flag] = "false"

import bot


class ModelRouteDeadlineTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {
            "CLAUDE_URL": "https://primary.invalid/v1", "CLAUDE_KEY": "test",
            "CLAUDE_MODELS": ["primary-one", "primary-two"], "API_FORMAT": "openai",
            "BACKUP_BASE_URL": "https://backup.invalid/v1", "BACKUP_API_KEY": "test",
            "BACKUP_MODELS": ["backup"], "BACKUP_API_FORMAT": "openai", "CECI_SEEN": {},
        }.items():
            self.stack.enter_context(mock.patch.object(bot, name, value))
        for name in ("build_cross_chat_context", "build_group_identity_hint"):
            self.stack.enter_context(mock.patch.object(bot, name, return_value=""))
        self.stack.enter_context(mock.patch.object(bot, "_hub_process_capabilities", side_effect=lambda text: text))
        self.stack.enter_context(mock.patch.object(bot, "_record_outbound_hard_timeout"))
        self.stack.enter_context(mock.patch.object(bot, "_model_api_hard_timeout", return_value=20.0))

    @staticmethod
    def response(text):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": text}}]}
        return response

    def call(self):
        return bot.call_claude("hello", "", [{"role": "user", "content": "hello"}], "", chat_id="123")

    def test_primary_success_after_twelve_seconds_within_budget(self):
        for api_format in ("openai", "anthropic"):
            now = [100.0]

            def post_response(url, **kwargs):
                self.assertGreater(kwargs["timeout"][1], 12)
                self.assertLessEqual(kwargs["timeout"][1], 20)
                now[0] += 15
                return self.response("ok")

            with self.subTest(api_format=api_format), \
                    mock.patch.object(bot, "API_FORMAT", api_format), \
                    mock.patch.object(bot.time, "monotonic", side_effect=lambda: now[0]), \
                    mock.patch.object(bot.requests, "post", side_effect=post_response) as post:
                self.assertEqual(self.call()["text"], "ok")
                self.assertEqual(post.call_count, 1)
                self.assertIn("primary.invalid", post.call_args.args[0])

    def test_failures_fall_back_serially(self):
        with mock.patch.object(bot.requests, "post", side_effect=[
            bot.requests.exceptions.Timeout(), bot.requests.exceptions.Timeout(), self.response("backup")
        ]) as post:
            self.assertEqual(self.call()["text"], "backup")
        self.assertEqual([c.kwargs["json"]["model"] for c in post.call_args_list],
                         ["primary-one", "primary-two", "backup"])

    def test_late_result_stops_remaining_primary_models(self):
        now = [100.0]

        def post_response(url, **kwargs):
            if "primary.invalid" in url:
                now[0] += 21
                return self.response("late")
            return self.response("backup")

        with mock.patch.object(bot.time, "monotonic", side_effect=lambda: now[0]), \
                mock.patch.object(bot.requests, "post", side_effect=post_response) as post:
            self.assertEqual(self.call()["text"], "backup")
            self.assertEqual(post.call_count, 2)

    def test_outer_deadline_survives_unresponsive_transport(self):
        release = threading.Event()
        finished = threading.Event()

        def post_response(url, **kwargs):
            if "primary.invalid" in url:
                release.wait(timeout=2)
                finished.set()
                return self.response("late")
            return self.response("backup")

        with mock.patch.object(bot, "_model_api_hard_timeout", return_value=0.03), \
                mock.patch.object(bot.requests, "post", side_effect=post_response):
            try:
                self.assertEqual(self.call()["text"], "backup")
                self.assertFalse(finished.is_set())
            finally:
                release.set()
                self.assertTrue(finished.wait(timeout=1))


if __name__ == "__main__":
    unittest.main()
