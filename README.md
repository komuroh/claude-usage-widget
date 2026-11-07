# Claude Usage Widget

Claudeの使用率（5時間ウィンドウ + 週次）をデスクトップ右下に常時表示する、
枠なし・最前面固定のミニウィジェット（Windows専用）。

> **注意（非公式ツール）**: Anthropic とは無関係の非公式ツールです。claude.ai の**非公式な内部API**を使うため、
> 予告なく動かなくなる可能性があります。また Claude Desktop のログイン Cookie を読み取ってローカルに
> （DPAPI暗号化で）保存します。**自己責任**で、自分のPCでのみ使ってください。
> 「Refresh session」は `Claude.exe` を強制終了します（作業中のセッションが落ちます）。

## ダウンロード（Windows）
ビルド済みの exe は [Releases](https://github.com/komuroh/claude-usage-widget/releases/latest) から入手できます。

1. 最新リリースの `ClaudeUsageWidget.exe` をダウンロードして実行（Python不要）
2. 初回のみウィジェット内の「Refresh session」を押す（Claude Desktop が一度終了・再起動します）
3. スタートアップに入れる場合は exe のショートカットを `shell:startup` に置く

未署名のため SmartScreen / ウイルス対策ソフトが警告することがあります。気になる場合はリリースノートの SHA256 で
ファイルを照合するか、下記の手順でソースから自分でビルドしてください。

## ファイル構成
- `claude-usage-widget.py` — **本体（346行、単一ファイル）。exe化するのはこれ。**
- `claude-usage-widget.ps1` — 別方式の旧PowerShell実装（Claude CodeのOAuthトークンを使用、本日のトークン数/概算コストも表示）
- `ClaudeUsageWidget.spec` — PyInstaller ビルド定義
- `build-exe.md` — exeビルド手順

## 動作概要
デスクトップ右下に枠なし・最前面のミニ窓を出し、**5時間ウィンドウ**と**週次**の使用率を
バー付きで表示。60秒ごとに自動更新。ドラッグで移動、✕で終了。

### 使用率の取得
1. Claude Desktop アプリの Cookie DB（Chromium形式）を探す
   - 従来型: `%APPDATA%\Claude`
   - MSIX型: `%LOCALAPPDATA%\Packages\*Claude*\LocalCache\Roaming\Claude`
2. `Local State` の `os_crypt.encrypted_key` を DPAPI で復号 → AES-GCMマスターキー
3. Cookie を復号（v10/v11=AES-256-GCM、それ以外=旧DPAPI）
4. `sessionKey` 等の Cookie で claude.ai 内部API
   - `GET /api/organizations` → org uuid
   - `GET /api/organizations/{uuid}/usage` → `five_hour` / `seven_day` の `utilization`, `resets_at`
5. Cookie は `%LOCALAPPDATA%\claude-usage\session.bin` に DPAPI暗号化して保存

### Refresh session ボタン
Cookie DB は Claude Desktop 起動中は排他ロックされるため:
Claude Desktop を終了（taskkill）→ DBコピー → 復号・キャッシュ更新 →
元々起動していれば `explorer.exe shell:appsFolder\{AppID}` で再起動。別スレッドで実行。

## 実行 / ビルド
```
pip install pycryptodome            # 実行に必要
python claude-usage-widget.py       # そのまま起動
# exe化:
pip install pyinstaller
pyinstaller --onefile --noconsole --name ClaudeUsageWidget claude-usage-widget.py
# -> dist\ClaudeUsageWidget.exe
```
初回のみウィジェット内「Refresh session」でセッションキャッシュを作成する。

## 依存
- 標準ライブラリ（tkinter, sqlite3, ctypes, urllib ほか）
- `pycryptodome`（Cookie復号: `from Crypto.Cipher import AES`）

## ライセンス
MIT — [LICENSE](LICENSE) 参照。
