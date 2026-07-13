// PixivVault Extension Background Service Worker

const SERVER_URL = "http://127.0.0.1:25010";
const FETCH_TIMEOUT_MS = 8000;

// PixivVaultプロセスがフリーズ/デッドロックしている場合、応答が永久に返らずボタンが
// 「送信中...」のままハングし続けるのを防ぐため、タイムアウト付きfetchを使用する。
function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer));
}

// fetch自体が失敗した(=サーバーに接続すらできなかった)場合の分類。
// ブラウザのエラーメッセージ文言に依存せず、Errorの型で判定する。
function classifyFetchError(err) {
    return err && err.name === 'AbortError' ? 'timeout' : 'network';
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "sendDownloadRequest") {
        fetchWithTimeout(`${SERVER_URL}/download`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(request.payload)
        })
        .then(async (response) => {
            if (response.ok) {
                sendResponse({ success: true });
            } else {
                // サーバーには接続できたが、アプリ側がエラーを返した(=起動待ちではない)ケース。
                const text = await response.text();
                sendResponse({ success: false, error: text, kind: 'http' });
            }
        })
        .catch((err) => {
            sendResponse({ success: false, error: err.toString(), kind: classifyFetchError(err) });
        });
        return true; // 非同期で sendResponse を返すため true を返す
    } else if (request.action === "fetchStatus") {
        fetchWithTimeout(`${SERVER_URL}${request.path}`)
        .then(res => {
            if (!res.ok) {
                return res.text().then(text => { throw new Error(text || `HTTP ${res.status}`); });
            }
            return res.json();
        })
        .then(data => sendResponse({ success: true, data: data }))
        .catch(err => sendResponse({ success: false, error: err.toString(), kind: classifyFetchError(err) }));
        return true;
    }
});
