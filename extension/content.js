// PixivVault Web Extension Content Script

const SERVER_URL = "http://127.0.0.1:25010/download";

async function sendDownloadRequest(payload, buttonElement) {
    const originalText = buttonElement.innerText;
    buttonElement.innerText = "送信中...";
    buttonElement.disabled = true;

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
        buttonElement.innerText = "❌ 接続エラー";
        buttonElement.classList.add("pv-error");
        console.error("PixivVault Fetch Error:", err);
        alert("PixivVaultアプリが起動しているか確認してください。");
    }

    setTimeout(() => {
        buttonElement.innerText = originalText;
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
    // ユーザーを表すリンクを探す。 href="/users/12345" が対象
    const userLinks = document.querySelectorAll('a[href^="/users/"]:not(.pv-processed)');
    
    userLinks.forEach(link => {
        const href = link.getAttribute('href');
        const match = href.match(/^\/users\/(\d+)(\/|$)/);
        if (!match) return;
        
        const userId = match[1];
        link.classList.add('pv-processed');
        
        // ユーザー名やアイコンの親要素にボタンを追加する
        // ユーザーカードの構造に依存するため、とりあえずリンクの隣に配置
        const parent = link.parentElement;
        
        const btn = createVaultButton("差分DL", (btnEl) => {
            sendDownloadRequest({ type: "user", user_id: userId }, btnEl);
        });
        btn.classList.add("pv-small-btn");
        
        parent.appendChild(btn);
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
