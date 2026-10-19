"""
Preset cho các loại nội dung video ngắn phù hợp nhất với MoneyPrinterTurbo.

Mỗi preset gồm system prompt viết kịch bản riêng, gợi ý SEO cho nội dung đăng
bài, danh sách thông tin cần hỏi lại người dùng (nếu có), gợi ý cảnh quay cho từ
khoá tìm video kho (nếu có) và các tham số dựng video (tốc độ đọc, thời lượng
clip, chuyển cảnh, phụ đề...). Các thiết lập còn lại (giọng đọc, font, màu phụ
đề...) lấy từ config.toml giống CLI.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Sequence

from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import llm
from app.utils import utils

# TikTok và YouTube chuyển lời đọc thành văn bản để xếp hạng tìm kiếm, nên từ
# khoá chính phải được nói ra ngay trong câu đầu, không chỉ nằm trong caption.
_COMMON_RULES = """
## Quy tắc bắt buộc:
1. Chỉ trả về lời đọc thuần: không markdown, không tiêu đề, không emoji, không hashtag, không gạch đầu dòng, không đánh số kiểu "1.".
2. Không ghi "người dẫn", "voiceover" hay chỉ dẫn hình ảnh, âm thanh; mọi chữ đều sẽ được đọc thành tiếng.
3. Không dùng ngoặc đơn hay ngoặc vuông vì phần trong ngoặc sẽ bị xoá khi dựng video.
4. Viết để giọng đọc máy đọc đúng: ghi đầy đủ đơn vị và chữ viết tắt, ví dụ "199 nghìn đồng" thay cho "199k", "2 triệu" thay cho "2tr", "500 mi-li-lít" thay cho "500ml"; không dùng ký hiệu như /, &, +, ~.
5. Câu đầu tiên là câu móc (hook) gây tò mò và chứa từ khoá chính của chủ đề, tức cụm từ người xem sẽ gõ để tìm video này. Không mở đầu bằng lời chào hay giới thiệu bản thân.
6. Nhắc lại từ khoá chính hoặc cách nói gần nghĩa thêm 1–2 lần một cách tự nhiên, không nhồi nhét.
7. Mỗi câu một ý, tối đa khoảng 20 từ, văn nói tự nhiên, gọi người xem là "bạn".
8. Không câu đệm, không lặp ý, không nói chung chung; câu nào cũng phải đem lại thông tin, cảm xúc hoặc lý do để xem tiếp.
9. Không nhắc đến prompt, số đoạn hay bản thân kịch bản; không kết bằng "cảm ơn đã xem".
10. Chia đúng số đoạn được yêu cầu, các đoạn cách nhau bằng một dòng trống.
11. Viết cùng ngôn ngữ với chủ đề video.
""".strip()


def _system_prompt(role: str, goals: str) -> str:
    return f"# Vai trò: {role}\n\n## Mục tiêu:\n{goals.strip()}\n\n{_COMMON_RULES}"


@dataclass(frozen=True)
class ContentPreset:
    key: str
    command: str
    title: str
    description: str
    example: str
    system_prompt: str
    # Thời lượng mặc định (giây) khi người dùng không chỉ định.
    default_seconds: int
    overrides: dict[str, Any] = field(default_factory=dict)
    # Tin tức cần nội dung gốc để AI không tự bịa sự kiện.
    requires_source_text: bool = False
    min_prompt_length: int = 3
    accepts_media: bool = False
    # Sản phẩm phải có ảnh/video thật, không dùng video kho có sẵn.
    requires_media: bool = False
    # Gợi ý riêng cho tiêu đề, mô tả và hashtag khi đăng bài.
    seo_hint: str = ""
    # Hashtag bù vào khi AI trả về quá ít hashtag dùng được.
    default_hashtags: tuple[str, ...] = ()
    # Thông tin cần có trước khi tạo video; rỗng nghĩa là không hỏi lại người dùng.
    clarify: str = ""
    # Cảnh quay gợi ý cho từ khoá tìm video kho, dùng sau khi viết kịch bản; rỗng
    # nghĩa là pipeline tự sinh từ khoá như trước.
    visual_hint: str = ""


PRESETS: dict[str, ContentPreset] = {
    preset.key: preset
    for preset in (
        ContentPreset(
            key="facts",
            command="kienthuc",
            title="Kiến thức / sự thật thú vị",
            description=(
                "Video 'Có thể bạn chưa biết': 3–5 sự thật bất ngờ, mỗi điều kèm giải "
                "thích dễ hiểu. Chủ đề càng cụ thể video càng hay."
            ),
            example="/kienthuc 5 sự thật thú vị về đại dương",
            system_prompt=_system_prompt(
                "Biên kịch video kiến thức ngắn cho TikTok, YouTube Shorts và Facebook Reels",
                """
- {length}
- Từ khoá chính là chủ đề kiến thức người xem quan tâm, ví dụ "sự thật về đại dương".
- Câu đầu là một con số, phép so sánh hoặc khẳng định gây bất ngờ gắn với từ khoá; có thể dùng "Có thể bạn chưa biết" nhưng không bắt buộc.
- Có thể báo trước rằng điều cuối cùng là bất ngờ nhất để giữ người xem đến hết, nếu đúng với cách sắp xếp.
- Thân bài gồm 3–5 sự thật, sắp xếp từ thú vị đến khó tin nhất, nối bằng "thứ nhất", "tiếp theo", "cuối cùng".
- Mỗi sự thật gồm nội dung chính và một câu giải thích vì sao hoặc so sánh đời thường để dễ hình dung.
- Chỉ dùng kiến thức đã được kiểm chứng rộng rãi; không bịa số liệu, tên nghiên cứu hay trích dẫn; con số không chắc chắn thì nói "khoảng" hoặc "theo các nhà khoa học".
- Ưu tiên câu gợi hình ảnh cụ thể có thể quay được, để cảnh minh hoạ khớp với lời đọc.
- Kết thúc bằng một câu hỏi cụ thể mời người xem bình luận, ví dụ họ đã biết điều nào trong số đó.
""",
            ),
            default_seconds=55,
            overrides={
                "match_materials_to_script": True,
                "video_clip_duration": 3,
                "voice_rate": 1.1,
                "subtitle_animation": "pop_spring",
            },
            seo_hint=(
                'Từ khoá chính là chủ đề kiến thức, ví dụ "sự thật về đại dương". '
                "Hashtag gợi ý: #kienthuc, #cothebanchuabiet, #hoccungtiktok kèm "
                "hashtag theo chủ đề."
            ),
            default_hashtags=("#kienthuc", "#cothebanchuabiet", "#hoccungtiktok"),
        ),
        ContentPreset(
            key="motivation",
            command="dongluc",
            title="Động lực / triết lý sống",
            description=(
                "Video truyền cảm hứng: chạm đúng cảm xúc, rút ra một bài học và một việc "
                "nhỏ làm được ngay. Giọng chậm, nhạc nền rõ hơn."
            ),
            example="/dongluc Kiên trì khi mọi thứ thất bại",
            system_prompt=_system_prompt(
                "Người viết lời cho video truyền cảm hứng",
                """
