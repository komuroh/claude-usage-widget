# exe のビルド手順（Windows）

```
pip install pycryptodome pyinstaller
pyinstaller ClaudeUsageWidget.spec
```
完成物: `dist\ClaudeUsageWidget.exe`（単一exe・コンソール非表示）

- 初回のみ、ウィジェット内の「Refresh session」を押してセッションキャッシュ（`%LOCALAPPDATA%\claude-usage\session.bin`）を作成してください。
- スタートアップ登録: exe のショートカットを `shell:startup` に置く。
- ビルド済みexeは [Releases](../../releases) からも入手できます（未署名のため SmartScreen/ウイルス対策ソフトが警告する場合があります）。
