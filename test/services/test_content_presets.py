import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import VideoParams
from app.services import content_presets as cp
from app.services import llm


class TestPresetDefinitions(unittest.TestCase):
    def test_every_prompt_has_length_placeholder(self):
        for preset in cp.PRESETS.values():
            self.assertIn("{length}", preset.system_prompt, preset.key)

    def test_product_requires_media(self):
        product = cp.PRESETS_BY_COMMAND["sanpham"]

        self.assertIn("ảnh/video", cp.validate_prompt(product, "Bình giữ nhiệt", 0))
        self.assertIsNone(cp.validate_prompt(product, "Bình giữ nhiệt", 2))
        with self.assertRaises(ValueError):
            cp.build_params(product, "Bình giữ nhiệt")

    def test_healing_reads_slowly_over_long_calm_clips(self):
        preset = cp.PRESETS_BY_COMMAND["chualanh"]
        params = cp.build_params(preset, "Khi bạn mệt mỏi vì phải tỏ ra ổn")

        self.assertEqual(params.voice_rate, 0.9)
        self.assertEqual(params.video_clip_duration, 5)
        self.assertFalse(params.match_materials_to_script)
        self.assertEqual(params.cover_label, "Chữa lành")
        self.assertIn("calm lake", preset.visual_hint)


class TestBuildParams(unittest.TestCase):
    def test_short_prompt_is_subject_only(self):
        params = cp.build_params(cp.PRESETS_BY_COMMAND["diadiem"], "Vịnh Hạ Long")

        self.assertEqual(params.video_subject, "Vịnh Hạ Long")
        self.assertEqual(params.video_script_prompt, "")

    def test_answers_go_to_script_prompt_and_first_line_stays_subject(self):
        prompt = cp.merge_answers("Chợ nổi", ["Chợ nổi nào?"], "Cái Răng, Cần Thơ")
        params = cp.build_params(cp.PRESETS_BY_COMMAND["diadiem"], prompt)

        self.assertEqual(params.video_subject, "Chợ nổi")
        self.assertIn("Cái Răng, Cần Thơ", params.video_script_prompt)
        self.assertEqual(params.cover_title, "Chợ nổi")


class TestLanguages(unittest.TestCase):
    def test_english_reads_in_english_with_vietnamese_subtitles(self):
        params = cp.build_params(
            cp.PRESETS_BY_COMMAND["meo"], "tiết kiệm tiền", language="en-US", duration_seconds=60
        )

        self.assertEqual(params.video_language, "en-US")
        self.assertEqual(params.voice_name, "en-US-AriaNeural-Female")
        self.assertEqual(params.subtitle_language, "vi-VN")
        self.assertIn("tiếng Anh Mỹ", params.custom_system_prompt)
        # 60 giây × 2,6 từ/giây × tốc độ đọc 1,1 của /meo.
        self.assertIn("154–180 từ", params.custom_system_prompt)

    def test_vietnamese_keeps_previous_behaviour(self):
        params = cp.build_params(
            cp.PRESETS_BY_COMMAND["meo"], "tiết kiệm tiền", duration_seconds=60
        )

        self.assertEqual(params.video_language, "")
        self.assertEqual(params.subtitle_language, "")
        self.assertIn("184–214 từ", params.custom_system_prompt)
        self.assertNotIn("tiếng Anh Mỹ", params.custom_system_prompt)

    def test_voice_override_wins(self):
        params = cp.build_params(
            cp.PRESETS_BY_COMMAND["meo"], "tips", language="en-US",
            voice_name="en-US-GuyNeural-Male",
        )
        self.assertEqual(params.voice_name, "en-US-GuyNeural-Male")

    def test_vietnamese_replaces_ui_voice_of_another_language_only(self):
        vi = cp.get_language("vi-VN")
        cases = {
            "en-US-AriaNeural-Female": "vi-VN-HoaiMyNeural-Female",
            "vi-VN-NamMinhNeural-Male": "vi-VN-NamMinhNeural-Male",
            "elevenlabs:abc:Trieu Duong": "elevenlabs:abc:Trieu Duong",
            "no-voice": "no-voice",
        }
        for ui_voice, expected in cases.items():
            self.assertEqual(cp._resolve_voice(vi, ui_voice, None), expected, ui_voice)

    def test_unknown_language_falls_back_to_default(self):
        self.assertEqual(cp.get_language("fr-FR").code, cp.DEFAULT_LANGUAGE)
        self.assertEqual(cp.get_language(None).code, cp.DEFAULT_LANGUAGE)

    def test_english_post_does_not_top_up_vietnamese_hashtags(self):
        data = {"title": "Money tips", "hashtags": ["#moneytips"]}
        preset = cp.PRESETS_BY_COMMAND["meo"]
        with patch.object(llm, "generate_json_object", return_value=data):
            english = cp.generate_post(preset, "tips", "script", "en-US")
            vietnamese = cp.generate_post(preset, "mẹo", "kịch bản")

        self.assertEqual(english.hashtags, ["#moneytips"])
        self.assertEqual(vietnamese.hashtags[0], "#moneytips")
        self.assertIn("#meohay", vietnamese.hashtags)


