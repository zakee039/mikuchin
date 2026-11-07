<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin · Miku亲

**ローカル・マルチモーダル AI コンパニオン＆画像制作ワークスペース**

**メインアプリ v0.2.5** · [ダウンロード / GitHub Releases](https://github.com/zakee039/mikuchin/releases/tag/v0.2.5)

**個別バージョン：**メインアプリ `0.2.5` · Windows ランチャー `0.2.4` · Android クライアント `0.2.4`（versionCode 204）。今回の更新対象はメインアプリのみで、ランチャーと APK のバイナリは変更ありません。

[公式サイト](https://mikuchin.zakee.fun) · [個人サイト](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

[**简体中文**](README.md) · [**日本語**](README.ja-JP.md) · [**English**](README.en-US.md)

</div>

---

## Mikuchin（Miku亲）とは

**Mikuchin（Miku亲）** は、個人で運用するローカル AI コンパニオン＆クリエイティブワークスペースです。単なるチャット UI ではなく、会話、キャラクター設定とワールドブック、参照画像を使った画像生成、ハードウェア／推論モニタリングをひとつにまとめています。

ローカル推論には **PolyStrata** を使用し、ブラウザ用ワークスペース、Windows トレイマネージャー、Android クライアントを提供します。Android アプリからは直接接続するか、内蔵ユーザー空間 Tailscale で自身の Tailnet に参加して PC の Mikuchin に接続できます。**スマートフォン上で大規模モデルを推論するアプリではありません**。

モデル、履歴、キャラクター、画像は自分の端末で管理できます。ただし、Tailscale、Cloudflare Tunnel、外部 MCP などの利用時には、それぞれの通信とアクセス権を確認してください。

## ✨ 主な機能

1. **インテリジェントチャット＆SessionV1 エンジン**
   - リアルタイムのトークンストリーミング出力、思考プロセス（Thinking）の折りたたみ表示、マルチモーダル画像認識（ドラッグ＆ドロップ・貼り付け・アップロード）、MCP 外部ツール連携およびチャット内画像生成ツールを搭載。
   - **モデル別 SessionV1 KV キャッシュ**：SQLite データベースとモデルごとの KV スナップショットにより、長文コンテキストの高速復元、KV のロック／解放、ピン留め、Markdown エクスポートに対応。
   - **3つの会話モード**：「通常アシスタント（グローバルユーザー設定と履歴を継承）」「ステートレスモード（履歴やキャラクターを含めず現在の1ターンのみを送信しつつ、画面上の履歴保存と画像生成は維持）」「カスタムキャラクター」。

2. **キャラクタースタジオ＆ワールドブック（Worldbook）**
   - モデルから独立した `character_cards.sqlite3` により、SillyTavern `chara_card_v2` 形式のインポート／エクスポートに完全対応。
   - **3段階のユーザーアイデンティティ設定**：キャラクターごとに「ユーザー情報なし」「グローバル設定を継承」「キャラクター固有のユーザー設定」を選択可能。
   - **セッション単位のロールロック**：最初のメッセージ送信後に会話のキャラクターを固定し、履歴一覧にはキャラクター名のカラー透かしラベルを表示。
   - **キャラクター立ち絵の弱参照機能**：キャラクターに参照画像（`reference.png`）を登録すると、公式 Qwen 画像モデルでのチャット内画像生成時に画風・外見の弱い参照として自動活用（服装やシーンは会話の指示を最優先）。すべての編集は自動保存（Autosave）されます。

3. **画像生成スタジオ（Image Studio）**
   - **複数モデルプロファイル対応**：**Qwen-Image 2.1 Turbo Official**（8ステップ高速生成、`--ref-image` ネイティブ参照編集、Qwen LoRA 対応）、**Qwen-Image 2.1 Turbo Uncensored**、**Animagine XL 4.0**、**SDXL Base 1.0**（`img2img` 対応）を自由に切り替え可能。
   - **3層プロンプト＆AI ワンクリック解析**：モデル間で共有される「自然言語入力」と、モデルごとに保存される「Positive / Negative Prompt」下書きを備え、現在の LLM を使って自然言語から英語プロンプトへの自動変換が可能。
   - 縦横サイズの個別指定（`384` / `512` / `768` / `1024`）、ステップ数、シード値、アップスケール、LoRA 選択、ワンクリッククリアに対応。

4. **リアルタイムハードウェア＆推論モニター（Monitor）**
   - GPU VRAM 使用量、システム RAM、Prefill / Decode 速度（tok/s）、入出力トークン統計、KV キャッシュヒット率、直近リクエストのレイテンシをリアルタイム表示。

5. **Windows ネイティブマネージャー（Tauri 2）**
   - システムトレイ常駐、モデル設定のワンクリック切り替え、プロセスのウォッチドッグ監視、アイドル時の自動アンロード（0〜1440分）、LAN アクセス制御、Windows DPAPI による認証情報保護、および **Cloudflare Tunnel** の状態監視・遅延テスト・再起動をサポート。

6. **Android クライアント（ユーザー空間 Tailscale `tsnet` 内蔵）**
   - **ライトテーマ＆伸縮レイアウト**：ログイン前はシンプルな接続画面のみを表示し、接続後は**最新のチャット画面へ直行**。左上の履歴ドロワーボタンと、枠線のない下部5ボタンナビゲーション（画像・キャラクター・設定・モニター・概要）を搭載。
   - **ユーザー空間 Tailscale 統合**：公式 `tailscale.com/tsnet`（Go + `gomobile` AAR）をアプリ内に内蔵。**Android の `VpnService` を一切使用しない**ため、Android の VPN スロットを占有しません。実際の接続経路は端末の設定に依存し、Root 化や公式 Tailscale アプリのインストールも不要です。
   - **2段階 Web OAuth 認証＆Keystore 暗号化**：Tailscale モードでは先にブラウザで OAuth デバイス認証を完了してからエンドポイントと API キー入力欄を展開。API キーは Android Keystore（`AES/GCM/NoPadding`）で暗号化保存されます。

7. **日・中・英 3言語リアルタイム切り替え（i18n）**
   - Web UI、モバイル画面、Windows マネージャー、トレイメニューの表示言語を `简体中文` / `日本語` / `English` 間で即座に切り替え可能（会話本文やキャラクター設定は翻訳されません）。

## 📂 プロジェクト構成

```text
mikuchin/
├── assets/                 # アイコン・ブランド画像
├── backend/
│   ├── polystrata/         # 推論エンジン（Git サブモジュール）
│   └── services/           # サービス・オーケストレーション
├── character/              # キャラクターカード・参照画像
├── chat/                   # 会話履歴・生成画像・KV スナップショット
├── config/                 # ローカル設定（Git 管理対象外）
├── docs/                   # 公式サイト (GitHub Pages: mikuchin.zakee.fun)
├── frontend/
│   ├── android/            # Kotlin / WebView / tsnet クライアント
│   ├── launcher/           # Windows Tauri 2 マネージャー
│   ├── locales/            # 日本語・中国語・英語辞書
│   └── web/                # 共通 Web UI
└── scripts/                # ビルド・メンテナンス用スクリプト
```

## 📦 ダウンロードとビルド

[GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest) から Windows インストーラーと Android APK を取得できます。**モデルの重みは配布物に含まれません**。ローカルのモデルファイルを準備し、ランチャーから設定ファイルを登録してください。

```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# すでに clone 済みの場合: git submodule update --init --recursive
```

```powershell
python scripts/build-locales.py
powershell -ExecutionPolicy Bypass -File scripts/build-launcher.ps1
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
```

Android では「直接接続」または「Tailscale」を選択します。Tailscale モードではブラウザ認証のほか、Tailnet ACL/Grants と接続先のファイアウォールで API ポートへのアクセスを許可する必要があります。Android アプリ自体でモデルを推論するのではなく、Mikuchin サーバーへ接続します。

## 🔒 セキュリティと注意事項

API Key、Tailnet の認証状態、会話データ、モデル重みは GitHub に含めないでください。ネットワーク環境により VPN の共存動作が変わるため、端末上で検証してください。v0.2.4 APK はリリース用署名で配布しています。以前の Android Debug 証明書で署名された APK からの上書き更新はできない場合があるため、設定を控えてから再インストールしてください。PolyStrata のライセンスと帰属はサブモジュールの原文をご確認ください。
