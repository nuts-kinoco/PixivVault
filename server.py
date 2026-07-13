import json
import threading
import queue
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from win11toast import toast

from database import Database
from pixiv_client import PixivClient
from core import run_backup, run_single_work_backup

logger = logging.getLogger(__name__)

# 拡張機能(サービスワーカー)からのリクエストは Origin: chrome-extension://<id> になる。
# Webページから直接 127.0.0.1 に叩かれるドライブバイ攻撃を防ぐため、この形式以外の Origin は拒否する。
ALLOWED_ORIGIN_PREFIX = 'chrome-extension://'


class PixivVaultRequestHandler(BaseHTTPRequestHandler):
    def _is_allowed_origin(self, origin):
        return bool(origin) and origin.startswith(ALLOWED_ORIGIN_PREFIX)

    def _send_cors_headers(self, origin=None):
        if origin and self._is_allowed_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Access-Control-Request-Private-Network')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def do_OPTIONS(self):
        origin = self.headers.get('Origin', '')
        self.send_response(200)
        self._send_cors_headers(origin)
        self.end_headers()

    def _check_origin(self):
        """許可されていない Origin からのリクエストを拒否する。True を返したら処理続行可。"""
        origin = self.headers.get('Origin', '')
        if not self._is_allowed_origin(origin):
            self._send_response(403, {"status": "error", "message": "Forbidden"})
            return False
        return True

    def do_GET(self):
        if not self._check_origin():
            return
        if self.path.startswith('/api/work/'):
            work_id = self.path.split('/')[-1].split('?')[0]
            work = self.server.db.get_work(work_id)
            if work:
                self._send_response(200, {
                    "downloaded": True,
                    "update_date": work["update_date"],
                    "is_deleted": bool(work["is_deleted"]),
                    "is_latest": True
                })
            else:
                self._send_response(200, {"downloaded": False})
        elif self.path.startswith('/api/user/') and self.path.endswith('/status'):
            parts = self.path.split('/')
            if len(parts) >= 4:
                user_id = parts[3]
                # Pixiv APIではなくDB内の保存数で返す（余分なAPIリクエストを防ぐ）
                db_work_ids = self.server.db.get_user_work_ids(user_id)
                downloaded = len(db_work_ids)
                # DBに保存済みの件数を total として返す（フル表示）
                self._send_response(200, {
                    "downloaded": downloaded,
                    "total": downloaded  # 差分表示は extension 側で別途実装予定
                })
            else:
                self._send_response(400, {"status": "error", "message": "Invalid path"})
        else:
            self._send_response(404, {"status": "error", "message": "Not found"})

    def do_POST(self):
        if not self._check_origin():
            return
        if self.path == '/download':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                req_type = data.get('type')
                
                if req_type == 'user':
                    user_id = data.get('user_id')
                    new_only = data.get('new_only', False)
                    if user_id:
                        if self.server.enqueue(f"user_{user_id}", {'type': 'user', 'user_id': user_id, 'new_only': new_only}):
                            self._send_response(200, {"status": "ok", "message": f"Queued user {user_id} backup"})
                        else:
                            self._send_response(200, {"status": "ok", "message": f"User {user_id} backup already queued"})
                    else:
                        self._send_response(400, {"status": "error", "message": "Missing user_id"})
                elif req_type == 'work':
                    work_id = data.get('work_id')
                    is_novel = data.get('is_novel', False)
                    if work_id:
                        if self.server.enqueue(f"work_{work_id}", {'type': 'work', 'work_id': work_id, 'is_novel': is_novel}):
                            self._send_response(200, {"status": "ok", "message": f"Queued work {work_id} backup"})
                        else:
                            self._send_response(200, {"status": "ok", "message": f"Work {work_id} backup already queued"})
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
        self._send_cors_headers(self.headers.get('Origin', ''))
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
        self.download_queue = queue.Queue()
        # キュー投入済み(未処理)または処理中のジョブキーを保持し、同一ジョブの多重投入を防ぐ。
        self._queued_keys = set()
        self._queued_keys_lock = threading.Lock()
        self.worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self.worker_thread.start()

    def enqueue(self, key, task):
        """同一keyが投入済み/処理中でなければキューに追加する。追加した場合Trueを返す。"""
        with self._queued_keys_lock:
            if key in self._queued_keys:
                return False
            self._queued_keys.add(key)
        task['key'] = key
        self.download_queue.put(task)
        return True

    def _queue_worker(self):
        while True:
            task = self.download_queue.get()
            try:
                if task['type'] == 'user':
                    self.trigger_user_backup(task['user_id'], task['new_only'])
                elif task['type'] == 'work':
                    self.trigger_work_backup(task['work_id'], task['is_novel'])
            except Exception as e:
                logger.error(f"Worker error: {e}")
            finally:
                with self._queued_keys_lock:
                    self._queued_keys.discard(task.get('key'))
                self.download_queue.task_done()

    def notify(self, title, message):
        try:
            if self.db.get_setting("enable_notifications", "1") == "1":
                threading.Thread(target=lambda: toast(title, message, app_id="PixivVault"), daemon=True).start()
        except Exception as e:
            logger.error(f"通知の送信に失敗しました: {e}")

    def trigger_user_backup(self, user_id, new_only=False):
        flow_name = f"ext_user_{user_id}"
        try:
            from gui import gui_set_flow_active
            if gui_set_flow_active[0]:
                gui_set_flow_active[0](flow_name, True)
        except Exception:
            pass
        try:
            self.notify("PixivVault ダウンロード開始", f"ユーザーID: {user_id} のバックアップを開始します。")
            def log_cb(msg, color=None):
                logger.debug(f"[拡張機能連携] {msg}")
                try:
                    from gui import gui_queue_log_callback
                    if gui_queue_log_callback and gui_queue_log_callback[0]:
                        if color:
                            gui_queue_log_callback[0](msg, color)
                        else:
                            gui_queue_log_callback[0](msg)
                except Exception as e:
                    logger.debug(f"GUIキューログ転送エラー: {e}")

            # Cookie更新をアプリ再起動なしに反映させるため、起動時に使い回すのではなく都度生成する
            client = PixivClient()
            log_cb(f"=== ユーザーID: {user_id} のバックアップ開始 ===")

            run_backup(user_id=user_id, client=client, db=self.db, target_type="both", log_callback=log_cb, new_only=new_only)

            self.notify("PixivVault ダウンロード完了", f"ユーザーID: {user_id} のバックアップが完了しました！")
            log_cb(f"=== ユーザーID: {user_id} 完了 ===")
        except Exception as e:
            logger.exception(f"拡張機能からのユーザーダウンロードに失敗 (ID: {user_id}): {e}")
            self.notify("PixivVault エラー", f"ダウンロードに失敗しました: {e}")
            try:
                from gui import gui_queue_log_callback
                if gui_queue_log_callback and gui_queue_log_callback[0]:
                    gui_queue_log_callback[0](f"[エラー] ユーザー {user_id}: {e}", color="red")
            except Exception:
                pass
        finally:
            try:
                from gui import gui_set_flow_active
                if gui_set_flow_active[0]:
                    gui_set_flow_active[0](flow_name, False)
            except Exception:
                pass

    def trigger_work_backup(self, work_id, is_novel):
        flow_name = f"ext_work_{work_id}"
        try:
            from gui import gui_set_flow_active
            if gui_set_flow_active[0]:
                gui_set_flow_active[0](flow_name, True)
        except Exception:
            pass
        try:
            type_str = "小説" if is_novel else "イラスト/マンガ"
            self.notify("PixivVault ダウンロード開始", f"{type_str} ID: {work_id} の保存を開始します。")

            def log_cb(msg, color=None):
                logger.debug(f"[拡張機能連携] {msg}")
                try:
                    from gui import gui_queue_log_callback
                    if gui_queue_log_callback and gui_queue_log_callback[0]:
                        if color:
                            gui_queue_log_callback[0](msg, color)
                        else:
                            gui_queue_log_callback[0](msg)
                except Exception as e:
                    logger.debug(f"GUIキューログ転送エラー: {e}")

            # Cookie更新をアプリ再起動なしに反映させるため、起動時に使い回すのではなく都度生成する
            client = PixivClient()
            log_cb(f"=== {type_str} ID: {work_id} の保存開始 ===")

            run_single_work_backup(work_id=work_id, is_novel=is_novel, client=client, db=self.db, log_callback=log_cb)

            self.notify("PixivVault ダウンロード完了", f"作品の保存が完了しました！")
            log_cb(f"=== {type_str} ID: {work_id} 完了 ===")
        except Exception as e:
            logger.exception(f"拡張機能からの作品ダウンロードに失敗 (ID: {work_id}): {e}")
            self.notify("PixivVault エラー", f"ダウンロードに失敗しました: {e}")
            try:
                from gui import gui_queue_log_callback
                if gui_queue_log_callback and gui_queue_log_callback[0]:
                    gui_queue_log_callback[0](f"[エラー] 作品 {work_id}: {e}", color="red")
            except Exception:
                pass
        finally:
            try:
                from gui import gui_set_flow_active
                if gui_set_flow_active[0]:
                    gui_set_flow_active[0](flow_name, False)
            except Exception:
                pass

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