class TestClarifyingQuestions(unittest.TestCase):
    def test_preset_without_checklist_never_calls_llm(self):
        with patch.object(llm, "generate_json_object") as generate:
            questions = cp.clarifying_questions(cp.PRESETS_BY_COMMAND["kienthuc"], "Đại dương")

        self.assertEqual(questions, [])
        generate.assert_not_called()

    def test_questions_are_cleaned_and_capped(self):
        raw = {"questions": ["  Giá bán\n bao nhiêu? ", "", "Mua ở đâu?", "Màu gì?", "Size?"]}
        with patch.object(llm, "generate_json_object", return_value=raw):
            questions = cp.clarifying_questions(
                cp.PRESETS_BY_COMMAND["sanpham"], "Bình giữ nhiệt", media_count=2
            )

        self.assertEqual(questions, ["Giá bán bao nhiêu?", "Mua ở đâu?", "Màu gì?"])

    def test_llm_failure_means_no_questions(self):
        for response in (None, {"questions": "không phải list"}, {}):
            with patch.object(llm, "generate_json_object", return_value=response):
                questions = cp.clarifying_questions(cp.PRESETS_BY_COMMAND["meo"], "sức khoẻ")
            self.assertEqual(questions, [])


class TestSubtopics(unittest.TestCase):
    def test_topics_are_cleaned_deduplicated_and_capped_to_count(self):
        raw = {
            "topics": [
                {"title": " Mẹo  tiết kiệm\n tiền ăn ", "content": "Nấu cơm  mang đi."},
                {"title": "mẹo tiết kiệm tiền ăn", "content": "Trùng tên."},
                {"title": "", "content": "Không có tên."},
                "Mẹo tiết kiệm tiền điện",
                {"title": "Mẹo săn ưu đãi", "content": "x" * 400},
            ]
        }
        with patch.object(llm, "generate_json_object", return_value=raw) as generate:
            topics = cp.generate_subtopics(cp.PRESETS_BY_COMMAND["meo"], "tiết kiệm tiền", 2)

        self.assertEqual(
            topics,
            [
                cp.Subtopic("Mẹo tiết kiệm tiền ăn", "Nấu cơm mang đi."),
                cp.Subtopic("Mẹo tiết kiệm tiền điện", ""),
            ],
        )
        prompt = generate.call_args.args[0]
        self.assertIn("đúng 2 chủ đề con", prompt)
        self.assertIn("5 mẹo tiết kiệm tiền cho sinh viên", prompt)
        self.assertNotIn("Góp ý", prompt)

    def test_feedback_includes_previous_list_and_may_change_count(self):
        previous = [cp.Subtopic("Mẹo A", "Ý A"), cp.Subtopic("Mẹo B", "Ý B")]
        raw = {"topics": [{"title": f"Mẹo {i}", "content": ""} for i in range(3)]}
        with patch.object(llm, "generate_json_object", return_value=raw) as generate:
            topics = cp.generate_subtopics(
                cp.PRESETS_BY_COMMAND["meo"], "tiết kiệm", 2, previous, "thêm một mẹo"
            )

        self.assertEqual(len(topics), 3)
        prompt = generate.call_args.args[0]
        self.assertIn("1. Mẹo A: Ý A", prompt)
        self.assertIn("thêm một mẹo", prompt)

    def test_long_content_is_cut_and_prompt_keeps_title_as_subject(self):
        raw = {"topics": [{"title": "Kỷ luật buổi sáng", "content": "ý " * 300}]}
        with patch.object(llm, "generate_json_object", return_value=raw):
            [topic] = cp.generate_subtopics(cp.PRESETS_BY_COMMAND["dongluc"], "kỷ luật", 1)

        self.assertLessEqual(len(topic.content), 300)
        params = cp.build_params(cp.PRESETS_BY_COMMAND["dongluc"], topic.prompt())
        self.assertEqual(params.video_subject, "Kỷ luật buổi sáng")
        self.assertIn(topic.content, params.video_script_prompt)

    def test_llm_failure_means_no_topics(self):
        for response in (None, {"topics": "không phải list"}, {}):
            with patch.object(llm, "generate_json_object", return_value=response):
                topics = cp.generate_subtopics(cp.PRESETS_BY_COMMAND["kienthuc"], "đại dương", 5)
            self.assertEqual(topics, [])


