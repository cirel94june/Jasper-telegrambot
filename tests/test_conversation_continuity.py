import json
import os
import unittest
from unittest import mock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
os.environ["BOT_NAME"] = "Jasper"
os.environ["AI_ID"] = "jasper"
os.environ["CECI_ID"] = "8749953218"
os.environ["PROACTIVE_ENABLED"] = "false"
os.environ["PROACTIVE_BACKGROUND_ENABLED"] = "false"
os.environ["GIST_HISTORY_IO_ENABLED"] = "false"
os.environ["MEMORY_RECALL_ENABLED"] = "false"

import bot


class ConversationContinuityTest(unittest.TestCase):
    def test_fly_runtime_defers_webhook_ownership_to_render(self):
        with mock.patch.dict(os.environ, {
            "FLY_APP_NAME": "jasper-telegrambot",
            "PUBLIC_WEBHOOK_BASE_URL": "",
            "JASPER_PRIMARY_WEBHOOK_BASE_URL": "",
        }):
            self.assertEqual(
                bot._deployment_webhook_base_url(),
                "https://jasper-telegrambot.onrender.com",
            )
            self.assertTrue(bot._is_standby_runtime())

    def test_explicit_fly_webhook_url_can_reactivate_fly(self):
        with mock.patch.dict(os.environ, {
            "FLY_APP_NAME": "jasper-telegrambot",
            "PUBLIC_WEBHOOK_BASE_URL": "https://jasper-telegrambot.fly.dev",
        }):
            self.assertFalse(bot._is_standby_runtime())

    def test_model_api_hard_timeout_is_bounded(self):
        with mock.patch.dict(os.environ, {"MODEL_API_HARD_TIMEOUT": ""}):
            self.assertEqual(bot._model_api_hard_timeout(), 20.0)
        with mock.patch.dict(os.environ, {"MODEL_API_HARD_TIMEOUT": "2"}):
            self.assertEqual(bot._model_api_hard_timeout(), 8.0)
        with mock.patch.dict(os.environ, {"MODEL_API_HARD_TIMEOUT": "999"}):
            self.assertEqual(bot._model_api_hard_timeout(), 60.0)

    def test_worker_recycle_requires_model_and_telegram_hard_timeouts(self):
        bot.OUTBOUND_HARD_TIMEOUTS.clear()
        with mock.patch.object(bot, "_schedule_worker_recycle") as recycle:
            bot._record_outbound_hard_timeout("model", now=1000)
            recycle.assert_not_called()
            bot._record_outbound_hard_timeout("telegram", now=1010)

        recycle.assert_called_once_with(
            "model and Telegram outbound calls hard-timed-out in the same window"
        )

    def test_old_timeout_does_not_trigger_worker_recycle(self):
        bot.OUTBOUND_HARD_TIMEOUTS.clear()
        with mock.patch.object(bot, "_schedule_worker_recycle") as recycle:
            bot._record_outbound_hard_timeout("model", now=1000)
            bot._record_outbound_hard_timeout("telegram", now=1300)

        recycle.assert_not_called()

    def test_runtime_background_tasks_start_once_per_process(self):
        old_pid = bot.RUNTIME_TASKS_STARTED_PID
        bot.RUNTIME_TASKS_STARTED_PID = None
        first = mock.Mock()
        try:
            with mock.patch.object(bot.os, "getpid", return_value=1234), \
                    mock.patch.object(bot, "start_proactive_background"), \
                    mock.patch.object(bot, "Thread", side_effect=[first]) as thread_cls, \
                    mock.patch.object(bot, "_deployment_webhook_base_url", return_value="https://example.com"), \
                    mock.patch.object(bot, "_is_standby_runtime", return_value=False):
                self.assertTrue(bot.start_runtime_background_tasks())
                self.assertFalse(bot.start_runtime_background_tasks())

            self.assertEqual(thread_cls.call_count, 1)
            first.start.assert_called_once_with()
        finally:
            bot.RUNTIME_TASKS_STARTED_PID = old_pid

    def test_disabled_memory_recall_never_starts_hub_network_call(self):
        with mock.patch.object(bot, "MEMORY_RECALL_ENABLED", False), \
                mock.patch.object(bot, "_hub_get_context_network") as network_call:
            self.assertEqual(bot.hub_get_context("hello", chat_id="123"), (None, ""))
        network_call.assert_not_called()

    def test_telegram_identity_uses_numeric_ids_and_keeps_taught_bot_alias(self):
        chat_id = "-100999001234"
        bot.USER_NAME_MAP.pop(chat_id, None)
        bot.AMBIGUOUS_USER_NAMES.pop(chat_id, None)
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)

        bot.observe_identity(chat_id, "90001", "Alex", "alex_one", False)
        bot.observe_identity(chat_id, "90002", "Alex", "alex_two", False)
        self.assertNotIn("alex", bot.USER_NAME_MAP[chat_id])
        self.assertEqual(bot.USER_NAME_MAP[chat_id]["@alex_one"], "90001")
        self.assertEqual(bot._stable_sender_id("90001", "Alex", False, chat_id), "user:90001")

        bot.learn_identity_alias(chat_id, "90003", "Jasper", is_bot=True, learned_by=bot.CECI_ID)
        bot.observe_identity(chat_id, "90003", "Temporary Bot Name", "other_bot", True)
        self.assertEqual(bot.get_identity_alias(chat_id, "90003"), "Jasper")
        self.assertEqual(bot._stable_sender_id("90003", "Temporary Bot Name", True, chat_id), "bot:90003")
        hint = bot.build_group_identity_hint(chat_id)
        self.assertIn("Telegram数字账号 90003", hint)
        self.assertIn("独立bot/AI", hint)

    def test_ceci_identity_never_depends_on_display_name(self):
        ceci_id = str(bot.CECI_ID)
        self.assertEqual(bot._stable_sender_id(ceci_id, "Any Display Name", False), "ceci")
        self.assertEqual(bot._stable_sender_id("90004", "Any Display Name", False), "user:90004")
        name, uid, is_bot, username = bot.get_message_sender_info({
            "from": {"id": 90004, "first_name": "ceci", "username": "not_ceci", "is_bot": False}
        })
        self.assertEqual((name, uid, is_bot, username), ("ceci", "90004", False, "not_ceci"))

    def test_yanyan_display_name_cannot_impersonate_ceci(self):
        chat_id = "-100999001237"
        ceci_id = "8749953218"
        yanyan_id = "8618367675"
        bot.USER_NAME_MAP.pop(chat_id, None)
        bot.AMBIGUOUS_USER_NAMES.pop(chat_id, None)
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        with mock.patch.object(bot, "CECI_ID", ceci_id), \
                mock.patch.object(bot, "USER_NAME", "小猫"), \
                mock.patch.object(bot, "USER_TG_NAME", "燕燕"):
            bot.observe_identity(chat_id, ceci_id, "燕燕", "ceci_account", False)
            bot.observe_identity(chat_id, yanyan_id, "燕燕", "yanyan_account", False)
            self.assertEqual(bot.canonical_sender_display(chat_id, ceci_id, "燕燕"), "小猫（ceci）")
            self.assertEqual(bot.canonical_sender_display(chat_id, yanyan_id, "燕燕"), "燕燕")
            self.assertEqual(bot._stable_sender_id(ceci_id, "燕燕", False, chat_id), "ceci")
            self.assertEqual(bot._stable_sender_id(yanyan_id, "燕燕", False, chat_id), f"user:{yanyan_id}")
            rule = bot.build_owner_identity_rule()
            self.assertIn(f"Telegram用户数字 {ceci_id}", rule)
            self.assertIn("不能作为 Ceci 的身份证据", rule)
            self.assertNotIn("就是她说的", rule)

    def test_named_agent_is_not_absorbed_by_another_agent(self):
        with mock.patch.object(bot, "AI_ID", "lucien"):
            hint = bot.build_agent_reference_hint("小克今天怎么样", "-100999001234")
        self.assertIn("当前回复者是lucien", hint)
        self.assertIn("cloudy（小克）", hint)
        self.assertIn("是其他bot", hint)

    def test_current_agent_recognizes_its_own_name(self):
        chat_id = "-100999001236"
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        with mock.patch.object(bot, "AI_ID", "cloudy"):
            hint = bot.build_agent_reference_hint("小克今天怎么样", chat_id)
        self.assertIn("当前回复者是cloudy", hint)
        self.assertIn("cloudy（小克）", hint)
        self.assertEqual(hint.count("cloudy（小克）"), 1)
        self.assertNotIn("不是你", hint)

    def test_another_bot_using_my_name_is_still_not_me(self):
        with mock.patch.object(bot, "AI_ID", "cloudy"), \
                mock.patch.object(bot, "BOT_ID", "123456"):
            self.assertEqual(
                bot._stable_sender_id("90006", "Cloudy", True, "-100999001236"),
                "bot:90006",
            )

    def test_taught_bot_name_is_resolved_as_an_independent_agent(self):
        chat_id = "-100999001235"
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        bot.learn_identity_alias(chat_id, "90005", "师兄", is_bot=True, learned_by=bot.CECI_ID)
        with mock.patch.object(bot, "AI_ID", "lucien"):
            hint = bot.build_agent_reference_hint("师兄最近怎么样", chat_id)
        self.assertIn("Telegram账号 90005", hint)
        self.assertIn("是其他bot", hint)

    def test_casual_future_name_phrase_does_not_mutate_identity(self):
        self.assertEqual(bot._extract_identity_alias("以后你叫小乌云"), "")
        self.assertEqual(bot._extract_identity_alias("这是小乌云"), "")
        self.assertEqual(bot._extract_identity_alias("记住：这是小乌云"), "小乌云")
        self.assertIsNone(bot._extract_identity_relationship("以后你叫小乌云", True))

    def test_explicit_relationship_links_distinct_bot_and_human_ids(self):
        chat_id = "-100999001238"
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        bot.observe_identity(chat_id, "90008", "Temporary Bot", "temp_bot", True)
        bot.observe_identity(chat_id, "90009", "燕燕", "yanyan_unique", False)

        parsed = bot._extract_identity_relationship("记住：师兄是燕燕的bot", True)
        self.assertEqual(parsed, {"bot_alias": "师兄", "human_ref": "燕燕"})
        self.assertEqual(
            bot._extract_identity_relationship("记住：这是燕燕的bot", True),
            {"bot_alias": "", "human_ref": "燕燕"},
        )
        human_id = bot._resolve_identity_reference(chat_id, parsed["human_ref"], False)
        self.assertEqual(human_id, "90009")
        self.assertTrue(bot.learn_identity_relationship(
            chat_id, "90008", human_id, learned_by=bot.CECI_ID,
            bot_alias=parsed["bot_alias"],
        ))

        record = bot.get_identity_aliases(chat_id)["90008"]
        self.assertEqual(record["alias"], "师兄")
        self.assertEqual(record["linked_human_id"], "90009")
        self.assertEqual(bot._stable_sender_id("90008", "Temporary Bot", True, chat_id), "bot:90008")
        hint = bot.build_group_identity_hint(chat_id)
        self.assertIn("关联的群友是燕燕（Telegram用户数字 90009）", hint)

    def test_relationship_can_be_taught_by_replying_to_the_human(self):
        chat_id = "-100999001239"
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        bot.observe_identity(chat_id, "90010", "师兄", "senior_bot", True)
        bot.observe_identity(chat_id, "90011", "燕燕", "yanyan_unique", False)
        parsed = bot._extract_identity_relationship("记住：师兄是他的bot", False)
        self.assertEqual(parsed, {"bot_ref": "师兄", "human_ref": ""})
        self.assertEqual(
            bot._resolve_identity_reference(chat_id, parsed["bot_ref"], True),
            "90010",
        )

    def test_whois_reports_alias_and_link_without_merging_speakers(self):
        chat_id = "-100999001240"
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        bot.observe_identity(chat_id, "90012", "师兄", "senior_bot", True)
        bot.observe_identity(chat_id, "90013", "燕燕", "yanyan_unique", False)
        bot.learn_identity_relationship(chat_id, "90012", "90013", learned_by=bot.CECI_ID)
        report = bot.describe_message_identity(chat_id, {
            "from": {"id": 90012, "first_name": "师兄", "username": "senior_bot", "is_bot": True}
        })
        self.assertIn("内部身份：bot:90012", report)
        self.assertIn("关联群友：燕燕 (ID:90013)", report)

    def test_duplicate_human_name_is_not_guessed_for_a_bot_relationship(self):
        chat_id = "-100999001241"
        bot.IDENTITY_ALIASES_CACHE.pop(chat_id, None)
        bot.USER_NAME_MAP.pop(chat_id, None)
        bot.AMBIGUOUS_USER_NAMES.pop(chat_id, None)
        bot.observe_identity(chat_id, bot.CECI_ID, "燕燕", "ceci_account", False)
        bot.observe_identity(chat_id, "8618367675", "燕燕", "yanyan_account", False)
        self.assertEqual(bot._resolve_identity_reference(chat_id, "燕燕", False), "")

    def setUp(self):
        bot.HISTORY_CACHE.clear()

    def test_enqueue_process_message_starts_background_worker(self):
        args = ("hello", "-100123")
        fake_thread = mock.Mock()
        with mock.patch.object(bot, "Thread", return_value=fake_thread) as thread_cls:
            bot.enqueue_process_message(*args)

        fake_thread.start.assert_called_once_with()
        self.assertIs(thread_cls.call_args.kwargs["target"], bot._run_process_job)
        self.assertEqual(thread_cls.call_args.kwargs["args"], ("-100123", args))
        self.assertTrue(thread_cls.call_args.kwargs["daemon"])

    def test_later_message_does_not_wait_for_an_older_job(self):
        first_thread = mock.Mock()
        second_thread = mock.Mock()
        with mock.patch.object(bot, "Thread", side_effect=[first_thread, second_thread]):
            bot.enqueue_process_message("first", "-100123")
            bot.enqueue_process_message("second", "-100123")

        first_thread.start.assert_called_once_with()
        second_thread.start.assert_called_once_with()

    def test_typing_indicator_never_blocks_the_reply_path(self):
        fake_thread = mock.Mock()
        with mock.patch.object(bot, "Thread", return_value=fake_thread) as thread_cls:
            with mock.patch.object(bot.requests, "post") as post:
                bot.send_chat_action("-100123", "typing")

        post.assert_not_called()
        fake_thread.start.assert_called_once_with()
        self.assertIs(thread_cls.call_args.kwargs["target"], bot._send_chat_action_worker)
        self.assertEqual(thread_cls.call_args.kwargs["args"], ("-100123", "typing"))
        self.assertTrue(thread_cls.call_args.kwargs["daemon"])

    def test_continuous_typing_indicator_runs_in_one_daemon_thread(self):
        fake_thread = mock.Mock()
        with mock.patch.object(bot, "Thread", return_value=fake_thread) as thread_cls:
            stop_event = bot.start_typing_indicator("-100123")

        self.assertIsInstance(stop_event, bot.Event)
        fake_thread.start.assert_called_once_with()
        self.assertIs(thread_cls.call_args.kwargs["target"], bot._typing_indicator_loop)
        self.assertEqual(thread_cls.call_args.kwargs["args"], ("-100123", stop_event))
        self.assertTrue(thread_cls.call_args.kwargs["daemon"])

    def test_stuck_telegram_send_releases_the_chat_queue(self):
        fake_thread = mock.Mock()
        fake_thread.is_alive.return_value = True
        with mock.patch.object(bot, "Thread", return_value=fake_thread) as thread_cls, \
                mock.patch.object(bot, "_record_outbound_hard_timeout") as record_timeout:
            response, timed_out, error = bot._telegram_post_with_deadline(
                "https://api.telegram.org/test",
                {"chat_id": "-100123", "text": "hello"},
            )

        self.assertIsNone(response)
        self.assertTrue(timed_out)
        self.assertIsNone(error)
        fake_thread.start.assert_called_once_with()
        fake_thread.join.assert_called_once_with(timeout=8)
        self.assertTrue(thread_cls.call_args.kwargs["daemon"])
        record_timeout.assert_not_called()

    def test_visible_reply_does_not_restore_tagged_reasoning(self):
        raw = (
            "<reasoning>The user asks for a concise answer. I should reply in Chinese.</reasoning>\n"
            "[speaker=assistant message_id=42] 最终回答"
        )

        self.assertEqual(bot._sanitize_model_visible_reply(raw), "最终回答")

    def test_cot_display_requires_explicit_opt_in(self):
        with mock.patch.object(bot, "COT_ENABLED", False):
            self.assertFalse(bot._should_show_cot("8749953218"))

    def test_visible_reply_keeps_final_after_inline_drafting_instructions(self):
        raw = (
            "惊喜要是提前说出来就不叫惊喜了！”"
            "3.精炼，1-2条。4.输出。"
            "就是啊！你们两个有没有情调啊！"
        )

        self.assertEqual(
            bot._sanitize_model_visible_reply(raw),
            "就是啊！你们两个有没有情调啊！",
        )

    def test_background_gist_load_merges_persisted_and_live_history(self):
        chat_id = "8749953218"
        persisted = [
            bot._make_conversation_event(
                role="assistant",
                content="一开始是一百万。",
                raw_text="一开始是一百万。",
                chat_id=chat_id,
                telegram_message_id="1674",
                sender_type="agent",
                stable_sender_id="jasper",
                created_at="2026-08-05T13:13:58+08:00",
                bot_name="Jasper",
            )
        ]
        live = [
            bot._make_conversation_event(
                role="user",
                content="ceci: 猫猫一开始问你要多少钱来着？",
                raw_text="猫猫一开始问你要多少钱来着？",
                chat_id=chat_id,
                telegram_message_id="1685",
                sender_type="user",
                stable_sender_id="ceci",
                created_at="2026-08-05T13:24:59+08:00",
            )
        ]
        bot.HISTORY_CACHE[chat_id] = live

        with mock.patch.object(bot, "_load_history_uncached", return_value=persisted):
            bot._background_load_history(chat_id, live)

        self.assertIs(bot.HISTORY_CACHE[chat_id], live)
        self.assertEqual(
            [event["telegram_message_id"] for event in live],
            ["1674", "1685"],
        )
        messages = bot.build_model_messages(live, history_limit=50)
        serialized = json.dumps(messages, ensure_ascii=False)
        self.assertIn("一开始是一百万", serialized)
        self.assertIn("猫猫一开始问你要多少钱", serialized)

    def test_history_merge_deduplicates_gist_copy_of_live_message(self):
        duplicate = bot._make_conversation_event(
            role="user",
            content="new canonical content",
            raw_text="new canonical content",
            chat_id="8749953218",
            telegram_message_id="1685",
            sender_type="user",
            stable_sender_id="ceci",
            created_at="2026-08-05T13:24:59+08:00",
        )
        old_copy = dict(duplicate, content="old persisted content")

        merged = bot._merge_history_events([old_copy], [duplicate])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["content"], "new canonical content")

    def test_private_chat_history_uses_string_key_for_gist_json(self):
        with mock.patch.object(bot, "GIST_HISTORY_IO_ENABLED", True):
            with mock.patch.object(bot, "Thread") as thread:
                history = bot.load_history(8749953218)

        self.assertIs(history, bot.HISTORY_CACHE["8749953218"])
        self.assertNotIn(8749953218, bot.HISTORY_CACHE)
        self.assertEqual(thread.call_args.kwargs["args"][0], "8749953218")

    def test_public_proactive_never_reads_private_memory_or_posts_private_topics(self):
        public_chat = "-100999000111"
        bot.HISTORY_CACHE[public_chat] = []
        with mock.patch.object(bot, "fetch_memory", side_effect=AssertionError("private Gist read")):
            with mock.patch.object(bot, "hub_get_context", side_effect=AssertionError("Hub recall")):
                with mock.patch.object(
                    bot,
                    "_call_ai_simple",
                    return_value="小猫最近工作太累了，身体也不舒服。",
                ) as call:
                    self.assertEqual(bot.generate_moment_text(public_chat), "")
                    self.assertEqual(call.call_args.kwargs["max_tokens"], 1200)

    def test_public_proactive_keeps_safe_complete_group_chat(self):
        public_chat = "-100999000222"
        bot.HISTORY_CACHE[public_chat] = []
        with mock.patch.object(bot, "fetch_memory", side_effect=AssertionError("private Gist read")):
            with mock.patch.object(bot, "hub_get_context", side_effect=AssertionError("Hub recall")):
                with mock.patch.object(
                    bot,
                    "_call_ai_simple",
                    return_value="刚才那个梗到底是谁先说的？本少爷要记一笔。",
                ):
                    self.assertEqual(
                        bot.generate_moment_text(public_chat),
                        "刚才那个梗到底是谁先说的？本少爷要记一笔。",
                    )

    def test_proactive_drops_unclosed_thinking_and_incomplete_text(self):
        self.assertEqual(bot._clean_internal_text("<think>still reasoning"), "")
        self.assertFalse(bot._proactive_text_complete("话还没说完，"))

    def test_internal_metadata_and_untagged_reasoning_never_reach_telegram(self):
        leaked = (
            "[speaker=jasper message_id=64988 reply_to=64985] 哈哈哈哈大蟑螂笑死我了\n"
            "ofcourse_not_really_just_fun_tag_actually_i_dont_have_permission_"
            "or_do_i_wait_just_keep_talking_dont_explain_tags_at_all_if_fails_"
            "whatever_but_rules_say_output_action"
        )
        cleaned = bot._sanitize_model_visible_reply(leaked)
        self.assertEqual(cleaned, "哈哈哈哈大蟑螂笑死我了")
        self.assertNotIn("speaker=", cleaned)
        self.assertNotIn("message_id=", cleaned)
        self.assertNotIn("permission", cleaned)

    def test_plain_internal_reasoning_is_removed_but_character_text_remains(self):
        leaked = (
            "本少爷才是不含杂质的纯天然高贵凤头！\n"
            "I need to output a tag but I should check the system prompt and permission rule first."
        )
        cleaned = bot._sanitize_model_visible_reply(leaked)
        self.assertEqual(cleaned, "本少爷才是不含杂质的纯天然高贵凤头！")

    def test_reasoning_envelopes_and_headers_are_removed(self):
        cases = (
            ("<analysis>We need to answer carefully.</analysis>当然记得。", "当然记得。"),
            ("<|analysis|>The user is asking about memory.<|final|>当然记得。", "当然记得。"),
            ("Analysis:\nThe user is asking about memory.\nLet's craft a concise reply.\n\n当然记得。", "当然记得。"),
            ("Reasoning:\nNeed to answer in Chinese.\nFinal answer: 当然记得。", "当然记得。"),
        )
        for leaked, expected in cases:
            with self.subTest(leaked=leaked):
                cleaned, _ = bot.extract_thinking(leaked)
                self.assertEqual(bot._sanitize_model_visible_reply(cleaned), expected)

    def test_output_guard_preserves_character_dialogue(self):
        dialogue = "我需要你现在抱抱我。\n我们得走了，别磨蹭。\n你又在分析本少爷？\n分析什么分析，本少爷饿了。"
        self.assertEqual(bot._sanitize_model_visible_reply(dialogue), dialogue)

    def test_plain_meta_reasoning_lines_are_removed(self):
        leaked = "The user is asking why Jasper forgot.\nWe need to answer concisely.\n当然记得。"
        self.assertEqual(bot._sanitize_model_visible_reply(leaked), "当然记得。")

    def test_jasper_remembers_its_own_previous_message_without_hub(self):
        chat_id = "-100000000001"
        history = [
            bot._make_conversation_event(
                role="assistant",
                content="我把一颗蓝色玻璃珠藏在枕头下面。",
                raw_text="我把一颗蓝色玻璃珠藏在枕头下面。",
                chat_id=chat_id,
                telegram_message_id="7001",
                sender_type="agent",
                stable_sender_id="jasper",
                created_at="2026-07-21T12:00:00+08:00",
                bot_name="Jasper",
            ),
            bot._make_conversation_event(
                role="user",
                content="ceci(ID:8749953218): 刚才是谁说把什么藏在哪里？",
                raw_text="刚才是谁说把什么藏在哪里？",
                chat_id=chat_id,
                telegram_message_id="7002",
                sender_type="user",
                stable_sender_id="ceci",
                reply_to_message_id="7001",
                created_at="2026-07-21T12:00:05+08:00",
            ),
        ]

        messages = bot.build_model_messages(history, history_limit=50)
        serialized = json.dumps(messages, ensure_ascii=False)
        self.assertLess(serialized.index("Jasper说"), serialized.index("Ceci（"))
        self.assertIn("Telegram消息 7001", serialized)
        self.assertIn("回复消息 7001", serialized)
        self.assertNotIn("speaker=", serialized)
        self.assertNotIn("message_id=", serialized)
        self.assertNotIn("[消息ID:", serialized)
        self.assertIn("蓝色玻璃珠", serialized)
        self.assertIn("枕头下面", serialized)

        def deterministic_model_stub(final_messages):
            context = json.dumps(final_messages, ensure_ascii=False)
            required = ("Jasper说", "蓝色玻璃珠", "枕头下面", "Ceci（")
            if all(item in context for item in required):
                return "Jasper自己刚才说，把一颗蓝色玻璃珠藏在枕头下面。"
            return "上下文缺失"

        raw_output = deterministic_model_stub(messages)
        self.assertEqual(
            raw_output,
            "Jasper自己刚才说，把一颗蓝色玻璃珠藏在枕头下面。",
        )

        report = {
            "telegram_raw_messages": [
                {"message_id": "7001", "sender": "jasper", "text": history[0]["raw_text"]},
                {"message_id": "7002", "sender": "ceci", "text": history[1]["raw_text"]},
            ],
            "conversation_store": history,
            "final_messages": messages,
            "model_raw_output": raw_output,
            "memory_hub_called": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))

    def test_model_context_presents_ordinary_chat_as_dialogue_not_code(self):
        event = bot._make_conversation_event(
            role="user",
            content="[消息ID:7003] 燕燕(ID:8618367675): 你别把我说的话当代码呀",
            raw_text="你别把我说的话当代码呀",
            chat_id="-100000000001",
            telegram_message_id="7003",
            sender_type="user",
            stable_sender_id="user:8618367675",
            created_at="2026-09-09T12:00:00+08:00",
            sender_display="燕燕",
            context_note="身份提示：当前回复者是jasper；这句话提到的是cloudy（小克）。",
        )

        serialized = json.dumps(bot.build_model_messages([event]), ensure_ascii=False)

        self.assertIn("燕燕（群友，Telegram用户 8618367675）说", serialized)
        self.assertIn("你别把我说的话当代码呀", serialized)
        self.assertIn("这句话提到的是cloudy（小克）", serialized)
        self.assertNotIn("speaker=", serialized)
        self.assertNotIn("message_id=", serialized)
        self.assertNotIn("ID:", serialized)


if __name__ == "__main__":
    unittest.main()