- {length}
- Từ khoá chính là chủ đề cảm xúc hoặc bài học, ví dụ "kiên trì", "vượt qua thất bại".
- Câu đầu gọi đúng một nỗi đau hoặc cảm xúc cụ thể mà người xem đang trải qua, như đang nói riêng với họ.
- Phần giữa đưa ra một góc nhìn mới hoặc bài học cốt lõi, minh hoạ bằng một câu chuyện ngắn hoặc hình ảnh ẩn dụ đời thường; không gán câu chuyện cho người thật nếu không chắc chắn.
- Đưa ra một việc nhỏ, cụ thể mà người xem có thể làm ngay hôm nay, để video có giá trị thực tế chứ không chỉ là lời động viên.
- Tránh câu sáo rỗng như "hãy luôn cố gắng", "rồi mọi chuyện sẽ ổn" nếu không kèm lý do hay ví dụ.
- Chỉ trích dẫn câu nói nổi tiếng khi chắc chắn đúng nguyên văn và đúng tác giả; nếu không chắc thì diễn đạt bằng lời của mình và không nêu tên tác giả.
- Giọng sâu lắng, chân thành, nhịp chậm; xen vài câu rất ngắn để tạo điểm nhấn.
- Kết thúc bằng một câu ngắn, mạnh, đáng nhớ, rồi mời người xem lưu lại hoặc gửi video cho một người đang cần nghe điều này.
""",
            ),
            default_seconds=40,
            overrides={
                "match_materials_to_script": False,
                "video_clip_duration": 4,
                "voice_rate": 0.95,
                "bgm_volume": 0.3,
                # Cắt cảnh trực tiếp: FadeIn của MoviePy mờ dần từ màu đen, tạo khung
                # đen đầu mỗi cảnh mà TikTok đánh giá là chất lượng thấp.
                "video_transition_mode": None,
            },
            seo_hint=(
                'Từ khoá chính là bài học hoặc cảm xúc, ví dụ "kiên trì", "vượt qua thất '
                'bại". Mô tả chạm cảm xúc và mời gửi video cho người đang cần. Hashtag '
                "gợi ý: #dongluc, #baihoccuocsong, #truyencamhung kèm hashtag theo chủ đề."
            ),
            default_hashtags=("#dongluc", "#baihoccuocsong", "#truyencamhung"),
            # Từ trừu tượng như success, failure, discipline chỉ có 0–2 clip dọc trên
            # Pixabay; cảnh cụ thể dưới đây có hàng chục clip (đo tháng 10/2026).
            visual_hint=(
                "cảnh gợi ý chí và cảm xúc, có nhiều trên kho video: người đi bộ một mình "
                "(man walking), đi bộ đường dài (hiking), con đường (road), leo núi "
                "(mountain climbing), bình minh trên núi (sunrise mountain), sóng biển "
                "(waves), cầu thang (stairs), nắng xuyên rừng (forest sunlight)"
            ),
        ),
        ContentPreset(
            key="healing",
            command="chualanh",
            title="Chữa lành / thư giãn",
            description=(
                "Video xoa dịu cảm xúc: lời thủ thỉ chậm rãi, công nhận cảm xúc và gợi một "
                "việc nhỏ để thả lỏng, trên nền thiên nhiên yên bình."
            ),
            example="/chualanh Khi bạn mệt mỏi vì phải tỏ ra ổn",
            system_prompt=_system_prompt(
                "Người viết lời cho video chữa lành, thư giãn",
                """
- {length}
- Từ khoá chính là cảm xúc hoặc hoàn cảnh người xem đang trải qua, ví dụ "mệt mỏi", "mất ngủ", "áp lực".
- Câu đầu gọi tên đúng cảm xúc đó bằng giọng dịu dàng, như đang ngồi cạnh người xem.
- Công nhận cảm xúc ấy là bình thường, rồi đưa ra một góc nhìn nhẹ nhàng giúp lòng nhẹ hơn; có thể mượn hình ảnh thiên nhiên như mặt hồ lặng, cơn mưa, ánh nắng qua tán lá.
- Gợi ý một việc nhỏ làm được ngay để thả lỏng, ví dụ hít thở chậm, uống một ngụm nước ấm, bước ra ngoài nhìn bầu trời.
- Không phán xét, không ra lệnh, tránh chữ "phải"; không hứa "mọi chuyện sẽ ổn" khi không có lý do.
- Không đưa lời khuyên y tế hay chẩn đoán. Nếu chủ đề chạm tới trầm cảm hay ý nghĩ làm hại bản thân, nhẹ nhàng khuyên người xem tìm đến người thân hoặc chuyên gia.
- Chỉ trích dẫn câu nói nổi tiếng khi chắc chắn đúng nguyên văn và đúng tác giả; nếu không chắc thì diễn đạt bằng lời của mình và không nêu tên tác giả.
- Câu ngắn, nhịp chậm; xen vài câu rất ngắn để tạo khoảng lặng.
- Kết thúc bằng một lời chúc bình yên ngắn, rồi mời người xem lưu lại để nghe khi cần.
""",
            ),
            default_seconds=45,
            overrides={
                "match_materials_to_script": False,
                "video_clip_duration": 5,
                "voice_rate": 0.9,
                "bgm_volume": 0.3,
                # Cắt cảnh trực tiếp như /dongluc để tránh khung đen đầu mỗi cảnh.
                "video_transition_mode": None,
            },
            seo_hint=(
                'Từ khoá chính là cảm xúc hoặc hoàn cảnh, ví dụ "mệt mỏi", "mất ngủ". Mô tả '
                "dịu dàng, mời lưu lại để nghe khi cần. Hashtag gợi ý: #chualanh, #binhyen, "
                "#thugian kèm hashtag theo chủ đề."
            ),
            default_hashtags=("#chualanh", "#binhyen", "#thugian"),
            visual_hint=(
                "thiên nhiên yên bình, chuyển động chậm: mặt hồ lặng (calm lake), nắng xuyên "
                "tán rừng (forest sunlight), mưa bên cửa sổ (rain window), giọt mưa (rain "
                "drops), tách trà (tea), cà phê bốc khói (coffee steam), ngọn nến (candle), "
                "lửa trại (campfire), trăng đêm (moon night), tuyết rơi (snowfall)"
            ),
        ),
        ContentPreset(
            key="tips",
            command="meo",
            title="Mẹo / hướng dẫn nhanh",
            description=(
                "3–5 mẹo làm được ngay, có cách làm và lý do: sức khoẻ, tài chính, năng "
                "suất, du lịch... Nêu rõ vấn đề và đối tượng, ví dụ: cho sinh viên."
            ),
            example="/meo 5 mẹo tiết kiệm tiền cho sinh viên",
            system_prompt=_system_prompt(
                "Biên kịch video mẹo hay ngắn gọn, thực dụng",
                """