class TestSearchTerms(unittest.TestCase):
    def test_hint_gives_clean_distinct_short_terms(self):
        params = VideoParams(video_subject="Kiên trì", video_script="Câu một.\n\nCâu hai.")
        raw = {"terms": [" man  walking ", "Man walking", "", "sunrise mountain", "x" * 60]}
        with patch.object(llm, "generate_json_object", return_value=raw) as generate:
            terms = cp.generate_search_terms(cp.PRESETS_BY_COMMAND["dongluc"], params)

        self.assertEqual(terms[:2], ["man walking", "sunrise mountain"])
        self.assertEqual(len(terms), 3)
        self.assertTrue(all(len(term) <= 40 for term in terms))
        prompt = generate.call_args.args[0]
        self.assertIn("5 từ khoá", prompt)
        self.assertIn("(man walking)", prompt)

    def test_no_hint_or_no_script_leaves_terms_to_pipeline(self):
        with_script = VideoParams(video_subject="Đại dương", video_script="Câu một.")
        without_script = VideoParams(video_subject="Kiên trì")
        with patch.object(llm, "generate_json_object") as generate:
            self.assertEqual(
                cp.generate_search_terms(cp.PRESETS_BY_COMMAND["kienthuc"], with_script), []
            )
            self.assertEqual(
                cp.generate_search_terms(cp.PRESETS_BY_COMMAND["dongluc"], without_script), []
            )

        generate.assert_not_called()

    def test_prepare_sets_terms_before_post(self):
        params = VideoParams(video_subject="Mệt mỏi", cover_title="Mệt mỏi")
        responses = [
            {"terms": ["calm lake", "rain window"]},
            {"keyword": "chữa lành", "title": "Khi bạn mệt mỏi", "caption": "c"},
        ]
        with patch.object(llm, "generate_script", return_value="Câu một.\n\nCâu hai."), \
                patch.object(llm, "generate_json_object", side_effect=responses):
            post = cp.prepare_script_and_post(cp.PRESETS_BY_COMMAND["chualanh"], params)

        self.assertEqual(params.video_terms, ["calm lake", "rain window"])
        self.assertEqual(post.title, "Khi bạn mệt mỏi")


class TestGifText(unittest.TestCase):
    def test_text_and_terms_are_cleaned(self):
        raw = {
            "text": " “Kiên trì  mỗi ngày,\n dù chậm.” ",
            "terms": ["man walking", "Man walking", "", "sunrise mountain", "road", "extra"],
        }
        with patch.object(llm, "generate_json_object", return_value=raw) as generate:
            result = cp.generate_gif_text(cp.PRESETS_BY_COMMAND["dongluc"], "Kiên trì")

        self.assertEqual(result.text, "Kiên trì mỗi ngày, dù chậm.")
        self.assertEqual(result.terms, ["man walking", "sunrise mountain", "road"])
        prompt = generate.call_args.args[0]
        self.assertIn("không lồng tiếng", prompt)
        self.assertIn("(man walking)", prompt)

    def test_scenes_used_earlier_in_the_batch_reach_the_prompt(self):
        with patch.object(llm, "generate_json_object", return_value={"text": "Hi"}) as generate:
            cp.generate_gif_text(
                cp.PRESETS_BY_COMMAND["dongluc"], "Kiên trì", None,
                ["man walking", "", "man walking", "road"],
            )
            cp.generate_gif_text(cp.PRESETS_BY_COMMAND["dongluc"], "Kiên trì")

        with_history, without_history = (call.args[0] for call in generate.call_args_list)
        self.assertIn("đã dùng cảnh: man walking, road;", with_history)
        self.assertNotIn("đã dùng cảnh", without_history)

    def test_english_and_news_rules_reach_the_prompt(self):
        with patch.object(llm, "generate_json_object", return_value={"text": "Hi"}) as generate:
            cp.generate_gif_text(cp.PRESETS_BY_COMMAND["tintuc"], "x" * 200, "en-US")

        prompt = generate.call_args.args[0]
        self.assertIn("tiếng Anh Mỹ", prompt)
        self.assertIn("nguồn tin", prompt)

    def test_failure_returns_none_and_long_text_is_cut(self):
        for response in (None, {}, {"text": ""}):
            with patch.object(llm, "generate_json_object", return_value=response):
                self.assertIsNone(cp.generate_gif_text(cp.PRESETS_BY_COMMAND["kienthuc"], "mèo"))
        with patch.object(llm, "generate_json_object", return_value={"text": "chữ " * 80}):
            result = cp.generate_gif_text(cp.PRESETS_BY_COMMAND["kienthuc"], "mèo")

        self.assertLessEqual(len(result.text), 160)
        self.assertTrue(result.text.endswith("…"))
        self.assertEqual(result.terms, [])
        self.assertEqual(result.detail, "")

    def test_detail_is_requested_cleaned_and_cut(self):
        raw = {"text": "Kiên trì", "detail": " “Mỗi ngày một bước.\n Chậm  mà chắc.” "}
        with patch.object(llm, "generate_json_object", return_value=raw) as generate:
            result = cp.generate_gif_text(cp.PRESETS_BY_COMMAND["dongluc"], "Kiên trì")
        with patch.object(llm, "generate_json_object", return_value={"text": "a", "detail": "từ " * 400}):
            long = cp.generate_gif_text(cp.PRESETS_BY_COMMAND["dongluc"], "Kiên trì")

        self.assertEqual(result.detail, "Mỗi ngày một bước. Chậm mà chắc.")
        prompt = generate.call_args.args[0]
        self.assertIn('"detail": lời diễn giải chi tiết hơn', prompt)
        self.assertIn("tiêu đề của ảnh GIF", prompt)
        self.assertLessEqual(len(long.detail), 800)
        self.assertTrue(long.detail.endswith("…"))


