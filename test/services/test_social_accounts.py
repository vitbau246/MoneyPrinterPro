import os
import shutil
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.services import content_presets as cp
from app.services import social_accounts as sa
from app.services import social_publish as sp
from app.utils import utils


class AccountsTestCase(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(utils.storage_dir("social"), ignore_errors=True)
        self.addCleanup(shutil.rmtree, utils.storage_dir("social"), True)


class TestConfirmedAccounts(AccountsTestCase):
    def test_save_and_reload(self):
        self.assertEqual(sa.confirmed(), {})
        sa.save({sa.TIKTOK: sa.Account("@meo", "@meo – Mèo", "u"), sa.YOUTUBE: sa.Account("UC1", "Kênh")})
        self.assertEqual(sa.confirmed()[sa.TIKTOK].label(), "@meo – Mèo (@meo)")
        # Kiểm tra lại mà chưa đăng nhập thì bỏ xác nhận cũ.
        sa.save({sa.TIKTOK: None})
        self.assertEqual(list(sa.confirmed()), [sa.YOUTUBE])

    def test_account_helpers(self):
        self.assertTrue(sa.Account("UC1", "A").same_as(sa.Account("UC1", "")))
        self.assertFalse(sa.Account("UC1", "A").same_as(sa.Account("UC2", "A")))
        self.assertFalse(sa.Account("UC1", "A").same_as(None))
        self.assertEqual(sa.Account("123", "123").label(), "123")
        self.assertEqual(sa.youtube_channel("https://studio.youtube.com/channel/UCab-1_x/videos/upload"), "UCab-1_x")
        self.assertEqual(sa.youtube_channel("https://accounts.google.com/"), "")

    def test_facebook_prefers_page_profile(self):
        context = MagicMock()
        context.cookies.return_value = [{"name": "c_user", "value": "100"}, {"name": "i_user", "value": "200"}]
        self.assertEqual(sa.facebook_id(context), "200")
        context.cookies.return_value = [{"name": "c_user", "value": "100"}]
        self.assertEqual(sa.facebook_id(context), "100")
        context.cookies.return_value = []
        self.assertEqual(sa.facebook_id(context), "")

    def test_check_and_save_keeps_old_on_errors(self):
        sa.save({sa.FACEBOOK: sa.Account("1", "Trang cũ")})

        @contextmanager
        def fake_connect():
            yield MagicMock()

        def detect(context, page, platform):
            if platform == sa.FACEBOOK:
                raise TimeoutError("chậm")
            return sa.Account("@x", "@x") if platform == sa.TIKTOK else None

        with patch.object(sa.social_browser, "connect", fake_connect), patch.object(sa, "detect", side_effect=detect):
            found = sa.check_and_save()
        self.assertEqual(found[sa.FACEBOOK], "chậm")
        self.assertIsNone(found[sa.YOUTUBE])
        self.assertEqual(sa.confirmed()[sa.FACEBOOK].name, "Trang cũ")
        self.assertEqual(sa.confirmed()[sa.TIKTOK].id, "@x")
        self.assertNotIn(sa.YOUTUBE, sa.confirmed())


class TestPublishGuards(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.video = os.path.join(utils.storage_dir("social", create=True), "v.mp4")
        with open(self.video, "wb") as file:
            file.write(b"v")

    def test_not_confirmed_stops_before_browser(self):
        with patch.object(sp.social_browser, "connect") as connect:
            with self.assertRaises(sp.NotConfirmed):
                sp.publish(sp.TIKTOK, sp.Content(self.video, "t"))
        connect.assert_not_called()

    def test_wrong_account_message(self):
        with self.assertRaises(sp.WrongAccount) as caught:
            sp._check_account(sp.YOUTUBE, sa.Account("UC2", ""), sa.Account("UC1", "Kênh chính"))
        self.assertIn("Kênh chính (UC1)", str(caught.exception))
        with self.assertRaises(sp.NotLoggedIn):
            sp._check_account(sp.YOUTUBE, None, sa.Account("UC1", "Kênh chính"))
        sp._check_account(sp.YOUTUBE, sa.Account("UC1", ""), sa.Account("UC1", "Kênh chính"))


class TestYoutubeTags(unittest.TestCase):
    def test_clean_tags(self):
        tags = cp.clean_tags(["#Mẹo ngủ", "mẹo ngủ", "  ", "giấc ngủ ngon"], ["ngủ ngon"])
        self.assertEqual(tags, ["Mẹo ngủ", "giấc ngủ ngon", "ngủ ngon"])
        long = cp.clean_tags([f"thẻ số {index:03d} " + "x" * 40 for index in range(30)])
        self.assertLessEqual(sum(len(tag) + 1 for tag in long), 450)

    def test_generate_post_reads_tags(self):
        data = {"keyword": "ngủ ngon", "title": "Ngủ ngon", "caption": "c", "hashtags": ["#a"], "tags": ["mẹo ngủ"]}
        with patch.object(cp.llm, "generate_json_object", return_value=data):
            post = cp.generate_post(cp.PRESETS_BY_COMMAND["meo"], "ngủ", "kịch bản")
        self.assertEqual(post.tags, ["mẹo ngủ", "ngủ ngon"])


if __name__ == "__main__":
    unittest.main()
