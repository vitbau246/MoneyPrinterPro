> **Nguồn / Source:** bản tuỳ biến dựa trên dự án gốc **MoneyPrinterTurbo** của Harry –
> https://github.com/harry0703/MoneyPrinterTurbo (giấy phép MIT, giữ nguyên trong `LICENSE`).
> Phần bổ sung trong bản này: bot Telegram, chế độ "Tạo nhanh" trên web (cùng chức năng với bot),
> ảnh GIF có chữ, thư viện thành phẩm, lập lịch và tự động đăng Facebook Reels / TikTok / YouTube
> Shorts. Bản này không kết nối tới kho gốc (không tự cập nhật, không kiểm tra phiên bản).
> This is a customised fork of the original project above (MIT License).

<div align="center">

# MoneyPrinterTurbo 💸

### オールインワン AI ショート動画生成ツール

動画の<b>テーマ</b>または<b>キーワード</b>を指定するだけで、MoneyPrinterTurbo が台本の生成、素材のマッチング、字幕と BGM の作成を行い、高画質のショート動画を出力します。

[![Version](https://img.shields.io/github/v/release/harry0703/MoneyPrinterTurbo?color=blue&label=version)](https://github.com/harry0703/MoneyPrinterTurbo/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://github.com/harry0703/MoneyPrinterTurbo/releases/latest)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Downloads](https://img.shields.io/github/downloads/harry0703/MoneyPrinterTurbo/total)](https://github.com/harry0703/MoneyPrinterTurbo/releases/latest)

<a href="https://trendshift.io/repositories/8731" target="_blank"><img src="https://trendshift.io/api/badge/repositories/8731" alt="harry0703%2FMoneyPrinterTurbo | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
<a href="https://www.star-history.com/harry0703/moneyprinterturbo"><img src="https://api.star-history.com/badge?repo=harry0703/MoneyPrinterTurbo" alt="Star History Rank" style="height: 55px;" height="55"/></a>

日本語 | [English](README-en.md) | [简体中文](README.md) | [Tiếng Việt](README-vi.md) | [リリース](https://github.com/harry0703/MoneyPrinterTurbo/releases) | [Issues](https://github.com/harry0703/MoneyPrinterTurbo/issues)

</div>

## スクリーンショット 🖥️

<h4 align="center">WebUI</h4>

![](docs/webui-en.jpg)

<h4 align="center">API</h4>

![](docs/api.jpg)

---

## スペシャルサンクス ❤️

<div align="center">
  <a href="https://platform.kimi.ai?track_id=track-f6b0a640d35c41deb03b247242a1058c&aff=moneyprinterturbo" target="_blank"><img src="https://gcdn.moonshot.cn/growth-cdn/sponsor/kimi-en.png" alt="Kimi sponsors MoneyPrinterTurbo" width="100%"></a>
</div>

本プロジェクトをスポンサードしてくださっている [Kimi](https://platform.kimi.ai?track_id=track-f6b0a640d35c41deb03b247242a1058c&aff=moneyprinterturbo) に感謝します！ [Kimi K3](https://www.kimi.com/blog/kimi-k3?aff=moneyprinterturbo) は Moonshot AI の最も高性能なモデルであり、世界初の 3T クラスのオープンモデルです。ネイティブの視覚能力と 100 万トークンのコンテキストウィンドウを備えた K3 は、ナレッジワーク、推論、長期にわたるタスクにおいて最先端の性能を発揮します。MoneyPrinterTurbo では、K3 が台本の作成と、最終的な映像素材を左右する検索キーワードの抽出を担い、動画制作を支えています。内容をより深く理解するほど、より適切な素材が得られます。

**MoneyPrinterTurbo ユーザー限定特典: 専用リンクから新規登録すると、初回のチャージ成功額の 10% 相当（上限 1,000 元）の API クレジットがボーナスとして付与されます。特典の終了は 2026 年 9 月 30 日です。Kimi オープンプラットフォーム（[中国語サイト](https://platform.kimi.com?track_id=track-2f5441d6ffd84c509dd079d78e9db5dc&aff=moneyprinterturbo) | [グローバル](https://platform.kimi.ai?track_id=track-f6b0a640d35c41deb03b247242a1058c&aff=moneyprinterturbo)）から API をお試しください。**

<br>
<table align="center">
  <tr>
    <td align="center" width="120">
      <a href="https://www.byteplus.com/en/product/modelark?utm_campaign=hw&utm_content=MoneyPrinterTurbo&utm_medium=devrel_tool_web&utm_source=OWO&utm_term=MoneyPrinterTurbo"><img src="docs/sponsors/byteplus-logo.svg" alt="BytePlus" height="25"></a><br>
      <a href="https://www.byteplus.com/en/product/modelark?utm_campaign=hw&utm_content=MoneyPrinterTurbo&utm_medium=devrel_tool_web&utm_source=OWO&utm_term=MoneyPrinterTurbo"><strong>BytePlus ModelArk</strong></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている ByteDance VolcEngine に感謝します！ VolcEngine Ark の中国主要モデル向け Agent/Coding Plan は初回購入なら 9.9 元から利用でき、GLM-5.3、Kimi-K3、DeepSeek、MiniMax、Doubao などに対応しています。新規ユーザーには 2,500 万トークンの無料枠が付与されます。1 つの統合 API で、コーディングとエージェント開発に最適化されています。<a href="https://www.byteplus.com/en/product/modelark?utm_campaign=hw&utm_content=MoneyPrinterTurbo&utm_medium=devrel_tool_web&utm_source=OWO&utm_term=MoneyPrinterTurbo">今すぐアクセス</a>
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://www.ccsub.net/register?ref=VCVDAWWY"><img src="docs/sponsors/ccsub-logo.png" alt="CCSub" height="36"></a><br>
      <a href="https://www.ccsub.net/register?ref=VCVDAWWY"><strong>CCSub</strong></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている <a href="https://www.ccsub.net/register?ref=VCVDAWWY">CCSub</a> に感謝します！ CCSub は安定的で手頃な AI API 中継プラットフォームであり、Claude.ai のサブスクリプションをそのまま置き換えられます。API キー 1 つで Claude Opus 4.8、Sonnet、Haiku、GPT-5、Gemini を直接 API のおよそ 30% のコストで利用でき、世界中どこからでも VPN は不要です。Claude Code、Codex、Cursor、Cline、Continue、Windsurf をはじめとする主要な AI コーディングツールに対応しています。<a href="https://www.ccsub.net/register?ref=VCVDAWWY">www.ccsub.net</a> から登録すると、初回登録時に 5 ドル分の無料クレジットがもらえます。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://go.apimart.ai/gh-moneyprinterturbo"><img src="docs/sponsors/apimart-logo.png" alt="APIMart" width="100"></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている <a href="https://go.apimart.ai/gh-moneyprinterturbo">APIMart</a> に感謝します！ APIMart は、AI 画像・動画生成に特化した低価格 API プラットフォームです。<strong>GPT-Image-2 は 1 枚あたり 0.006 米ドルから利用でき、1 米ドルで 160 枚以上の画像を生成できます</strong>。<strong>画像と動画を 1 つの非同期 API で扱い、コードを変更せずにモデルを切り替えられます</strong>。タスクを送信して ID を受け取った後、ポーリングまたはコールバックで結果を取得でき、数万枚規模のバッチ処理にも対応します。月額料金のない従量課金制で、<a href="https://go.apimart.ai/gh-moneyprinterturbo">こちらの登録リンク</a>からすぐに利用を開始できます。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://metaso.cn/minimax-h3/?s=MPT"><img src="docs/sponsors/metaso-logo.png" alt="Metaso" width="100"></a><br>
      <a href="https://metaso.cn/minimax-h3/?s=MPT"><strong>Metaso</strong></a>
    </td>
    <td align="left">
      <strong>Metaso の MiniMax H3 動画生成 API</strong><br>
      Metaso は、コストパフォーマンスに優れた MiniMax H3 動画生成サービスを提供しています。料金は <strong>768P が 1 秒あたり 0.09 元、2K が 1 秒あたり 0.15 元</strong>です。ネイティブ 2K、映像と音声の同期、OpenAI 互換 API、ComfyUI に対応しており、GPU を自分で用意・運用する必要はありません。<br>
      🎁 <a href="https://metaso.cn/minimax-h3/?s=MPT">MoneyPrinterTurbo 専用リンク</a>から登録すると、ボーナスクレジットや限定特典を受け取れます。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://ofox.ai/?utm_source=github&amp;utm_medium=sponsorship&amp;utm_content=moneyprinterturbo"><img src="docs/sponsors/ofox-logo.svg" alt="OfoxAI" width="120"></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている <a href="https://ofox.ai/?utm_source=github&amp;utm_medium=sponsorship&amp;utm_content=moneyprinterturbo">OfoxAI</a> に感謝します！ MoneyPrinterTurbo はすでに Ofox のマルチモデルによるテキスト動画生成に対応しており、API キーを設定するだけで利用を開始できます。Seedance、MiniMax H3、Wan で動画素材を作成し、GPT Image 2.5 と Seedream でカバー画像をデザインし、GPT、Claude、Gemini、DeepSeek で台本の推敲やアプリケーション開発を行えます。<strong>1 つのキーと共通の残高でテキスト・画像・動画モデルを利用でき</strong>、OpenAI 互換エンドポイントに加えて Anthropic と Gemini のネイティブインターフェースにも対応しています。<strong>従量課金、透明な料金体系、モデル提供元の公式チャネルにより、安定・高速・無制限のアクセスを提供します。</strong> <a href="https://ofox.ai/?utm_source=github&amp;utm_medium=sponsorship&amp;utm_content=moneyprinterturbo">OfoxAI のモデルと料金</a>をご覧ください。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://infistar.cc/register?aff=6T4EYXP2&amp;ref_source=link"><img src="docs/sponsors/infistar-logo.svg" alt="Infistar.ai" height="56"></a><br>
      <a href="https://infistar.cc/register?aff=6T4EYXP2&amp;ref_source=link"><strong>Infistar.ai</strong></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている <a href="https://infistar.cc/register?aff=6T4EYXP2&amp;ref_source=link">Infistar.ai</a> に感謝します！<br>
      ⚡ 低コストで信頼性の高いアクセス: 価格は公式レートのわずか 10% から。モデル倍率は透明で、詳細な利用履歴も確認できます。複数プロバイダーへの動的ルーティングにより、レート制限や予期しないサービス中断を回避できます。<br>
      🧠 台本作成に最適な最先端 LLM: OpenAI、Claude、Google Gemini、DeepSeek、Qwen などの主要モデルを OpenAI 互換 API 経由で利用できます。Infistar.ai は MoneyPrinterTurbo の台本生成と素材キーワード抽出のワークフローに、低レイテンシかつ高並列なサポートを提供します。<br>
      🎨 最先端のマルチモーダルエコシステム: FLUX、Midjourney、Seedance、Kling、Sora、Luma といった主要な画像・動画生成モデルを利用でき、次世代の AI 動画制作にすぐ活用できます。<br>
      🎁 MoneyPrinterTurbo ユーザーは、<a href="https://infistar.cc/register?aff=6T4EYXP2&amp;ref_source=link">専用の紹介リンク</a>から登録し、Infistar.ai が現在提供している限定特典を確認できます。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://www.shengsuanyun.com/?from=CH_XUQ4OTSK"><img src="docs/sponsors/shengsuanyun-logo.jpg" alt="Shengsuan Cloud" height="56"></a><br>
      <a href="https://www.shengsuanyun.com/?from=CH_XUQ4OTSK"><strong>Shengsuan Cloud</strong></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている <a href="https://www.shengsuanyun.com/?from=CH_XUQ4OTSK">Shengsuan Cloud</a> に感謝します！ Shengsuan Cloud は AI ネイティブなチーム向けの API 集約プラットフォームで、Claude、ChatGPT、Gemini などの主要な言語モデルやマルチモーダルモデルを、統一 API と従量課金で利用できます。<br>
      コンプライアンスに配慮した API サービスに加え、チームのコスト・権限管理、インテリジェントルーティング、セキュリティ対策、BYOK による認証情報管理、請求書発行に対応するエンタープライズゲートウェイも提供しています。<br>
      🎁 <a href="https://www.shengsuanyun.com/?from=CH_XUQ4OTSK">こちらのリンク</a>から新規登録すると、10 元分のトライアルクレジットを受け取れます。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://www.ucloud.cn/site/active/astraflow?ytag=geo_waituo_Money"><img src="docs/sponsors/astraflow-logo.png" alt="AstraFlow" height="56"></a><br>
      <a href="https://www.ucloud.cn/site/active/astraflow?ytag=geo_waituo_Money"><strong>AstraFlow</strong></a>
    </td>
    <td align="left">
      本プロジェクトをスポンサードしてくださっている <a href="https://www.ucloud.cn/site/active/astraflow?ytag=geo_waituo_Money">AstraFlow</a> に感謝します！<br>
      🎬 <strong>主要な動画モデルを 1 つのプラットフォームで</strong>: MiniMax-H3、Seedance-2.5 などを利用できます。台本と動画の生成を 1 か所で完結でき、個別のアカウント登録や連携は不要です。<br>
      🚀 <strong>200 以上の AI モデル、新モデルはリリース当日から利用可能</strong>: DeepSeek V4.1、Kimi K3、Qwen 3.8 Max、GLM 5.3 などを 1 つのプラットフォームで利用できます。<br>
      💰 <strong>上場企業 UCloud による運営で、透明な課金とコスト管理</strong>: API キーごとにコストを追跡し、詳細な利用履歴を確認できます。<br>
      🎁 <strong>MoneyPrinterTurbo ユーザー限定特典</strong>: <a href="https://www.ucloud.cn/site/active/astraflow?ytag=geo_waituo_Money">紹介リンク</a>から登録すると新規ユーザー向けクレジットを受け取り、すぐに利用を開始できます！ <a href="https://f.howxm.com/xs/u/HVFW5X8EIYV1">50 元分のコンピュートクレジットを受け取る</a>。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://reccloud.com"><img src="docs/sponsors/reccloud-logo.svg" alt="RecCloud" height="36"></a><br>
      <a href="https://reccloud.com"><strong>RecCloud</strong></a>
    </td>
    <td align="left">
      本プロジェクトは<strong>デプロイ</strong>と<strong>利用</strong>にあたって、初心者の方にはややハードルがあります。本プロジェクトをベースにした <code>AI Video Generator</code> サービスを無料で提供してくださっている <a href="https://reccloud.com">RecCloud（AI を活用したマルチメディアサービスプラットフォーム）</a>に、特に感謝いたします。デプロイ不要でオンラインから利用でき、とても便利です。
    </td>
  </tr>
  <tr>
    <td align="center" width="120">
      <a href="https://picwish.com"><img src="docs/sponsors/picwish-logo.svg" alt="Picwish" height="36"></a><br>
      <a href="https://picwish.com"><strong>Picwish</strong></a>
    </td>
    <td align="left">
      本プロジェクトを支援・スポンサードし、継続的な更新とメンテナンスを可能にしてくださっている <a href="https://picwish.com">Picwish</a> に感謝します。Picwish は<strong>画像処理分野</strong>に注力し、複雑な操作を極限まで簡素化する豊富な<strong>画像処理ツール</strong>を提供しており、画像処理を本当に手軽なものにしています。
    </td>
  </tr>
</table>

## 作者によるもう 1 つのオープンソースプロジェクト: MangoDisk ⭐

<p align="center">
  <a href="https://mangodisk.app/ja">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://assets.mangodisk.app/images/screenshots/ja/dark-01-deep-cleanup.jpg?ver=1.1.0">
      <source media="(prefers-color-scheme: light)" srcset="https://assets.mangodisk.app/images/screenshots/ja/light-01-deep-cleanup.jpg?ver=1.1.0">
      <img src="https://assets.mangodisk.app/images/screenshots/ja/light-01-deep-cleanup.jpg?ver=1.1.0" width="900" alt="MangoDisk ディープクリーン画面">
    </picture>
  </a>
</p>

<p align="center">
  <strong>macOS・Windows 向けのオープンソースのディスククリーンアップ、容量分析、システム最適化ツール</strong><br>
  キャッシュ、大容量ファイル、重複ファイル、アプリの残骸を整理し、容量分析、アプリのアンインストール、スタートアップ管理、システム最適化・メンテナンスにも対応します。
</p>

<p align="center">
  <a href="https://mangodisk.app/ja">MangoDisk 公式サイト</a> · <a href="https://github.com/harry0703/MangoDisk">GitHub で見る</a>
</p>

---

## 機能 🎯

### 制作フロー

- [x] **AI エージェント、WebUI、API、CLI** の 4 つの利用方法を提供し、手軽な動画制作から自動化ワークフローへの組み込みまで対応
- [x] テーマから台本、ナレーション、素材、字幕、BGM、編集までを自動化し、各工程で独自コンテンツを使用することも可能
- [x] **複数動画の一括生成**、タスク履歴、生成設定と API キーのインポート・エクスポート・復元に対応

### 台本とモデルプロバイダー

- [x] AI による**多言語動画台本**の生成・リライトに加え、独自台本の利用にも対応
- [x] [Kimi / Moonshot AI](https://platform.kimi.ai?track_id=track-f6b0a640d35c41deb03b247242a1058c&aff=moneyprinterturbo)、[OpenAI](https://platform.openai.com/api-keys)、[Anthropic Claude](https://platform.claude.com/settings/keys)、[Google Gemini](https://aistudio.google.com/app/apikey)、[DeepSeek](https://platform.deepseek.com/api_keys)、[Alibaba Cloud Qwen](https://qwen.ai/apiplatform)、[Microsoft Azure OpenAI](https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/OpenAI)、[ByteDance VolcEngine Ark](https://console.volcengine.com/ark)、[xAI Grok](https://console.x.ai/)、[MiniMax](https://platform.minimax.io/)、[Xiaomi MiMo](https://platform.xiaomimimo.com/docs/zh-CN/quick-start/first-api-call) などの主要なモデルサービスに対応
- [x] [Shengsuan Cloud](https://www.shengsuanyun.com/?from=CH_XUQ4OTSK)、[APIMart](https://go.apimart.ai/gh-moneyprinterturbo)、[Cloudflare AI Gateway](https://dash.cloudflare.com/)、[Alibaba ModelScope](https://modelscope.cn/docs/model-service/API-Inference/intro)、[AIHubMix](https://aihubmix.com/)、[AIML API](https://aimlapi.com/app/keys)、[EvoLink](https://evolink.ai/dashboard/keys)、[OpenRouter](https://openrouter.ai/settings/keys)、[API Route](https://www.api-route.com/)、[Ollama](https://ollama.com/)、[Claude Code サブスクリプション](https://code.claude.com/docs)、[OneAPI](https://github.com/songquanpeng/one-api)、[LiteLLM](https://docs.litellm.ai/docs/providers)、[Groq](https://console.groq.com/keys)、[Pollinations AI](https://enter.pollinations.ai/) などの統合ゲートウェイ、集約サービス、ローカルランタイムに対応

### 動画・画像素材

- [x] 手持ちの**ローカル画像・動画**をアップロードできるほか、[Pexels（無料）](https://www.pexels.com/api/)、[Pixabay（無料）](https://pixabay.com/api/docs/)、[Coverr](https://coverr.co/developers?ctx=header_navigation) の高画質ストック素材を利用可能
- [x] [Metaso MiniMax H3](https://metaso.cn/minimax-h3/?s=MPT) によるテキスト動画生成に対応し、`768P`／`2K`、4～15 秒の素材を `9:16`、`16:9`、`1:1` の 3 種類のアスペクト比で生成可能
- [x] [Shengsuan Cloud AI Video](https://www.shengsuanyun.com/?from=CH_XUQ4OTSK) で複数の AI 動画素材を生成し、プロジェクトのナレーション、字幕、編集フローで 1 本の動画に合成可能
- [x] [Volcano Engine Ark Seedance](https://console.volcengine.com/ark/region:ark+cn-beijing/apikey) をネイティブに統合し、台本の各セグメントから一貫した動画素材を生成可能
- [x] [WaveSpeed AI](https://wavespeed.ai) によるテキスト動画生成で、台本のキーワードからオリジナル素材を作成可能
- [x] [OFox](https://ofox.ai) のマルチモデルテキスト動画生成に対応し、1 つの API キーで Seedance、Wan などのモデルを利用可能
- [x] [OpenAI 互換の画像生成](https://platform.openai.com/docs/guides/image-generation)サービスや独自の画像ゲートウェイを接続し、生成画像を動きのある動画クリップに変換可能
- [x] クリップの長さ、フレームへの合わせ方、素材の使用順を調整し、アスペクト比や構成に合わせた編集が可能

### ナレーション・字幕・BGM

- [x] 自動ナレーション、音声ファイルのアップロード、音声なしの 3 つの方式に対応し、音声サンプルとナレーション全体をプレビュー可能
- [x] **Edge TTS（無料・API キー不要）**、Azure Speech、SiliconFlow、Google Gemini、Xiaomi MiMo、MiniMax、ElevenLabs、Chatterbox、Kokoro、Fish Audio、ModelBest VoxCPM などの音声サービスに対応
- [x] 字幕を自動生成し、フォント、位置、色、サイズ、縁取り、背景スタイルを調整可能
- [x] ランダム、ローカル、AI 生成の BGM に対応し、音量を個別に調整可能

### 出力と公開

- [x] 縦型 `9:16（1080×1920）`、横型 `16:9（1920×1080）`、正方形 `1:1（1080×1080）` に対応
- [x] 動画生成後、**TikTok、Instagram、YouTube Shorts** へワンクリックで自動公開可能

## ギャラリー 🎬

以下の例はすべて MoneyPrinterTurbo で生成されたものです。

### 縦型 9:16

<table width="100%">
<tr>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=03-zh-portrait-city-morning.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/03-zh-portrait-city-morning.jpg" width="180" alt="When the City Wakes"></a><br><strong>When the City Wakes</strong><br>中国語 · 14 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=05-zh-portrait-clean-energy.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/05-zh-portrait-clean-energy.jpg" width="180" alt="The Future of Clean Energy"></a><br><strong>The Future of Clean Energy</strong><br>中国語 · 24 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=07-zh-portrait-space-exploration.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/07-zh-portrait-space-exploration.jpg" width="180" alt="Why We Still Explore Space"></a><br><strong>Why We Still Explore Space</strong><br>中国語 · 27 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=17-zh-portrait-seed-journey.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/17-zh-portrait-seed-journey.jpg" width="180" alt="A Seed's Journey"></a><br><strong>A Seed's Journey</strong><br>中国語 · 44 秒</td>
</tr>
<tr>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=09-en-portrait-future-robotics.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/09-en-portrait-future-robotics.jpg" width="180" alt="The Future of Everyday Robotics"></a><br><strong>The Future of Everyday Robotics</strong><br>英語 · 21 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=11-en-portrait-small-habits.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/11-en-portrait-small-habits.jpg" width="180" alt="Small Habits, Lasting Change"></a><br><strong>Small Habits, Lasting Change</strong><br>英語 · 19 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=13-en-portrait-creative-work.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/13-en-portrait-creative-work.jpg" width="180" alt="Making Space for Creative Work"></a><br><strong>Making Space for Creative Work</strong><br>英語 · 20 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=15-en-portrait-coffee-science.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/15-en-portrait-coffee-science.jpg" width="180" alt="The Science Inside Coffee"></a><br><strong>The Science Inside Coffee</strong><br>英語 · 23 秒</td>
</tr>
</table>

### 横型 16:9

<table width="100%">
<tr>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=02-zh-landscape-deep-ocean.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/02-zh-landscape-deep-ocean.jpg" width="280" alt="Light in the Deep Ocean"></a><br><strong>Light in the Deep Ocean</strong><br>中国語 · 23 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=04-zh-landscape-reading-power.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/04-zh-landscape-reading-power.jpg" width="280" alt="How Reading Shapes Us"></a><br><strong>How Reading Shapes Us</strong><br>中国語 · 23 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=06-zh-landscape-pour-over-coffee.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/06-zh-landscape-pour-over-coffee.jpg" width="280" alt="The Details of Pour-Over Coffee"></a><br><strong>The Details of Pour-Over Coffee</strong><br>中国語 · 23 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=08-zh-landscape-spring-journey.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/08-zh-landscape-spring-journey.jpg" width="280" alt="Spring Is Made for Travel"></a><br><strong>Spring Is Made for Travel</strong><br>中国語 · 14 秒</td>
</tr>
<tr>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=10-en-landscape-ocean-conservation.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/10-en-landscape-ocean-conservation.jpg" width="280" alt="Why Ocean Conservation Matters"></a><br><strong>Why Ocean Conservation Matters</strong><br>英語 · 25 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=14-en-landscape-sustainable-cities.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/14-en-landscape-sustainable-cities.jpg" width="280" alt="Designing More Sustainable Cities"></a><br><strong>Designing More Sustainable Cities</strong><br>英語 · 27 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=16-en-landscape-mountain-perspective.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/16-en-landscape-mountain-perspective.jpg" width="280" alt="What Mountains Teach Us"></a><br><strong>What Mountains Teach Us</strong><br>英語 · 18 秒</td>
<td align="center" width="25%"><a href="https://harry0703.github.io/mpt-assets/?video=18-en-landscape-history-of-flight.mp4"><img src="https://github.com/harry0703/mpt-assets/releases/download/assets/18-en-landscape-history-of-flight.jpg" width="280" alt="A Brief History of Human Flight"></a><br><strong>A Brief History of Human Flight</strong><br>英語 · 59 秒</td>
</tr>
</table>

## 動作環境 📦

- 推奨プラットフォーム: Windows 10 以降、macOS 11 以降、または主要な Linux ディストリビューション
- ローカル環境へのデプロイには Python 3.11 以降が必要です。Python 3.11 を推奨します
- GPU は必須ではありませんが、ローカルでの文字起こしや動画処理を高速化したい場合、一括生成をより快適に行いたい場合には推奨されます

| 項目   | 最低   | 推奨           | 最適           |
| ------ | ------ | -------------- | -------------- |
| CPU    | 4 コア | 6〜8 コア      | 8 コア以上     |
| メモリ | 4 GB   | 8 GB           | 16 GB 以上     |
| GPU    | 不要   | VRAM 4 GB 以上 | VRAM 8 GB 以上 |

- 主にクラウド LLM、クラウド TTS、オンライン素材ソースを利用する場合は、GPU よりも CPU とメモリのほうが重要です
- `faster-whisper`、一括生成、負荷の高いローカル処理を利用する場合は、GPU によってスループットが目に見えて向上します

## 必要な API と推定コスト 💰

### 動画が作られる流れ

各生成タスクは同じパイプラインで実行されます（`app/services/task.py` を参照）。各工程はそれぞれ 1 つの設定可能なサービスに対応しており、そのサービスによって費用が発生するかどうかが決まります:

| # | 工程 | 使用するサービス | 設定キー |
| - | ---- | ---------------- | -------- |
| 1 | 台本 | LLM（`generate_script`）。独自の台本を指定した場合はスキップ | `llm_provider` + `<provider>_api_key` |
| 2 | 検索キーワード | LLM（`generate_terms`）。キーワードを指定した場合や `local` 素材を使う場合はスキップ | 同上 |
| 3 | ナレーション | TTS プロバイダー | WebUI の `tts_server`、`[azure]`、`[elevenlabs]`、... |
| 4 | 字幕 | Edge TTS のタイムスタンプまたはローカル Whisper | `subtitle_provider` |
| 5 | 映像素材 | ストック素材の検索または AI 生成 | `video_source` + 対応するキー |
| 6 | BGM | ローカルファイルまたは AI 音楽 | `bgm_type`、`sonilo_api_key`、`[elevenlabs]` |
| 7 | レンダリング | ローカルの FFmpeg / MoviePy | `ffmpeg_path`、`video_codec` |
| 8 | 公開（任意） | Upload-Post | `upload_post_*` |

### 必要な API

既定の `pexels` 素材ソースを使う標準的な実行では、**2 つの API キー**が必要です:

| API | 必須？ | 用途 | 無料の選択肢 | 取得先 |
| --- | ------ | ---- | ------------ | ------ |
| **LLM プロバイダー**（いずれか 1 つ） | ✅ 必須* | 台本と素材検索キーワードの作成 | Ollama（ローカル）、OpenRouter の無料モデル、Gemini の無料枠、Pollinations、または既存のサブスクリプションでの Claude Code | [台本とモデルプロバイダー](#台本とモデルプロバイダー)を参照 |
| **素材ソース**（いずれか 1 つ） | ✅ 必須** | 映像クリップの検索または生成 | Pexels と Pixabay は無料 | [Pexels](https://www.pexels.com/api/) · [Pixabay](https://pixabay.com/api/docs/) |
| TTS 音声 | ⚪ 任意 | ナレーション | **Edge TTS**（WebUI の `Azure TTS V1`）は無料で、キー不要 | Azure Speech、ElevenLabs、MiniMax、Fish Audio、SiliconFlow、... |
| 字幕 | ⚪ 任意 | 字幕のタイミング | `edge` モード（既定）と `whisper`（ローカル実行）はどちらも無料 | — |
| AI BGM | ⚪ 任意 | 動画に合わせて生成される音楽 | `resource/songs` に同梱の楽曲は無料 | [Sonilo](https://platform.sonilo.com/dashboard) · [ElevenLabs Music](https://elevenlabs.io/app/settings/api-keys) |
| TwelveLabs | ⚪ 任意 | 意味に基づく素材のランク付けと動画 QA | — | [TwelveLabs](https://playground.twelvelabs.io/) |
| Upload-Post | ⚪ 任意 | TikTok、Instagram、YouTube への自動公開 | — | [Upload-Post](https://upload-post.com/) |

\* LLM を省略できるのは、独自の台本**と**独自の検索キーワードの**両方**を指定した場合（API/CLI）、または独自の台本を指定して `video_source = "local"` を使う場合のみです。<br>
\** 独自の画像・動画で `video_source = "local"` を使う場合、素材ソースのキーは不要です。

> **費用ゼロの最小構成:** 無料の Pexels キー、無料またはローカルの LLM（Ollama など）、Edge TTS、`edge` 字幕、同梱の BGM。

### 動画 1 本あたりの推定コスト

以下の見積もりは、英語約 150 語（≈ 900 文字、中国語なら約 250 文字）の **60 秒動画**、`video_clip_duration = 5`（つまり約 **12 クリップ**）、`video_count = 1` を前提としています。レンダリングはローカルで行われるため、自分のハードウェアと電気代以外の費用はかかりません。

**工程ごとのコスト**

| 工程 | 無料の選択肢 | 60 秒動画 1 本あたりの一般的な有料コスト |
| ---- | ------------ | ---------------------------------------- |
| LLM（2 回の呼び出し、合計約 1.5k–3k トークン） | Ollama / 無料枠のモデル: $0 | DeepSeek、Kimi、Qwen、GPT-mini クラス、Gemini Flash クラスのモデルなら通常 **< $0.01**。最上位モデルでは数セント |
| ナレーション（≈ 900 文字） | Edge TTS: $0 | Azure Speech ニューラル: 約 $0.015 · ElevenLabs / MiniMax HD: プランとモデルにより約 $0.05–0.30 |
| 字幕 | `edge` / ローカル Whisper: $0 | — |
| ストック素材（Pexels / Pixabay） | $0 | Coverr: プランによる |
| AI 画像（`openai_image`、約 12 枚） | ローカルの ComfyUI/SD ゲートウェイ: $0 | 約 $0.07（APIMart などの中継サービスで $0.006/枚の場合）から、公式のプレミアムエンドポイントでは $0.50 以上 |
| AI 動画クリップ（≈ 60 秒分の素材） | — | **圧倒的に最大のコスト。** 次の表を参照 |
| AI BGM（Sonilo / ElevenLabs Music） | 同梱の楽曲: $0 | プロバイダーにより生成ごとに課金 |

**AI 動画素材（生成クリップ 60 秒分）**

AI 動画ソースは、ナレーションの長さを満たすまでクリップを 1 本ずつ生成します。有料クリップの本数はおよそ `ceil(ナレーションの秒数 × video_count / video_clip_duration)` で、WebUI はこの見積もりを表示し、送信前に課金の確認を求めます。

| ソース / モデル | 参考価格 | ≈ 60 秒あたりのコスト |
| --------------- | -------- | --------------------- |
| Metaso MiniMax H3 – 768P | CNY 0.09 / 秒 | ≈ CNY 5.4（≈ $0.75） |
| Metaso MiniMax H3 – 2K | CNY 0.15 / 秒 | ≈ CNY 9（≈ $1.25） |
| Shengsuan Cloud – Jimeng 3.0 720p | CNY 0.23 / 秒 | ≈ CNY 13.8（≈ $1.9） |
| Shengsuan Cloud – Wan 2.2 fast | CNY 0.35（480P）– 0.77（720P）/ クリップ | 12 クリップで ≈ CNY 4.2–9.2 |
| Shengsuan Cloud – Veo 3.1 Fast | CNY 0.70 / 秒 | ≈ CNY 42（≈ $5.8） |
| Shengsuan Cloud – Vidu Q3 Pro | CNY 0.44–1.00 / 秒 | ≈ CNY 26–60 |
| Shengsuan Cloud – Veo 3 / Veo 3.1 | CNY 1.40 / 秒 | ≈ CNY 84（≈ $11.7） |
| Shengsuan Cloud – Kling v2 / v2.1 Master | 5 秒クリップあたり CNY 10 | ≈ CNY 120（≈ $16.7） |
| Volcano Engine Seedance、WaveSpeed、OFox | モデル、解像度、長さに応じてクリップごとに課金 | 各プロバイダーの料金ページを確認 |

**構成別のまとめ**

| 構成 | サービス | ≈ 60 秒動画 1 本あたりのコスト |
| ---- | -------- | ------------------------------ |
| 🆓 無料 | Pexels/Pixabay + Ollama または無料枠の LLM + Edge TTS + 同梱の BGM | **$0** |
| 💡 低予算（最初はこちらを推奨） | Pexels + 低価格のクラウド LLM（DeepSeek、Kimi、...）+ Edge TTS | **< $0.01** |
| 🎙️ 高品質ナレーション | 低予算 + Azure Speech / ElevenLabs / MiniMax TTS | **≈ $0.02–0.35** |
| 🖼️ AI 画像 | 高品質ナレーション + `openai_image` | **≈ $0.10–0.90** |
| 🎬 AI 動画 | 上記いずれかの構成 + AI 動画ソース | モデルにより **≈ $0.75–17+** |

> ⚠️ 価格は目安としての参考値です（米ドル換算は約 CNY 7.2 = $1）。プロバイダーの料金、無料枠、キャンペーンは頻繁に変更されます。必ず各プロバイダーの最新の料金ページを確認してください。最終的な請求額は実際の利用量に基づきます。一括出力（`video_count > 1`）、長い台本、短い `video_clip_duration`、音声プレビューの繰り返しはいずれもコストを比例して増加させます。ナレーション全体のプレビューでは、選択した TTS サービスが再度呼び出されます。

## クイックスタート 🚀

### おすすめの手順

- 手動でのインストールや設定をしたくない場合: AI エージェントで動画を生成する
- Windows ユーザー: まずはワンクリックパッケージを使うのが最短で試せます
- macOS / Linux ユーザー: ローカル環境の主要な手順として `uv` を使用します
- より独立した実行環境が欲しい場合: Docker でデプロイします

### AI エージェントで動画を生成する

お使いの AI エージェントが Skill ドキュメントを読み、ローカルのターミナルを操作できるなら、以下のプロンプトを送ってください。エージェントが MoneyPrinterTurbo のインストールと設定を行い、動画を生成して、動画ファイルのパスを返します。未設定の必須 API キーだけを尋ねてきます。このワークフローは現在 macOS と Windows に対応しています。

```text
Use this Skill: https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/main/docs/skill/SKILL.md
Create a video with the topic "How AI is changing everyday life."
```

### Google Colab で実行する

ローカル環境を用意せずに MoneyPrinterTurbo を試したいですか？ Google Colab で直接実行できます！

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/harry0703/MoneyPrinterTurbo/blob/main/docs/MoneyPrinterTurbo.ipynb)

### Windows

GitHub Releases から最新の Windows 用ワンクリックパッケージをダウンロードし、そのまま展開してください。

- [最新の Windows 用ワンクリックパッケージをダウンロード](https://github.com/harry0703/MoneyPrinterTurbo/releases/latest)

> 同ページの **Assets** から `.7z` ファイルをダウンロードしてください。GitHub が
> 自動生成する `Source code (zip)` / `Source code (tar.gz)` はソースコードのみで、
> 展開しても `webui.bat` だけが現れ、`start.bat` と `update.bat` は含まれません。

ダウンロード後は、まず `update.bat` を**ダブルクリック**して**最新のコード**に更新し、その後 `start.bat` をダブルクリックして起動することを推奨します

起動するとブラウザーが自動的に開きます（真っ白な画面になる場合は **Chrome** または **Edge** の利用を推奨します）

### macOS / Linux

以下のローカルセットアップまたは Docker の手順を参照してください。

## インストールとデプロイ 📥

### 前提条件

- ローカル環境へのデプロイには Python 3.11 以降が必要です
- Windows では、プロジェクトのパスに非 ASCII 文字、特殊文字、スペースを含めないでください

#### ① プロジェクトをクローンする

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
```

#### ② 初期設定を行う

初回起動時に `config.example.toml` から `config.toml` が自動作成されるため、設定ファイルを手動で作成する必要はありません。クラウド LLM、オンライン素材、AI 動画などのサービスを利用する前に、WebUI の基本設定で対応する API キーを入力してください。

### Docker でデプロイ 🐳

#### ① Docker コンテナを起動する

Docker が未インストールの場合は、先に [Docker Desktop をダウンロードしてインストール](https://www.docker.com/products/docker-desktop/)してください。
Windows をお使いの場合は、Microsoft のドキュメントを参照してください:

1. [WSL をインストールする](https://learn.microsoft.com/en-us/windows/wsl/install)
2. [WSL で Docker コンテナを使用する](https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-containers)

```shell
cd MoneyPrinterTurbo
docker compose -f docker-compose.release.yml up
```

> 既定では `docker-compose.release.yml` を推奨します。GitHub Container Registry からビルド済みイメージ `ghcr.io/harry0703/moneyprinterturbo:latest` を取得します。
> ローカルでイメージをビルドする必要がある場合は、これまでどおり `docker compose up` を実行できます。
> 初回起動の前に、`config.example.toml` を `config.toml` にコピーしておくと、コンテナにマウントされます。

#### ② WebUI にアクセスする

ブラウザーで http://127.0.0.1:8501 を開きます

#### ③ API ドキュメントにアクセスする

ブラウザーで http://127.0.0.1:8080/docs または http://127.0.0.1:8080/redoc を開きます

> API はデフォルトで同一オリジンのブラウザーアクセスのみを許可します。別のブラウザーフロントエンドから API を直接呼び出す場合に限り、環境変数 `CORS_ALLOWED_ORIGINS` へ信頼するオリジンを設定してください（例: `http://localhost:3000,https://frontend.example.com`）。curl、Postman、n8n、その他のサーバー側クライアントは CORS の影響を受けません。

### 手動でデプロイ 📦

#### ① Python の仮想環境を作成する

[uv](https://docs.astral.sh/uv/) を使って Python 環境と依存関係を管理します。本プロジェクトは Python 3.11 以降に対応しており、以下の例では Python 3.11 を使用します。

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
uv python install 3.11
uv sync --frozen
```

`uv` をまだ使っていない場合は、これまでどおり `venv + pip` も利用できます。

```shell
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

補足:

- 現在は `pyproject.toml` が主要な依存関係の定義ファイルです。
- `uv.lock` が解決済みの環境を固定するため、既定では `uv sync --frozen` を推奨します。
- `requirements.txt` は従来の `pip` によるインストールのためだけに残されています。

#### ② WebUI を起動する 🌐

以下のコマンドは MoneyPrinterTurbo プロジェクトの`ルートディレクトリ`で実行する必要がある点に注意してください

###### Windows

```powershell
.\webui.bat
```

`webui.bat` は CMD から実行することもできます。
`webui.bat` は、プロジェクトの `.venv` またはポータブルパッケージに同梱された Python を優先して使用します。プロジェクトの Python が見つからず、`uv` がインストールされている場合は、自動的に `uv run streamlit` にフォールバックします。
同じ LAN 内の別の端末から WebUI にアクセスできるようにするには、`webui.bat` を実行する前に `set MPT_WEBUI_HOST=0.0.0.0` を実行してください。

###### macOS または Linux

```shell
sh webui.sh
```

このスクリプトは、プロジェクトの仮想環境または `uv` を自動的に使用し、利用可能なローカルポートを選択します。同じ LAN 内の別の端末からアクセスできるようにするには、次のように実行します:

```shell
MPT_WEBUI_HOST=0.0.0.0 sh webui.sh
```

起動するとブラウザーが自動的に開きます

#### ③ API サービスを起動する 🚀

```shell
uv run python main.py
```

仮想環境を手動で有効化済みの場合は、これまでどおり次のように実行できます:

```shell
python main.py
```

> API はデフォルトで `127.0.0.1` のみで待ち受けます。ほかの端末から呼び出す場合は、`config.toml` で `listen_host = "0.0.0.0"` **と**十分に強力な `api_key` の両方を設定し、`x-api-key` ヘッダーでキーを送信してください。`api_key` が空の間は `localhost` / `127.0.0.1` 宛てのリクエストのみを受け付けるため、LAN 内の端末による有料 API クレジットの不正利用や、悪意のある Web サイトによる DNS リバインディング攻撃を防げます。キーなしで追加のホスト名を信頼するには、`config.toml` の `allowed_hosts` または環境変数 `MPT_ALLOWED_HOSTS` を設定してください。

#### ④ CLI のみのモード（ブラウザー不要） ⌨️

ブラウザーやポートフォワーディングが利用できない場合は、コマンドラインから直接動画を生成できます。最もシンプルな生成コマンドは次のとおりです:

```shell
uv run python cli.py --video-subject "How AI is changing everyday life"
```

字幕スタイルとナレーションのオプションは、**明示的な CLI オプション > `config.toml` に保存された `[ui]` の値 > 組み込みの既定値**の順に解決されます。BGM、動画の本数、段落数などその他の生成設定は WebUI から引き継がれません。WebUI でアップロード音声を使う設定にしている場合、アップロードしたパスは保存されないため、`--custom-audio-file` を明示的に指定してください。

コマンドの完全なリファレンス、パラメーターの説明、使い方については、次を実行してください:

```shell
uv run python cli.py --help
```

複数のタスクを順番に実行するには、`--batch-file` で UTF-8 の JSON 配列または
JSONL マニフェストを指定します。CLI オプションが共通の既定値となり、各オブジェクトで
`VideoParams` フィールドを上書きできます。

```json
[
  { "video_subject": "How solar panels work" },
  { "video_subject": "How wind turbines work", "video_aspect": "16:9" }
]
```

```shell
uv run python cli.py --batch-file ./tasks.json --stop-at video
```

マニフェストのパスは現在の作業ディレクトリを基準に解決されます。マニフェスト内の相対的な
`custom_audio_file` とローカルの `video_materials[].url` はマニフェストのディレクトリを
基準に解決されますが、CLI の既定値として指定したファイルパスは通常どおり現在の作業
ディレクトリを基準とします。マニフェストは最大 100 タスク、1 MiB までです。最初のタスクを
開始する前に全項目とローカルファイルを検証し、個別タスクが実行時に失敗しても後続タスクを
続行して、最後に JSON サマリーを 1 つ出力します。サマリーには `total`、`succeeded`、
`failed`、`tasks` が含まれ、各タスクの項目には `index`、`task_id`、`status`、`result`、
`failed_stage`、`error` が含まれます。

## ナレーション・字幕・BGM 🎙️

### 音声合成

WebUI の **Azure TTS V1** は **Edge TTS** を利用しており、無料かつ API キー不要です。MoneyPrinterTurbo は **Azure TTS V2**、**SiliconFlow TTS**、**Google Gemini TTS**、**Xiaomi MiMo TTS**、**MiniMax TTS**、**ElevenLabs TTS**、セルフホストの **Chatterbox TTS**、セルフホストの **Kokoro TTS**、**Fish Audio TTS**、[ModelBest VoxCPM TTS](https://platform.modelbest.cn/console/docs/api/audio)、および音声なしモードにも対応しています。

WebUI でプロバイダーと音声を選択し、必要な認証情報については画面の案内に従ってください。Edge TTS に API キーは不要です。[Azure TTS V2](https://portal.azure.com/) やその他のクラウドプロバイダーでは、それぞれのプラットフォームで発行した認証情報が必要です。利用可能な Edge TTS の音声は[音声リスト](./docs/voice-list.txt)で確認できます。

ModelBest VoxCPM には、API キーと `speech_synthesis` 機能を持つモデル ID が必要です。SSE レスポンスで WAV 音声がストリーミングされ、MoneyPrinterTurbo が動画パイプラインで使用する MP3 に自動変換します。この連携は既定の音声による標準的なテキスト読み上げに対応しており、参照音声による音声クローンにはまだ対応していません。

### 字幕生成

字幕の生成モードは 2 種類あります:

- **edge**: TTS のタイムスタンプを利用します。GPU なしで高速に動作し、既定のモードです。
- **whisper**: より正確な字幕のタイムラインが必要な場合に、ローカルの `faster-whisper` による文字起こしを利用します。モデルは初回利用時にダウンロードされます。

モードを切り替えるには `config.toml` の `subtitle_provider` を設定します。Whisper は既定で約 3 GB の `large-v3` モデルを使用します。より小さく高速な約 1.6 GB の `large-v3-turbo` モデルを使う場合:

```toml
[app]
subtitle_provider = "whisper"

[whisper]
model_size = "large-v3-turbo"
```

> 初回利用時、Whisper は Hugging Face からモデルを自動的にダウンロードします。自動ダウンロードに失敗する場合は、[Hugging Face](https://huggingface.co/Systran/faster-whisper-large-v3) から `whisper-large-v3` を手動でダウンロードしてください。

モデルを展開したら、ディレクトリ全体を `.\MoneyPrinterTurbo\models` に配置します。最終的なパスは `.\MoneyPrinterTurbo\models\whisper-large-v3` になります:

```
MoneyPrinterTurbo
  ├─models
  │   └─whisper-large-v3
  │          config.json
  │          model.bin
  │          preprocessor_config.json
  │          tokenizer.json
  │          vocabulary.json
```

### BGM

動画の BGM は、プロジェクトの `resource/songs` ディレクトリにあります。

> 現在のプロジェクトには YouTube 動画由来の既定の音楽がいくつか含まれています。著作権上の問題がある場合は削除してください。

### 字幕フォント

動画の字幕描画に使うフォントは、プロジェクトの `resource/fonts` ディレクトリにあります。独自のフォントを追加することもできます。

## よくある質問 🤔

<details>
<summary>RuntimeError: No ffmpeg exe could be found</summary>

通常、ffmpeg は自動的にダウンロードされ、検出されます。
しかし、環境の問題で自動ダウンロードができない場合は、次のようなエラーが発生することがあります:

```
RuntimeError: No ffmpeg exe could be found.
Install ffmpeg on your system, or set the IMAGEIO_FFMPEG_EXE environment variable.
```

この場合は、[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) から FFmpeg をダウンロードして展開し、`ffmpeg_path` に実際のインストールパスを設定してください。

```toml
[app]
# 実際のパスに合わせて設定してください。Windows のパス区切り文字は \\ である点に注意してください
ffmpeg_path = "C:\\Users\\harry\\Downloads\\ffmpeg.exe"
```

</details>

<details>
<summary>OSError: [Errno 24] Too many open files</summary>

これはシステムのオープンファイル数の上限が原因です。システムのファイルオープン数の上限を変更することで解決できます。

現在の上限を確認します:

```shell
ulimit -n
```

低すぎる場合は、例えば次のように引き上げます:

```shell
ulimit -n 10240
```

</details>

<details>
<summary>Whisper モデルのダウンロードに失敗する</summary>

```
LocalEntryNotFoundError: Cannot find an appropriate cached snapshot folder for the specified revision on the local disk and
outgoing traffic has been disabled.
To enable repo look-ups and downloads online, pass 'local_files_only=False' as input.
```

または

```
An error occurred while synchronizing the model Systran/faster-whisper-large-v3 from the Hugging Face Hub:
An error happened while trying to locate the files on the Hub and we cannot find the appropriate snapshot folder for the
specified revision on the local disk. Please check your internet connection and try again.
Trying to load the model directly from the local cache, if it exists.
```

解決方法: [Hugging Face からモデルを手動でダウンロードする方法を参照してください](#字幕生成)

</details>

## フィードバックと提案 📢

- [issue](https://github.com/harry0703/MoneyPrinterTurbo/issues) または [pull request](https://github.com/harry0703/MoneyPrinterTurbo/pulls) を送っていただけます。

## ライセンス 📝

[`LICENSE`](LICENSE) ファイルをクリックしてご覧ください
