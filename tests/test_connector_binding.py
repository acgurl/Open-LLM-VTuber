import unittest

from pydantic import ValidationError

from open_llm_vtuber.config_manager.connectors import (
    BindingConfig,
    ConnectorsConfig,
    QQConnectorConfig,
)
from open_llm_vtuber.connectors.binding import (
    MAX_FAILED_ATTEMPTS,
    BindCodeStore,
    email_domain_allowed,
    user_eligible,
)
from open_llm_vtuber.connectors.formatting import clean_reply, split_reply


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class EmailDomainTests(unittest.TestCase):
    def test_domain_and_subdomains_are_allowed(self):
        self.assertTrue(email_domain_allowed("a@cuc.edu.cn", ["cuc.edu.cn"]))
        self.assertTrue(email_domain_allowed("a@mail.CUC.edu.cn", ["cuc.edu.cn"]))

    def test_lookalike_domains_are_rejected(self):
        for email in (
            "a@evilcuc.edu.cn",
            "a@cuc.edu.cn.evil.com",
            "a@cuc.edu",
            "cuc.edu.cn",
            "a@b@cuc.edu.cn",
        ):
            self.assertFalse(email_domain_allowed(email, ["cuc.edu.cn"]), email)

    def test_user_eligible_needs_a_matching_login_email(self):
        self.assertFalse(user_eligible(None, ["cuc.edu.cn"]))
        self.assertFalse(user_eligible({"emails": []}, ["cuc.edu.cn"]))
        self.assertFalse(user_eligible({"emails": ["a@qq.com"]}, ["cuc.edu.cn"]))
        self.assertTrue(
            user_eligible({"emails": ["a@qq.com", "b@cuc.edu.cn"]}, ["cuc.edu.cn"])
        )


class BindCodeStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.store = BindCodeStore(ttl_seconds=600, clock=self.clock)

    def test_code_is_single_use_and_case_insensitive(self):
        code, ttl = self.store.issue("alice")
        self.assertEqual(ttl, 600)
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertEqual(
            self.store.redeem(code.lower().replace("-", " "), "qq:u:1"), "alice"
        )
        self.assertIsNone(self.store.redeem(code, "qq:u:1"))

    def test_code_expires(self):
        code, _ = self.store.issue("alice")
        self.clock.now += 601
        self.assertIsNone(self.store.redeem(code, "qq:u:1"))

    def test_new_code_revokes_the_previous_one(self):
        first, _ = self.store.issue("alice")
        second, _ = self.store.issue("alice")
        self.assertIsNone(self.store.redeem(first, "qq:u:1"))
        self.assertEqual(self.store.redeem(second, "qq:u:1"), "alice")

    def test_failed_attempts_lock_the_platform_account(self):
        code, _ = self.store.issue("alice")
        for _ in range(MAX_FAILED_ATTEMPTS):
            self.assertIsNone(self.store.redeem("AAAA-AAAA", "qq:u:attacker"))
        self.assertTrue(self.store.is_locked("qq:u:attacker"))
        # Even the right code is refused while locked ...
        self.assertIsNone(self.store.redeem(code, "qq:u:attacker"))
        # ... but other accounts are unaffected, and the lock expires.
        self.assertFalse(self.store.is_locked("qq:u:owner"))
        self.clock.now += 601
        self.assertFalse(self.store.is_locked("qq:u:attacker"))


class FormattingTests(unittest.TestCase):
    def test_clean_reply_drops_think_blocks_and_known_tags_only(self):
        text = "<think>内部推理</think>[joy]你好！参考 [1]。\n\n\n\n[Wave]再见"
        self.assertEqual(clean_reply(text, ["joy", "wave"]), "你好！参考 [1]。\n\n再见")

    def test_unclosed_think_block_is_dropped(self):
        self.assertEqual(clean_reply("答案<think>还没想完"), "答案")

    def test_split_reply_prefers_sentence_boundaries(self):
        parts = split_reply("第一句话。第二句话。第三句话。", max_chars=12, max_parts=4)
        self.assertEqual(parts, ["第一句话。第二句话。", "第三句话。"])

    def test_split_reply_truncates_the_last_part(self):
        parts = split_reply("甲" * 50, max_chars=10, max_parts=2)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[-1].endswith("……"))
        self.assertTrue(all(len(part) <= 10 for part in parts))


class ConnectorConfigTests(unittest.TestCase):
    def test_defaults_are_disabled_and_campus_only(self):
        config = ConnectorsConfig()
        self.assertFalse(config.enabled)
        self.assertEqual(config.binding.allowed_email_domains, ["cuc.edu.cn"])

    def test_domains_are_normalized(self):
        config = BindingConfig(allowed_email_domains=["@CUC.edu.cn.", "cuc.edu.cn"])
        self.assertEqual(config.allowed_email_domains, ["cuc.edu.cn"])
        with self.assertRaises(ValidationError):
            BindingConfig(allowed_email_domains=["not a domain"])

    def test_enabled_instance_requires_resolved_credentials(self):
        with self.assertRaises(ValidationError):
            QQConnectorConfig(
                id="qq", enabled=True, app_id="1", app_secret="${QQ_SECRET}"
            )
        QQConnectorConfig(id="qq", enabled=False, app_id="", app_secret="")

    def test_instance_ids_must_be_unique(self):
        with self.assertRaises(ValidationError):
            ConnectorsConfig(
                instances=[{"type": "qq", "id": "qq"}, {"type": "qq", "id": "qq"}]
            )


if __name__ == "__main__":
    unittest.main()