- {length}
- Từ khoá chính có dạng "mẹo" hoặc "cách" kèm vấn đề, ví dụ "mẹo tiết kiệm tiền cho sinh viên"; câu đầu nêu từ khoá cùng lợi ích cụ thể người xem nhận được.
- Lợi ích hứa hẹn phải thực tế; không hứa kết quả bằng con số nếu không chắc chắn.
- Đưa ra 3–5 mẹo, đánh số bằng lời: "mẹo số một", "mẹo số hai"...; có thể báo trước mẹo cuối là mẹo nhiều người bỏ qua nhất để giữ người xem.
- Mỗi mẹo nói rõ làm gì, làm thế nào bằng bước hoặc ví dụ cụ thể, và vì sao hiệu quả. Bỏ qua mẹo hiển nhiên ai cũng biết.
- Mẹo phải an toàn và làm được ngay. Với sức khoẻ, tài chính, pháp lý: không đưa lời khuyên nguy hiểm và nhắc hỏi ý kiến chuyên gia khi cần.
- Ưu tiên câu gợi hình ảnh cụ thể có thể quay được, để cảnh minh hoạ khớp với lời đọc.
- Kết thúc bằng lời nhắc lưu video để dùng khi cần và một câu hỏi mời người xem chia sẻ mẹo của họ.
""",
            ),
            default_seconds=55,
            overrides={
                "match_materials_to_script": True,
                "video_clip_duration": 3,
                "voice_rate": 1.1,
                "subtitle_animation": "pop_spring",
            },
            seo_hint=(
                'Từ khoá chính có dạng "mẹo" hoặc "cách" kèm vấn đề, ví dụ "mẹo tiết kiệm '
                'tiền". Mô tả nêu lợi ích cụ thể và mời lưu lại. Hashtag gợi ý: #meohay, '
                "#meovat, #kinhnghiem kèm hashtag theo chủ đề."
            ),
            default_hashtags=("#meohay", "#meovat", "#kinhnghiem"),
            clarify="""
Bắt buộc:
- Vấn đề hoặc mục tiêu cụ thể. Chủ đề chỉ gồm một hai từ rất rộng như "sức khoẻ", "tiền", "học tập" thì cần hỏi người dùng muốn giải quyết việc gì.
Nên có, chỉ hỏi kèm khi đã phải hỏi mục bắt buộc:
- Đối tượng áp dụng, ví dụ sinh viên, nhân viên văn phòng, người mới bắt đầu.
""",
        ),
        ContentPreset(
            key="news",
            command="tintuc",
            title="Tin tức / tóm tắt",
            description=(
                "Tóm tắt bài báo bạn dán vào thành bản tin ngắn, trung lập, không thêm "
                "thông tin ngoài bài."
            ),
            example="/tintuc <dán nội dung bài báo, ít nhất 150 ký tự>",
            system_prompt=_system_prompt(
                "Biên tập viên bản tin ngắn",
                """
- Tóm tắt NGUỒN TIN trong phần "Additional User Requirements" thành bản tin ngắn để đọc. {length}
- CHỈ dùng thông tin có trong nguồn tin. Tuyệt đối không thêm sự kiện, số liệu, tên người, trích dẫn, nguyên nhân hay dự đoán không có trong nguồn.
- Từ khoá chính là sự kiện hoặc đối tượng trung tâm của tin, ví dụ tên chính sách, địa danh, tổ chức; nêu ngay trong câu đầu.
- Theo kiểu kim tự tháp ngược: câu đầu nêu điều quan trọng nhất là ai, làm gì, ở đâu, khi nào; tiếp theo là chi tiết và số liệu chính; sau cùng là bối cảnh, chỉ khi nguồn có nêu.
- Nếu nguồn nêu tác động tới người dân, nói rõ điều đó ảnh hưởng thế nào đến người xem.
- Giọng trung lập, khách quan, không giật tít, không bình luận cá nhân; giữ đúng tên riêng và con số như nguồn.
- Nếu nguồn có thời gian hoặc nơi đăng tin, nhắc lại ngắn gọn.
- Kết thúc bằng một câu hỏi trung lập mời người xem chia sẻ ý kiến, hoặc lời nhắc theo dõi để cập nhật diễn biến.
""",
            ),
            default_seconds=45,
            overrides={
                "match_materials_to_script": True,
                "video_clip_duration": 4,
                "voice_rate": 1.05,
                "bgm_volume": 0.12,
            },
            requires_source_text=True,
            min_prompt_length=150,
            seo_hint=(
                "Tiêu đề trung lập, nêu đúng sự kiện chính, không giật tít. Từ khoá chính "
                "là tên sự kiện, chính sách, địa danh hoặc tổ chức trong tin. Hashtag gợi "
                "ý: #tintuc, #tinmoi kèm tên sự kiện, địa danh."
            ),
            default_hashtags=("#tintuc", "#tinmoi", "#thoisu"),
        ),
        ContentPreset(
            key="product",
            command="sanpham",
            title="Giới thiệu sản phẩm",
            description=(
                "Video bán hàng dựng từ ảnh/video thật của sản phẩm (bắt buộc gửi kèm). "
                "Caption nên có: tên sản phẩm, 2–3 điểm nổi bật, giá/ưu đãi, cách mua."
            ),
            example=(
                "[gửi ảnh] caption: /sanpham Bình giữ nhiệt inox 500ml, giữ lạnh 24h, "
                "giá 199k, đặt qua inbox"
            ),
            system_prompt=_system_prompt(
                "Copywriter video bán hàng ngắn cho TikTok, Facebook Reels và YouTube Shorts",
                """
- {length}
- Chỉ dựa trên thông tin người dùng cung cấp về sản phẩm.
- Từ khoá chính là loại sản phẩm kèm đặc điểm nổi bật theo cách khách hàng gõ tìm kiếm, ví dụ "bình giữ nhiệt 500 mi-li-lít", kèm tên thương hiệu nếu có.
- Đi theo trình tự bán hàng:
  Mở đầu nói trúng vấn đề khách hàng hay gặp hoặc kết quả hấp dẫn nhất sản phẩm mang lại.
  Giới thiệu sản phẩm như lời giải cho vấn đề đó.
  Trình bày 2–4 điểm nổi bật; mỗi điểm biến tính năng thành lợi ích cụ thể, tả bằng cảm giác khi cầm, dùng, nhìn, nếm.
  Nêu bằng chứng tạo niềm tin như số đã bán, đánh giá, chứng nhận, bảo hành, chỉ khi người dùng cung cấp.
  Nêu giá, ưu đãi, quà tặng, thời hạn khuyến mãi, chỉ khi người dùng cung cấp.
  Kết thúc bằng lời kêu gọi hành động rõ ràng qua đúng kênh mua người dùng nêu; nếu không có thì mời nhắn tin để được tư vấn.
- Hình trong video là ảnh thật của sản phẩm, nên lời đọc luôn nói về đúng sản phẩm này, không lan man.
- Không đọc đường link. Số điện thoại viết từng chữ số bằng chữ để giọng đọc đọc rõ.
- Không bịa giá, khuyến mãi, thông số, chứng nhận, công dụng hay cam kết. Không dùng từ tuyệt đối như "tốt nhất", "số một", "duy nhất", "chữa khỏi" khi người dùng không đưa ra căn cứ.
""",
            ),
            default_seconds=35,
            overrides={
                "match_materials_to_script": False,
                "video_clip_duration": 3,
                "voice_rate": 1.05,
                "video_transition_mode": None,
            },
            accepts_media=True,
            requires_media=True,
            seo_hint=(
                "Từ khoá chính là loại sản phẩm kèm đặc điểm nổi bật theo cách khách hàng "
                "tìm kiếm, thêm tên thương hiệu nếu có. Mô tả nêu lợi ích chính, giá hoặc "
                "ưu đãi nếu kịch bản có, và cách mua. Hashtag gợi ý: tên loại sản phẩm, "
                "#review kèm loại sản phẩm, ngành hàng."
            ),
            default_hashtags=("#review", "#muasam", "#sanphamhot"),
            clarify="""