class TestPostPackage(unittest.TestCase):
    def test_hashtags_are_unaccented_specific_and_topped_up(self):
        data = {
            "keyword": "du lịch Đà Lạt",
            "title": "“Du lịch Đà Lạt 2 ngày 1 đêm”",
            "caption": "Du lịch Đà Lạt tự túc...",
            "hashtags": ["#Du lịch Đà Lạt", "#fyp", "dulichdalat", "#Ẩm_thực"],
        }
        with patch.object(llm, "generate_json_object", return_value=data):
            post = cp.generate_post(cp.PRESETS_BY_COMMAND["diadiem"], "Đà Lạt", "Kịch bản")

        self.assertEqual(post.title, "Du lịch Đà Lạt 2 ngày 1 đêm")
        self.assertEqual(
            post.hashtags,
            ["#dulichdalat", "#am_thuc", "#dulich", "#dulichvietnam", "#reviewdulich"],
        )

    def test_missing_title_returns_none(self):
        with patch.object(llm, "generate_json_object", return_value={"caption": "x"}):
            self.assertIsNone(cp.generate_post(cp.PRESETS_BY_COMMAND["meo"], "a", "b"))

    def test_text_fits_limit(self):
        post = cp.PostPackage("k", "Tiêu đề", "chữ " * 400, ["#a", "#b"])
        text = post.text(200)

        self.assertLessEqual(len(text), 200)
        self.assertTrue(text.startswith("Tiêu đề\n\n"))
        self.assertTrue(text.endswith("#a #b"))


class TestPrepareScriptAndPost(unittest.TestCase):
    def test_sets_script_and_seo_cover_title(self):
        params = VideoParams(video_subject="Đà Lạt", cover_title="Đà Lạt")
        data = {"keyword": "du lịch Đà Lạt", "title": "Du lịch Đà Lạt", "caption": "c"}
        with patch.object(llm, "generate_script", return_value="Câu một.\n\nCâu hai."), \
                patch.object(llm, "generate_json_object", return_value=data):
            post = cp.prepare_script_and_post(cp.PRESETS_BY_COMMAND["diadiem"], params)

        self.assertEqual(post.keyword, "du lịch Đà Lạt")
        self.assertEqual(params.video_script, "Câu một.\n\nCâu hai.")
        self.assertEqual(params.cover_title, "Du lịch Đà Lạt")
        # /diadiem không có gợi ý cảnh quay: pipeline tự sinh từ khoá như trước.
        self.assertIsNone(params.video_terms)

    def test_script_error_leaves_params_for_pipeline(self):
        params = VideoParams(video_subject="Đà Lạt", cover_title="Đà Lạt")
        with patch.object(llm, "generate_script", return_value="Error: quota"), \
                patch.object(llm, "generate_json_object") as generate:
            post = cp.prepare_script_and_post(cp.PRESETS_BY_COMMAND["diadiem"], params)

        self.assertIsNone(post)
        self.assertEqual(params.video_script, "")
        self.assertEqual(params.cover_title, "Đà Lạt")
        generate.assert_not_called()


class TestGenerateJsonObject(unittest.TestCase):
    def test_parses_fenced_and_embedded_json(self):
        for response in ('```json\n{"a": 1}\n```', 'Kết quả: {"a": 1} nhé'):
            with patch.object(llm, "_generate_response", return_value=response):
                self.assertEqual(llm.generate_json_object("p"), {"a": 1})

    def test_returns_none_on_provider_error_or_non_object(self):
        for response in ("Error: api_key is not set", "[1, 2]", "không có json"):
            with patch.object(llm, "_generate_response", return_value=response):
                self.assertIsNone(llm.generate_json_object("p"))


if __name__ == "__main__":
    unittest.main()
