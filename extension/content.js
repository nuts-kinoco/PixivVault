// PixivVault Web Extension Content Script

const SERVER_URL = "http://127.0.0.1:25010/download";

async function sendDownloadRequest(payload, buttonElement, isRetry = false) {
    const originalText = isRetry ? "差分DL" : buttonElement.innerText; // Fallback original text
    
    if (!isRetry) {
        buttonElement.innerText = "送信中...";
        buttonElement.disabled = true;
    }

    try {
        const response = await fetch(SERVER_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            buttonElement.innerText = "✓ 送信完了";
            buttonElement.classList.add("pv-success");
        } else {
            buttonElement.innerText = "❌ 失敗";
            buttonElement.classList.add("pv-error");
            console.error("PixivVault Server Error:", await response.text());
        }
    } catch (err) {
        if (!isRetry) {
            console.warn("PixivVault Fetch Error. Attempting to start the app...", err);
            buttonElement.innerText = "アプリ起動中...";
            buttonElement.classList.remove("pv-error");
            
            // アプリを自動起動するためのカスタムURIスキームを叩く
            window.location.href = "pixivvault://start";
            
            // アプリが起動してサーバーが立ち上がるまで数秒待機してからリトライ
            setTimeout(() => {
                buttonElement.innerText = "再送信中...";
                sendDownloadRequest(payload, buttonElement, true);
            }, 4000);
            return; // ここで一旦終了（リトライ側でボタン状態を戻す）
        } else {
            buttonElement.innerText = "❌ 接続エラー";
            buttonElement.classList.add("pv-error");
            console.error("PixivVault Fetch Retry Error:", err);
            alert("PixivVaultアプリの起動に失敗しました。自動起動が有効になっているか確認してください。");
        }
    }

    setTimeout(() => {
        // 元のテキストに戻す（ハードコードのテキストではなく要素の初期状態など工夫も可能だがシンプルに）
        buttonElement.innerText = (payload.type === 'user') ? "差分DL" : "📥 PixivVaultに保存";
        buttonElement.disabled = false;
        buttonElement.classList.remove("pv-success", "pv-error");
    }, 3000);
}

function createVaultButton(text, onClick) {
    const btn = document.createElement("button");
    btn.className = "pixiv-vault-btn";
    btn.innerText = text;
    btn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick(btn);
    };
    return btn;
}

// ==========================================
// 1. 作品単体ページ (/artworks/ID)
// ==========================================
function injectArtworkButton() {
    const match = window.location.pathname.match(/^\/artworks\/(\d+)/);
    if (!match) return;
    
    const workId = match[1];
    
    // PixivのUIはSPAで動的に変わるため、すでにボタンがあればスキップ
    if (document.getElementById(`pv-artwork-${workId}`)) return;

    // 「いいね」「ブックマーク」などのアクションバーを探す (Pixivのクラスや構造は変わりやすいので複数候補)
    const actionBars = document.querySelectorAll('section figure, aside section');
    if (actionBars.length === 0) return;
    
    // とりあえず見つけやすい場所に注入する（タイトル横やブックマークボタン付近）
    const targetParent = document.querySelector('main section > div > div > h1')?.parentElement?.parentElement || document.body;
    
    const btn = createVaultButton("📥 PixivVaultに保存", (btnEl) => {
        sendDownloadRequest({ type: "work", work_id: workId, is_novel: false }, btnEl);
    });
    btn.id = `pv-artwork-${workId}`;
    btn.classList.add("pv-floating-btn"); // 画面右下に固定配置するフォールバック
    
    document.body.appendChild(btn);
}

// ==========================================
// 2. 小説単体ページ (/novel/show.php?id=ID)
// ==========================================
function injectNovelButton() {
    const params = new URLSearchParams(window.location.search);
    const novelId = params.get('id');
    if (!novelId || !window.location.pathname.includes('/novel/show.php')) return;

    if (document.getElementById(`pv-novel-${novelId}`)) return;

    const btn = createVaultButton("📥 PixivVaultに保存", (btnEl) => {
        sendDownloadRequest({ type: "work", work_id: novelId, is_novel: true }, btnEl);
    });
    btn.id = `pv-novel-${novelId}`;
    btn.classList.add("pv-floating-btn");
    
    document.body.appendChild(btn);
}

// ==========================================
// 3. フォロー中一覧ページ等のユーザーカード
// ==========================================
function injectUserButtons() {
    const userLinks = document.querySelectorAll('a[href^="/users/"]');
    
    // 現在のページで処理済みのuserIdを記録
    const processedUsers = new Set();
    
    userLinks.forEach(link => {
        const href = link.getAttribute('href');
        const match = href.match(/^\/users\/(\d+)(\/|$)/);
        if (!match) return;
        
        const userId = match[1];
        
        // 1ユーザーにつき1回だけ処理 (最初に見つかるリンク＝アイコン画像を想定)
        if (processedUsers.has(userId)) return;
        processedUsers.add(userId);
        
        const btnId = `pv-user-${userId}`;
        if (document.getElementById(btnId)) return;
        
        const btn = createVaultButton("差分DL", (btnEl) => {
            sendDownloadRequest({ type: "user", user_id: userId }, btnEl);
        });
        btn.id = btnId;
        btn.classList.add("pv-small-btn");
        // アイコンの左に配置するためのスタイル調整
        btn.style.marginRight = "16px";
        btn.style.marginLeft = "0";
        btn.style.flexShrink = "0";
        
        const parent = link.parentElement;
        if (parent) {
            parent.insertBefore(btn, link);
            // 親要素をフレックスボックスにして横並びを整える
            parent.style.display = 'flex';
            parent.style.alignItems = 'center';
        }
    });
}

// ==========================================
// SPA遷移対応 (MutationObserver)
// ==========================================
const observer = new MutationObserver((mutations) => {
    injectArtworkButton();
    injectNovelButton();
    
    // 特定のページのみユーザーボタンを注入
    if (window.location.pathname.includes('/following') || window.location.pathname.includes('/users/')) {
        injectUserButtons();
    }
});

observer.observe(document.body, { childList: true, subtree: true });

// 初回実行
injectArtworkButton();
injectNovelButton();
if (window.location.pathname.includes('/following') || window.location.pathname.includes('/users/')) {
    injectUserButtons();
}