Bắt buộc:
- Tên hoặc loại sản phẩm cụ thể.
- Ít nhất 2 điểm nổi bật hoặc công dụng cụ thể, như chất liệu, kích thước, tính năng, cảm giác khi dùng.
Nên có, chỉ hỏi kèm khi đã phải hỏi mục bắt buộc:
- Giá bán hoặc ưu đãi đang có.
- Cách mua hoặc liên hệ: tên cửa hàng, địa chỉ, số điện thoại, nhắn tin.
""",
        ),
        ContentPreset(
            key="place",
            command="diadiem",
            title="Khám phá địa điểm",
            description=(
                "Khám phá sâu một điểm đến: cảnh đẹp, điểm tham quan, khu vui chơi, ẩm "
                "thực và kinh nghiệm thực tế. Có thể gửi kèm ảnh/video riêng."
            ),
            example="/diadiem Đà Lạt 2 ngày 1 đêm: săn mây, cà phê view đồi, chợ đêm",
            system_prompt=_system_prompt(
                "Hướng dẫn viên du lịch kiêm biên kịch video khám phá điểm đến",
                """
- {length}
- Từ khoá chính là tên địa điểm kèm ý định tìm kiếm, ví dụ "du lịch Hạ Long", "ăn gì ở Đà Lạt"; nhắc tên địa điểm trong câu đầu và 1–2 lần sau đó.
- Câu đầu nêu một điều đặc biệt, kỷ lục, khung cảnh ấn tượng hoặc điều ít người biết về nơi này, khiến người xem muốn đến ngay.
- Thân bài đi sâu theo cách sắp xếp hợp với yêu cầu: các điểm nổi bật; lịch trình sáng, chiều, tối; hoặc hành trình ẩm thực.
- Chọn những ý phù hợp: nguồn gốc, câu chuyện hay truyền thuyết ngắn; cảnh quan và công trình nổi bật; điểm tham quan, khu vui chơi, trải nghiệm nên thử; món đặc sản và nơi thưởng thức; thời điểm đẹp nhất để đến.
- Mỗi ý gọi tên cụ thể và tả bằng hình ảnh, âm thanh, mùi vị; mỗi câu nên gắn với một khung cảnh có thể quay được để cảnh minh hoạ khớp với lời đọc.
- Thêm ít nhất một kinh nghiệm thực tế hữu ích, như thời điểm tránh đông, cách di chuyển hoặc điều cần lưu ý.
- Ưu tiên thông tin người dùng cung cấp; phần bổ sung chỉ dùng kiến thức phổ biến, chắc chắn đúng.
- Không bịa giá vé, giờ mở cửa, địa chỉ, khuyến mãi hay số liệu; không chắc chắn thì bỏ qua.
- Kết thúc bằng lời mời lưu video cho chuyến đi tới hoặc rủ người xem tag bạn đồng hành, kèm câu hỏi họ đã từng đến đây chưa.
""",
            ),
            default_seconds=60,
            overrides={
                "match_materials_to_script": True,
                "video_clip_duration": 4,
                "voice_rate": 1.0,
                "video_transition_mode": None,
            },
            accepts_media=True,
            seo_hint=(
                'Từ khoá chính là tên địa điểm kèm ý định tìm kiếm, ví dụ "du lịch Hạ '
                'Long", "ăn gì ở Đà Lạt". Mô tả gợi cảm hứng, thêm một kinh nghiệm hữu ích '
                "có trong kịch bản và mời lưu lại cho chuyến đi. Hashtag gợi ý: #dulich kèm "
                "tên địa danh, tên địa danh, #dulichvietnam, #reviewdulich, #anuong nếu có "
                "ẩm thực."
            ),
            default_hashtags=("#dulich", "#dulichvietnam", "#reviewdulich"),
            clarify="""
Bắt buộc:
- Địa điểm cụ thể, xác định được vị trí. Tên quá chung hoặc dễ trùng như "chợ nổi", "biển", "chùa", "núi" thì cần hỏi tên và tỉnh, thành phố.
Nên có, chỉ hỏi kèm khi đã phải hỏi mục bắt buộc:
- Muốn tập trung vào đâu: cảnh đẹp, vui chơi, ẩm thực hay lịch trình.
""",
        ),
    )
}

PRESETS_BY_COMMAND: dict[str, ContentPreset] = {
    preset.command: preset for preset in PRESETS.values()
}

MIN_DURATION_SECONDS = 15
MAX_DURATION_SECONDS = 180
# Đo từ giọng Edge TTS tiếng Việt ở tốc độ 1.0 (khoảng 3,0–3,2 từ/giây).
WORDS_PER_SECOND = 3.1


@dataclass(frozen=True)
class Language:
    """Ngôn ngữ của video: lời đọc, giọng đọc và phụ đề."""

    code: str
    name: str
    # Ngôn ngữ viết kịch bản; rỗng nghĩa là viết theo ngôn ngữ của chủ đề như trước.
    script_language: str
    # Giọng đọc mặc định; rỗng nghĩa là dùng [ui].voice_name trong config.toml.
    voice: str = ""
    # Dùng khi [ui].voice_name là giọng của ngôn ngữ khác.
    fallback_voice: str = ""
    # Phụ đề dịch sang ngôn ngữ này; rỗng nghĩa là phụ đề đúng lời đọc.
    subtitle_language: str = ""
    # Số từ đọc được mỗi giây ở tốc độ 1.0, để quy đổi thời lượng ra độ dài kịch bản.
    words_per_second: float = WORDS_PER_SECOND
    # Thêm vào cuối system prompt, sau các quy tắc chung.
    instruction: str = ""


DEFAULT_LANGUAGE = "vi-VN"
LANGUAGES: dict[str, Language] = {
    language.code: language
    for language in (
        Language(
            code="vi-VN",
            name="Tiếng Việt",
            script_language="",
            fallback_voice="vi-VN-HoaiMyNeural-Female",
        ),
        Language(
            code="en-US",
            name="Tiếng Anh (Mỹ), phụ đề tiếng Việt",
            script_language="en-US",
            voice="en-US-AriaNeural-Female",
            subtitle_language="vi-VN",
            # Giọng Aria đọc khoảng 150–160 từ tiếng Anh mỗi phút.
            words_per_second=2.6,
            instruction=(
                "## Ngôn ngữ lời đọc:\n"
                "Viết toàn bộ lời đọc bằng tiếng Anh Mỹ tự nhiên, kể cả khi chủ đề, yêu "
                "cầu hay ý chính được viết bằng tiếng Việt; không áp dụng quy tắc viết "
                'cùng ngôn ngữ với chủ đề. Gọi người xem là "you". Độ dài tính theo số '
                "từ tiếng Anh."
            ),
        ),
    )
}
_VOICE_LOCALE_RE = re.compile(r"^([a-z]{2,3})-[A-Z]{2}-")


def get_language(code: str | None) -> Language:
    return LANGUAGES.get(code or "", LANGUAGES[DEFAULT_LANGUAGE])


def _resolve_voice(language: Language, ui_voice: str, override: str | None) -> str:
    """
    Giọng đọc theo ngôn ngữ: giọng chỉ định > giọng mặc định của ngôn ngữ >
    [ui].voice_name, trừ khi đó là giọng Edge/Azure của ngôn ngữ khác.
    """
    if override or language.voice:
        return override or language.voice
    locale = _VOICE_LOCALE_RE.match(ui_voice or "")
    if locale and locale[1] != language.code.split("-")[0] and language.fallback_voice:
        return language.fallback_voice
    return ui_voice

_MAX_SUBJECT_LENGTH = 200
_MAX_SOURCE_LENGTH = 2000
# Tiêu đề in lên ảnh bìa; ngắn thì chữ to, dễ đọc trên điện thoại.
_COVER_TITLE_LENGTH = 70
MAX_QUESTIONS = 3
_HASHTAG_COUNT = 5
# Hashtag không mô tả nội dung, không giúp nền tảng phân loại video.
_GENERIC_HASHTAGS = {"fyp", "foryou", "foryoupage", "viral", "trending", "xuhuong", "xh"}


def _cut(text: str, limit: int) -> str:
    """Cắt ở ranh giới từ để không để lại nửa chữ."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def cover_title(prompt: str, limit: int = 90) -> str:
    """Tiêu đề cover: dòng đầu của nội dung, cắt ở ranh giới từ nếu quá dài."""
    lines = (prompt or "").strip().splitlines()
    title = lines[0].strip() if lines else ""
    if len(title) <= limit:
        return title
    return _cut(title, limit) + "…"


