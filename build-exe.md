# claude-usage-widget.exe の作り方

これはユーザーのWindows機で実行してください（ClaudeのサンドボックスはmacOS/Linuxのため、ここではWindows向けexeをビルドできません）。

## 手順

1. `outputs\outputs` フォルダに移動
   ```
   cd "%USERPROFILE%\Downloads\outputs\outputs"
   ```

2. 依存関係をインストール（一度だけ）
   ```
   pip install pycryptodome pyinstaller
   ```

3. exeをビルド（アイコンなし・コンソール非表示の単一exe）
   ```
   pyinstaller --onefile --noconsole --name ClaudeUsageWidget claude-usage-widget.py
   ```

4. 完成物は `dist\ClaudeUsageWidget.exe`

## 補足

- `get-desktop-session.py` はもう不要です（`claude-usage-widget.py` に処理を統合済み）。exe単体で「使用率表示」「セッション再取得(Refresh session)」「Claude Desktopの終了/再起動」まで完結します。
- 初回だけ、ウィジェット内の「Refresh session (close & reopen)」ボタンを押してセッションキャッシュを作成してください（`%LOCALAPPDATA%\claude-usage\session.bin`）。
- スタートアップに登録したい場合は `dist\ClaudeUsageWidget.exe` のショートカットを `shell:startup` フォルダに置いてください。
