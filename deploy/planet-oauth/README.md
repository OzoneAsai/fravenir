# Planet OAuth

稼働中の Planet OAuth のソース一式です。Fravenir の認証ブリッジおよび掲示板の TOTP 認証ゲートと組み合わせて使います。

- `app.py`: FastAPI OAuth サーバー。動的クライアント登録、PKCE、TOTP、JWT、リフレッシュトークン、ChatGPT クライアント認証を扱います。
- `bootstrap.py`: 新規環境の秘密情報と TOTP 登録 URI を生成します。既存の `oauth.env` は保存します。
- `run-with-log.ps1`: Windows 上で Uvicorn を起動し、標準出力・標準エラーをログへ保存します。
- `rotate_totp_account.py` / `perform-totp-rotation.ps1`: 既存環境用の TOTP 変更手順です。バックアップを取得しますが、サービス停止・認証情報変更を伴うため、新規セットアップ時には実行しません。

## 新規の検証環境で起動する

Python 3.12 を使用します。本番ディレクトリを上書きせず、まず独立したディレクトリで準備してください。

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

`bootstrap.py` の `PUBLIC_BASE` を自分の HTTPS オリジンに設定してから、検証用のディレクトリ内で実行します。

```powershell
.\venv\Scripts\python.exe bootstrap.py
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8002 --env-file oauth.env
```

`oauth.env.example` は設定項目の説明用です。空の秘密情報のままでは起動しません。`bootstrap.py` が生成する `oauth.env`、登録 URI、QR コード、DB は機密データです。Git に追加しないでください。

## Windows の既存構成

運用スクリプトは `C:\ProgramData\PlanetOAuth`、`Planet-OAuth` タスク、`FravenirMCP` サービスを前提とする環境固有の原本です。TOTP 変更スクリプトには利用環境のダウンロード先も含まれます。利用前にパス・公開オリジン・タスク構成を確認してください。

Fravenir 側のソースは隣の `../windows/` にあります。`oauth_bridge.py` は従来の Planet `.env` の `PLANET_OAUTH_*` 設定を読み、`board_auth.py` はこの OAuth サーバーの設定を利用します。両者の署名鍵・issuer・audience は対応させる必要があります。公開ネットワーク側の TLS 終端とルーティングは別途設定してください。

この配布物には実環境の DB、トークン、TOTP シード、署名鍵、登録 URI、QR コード、ログを含めていません。公開用コピーの検証結果は [`../SOURCE-PUBLICATION.md`](../SOURCE-PUBLICATION.md) に記録します。

## 検証と運用ツールの依存関係

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\venv\Scripts\python.exe -m pytest tests -q
```

テストは毎回生成した鍵と一時 DB を使い、実環境の設定を読みません。PKCE、TOTP の再利用拒否、認可コード・リフレッシュトークンの再利用拒否、失効、設定不備時の起動拒否を確認します。TOTP 変更ツールで QR を生成する場合は、追加で `requirements-ops.txt` をインストールしてください。