def validate_prompt(
    preset: ContentPreset, prompt: str, media_count: int | None = None
) -> str | None:
    """
    Trả về thông báo lỗi tiếng Việt nếu prompt không dùng được, ngược lại None.

    ``media_count`` là số ảnh/video gửi kèm; None nghĩa là bỏ qua kiểm tra này.
    """
    prompt = (prompt or "").strip()
    if preset.requires_media and media_count == 0:
        return (
            f"Lệnh /{preset.command} cần ảnh/video thật của sản phẩm. Hãy gửi ảnh "
            f"hoặc album, caption bắt đầu bằng /{preset.command} <mô tả sản phẩm>."
        )
    if len(prompt) < preset.min_prompt_length:
        if preset.requires_source_text:
            return (
                f"Lệnh /{preset.command} cần nội dung bài báo gốc (ít nhất "
                f"{preset.min_prompt_length} ký tự) để không bịa tin. "
                f"Hiện có {len(prompt)} ký tự."
            )
        return f"Hãy nhập chủ đề sau lệnh. Ví dụ: {preset.example}"
    return None


def normalize_duration(seconds: int | float | None) -> int | None:
    if seconds is None:
        return None
    return int(min(max(seconds, MIN_DURATION_SECONDS), MAX_DURATION_SECONDS))


def _length_instruction(
    seconds: int, voice_rate: float, words_per_second: float = WORDS_PER_SECOND
) -> str:
    # Độ dài video do giọng đọc quyết định, nên quy đổi thời lượng ra số từ.
    words = seconds * words_per_second * max(voice_rate, 0.5)
    low, high = int(words * 0.9), int(words * 1.05)
    return (
        f"Độ dài BẮT BUỘC: {low}–{high} từ (đọc khoảng {seconds} giây). "
        f"Không viết dài hơn {high} từ."
    )


# ------------------------------------------------- hỏi lại người dùng

_CLARIFY_PROMPT = """
# Vai trò: Biên tập viên video ngắn

Người dùng muốn tạo video loại "{title}". Hãy kiểm tra yêu cầu đã đủ thông tin để làm một video có giá trị chưa.

## Thông tin cần có:
{checklist}

## Quy tắc:
1. Mặc định là KHÔNG hỏi. Chỉ hỏi khi thiếu thông tin bắt buộc mà không thể tự suy ra hợp lý.
2. Không hỏi về thời lượng, khung hình, giọng đọc, nhạc nền hay hình ảnh.
3. Tối đa {max_questions} câu hỏi; mỗi câu ngắn, dễ trả lời, kèm ví dụ gợi ý.
4. Viết bằng ngôn ngữ của yêu cầu, gọi người dùng là "bạn".
5. Chỉ trả về một object JSON, không markdown, không giải thích: {{"questions": ["..."]}}. Đủ thông tin thì trả về {{"questions": []}}.

## Yêu cầu của người dùng:
{prompt}{media_note}
""".strip()


def clarifying_questions(
    preset: ContentPreset, prompt: str, media_count: int = 0
) -> list[str]:
    """
    Câu hỏi cần người dùng trả lời trước khi tạo video; rỗng khi đủ thông tin,
    preset không cần hỏi hoặc AI không trả lời được (khi đó vẫn tạo video).
    """
    if not preset.clarify:
        return []
    media_note = f"\n(Đã gửi kèm {media_count} ảnh/video.)" if media_count else ""
    data = llm.generate_json_object(
        _CLARIFY_PROMPT.format(
            title=preset.title,
            checklist=preset.clarify.strip(),
            max_questions=MAX_QUESTIONS,
            prompt=prompt.strip()[:_MAX_SOURCE_LENGTH],
            media_note=media_note,
        )
    )
    raw = (data or {}).get("questions")
    if not isinstance(raw, list):
        return []
    questions = [" ".join(str(item).split()) for item in raw]
    return [question[:200] for question in questions if question][:MAX_QUESTIONS]


def merge_answers(prompt: str, questions: Sequence[str], answer: str) -> str:
    """Ghép câu trả lời vào yêu cầu; dòng đầu giữ nguyên để làm chủ đề video."""
    asked = "\n".join(f"- {question}" for question in questions)
    return (
        f"{prompt.strip()}\n\nThông tin bổ sung từ người dùng:\n"
        f"Câu hỏi:\n{asked}\nTrả lời: {answer.strip()}"
    )


# ------------------------------------------------- chủ đề con cho loạt video

MAX_BATCH_TOPICS = 30
_SUBTOPIC_TITLE_LENGTH = 100
_SUBTOPIC_CONTENT_LENGTH = 300

