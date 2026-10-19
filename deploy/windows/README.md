# Windows deployment source

現在の Windows 配備で使う Fravenir の補助ソースを収録しています。

- `oauth_bridge.py`: OAuth bearer token を検証し MCP バックエンドへ転送。
- `board_auth.py`: Planet OAuth の TOTP を利用する掲示板認証ゲート。
- `FravenirSupervisor.cs`: MCP・ブリッジ・管理 UI・認証ゲートを監視する Windows サービス。
- `*.ps1`: 当該環境のインストール・起動・ルーティング更新用スクリプト。

Python のブリッジと認証ゲートはリポジトリ直下の `deploy.windows` パッケージです。C# と PowerShell の原本は配備先では `C:\ProgramData\Fravenir` 直下に配置されます。これらのスクリプトは固定パス、サービス名、既存の Planet/Caddy 設定を前提としており、汎用インストーラーではありません。サービス停止や既存設定の更新を行うものがあります。別環境でそのまま実行せず、バックアップを取得し、構成を確認してください。

OAuth サーバーのコードと設定例は [`../planet-oauth/`](../planet-oauth/README.md) にあります。実環境の鍵・環境変数ファイル・DB・ログ・実行ファイルは収録していません。
