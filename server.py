import json
import threading
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from win11toast import toast

from database import Database
from pixiv_client import PixivClient
from core import run_backup, run_single_work_backup

logger = logging.getLogger(__name__)

class PixivVaultRequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path == '/download':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                req_type = data.get('type')
                
                if req_type == 'user':
                    user_id = data.get('user_id')
                    if user_id:
                        threading.Thread(target=self.server.trigger_user_backup, args=(user_id,), daemon=True).start()
                        self._send_response(200, {"status": "ok", "message": f"Started user {user_id} backup"})
                    else:
                        self._send_response(400, {"status": "error", "message": "Missing user_id"})
                elif req_type == 'work':
                    work_id = data.get('work_id')
                    is_novel = data.get('is_novel', False)
                    if work_id:
                        threading.Thread(target=self.server.trigger_work_backup, args=(work_id, is_novel), daemon=True).start()
                        self._send_response(200, {"status": "ok", "message": f"Started work {work_id} backup"})
                    else:
                        self._send_response(400, {"status": "error", "message": "Missing work_id"})
                else:
                    self._send_response(400, {"status": "error", "message": "Invalid type"})
                    
            except json.JSONDecodeError:
                self._send_response(400, {"status": "error", "message": "Invalid JSON"})
        else:
            self._send_response(404, {"status": "error", "message": "Not found"})

    def _send_response(self, status_code, json_dict):
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(json_dict).encode('utf-8'))

    def log_message(self, format, *args):
        # http.server のデフォルトログ出力をロガーに流す
        logger.debug("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))


class PixivVaultServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, db, client):
        super().__init__(server_address, RequestHandlerClass)
        self.db = db
        self.client = client
        self.download_lock = threading.Lock()

    def notify(self, title, message):
        try:
            if self.db.get_setting("notify_enabled", "1") == "1":
                toast(title, message, app_id="PixivVault")
        except Exception as e:
            logger.error(f"通知の送信に失敗しました: {e}")

    def trigger_user_backup(self, user_id):
        # 同時実行を防ぐためのロック（簡易的）
        if not self.download_lock.acquire(blocking=False):
            self.notify("PixivVault 拡張機能", "他のダウンロード処理が実行中のため、順番待ちまたは失敗しました。")
            return
            
        try:
            self.notify("PixivVault ダウンロード開始", f"ユーザーID: {user_id} のバックアップを開始します。")
            # PixivVaultのログコールバック用
            def log_cb(msg):
                logger.debug(f"[拡張機能連携] {msg}")
                
            run_backup(user_id=user_id, client=self.client, db=self.db, target_type="both", log_callback=log_cb)
            
            self.notify("PixivVault ダウンロード完了", f"ユーザーID: {user_id} のバックアップが完了しました！")
        except Exception as e:
            logger.error(f"拡張機能からのユーザーダウンロードに失敗: {e}")
            self.notify("PixivVault エラー", f"ダウンロードに失敗しました: {e}")
        finally:
            self.download_lock.release()

    def trigger_work_backup(self, work_id, is_novel):
        if not self.download_lock.acquire(blocking=False):
            self.notify("PixivVault 拡張機能", "他のダウンロード処理が実行中のため、順番待ちまたは失敗しました。")
            return
            
        try:
            type_str = "小説" if is_novel else "イラスト/マンガ"
            self.notify("PixivVault ダウンロード開始", f"{type_str} ID: {work_id} の保存を開始します。")
            
            def log_cb(msg):
                logger.debug(f"[拡張機能連携] {msg}")
                
            run_single_work_backup(work_id=work_id, is_novel=is_novel, client=self.client, db=self.db, log_callback=log_cb)
            
            self.notify("PixivVault ダウンロード完了", f"作品の保存が完了しました！")
        except Exception as e:
            logger.error(f"拡張機能からの作品ダウンロードに失敗: {e}")
            self.notify("PixivVault エラー", f"ダウンロードに失敗しました: {e}")
        finally:
            self.download_lock.release()

def start_server(port, db, client):
    server_address = ('127.0.0.1', port)
    httpd = PixivVaultServer(server_address, PixivVaultRequestHandler, db, client)
    logger.info(f"拡張機能連携サーバーを 127.0.0.1:{port} で起動しました。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