_SUBTOPICS_PROMPT = """
# Vai trò: Biên tập viên kênh video ngắn trên TikTok, YouTube Shorts và Facebook Reels

Người dùng muốn làm một loạt video loại "{title}" xoay quanh chủ đề lớn bên dưới.
Mô tả loại video: {description}

## Yêu cầu:
1. Đề xuất đúng {count} chủ đề con, mỗi chủ đề con làm thành một video riêng.
2. Mỗi chủ đề con đi vào một khía cạnh, tình huống hoặc góc nhìn khác nhau; không trùng ý nhau và vẫn bám sát chủ đề lớn.
3. "title": tên video cụ thể, tối đa 80 ký tự, chứa từ khoá người xem sẽ gõ để tìm; ví dụ với loại video này: "{example}".
4. "content": 1–3 câu, tối đa 250 ký tự, nêu các ý chính video sẽ nói để người dùng duyệt trước.
5. Chỉ dùng kiến thức phổ biến, chắc chắn đúng; không bịa số liệu, giá, sự kiện hay trích dẫn.
6. Viết cùng ngôn ngữ với chủ đề lớn.
7. Chỉ trả về một object JSON hợp lệ, không markdown, không giải thích:
{{"topics": [{{"title": "...", "content": "..."}}]}}

## Chủ đề lớn:
{theme}{revision}
""".strip()

_SUBTOPICS_REVISION = """

## Danh sách đã đề xuất:
{previous}

## Góp ý của người dùng:
{feedback}

Sửa danh sách đã đề xuất theo góp ý. Trừ khi góp ý yêu cầu khác, giữ nguyên các chủ đề con không bị nhắc tới; nếu góp ý yêu cầu thêm hoặc bớt thì số chủ đề con có thể khác {count}."""


@dataclass
class Subtopic:
    """Một video trong loạt: tên video và các ý chính người dùng đã duyệt."""

    title: str
    content: str = ""

    def prompt(self) -> str:
        """Yêu cầu tạo video: dòng đầu làm chủ đề, ý chính đã duyệt đi vào kịch bản."""
        return f"{self.title}\n{self.content}" if self.content else self.title


def generate_subtopics(
    preset: ContentPreset,
    theme: str,
    count: int,
    previous: Sequence[Subtopic] = (),
    feedback: str = "",
) -> list[Subtopic]:
    """
    Đề xuất ``count`` chủ đề con kèm ý chính cho một loạt video cùng chủ đề lớn.

    Có ``feedback`` thì sửa danh sách ``previous`` theo góp ý của người dùng.
    Rỗng khi AI không trả lời được.
    """
    revision = ""
    if feedback.strip():
        listed = "\n".join(
            f"{index}. {topic.title}: {topic.content}"
            for index, topic in enumerate(previous, start=1)
        )
        revision = _SUBTOPICS_REVISION.format(
            previous=listed or "(trống)",
            feedback=feedback.strip()[:_MAX_SOURCE_LENGTH],
            count=count,
        )
    data = llm.generate_json_object(
        _SUBTOPICS_PROMPT.format(
            title=preset.title,
            description=preset.description,
            count=count,
            example=preset.example.split(" ", 1)[-1],
            theme=theme.strip()[:_MAX_SOURCE_LENGTH],
            revision=revision,
        )
    )
    raw = (data or {}).get("topics")
    if not isinstance(raw, list):
        return []
    topics: list[Subtopic] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            title, content = _one_line(item.get("title")), _one_line(item.get("content"))
        else:
            title, content = _one_line(item), ""
        title = _cut(title, _SUBTOPIC_TITLE_LENGTH)
        if title and title.lower() not in seen:
            seen.add(title.lower())
            topics.append(Subtopic(title, _cut(content, _SUBTOPIC_CONTENT_LENGTH)))
    # Lần đề xuất đầu giữ đúng số video người dùng yêu cầu; khi sửa theo góp ý
    # thì số lượng có thể đổi.
    return topics[: MAX_BATCH_TOPICS if revision else min(count, MAX_BATCH_TOPICS)]


# ------------------------------------------------- từ khoá tìm video kho

_TERMS_PROMPT = """
# Vai trò: Biên tập hình ảnh cho video ngắn dựng từ kho video miễn phí

Kịch bản bên dưới sẽ được minh hoạ bằng các đoạn video có sẵn trên Pixabay. Hãy viết {amount} từ khoá tìm kiếm.

## Yêu cầu:
1. Tiếng Anh, mỗi từ khoá 1–3 từ, là cảnh quay được: đối tượng, nơi chốn hoặc hành động cụ thể, ví dụ "calm lake", "man hiking", "rain window".
2. Không dùng từ trừu tượng như success, motivation, failure, dream, discipline, growth; thay bằng cảnh gợi được ý đó.
3. Ưu tiên các cảnh sau, chọn cảnh hợp với từng đoạn kịch bản: {visual_hint}.
4. {order_rule}
5. Các từ khoá khác nhau, không lặp ý.
6. Chỉ trả về một object JSON hợp lệ, không markdown, không giải thích: {{"terms": ["...", "..."]}}

## Chủ đề:
{subject}

## Kịch bản:
{script}
""".strip()

_TERM_LENGTH = 40


def generate_search_terms(preset: ContentPreset, params: VideoParams) -> list[str]:
    """
    Từ khoá tìm video kho là cảnh quay cụ thể theo ``visual_hint`` của preset.

    Rỗng khi preset không có gợi ý, chưa có kịch bản hoặc AI không trả lời được;
    khi đó pipeline tự sinh từ khoá như trước. Số lượng và thứ tự giống
    task.generate_terms để bước tải clip không đổi.
    """
    script = utils.remove_pause_tags(params.video_script or "").strip()
    if not preset.visual_hint or not script:
        return []
    amount = 8 if params.match_materials_to_script else 5
    order_rule = (
        "Giữ đúng thứ tự nội dung trong kịch bản: từ khoá trước minh hoạ đoạn trước."
        if params.match_materials_to_script
        else "Bao quát nhiều cảnh khác nhau trong kịch bản."
    )
    data = llm.generate_json_object(
        _TERMS_PROMPT.format(
            amount=amount,
            visual_hint=preset.visual_hint,
            order_rule=order_rule,
            subject=params.video_subject,
            script=script[:_MAX_SOURCE_LENGTH],
        )
    )
    raw = (data or {}).get("terms")
    if not isinstance(raw, list):
        return []
    terms: list[str] = []
    for item in raw:
        term = _cut(_one_line(item), _TERM_LENGTH)
        if term and term.lower() not in {existing.lower() for existing in terms}:
            terms.append(term)
    return terms[:amount]


# ------------------------------------------------- ảnh động (GIF) có chữ

# Chữ trên GIF phải đọc lướt được trong vài giây.
GIF_TEXT_LENGTH = 110
_GIF_TEXT_LIMIT = 160
# Lời diễn giải đi kèm (file .txt và caption Telegram) dài như lời thoại video ngắn.
_GIF_DETAIL_LIMIT = 800
_GIF_TERM_COUNT = 3

