<div align="center">

<img src="assets/icon.png" alt="Mikuchin" width="96" height="96" />

# Mikuchin · Miku亲

**ローカル・マルチモーダル AI コンパニオン＆画像制作ワークスペース**

**メインアプリ v0.5.1** · [ダウンロード / GitHub Releases](https://github.com/zakee039/mikuchin/releases/tag/v0.5.1)

**個別バージョン：**メインアプリ `0.5.1` · Windows ランチャー `0.5.1` · Android クライアント `0.5.1`（versionCode 501）。今回は全 3 コンポーネントを再ビルドしました。Release のマニフェストを参照してください。 以降のバージョンは個別に管理し、versions.json に記録します。

[公式サイト](https://mikuchin.zakee.fun) · [個人サイト](https://zakee.fun) · [Buy Me a Coffee](https://ifdian.net/a/zakee/plan)

[**简体中文**](README.md) · [**日本語**](README.ja-JP.md) · [**English**](README.en-US.md)

</div>

---

## Mikuchin（Miku亲）とは

**Mikuchin（Miku亲）** は、個人で運用するローカル AI コンパニオン＆クリエイティブワークスペースです。単なるチャット UI ではなく、会話、キャラクター設定とワールドブック、参照画像を使った画像生成、ハードウェア／推論モニタリングをひとつにまとめています。

ローカル推論には **PolyStrata** を使用し、ブラウザ用ワークスペース、Windows トレイマネージャー、Android クライアントを提供します。Android アプリからは直接接続するか、内蔵ユーザー空間 Tailscale で自身の Tailnet に参加して PC の Mikuchin に接続できます。**スマートフォン上で大規模モデルを推論するアプリではありません**。

モデル、履歴、キャラクター、画像は自分の端末で管理できます。ただし、Tailscale、Cloudflare Tunnel、外部 MCP などの利用時には、それぞれの通信とアクセス権を確認してください。

## ✨ 主な機能

### 1. インテリジェントチャット＆SessionV1 エンジン
- リアルタイムのトークンストリーミング出力、思考プロセス（Thinking）の折りたたみ表示、マルチモーダル画像認識（ドラッグ＆ドロップ・貼り付け・アップロード）、MCP 外部ツール連携およびチャット内画像生成ツールを搭載。
- **モデル別 SessionV1 KV キャッシュ**：SQLite データベースとモデルごとの KV スナップショットにより、長文コンテキストの高速復元、KV のロック／解放、ピン留め、Markdown エクスポートに対応。
- **3つの会話モード**：「通常アシスタント（グローバルユーザー設定と履歴を継承）」「ステートレスモード（履歴やキャラクターを含めず現在の1ターンのみを送信しつつ、画面上の履歴保存と画像生成は維持）」「カスタムキャラクター」。

### 2. キャラクタースタジオ＆ワールドブック（Worldbook）
- モデルから独立した `character_cards.sqlite3` により、SillyTavern `chara_card_v2` 形式のインポート／エクスポートに完全対応。
- **3段階のユーザーアイデンティティ設定**：キャラクターごとに「ユーザー情報なし」「グローバル設定を継承」「キャラクター固有のユーザー設定」を選択可能。
- **セッション単位のロールロック**：最初のメッセージ送信後に会話のキャラクターを固定し、履歴一覧にはキャラクター名のカラー透かしラベルを表示。
- **キャラクター立ち絵の弱参照機能**：キャラクターに参照画像（`reference.png`）を登録すると、公式 Qwen 画像モデルでのチャット内画像生成時に画風・外見の弱い参照として自動活用（服装やシーンは会話の指示を最優先）。すべての編集は自動保存（Autosave）されます。

### 3. 画像生成スタジオ（Image Studio）
- **複数モデルプロファイル対応**：**Qwen-Image 2.1 Turbo Official**（8ステップ高速生成、`--ref-image` ネイティブ参照編集、Qwen LoRA 対応）、**Qwen-Image 2.1 Turbo Uncensored**、**Animagine XL 4.0**、**SDXL Base 1.0**（`img2img` 対応）を自由に切り替え可能。
- **3層プロンプト＆AI ワンクリック解析**：モデル間で共有される「自然言語入力」と、モデルごとに保存される「Positive / Negative Prompt」下書きを備え、現在の LLM を使って自然言語から英語プロンプトへの自動変換が可能。
- 縦横サイズの個別指定（`384` / `512` / `768` / `1024`）、ステップ数、シード値、アップスケール、LoRA 選択、ワンクリッククリアに対応。
- **OpenAI 互換の画像 API（v0.2.9）**：設定画面でサービス、プロキシ、API キーを管理し、候補となるモデル ID を検出。複数の参照画像はモデルの対応状況に応じて段階的に制限され、生成状況・経過時間の表示と、任意でのローカル Real-ESRGAN 4× 超解像に対応。

### 4. 統合ギャラリー（Gallery）
- **統合ギャラリー・自動索引**：画像生成ページとチャット、ローカルモデルと外部 API の生成画像を一覧化。初回表示時に既存画像を読み込み、その後は生成成功時に `chat/gallery-index.sqlite3` を更新し、サムネイルをキャッシュします。プライベート画像を GitHub にアップロードしません。
- **一覧と画像ビューア**：画像生成 / チャット / ローカル / API などで絞り込み、日付順に並べ替え。画像を拡大し、PC では左右キーと `Esc`、スマートフォンではスワイプで操作できます。元画像と 4× 超解像画像は一組のカードとして表示され、影付きバッジに枚数（例：`2`）を表示。詳細画面では片方だけを削除することも可能です。
- **NSFW・複数選択管理**：NSFW 表示スイッチは**初期状態でオフ**、マークされた画像にはぼかしを適用。画像ごとの一時表示、手動の設定/解除、複数作品の一括 NSFW 設定に対応。モデル名の `uncensored` は初期判定の目安にすぎず、**画像内容の自動判定やアクセス制御ではありません**。複数選択と一括削除ができ、通常削除・一括削除は元画像と 4× 画像を**まとめて完全削除**します。削除済み画像へのチャット履歴内リンクは無効になります。

### 5. リアルタイムハードウェア＆推論モニター（Monitor）
- GPU VRAM 使用量、システム RAM、Prefill / Decode 速度（tok/s）、入出力トークン統計、KV キャッシュヒット率、直近リクエストのレイテンシをリアルタイム表示。

### 6. Windows ネイティブマネージャー（Tauri 2）
- システムトレイ常駐、モデル設定のワンクリック切り替え、プロセスのウォッチドッグ監視、アイドル時の自動アンロード（0〜1440分）、LAN アクセス制御、Windows DPAPI による認証情報保護、および **Cloudflare Tunnel** の状態監視・遅延テスト・再起動をサポート。

### 7. ほかのデバイスからアクセス（Remote Access）

推論処理、会話履歴、生成画像は Mikuchin を実行するホストで管理されます。ほかの端末にモデルを入れる必要はありません。ホストの起動、API Key、待ち受けアドレス、ファイアウォールとアクセス権限を確認してください。

#### 7.1 デスクトップからアクセス（Windows / Linux）

1. ホストで Mikuchin を起動し、API ポート（例：`15239`）を確認します。
2. 信頼できる LAN 内では、別のパソコンのブラウザから `http://<HOST_LAN_IP>:15239/` を開きます。ホスト側の LAN 待ち受けとファイアウォールで当該ポートを許可してください。
3. 別ネットワークからは、適切な ACL/Grants を設定した **Tailscale Tailnet**、またはアクセス制御付きの **Cloudflare Tunnel HTTPS ホスト名**を使用します。Mikuchin API Key を入力すれば、チャット、画像生成、ギャラリーを利用できます。Mac のブラウザも同様にアクセスできます。

#### 7.2 Android デバイスからアクセス

1. [GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest) から正式署名済みの Mikuchin APK を入手します。**Android は Mikuchin サーバーに接続するクライアントで、端末上でモデルを推論しません。**
2. アプリで **「直接接続」** または **「Tailscale」** を選びます。
   - **直接接続**：接続可能なホスト URL（LAN アドレスや自身の HTTPS Cloudflare Tunnel など）と Mikuchin API Key を入力します。
   - **Tailscale**：アプリ内のブラウザで OAuth 認証を完了してから、Mikuchin の接続先と API Key を入力します。Tailnet ACL/Grants、ホスト待ち受け、ファイアウォールで接続を許可してください。
3. 接続後はチャット、画像生成、ギャラリーを使用できます。

**Android クライアントの機能：**

- **ライトテーマ＆伸縮レイアウト**：ログイン前はシンプルな接続画面のみを表示し、接続後は**最新のチャット画面へ直行**。左上の履歴ドロワーボタンと、枠線のない下部6ボタンナビゲーション（画像生成・ギャラリー・キャラクター・設定・モニター・概要）を搭載。
- **ユーザー空間 Tailscale 統合**：公式 `tailscale.com/tsnet`（Go + `gomobile` AAR）をアプリ内に内蔵。**Android の `VpnService` を一切使用しない**ため、Android の VPN スロットを占有しません。実際の接続経路は端末の設定に依存し、Root 化や公式 Tailscale アプリのインストールも不要です。
- **認証情報の保護**：API キーは Android Keystore（`AES/GCM/NoPadding`）で暗号化保存されます。接続設定は認証済みのアプリ内で管理されます。

**アップグレード時の注意：** v0.5.1 は正式署名済み APK です。同じ証明書の旧版は通常上書きできますが、Debug 署名版では再インストールが必要になる場合があります。先にアプリ内設定をバックアップしてください。

#### 7.3 Apple デバイスからアクセス（iPhone / iPad / Mac）

**iPhone/iPad での利用に Mac・Xcode・開発者署名・IPA のサイドロードは不要です。** 既存の Mikuchin Web ワークスペースを Safari から利用します。推論・会話履歴・生成画像の保存先はあくまでご自身の Mikuchin サーバーであり、Apple デバイスはリモートのブラウザとして動作します。**ホーム画面のアイコンはネイティブアプリやオフライン推論機能ではありません。**

##### iPhone / iPad：Stash 内蔵 Tailscale + Safari

1. **サーバーを用意**：Windows 側で Mikuchin を起動し、Tailscale 経由で到達できるアドレスへの待ち受け（例：LAN アクセス）を有効にします。API ポート（例：`15239`）を PC のファイアウォールで許可し、Tailnet の ACL/Grants でも iPhone/iPad からのアクセスを許可します。公開ポートの開放は不要です。
2. **Stash から同じ Tailnet に参加**：iOS 版 Stash 3.4+ は `type: tailscale` をサポートします。Tailnet の自動ルーティングと MagicDNS には 3.6+ を推奨します。既存設定の `proxies` に以下のノードを**追加**し、他のプロキシ設定は上書きしないでください。Stash のノードメニューから **Tailscale** を開き、ブラウザで認証します。認証キーは公開設定に書き込まないでください。

   ```yaml
   proxies:
     - name: mikuchin-tailnet
       type: tailscale
   ```

   Stash 内蔵 Tailscale は Stash の VPN トンネルを共有するため、通常は公式 Tailscale VPN を同時起動する必要がありません。実際のルーティングは Stash のバージョンとルールに左右されます。詳しくは [Stash の Tailscale 解説](https://stash.wiki/en/proxy-protocols/proxy-types) と [内網接続ガイド](https://stash.wiki/features/nat-traversal) を参照してください。
3. **Safari で接続**：Stash の Tailnet 接続後、`http://<MIKUCHIN_HOST_TAILNET_IP>:15239/` を開きます（`<...>` は PC の Tailscale IPv4 アドレスと実際のポートに置換）。利用可能なら MagicDNS のホスト名も使えます。画面の案内に従って **Mikuchin API Key** を入力します。接続できない場合は、サーバー起動・待ち受け・ファイアウォール・Tailnet の許可・Stash ルールを確認します。
4. **ホーム画面に追加**：Safari の **共有 → ホーム画面に追加** を選び、表示される場合は **Web アプリとして開く（Open as Web App）** を有効にして追加します。以降はホーム画面のアイコンからアクセスできます。詳しくは [Apple 公式ガイド](https://support.apple.com/guide/iphone/iphea86e5236/ios) を参照してください。

##### その他の Apple 接続方法

- **Stash を使わない iPhone/iPad**：公式 [Tailscale iOS クライアント](https://tailscale.com/docs/install/ios) で Tailnet に参加してから Safari を開きます。iOS の VPN スロットを他の VPN と取り合う場合があります。
- **Tailnet を使わない場合**：ご自身で構成した、適切なアクセス制御のある **HTTPS Cloudflare Tunnel のホスト名**から Safari でアクセスし、Mikuchin API Key で認証します。[プロジェクト公式サイト](https://mikuchin.zakee.fun) は個人の推論サーバーの URL ではありません。
- **Mac**：Safari などのブラウザから Tailnet アドレス、または認証済みの HTTPS エンドポイントを開くだけです。ブラウザ利用のために専用 macOS アプリをビルドする必要はありません。

**セキュリティ**：正常に接続された Tailscale トンネル内の `http://` 通信はトンネル層で暗号化されますが、HTTP 自体がブラウザ向けの HTTPS/TLS やセキュアオリジンを提供するわけではありません。ブラウザのセキュアコンテキスト機能が必要な場合は、正規証明書の HTTPS 経由で接続してください。API Key 認証と Tailnet ACL を維持し、平文 HTTP をインターネットへ直接公開しないでください。サーバーがスリープ中またはオフラインのとき、ホーム画面のアイコンだけでモデルに接続することはできません。

### 8. 日・中・英 3言語リアルタイム切り替え（i18n）
- Web UI、モバイル画面、Windows マネージャー、トレイメニューの表示言語を `简体中文` / `日本語` / `English` 間で即座に切り替え可能（会話本文やキャラクター設定は翻訳されません）。

## 📂 プロジェクト構成

```text
mikuchin/
├── assets/                 # アイコン・ブランド画像
├── backend/
│   ├── polystrata/         # 推論エンジンの同梱ソース（本リポジトリで管理）
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

## 📥 モデルの準備とダウンロード案内

> 💡 **最も簡単なデプロイ方法**：コア推論エンジンには **PolyStrata** を使用しています。手動設定が面倒な場合は、**このリポジトリをあなたの AI アシスタントに丸ごと渡して、デプロイしてもらいましょう〜**

Windows インストーラーおよびリポジトリにはモデルの重みファイルが含まれていません。以下の GGUF / Safetensors ファイルを準備し、ランチャーから設定ファイルを登録してください：

### 1. 会話・マルチモーダル視覚メインモデル（Chat & Vision LLM、計 2 ファイル）
日常会話、ロールプレイ、画像認識、および画像生成後のキャラクター視覚フィードバックに使用します：
- `G4-MeroMero-26B-A4B-it-uncensored-heretic-Q4_K_M.gguf`（メイン言語モデル 4-bit 量子化重み）
- `G4-MeroMero-26B-A4B-it-uncensored-heretic-mmproj-BF16.gguf`（BF16 マルチモーダル視覚プロジェクター `mmproj`）
- **入手先**：Hugging Face [`llmfan46/G4-MeroMero-26B-A4B-it-uncensored-heretic-GGUF`](https://huggingface.co/llmfan46/G4-MeroMero-26B-A4B-it-uncensored-heretic-GGUF)

### 2. 画像生成モデルスイート（Qwen-Image 2.1 コンポーネント、計 5 ファイル）
チャット内描画および「画像スタジオ（Image Studio）」で使用します：
- `Qwen-Image-2.1-Turbo-AD-Q4_K.gguf` — 8 ステップ高速生成 DiT（[`AtomicChat/Qwen-Image-2.1-Turbo-GGUF`](https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-GGUF)）
- `qwen_image_2.1-Q4_K.gguf` — 標準マルチステップ生成 DiT（[`leejet/Qwen-Image-2.1-GGUF`](https://huggingface.co/leejet/Qwen-Image-2.1-GGUF)）
- `Qwen3VL-8B-Instruct-Q4_K_M.gguf` — テキストエンコーダー（[`Qwen/Qwen3-VL-8B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF)）
- `mmproj-Qwen3VL-8B-Instruct-F16.gguf` — ネイティブ参照画像編集（`--ref-image`）用視覚プロジェクター（[`Qwen/Qwen3-VL-8B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF)）
- `qwen_image_2.1_vae_bf16.safetensors` — 共有 BF16 VAE デコーダー（[`unsloth/Qwen-Image-2.1-FP8`](https://huggingface.co/unsloth/Qwen-Image-2.1-FP8) `vae/` ディレクトリ）

> PolyStrata 同梱スクリプト `python backend/polystrata/tools/image/install.py --models-dir models` での自動セットアップや、標準 SDXL チェックポイント（`Animagine XL 4.0 Opt`、`SDXL Base 1.0`）にも対応しています。

## 📦 ダウンロードとビルド

[GitHub Releases](https://github.com/zakee039/mikuchin/releases/latest) から Windows インストーラーと Android APK を取得できます。**モデルの重みは配布物に含まれません**。ローカルのモデルファイルを準備し、ランチャーから設定ファイルを登録してください。

```bash
git clone --recurse-submodules https://github.com/zakee039/mikuchin.git
# クローン済みの場合：git submodule update --init --recursive
```

Native main は**公式 PolyStrata**を Git サブモジュール（v0.1.45-poly.10）として固定し、上流ソースを改変しません。モデルの重み、Python/CUDA と画像生成のランタイムは別途必要です。現行 Windows Launcher のインストーラーだけでは**単体動作できません**。旧構成は old-mixed に保存されています。[Native 移行記録](docs/NATIVE_V040_MAIN_MIGRATION_2026-11-21.md)、[MIT ライセンス](backend/polystrata/LICENSE)、[第三者ライセンス表示](THIRD_PARTY_NOTICES.md) を参照してください。

```powershell
python scripts/build-locales.py
cd frontend/launcher
npm ci
npx tauri build --debug --no-bundle
cd ../..
powershell -ExecutionPolicy Bypass -File frontend/android/build-apk.ps1
```

## 🔒 セキュリティと注意事項

API Key、Tailnet の認証状態、会話データ、モデル重みは GitHub に含めないでください。ネットワーク環境により VPN の共存動作が変わるため、端末上で検証してください。同梱エンジンのライセンスと著作権表示を参照してください。