_GIF_PROMPT = """
# Vai trò: Biên tập viên ảnh động có chữ cho mạng xã hội

Người dùng muốn một ảnh GIF loại "{title}" có chữ chèn lên, không lồng tiếng.
Mô tả loại nội dung: {description}

## Yêu cầu:
1. "text": tiêu đề của ảnh GIF, được chèn lên ảnh và dùng làm tên file: một câu, hoặc hai câu rất ngắn, tối đa {max_chars} ký tự, chắt lọc ý hay nhất của yêu cầu đúng tinh thần loại nội dung trên; đọc lướt 3 giây là hiểu.
2. "detail": lời diễn giải chi tiết hơn "text", như lời thoại của một video ngắn cùng chủ đề: 3–5 câu, khoảng 250–500 ký tự, triển khai ý của "text" bằng giải thích hoặc ví dụ cụ thể, giọng văn tự nhiên để đọc thành tiếng; không chép lại nguyên văn "text".
3. Không hashtag, không emoji, không ngoặc kép bao quanh, không lời chào, không kêu gọi bình luận hay theo dõi.
4. Chỉ dùng kiến thức chắc chắn đúng; không bịa số liệu, sự kiện hay trích dẫn; không gán câu nói cho người thật khi không chắc nguyên văn.{source_rule}
5. {language_rule}
6. "terms": {term_count} từ khoá tìm video tiếng Anh, mỗi từ khoá 1–3 từ, là cảnh quay cụ thể minh hoạ đúng "text" (đối tượng, nơi chốn hoặc hành động), sát nghĩa nhất đứng đầu; không dùng từ trừu tượng như success, motivation, failure.{visual_rule}{variety_rule}
7. Chỉ trả về một object JSON hợp lệ, không markdown, không giải thích: {{"text": "...", "detail": "...", "terms": ["...", "...", "..."]}}

## Yêu cầu của người dùng:
{prompt}
""".strip()


@dataclass
class GifText:
    """Chữ chèn lên ảnh động (cũng là tiêu đề), từ khoá tìm clip Pixabay sát nghĩa nhất
    trước, và lời diễn giải chi tiết hơn; rỗng nếu AI không viết."""

    text: str
    terms: list[str]
    detail: str = ""


def generate_gif_text(
    preset: ContentPreset,
    prompt: str,
    language: str | None = None,
    avoid_terms: Sequence[str] = (),
) -> GifText | None:
    """
    Câu ngắn để chèn lên GIF kèm từ khoá cảnh quay và lời diễn giải; None nếu AI
    không trả lời được.

    ``avoid_terms``: cảnh các ảnh trước trong cùng loạt đã dùng, để loạt ảnh đa dạng.
    """
    lang = get_language(language)
    if lang.script_language.startswith("en"):
        language_rule = "Viết bằng tiếng Anh Mỹ tự nhiên, kể cả khi yêu cầu viết bằng tiếng Việt."
    else:
        language_rule = "Viết cùng ngôn ngữ với yêu cầu của người dùng."
    source_rule = (
        " Chỉ dùng thông tin có trong nguồn tin người dùng gửi."
        if preset.requires_source_text
        else ""
    )
    visual_rule = (
        f" Cảnh hợp với loại nội dung này: {preset.visual_hint}." if preset.visual_hint else ""
    )
    used = list(dict.fromkeys(term for term in avoid_terms if term))
    variety_rule = (
        f" Các ảnh trước trong cùng loạt đã dùng cảnh: {', '.join(used)}; nếu vẫn đúng ý "
        "thì chọn cảnh khác để loạt ảnh không lặp lại."
        if used
        else ""
    )
    data = llm.generate_json_object(
        _GIF_PROMPT.format(
            title=preset.title,
            description=preset.description,
            max_chars=GIF_TEXT_LENGTH,
            source_rule=source_rule,
            language_rule=language_rule,
            term_count=_GIF_TERM_COUNT,
            visual_rule=visual_rule,
            variety_rule=variety_rule,
            prompt=prompt.strip()[:_MAX_SOURCE_LENGTH],
        )
    )
    text = _one_line((data or {}).get("text"))
    if not text:
        return None
    if len(text) > _GIF_TEXT_LIMIT:
        text = _cut(text, _GIF_TEXT_LIMIT - 1) + "…"
    raw = data.get("terms")
    terms: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        term = _cut(_one_line(item), _TERM_LENGTH)
        if term and term.lower() not in {existing.lower() for existing in terms}:
            terms.append(term)
    detail = _one_line(data.get("detail"))
    if len(detail) > _GIF_DETAIL_LIMIT:
        detail = _cut(detail, _GIF_DETAIL_LIMIT - 1) + "…"
    return GifText(text, terms[:_GIF_TERM_COUNT], detail)


# ------------------------------------------------- nội dung đăng bài (SEO)

_POST_PROMPT = """
# Vai trò: Chuyên gia SEO video ngắn trên TikTok, YouTube Shorts và Facebook Reels

## Nhiệm vụ:
Viết nội dung đăng kèm video loại "{title}" dựa trên chủ đề và kịch bản bên dưới.

## Yêu cầu:
1. "keyword": từ khoá chính, cụm 2–5 từ người xem thực sự gõ vào ô tìm kiếm để tìm video này; ưu tiên cụm đã được nói trong câu đầu của kịch bản.
2. "title": tối đa 60 ký tự, chứa từ khoá chính trong 4 từ đầu, gây tò mò nhưng đúng nội dung; không emoji, không hashtag, không ngoặc kép. Tiêu đề được in lên ảnh bìa video và dùng làm tiêu đề YouTube Shorts.
3. "caption": 2–4 câu, khoảng 150–300 ký tự. Câu đầu chứa từ khoá chính trong 60 ký tự đầu vì nền tảng chỉ hiện chừng ấy trước chữ "xem thêm". Tóm tắt giá trị người xem nhận được, lồng ghép tự nhiên 2–3 từ khoá liên quan theo cách người dùng tìm kiếm, kết thúc bằng lời mời bình luận, lưu hoặc chia sẻ. Tối đa 2 emoji, không hashtag.
4. "hashtags": mảng {hashtag_count} hashtag viết liền, không dấu, chữ thường: một hashtag là từ khoá chính, 2–3 hashtag ngách đúng chủ đề, một hashtag chủ đề rộng. Không dùng hashtag chung chung như #fyp, #viral, #xuhuong.
5. Chỉ dùng thông tin có trong kịch bản; không bịa giá, ưu đãi, số liệu hay sự kiện.
6. Viết cùng ngôn ngữ với kịch bản.
7. Gợi ý riêng cho loại video này: {seo_hint}
8. Chỉ trả về một object JSON hợp lệ, không markdown, không giải thích:
{{"keyword": "...", "title": "...", "caption": "...", "hashtags": ["#...", "#..."]}}

## Chủ đề:
{subject}

## Kịch bản:
{script}
""".strip()


@dataclass
class PostPackage:
    """Nội dung đăng kèm video: từ khoá, tiêu đề, mô tả và hashtag chuẩn SEO."""

    keyword: str
    title: str
    caption: str
    hashtags: list[str]

    def text(self, limit: int = 1000) -> str:
        """Bản để dán thẳng khi đăng bài, gọn trong ``limit`` ký tự."""
        tags = " ".join(self.hashtags)
        room = max(limit - len(self.title) - len(tags) - 4, 0)
        caption = self.caption
        if len(caption) > room:
            caption = _cut(caption, room - 1) + "…" if room > 1 else ""
        return "\n\n".join(part for part in (self.title, caption, tags) if part)


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split()).strip("\"'“”")


def _strip_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _clean_hashtags(raw: Any, fallback: Sequence[str]) -> list[str]:
    """Hashtag viết liền, không dấu, chữ thường; TikTok Việt Nam khớp dạng không dấu tốt hơn."""
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[\s,]+", str(raw or ""))
    tags: list[str] = []
    for item in [*items, *fallback]:
        tag = re.sub(r"[^a-z0-9_]", "", _strip_diacritics(str(item)).lower())
        if tag and tag not in _GENERIC_HASHTAGS and f"#{tag}" not in tags:
            tags.append(f"#{tag}")
    return tags[:_HASHTAG_COUNT]


def generate_post(
    preset: ContentPreset, subject: str, script: str, language: str = ""
) -> PostPackage | None:
    """
    Viết tiêu đề, mô tả và hashtag chuẩn SEO từ kịch bản; None nếu AI không trả lời được.

    ``language`` là ngôn ngữ kịch bản; hashtag bù mặc định của preset là tiếng
    Việt nên chỉ dùng khi kịch bản không phải ngôn ngữ khác.
    """
    fallback = preset.default_hashtags if language[:2] in ("", "vi") else ()
    data = llm.generate_json_object(
        _POST_PROMPT.format(
            title=preset.title,
            hashtag_count=_HASHTAG_COUNT,
            seo_hint=preset.seo_hint or "không có",
            subject=subject,
            script=script,
        )
    )
    title = _one_line((data or {}).get("title"))[:100]
    if not title:
        return None
    return PostPackage(
        keyword=_one_line(data.get("keyword"))[:80],
        title=title,
        caption=str(data.get("caption") or "").strip()[:1000],
        hashtags=_clean_hashtags(data.get("hashtags"), fallback),
    )


def prepare_script_and_post(
    preset: ContentPreset, params: VideoParams
) -> PostPackage | None:
    """
    Viết kịch bản trước khi dựng để có nội dung đăng bài chuẩn SEO, rồi dùng
    tiêu đề SEO (chứa từ khoá chính) làm tiêu đề ảnh bìa. Preset có
    ``visual_hint`` thì chọn luôn từ khoá tìm video kho là cảnh quay cụ thể.

    Lỗi ở bước này không chặn tạo video: khi chưa có kịch bản, pipeline tự viết
    lại và ảnh bìa giữ tiêu đề lấy từ yêu cầu của người dùng; khi chưa có từ
    khoá, pipeline tự sinh từ khoá như trước.
    """
    script = llm.generate_script(
        video_subject=params.video_subject,
        language=params.video_language,
        paragraph_number=params.paragraph_number,
        video_script_prompt=params.video_script_prompt,
        custom_system_prompt=params.custom_system_prompt,
    )
    if not script or "Error: " in script:
        return None
    params.video_script = script
    try:
        terms = generate_search_terms(preset, params)
    except Exception as exc:
        logger.warning(f"failed to generate stock video search terms: {exc}")
        terms = []
    if terms:
        params.video_terms = terms
    try:
        post = generate_post(
            preset, params.video_subject, script, params.video_language or ""
        )
    except Exception as exc:
        logger.warning(f"failed to generate post metadata: {exc}")
        return None
    if post:
        params.cover_title = cover_title(post.title, _COVER_TITLE_LENGTH)
    return post


# ------------------------------------------------------------ dựng tham số


def build_params(
    preset: ContentPreset,
    prompt: str,
    material_paths: Sequence[str] | None = None,
    video_aspect: str | None = None,
    duration_seconds: int | None = None,
    language: str | None = None,
    voice_name: str | None = None,
) -> VideoParams:
    """
    Dựng VideoParams cho một preset.

    Thiết lập nền (giọng, font, phụ đề...) đọc từ config.toml qua đúng logic của
    CLI, sau đó preset ghi đè các tham số đặc trưng cho từng loại nội dung.
    ``duration_seconds`` là thời lượng mong muốn; None thì dùng mặc định của preset.
    ``language`` là mã trong LANGUAGES (mặc định tiếng Việt); ``voice_name`` thay
    giọng mặc định của ngôn ngữ đó.
    """
    lang = get_language(language)
    # Import trễ để module này dùng được mà không kéo theo argparse khi không cần.
    import cli

    if preset.requires_media and not material_paths:
        raise ValueError(f"Preset {preset.key} cần ảnh/video do người dùng cung cấp")

    prompt = prompt.strip()
    # Dòng đầu làm chủ đề; phần còn lại (mô tả dài, câu trả lời bổ sung, toàn bộ
    # bài báo) đi vào yêu cầu viết kịch bản.
    subject = _cut(prompt.splitlines()[0].strip() if prompt else "", _MAX_SUBJECT_LENGTH)
    if preset.requires_source_text:
        script_prompt = "NGUỒN TIN:\n" + prompt[:_MAX_SOURCE_LENGTH - 20]
    else:
        script_prompt = prompt[:_MAX_SOURCE_LENGTH] if prompt != subject else ""

    base = cli.build_video_params(cli.parse_args(["--video-subject", subject]))
    # dict(model) giữ nguyên giá trị đã validate, tránh cảnh báo serialize enum.
    values = dict(base)
    values.update(preset.overrides)
    seconds = normalize_duration(duration_seconds) or preset.default_seconds
    system_prompt = preset.system_prompt.replace(
        "{length}",
        _length_instruction(
            seconds, float(values["voice_rate"] or 1.0), lang.words_per_second
        ),
    )
    if lang.instruction:
        system_prompt += f"\n\n{lang.instruction}"
    values.update(
        video_subject=subject,
        video_script_prompt=script_prompt,
        custom_system_prompt=system_prompt,
        video_language=lang.script_language,
        voice_name=_resolve_voice(lang, values.get("voice_name") or "", voice_name),
        subtitle_language=lang.subtitle_language,
        # Khoảng 20 giây một đoạn, nằm trong giới hạn 1–10 của VideoParams.
        paragraph_number=min(max(round(seconds / 20), 1), 10),
        video_source=config.app.get("video_source", "pexels") or "pexels",
        video_aspect=VideoAspect(video_aspect or VideoAspect.portrait.value),
        video_materials=None,
        # Cover có tiêu đề ghép vào đầu video; [app].cover_intro_seconds = 0 để tắt.
        # prepare_script_and_post thay bằng tiêu đề SEO khi viết được.
        cover_title=cover_title(prompt),
        cover_label=preset.title.split("/")[0].strip(),
        cover_intro_seconds=min(max(float(config.app.get("cover_intro_seconds", 1.0)), 0), 5),
    )

    if material_paths:
        # Chia đều thời lượng cho từng ảnh/video để mỗi tệp xuất hiện một lần,
        # chỉ lặp lại khi người dùng gửi quá ít tệp.
        per_item = math.ceil(seconds / len(material_paths))
        values.update(
            video_source="local",
            # Giữ đúng thứ tự ảnh/video người dùng gửi.
            video_concat_mode="sequential",
            match_materials_to_script=False,
            video_clip_duration=min(max(per_item, values["video_clip_duration"]), 10),
            video_materials=[
                MaterialInfo(provider="local", url=path, duration=0)
                for path in material_paths
            ],
        )

    return VideoParams(**values)
