// ==== Настройка ====
const API_BASE = "https://expressbot1-production.up.railway.app";

// ==== Telegram WebApp init ====
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("#0b0e14");
  tg.setBackgroundColor?.("#0b0e14");
}
const initData = tg?.initData || "";
const tgUser = tg?.initDataUnsafe?.user || null;

// ==== API-клиент ====
async function apiPost(path, body = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initData, ...body }),
  });
  const data = await resp.json().catch(() => ({}));
  return { status: resp.status, data };
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function fmtDate(iso) {
  try { return new Date(iso).toLocaleDateString("ru-RU"); } catch { return "—"; }
}

// ==== Навигация: вкладки + подстраницы ====
const tabs = ["dashboard", "history", "referral", "profile"];
const subpages = ["express", "subscription", "admin"];
let currentTab = "dashboard";
let currentSub = null;

const screens = {};
document.querySelectorAll(".screen").forEach((el) => {
  screens[el.dataset.screen] = el;
});
const tabbar = document.getElementById("tabbar");
const tabEls = {};
tabbar.querySelectorAll(".tab").forEach((el) => {
  tabEls[el.dataset.tab] = el;
  el.addEventListener("click", () => goTab(el.dataset.tab));
});

function render() {
  Object.entries(screens).forEach(([name, el]) => {
    const visible = currentSub ? name === currentSub : name === currentTab;
    el.hidden = !visible;
  });
  Object.entries(tabEls).forEach(([name, el]) => {
    el.classList.toggle("is-active", name === currentTab && !currentSub);
  });
  tabbar.hidden = !!currentSub;
}

function goTab(tab) {
  currentTab = tab;
  currentSub = null;
  render();
  if (tab === "history") loadHistory();
  if (tab === "referral") loadReferral();
  if (tab === "dashboard") loadDashboard();
  tg?.HapticFeedback?.selectionChanged?.();
}

function openSub(name) {
  currentSub = name;
  render();
  tg?.HapticFeedback?.impactOccurred?.("light");
}

function closeSub() {
  currentSub = null;
  render();
}

document.querySelectorAll("[data-back]").forEach((el) => el.addEventListener("click", closeSub));
document.querySelectorAll("[data-goto]").forEach((el) => {
  el.addEventListener("click", () => goTab(el.dataset.goto));
});

// ==== Аккаунт (грузим один раз на старте, переиспользуем) ====
let account = null;

async function loadAccount() {
  if (!initData) return;
  const { status, data } = await apiPost("/api/account");
  if (status === 200 && data.ok) {
    account = data;
    applyAccountToUI();
  }
}

function applyAccountToUI() {
  if (!account) return;

  const initial = (tgUser?.first_name || "?")[0].toUpperCase();
  const name = tgUser?.first_name || "Без имени";
  const handle = tgUser?.username ? `@${tgUser.username}` : "—";

  document.getElementById("dash-avatar").textContent = initial;
  document.getElementById("dash-name").textContent = name;
  document.getElementById("dash-handle").textContent = handle;
  document.getElementById("profile-avatar").textContent = initial;
  document.getElementById("profile-name").textContent = name;
  document.getElementById("profile-handle").textContent = handle;

  document.getElementById("stat-total").textContent = account.express_count ?? 0;

  const subEl = document.getElementById("stat-sub");
  const badgeEl = document.getElementById("profile-badge");
  if (account.subscribed) {
    subEl.textContent = "Активна";
    badgeEl.textContent = `Подписка до ${fmtDate(account.expires_at)}`;
    badgeEl.classList.remove("badge--muted");
  } else {
    subEl.textContent = "Нет";
    badgeEl.textContent = "Без подписки";
    badgeEl.classList.add("badge--muted");
  }

  document.getElementById("menu-admin").hidden = !account.is_admin;
}

// ==== Dashboard: последние экспрессы ====
async function loadDashboard() {
  await loadAccount();
  const { status, data } = await apiPost("/api/history");
  const container = document.getElementById("dash-history-list");
  if (status !== 200 || !data.ok || data.items.length === 0) {
    container.innerHTML = `<div class="empty-hint">Пока нет собранных экспрессов</div>`;
    return;
  }
  container.innerHTML = data.items.slice(0, 3).map(renderHistoryItem).join("");
}

document.getElementById("goto-history").addEventListener("click", () => goTab("history"));
document.getElementById("open-express-btn").addEventListener("click", () => {
  openSub("express");
  resetExpressScreen();
});

// ==== История (полная) ====
function renderHistoryItem(item) {
  const total = item.total_odds ? `x${item.total_odds}` : "?";
  return `
    <div class="list-item">
      <div class="list-item__top">
        <span class="list-item__title">${fmtDate(item.created_at)} · ${item.legs_count} событий</span>
        <span class="list-item__badge">${total}</span>
      </div>
      <div class="list-item__sub">Цель x${item.target_odds}</div>
    </div>
  `;
}

async function loadHistory() {
  const container = document.getElementById("history-list");
  container.innerHTML = `<div class="empty-hint">Загрузка…</div>`;
  const { status, data } = await apiPost("/api/history");
  if (status !== 200 || !data.ok || data.items.length === 0) {
    container.innerHTML = `<div class="empty-hint">Пока нет собранных экспрессов</div>`;
    return;
  }
  container.innerHTML = data.items.map(renderHistoryItem).join("");
}

// ==== Реферальная вкладка ====
async function loadReferral() {
  await loadAccount();
  if (!account) return;

  document.getElementById("ref-link").textContent = account.referral_link || "—";
  document.getElementById("ref-invited").textContent = account.referral_invited ?? 0;
  document.getElementById("ref-rewarded").textContent = account.referral_rewarded ?? 0;
  document.getElementById("ref-bonus-days").textContent = `+${account.referral_bonus_days ?? 7} дней`;
}

document.getElementById("ref-copy-btn").addEventListener("click", () => {
  if (!account?.referral_link) return;
  navigator.clipboard?.writeText(account.referral_link).then(() => {
    tg?.HapticFeedback?.notificationOccurred?.("success");
    const btn = document.getElementById("ref-copy-btn");
    const original = btn.textContent;
    btn.textContent = "Скопировано";
    setTimeout(() => { btn.textContent = original; }, 1500);
  });
});

// ==== Профиль: меню ====
document.getElementById("menu-subscription").addEventListener("click", () => {
  openSub("subscription");
  loadSubscription();
});
document.getElementById("menu-admin").addEventListener("click", () => {
  openSub("admin");
  loadAdmin();
});

// ==== Экспресс: пикер + генерация ====
const oddsPicker = document.getElementById("express-picker");
const oddsGenerating = document.getElementById("express-generating");
const oddsResult = document.getElementById("express-result");
const oddsErrorBox = document.getElementById("express-error");
const customOddsRow = document.getElementById("custom-odds-row");
const customOddsInput = document.getElementById("custom-odds-input");

let lastTargetOdds = null;

function resetExpressScreen() {
  oddsPicker.hidden = false;
  oddsGenerating.hidden = true;
  oddsResult.hidden = true;
  oddsErrorBox.hidden = true;
  customOddsRow.hidden = true;
}

document.querySelectorAll(".odds-chip[data-odds]").forEach((btn) => {
  btn.addEventListener("click", () => {
    tg?.HapticFeedback?.impactOccurred?.("light");
    runExpress(parseFloat(btn.dataset.odds));
  });
});

document.getElementById("odds-custom-btn").addEventListener("click", () => {
  customOddsRow.hidden = !customOddsRow.hidden;
  if (!customOddsRow.hidden) customOddsInput.focus();
});

document.getElementById("custom-odds-go").addEventListener("click", () => {
  const val = parseFloat(customOddsInput.value.replace(",", "."));
  if (!val || val <= 1) { customOddsInput.focus(); return; }
  runExpress(val);
});

document.getElementById("express-regenerate").addEventListener("click", () => {
  if (lastTargetOdds) runExpress(lastTargetOdds);
});
document.getElementById("express-done").addEventListener("click", () => {
  closeSub();
  loadDashboard();
});
document.getElementById("express-error-retry").addEventListener("click", () => {
  if (lastTargetOdds) runExpress(lastTargetOdds);
  else resetExpressScreen();
});

async function runExpress(targetOdds) {
  lastTargetOdds = targetOdds;
  oddsPicker.hidden = true;
  oddsResult.hidden = true;
  oddsErrorBox.hidden = true;
  oddsGenerating.hidden = false;

  const { status, data } = await apiPost("/api/express", { target_odds: targetOdds });

  if (status === 200 && data.ok) {
    renderExpressResult(data);
    oddsGenerating.hidden = true;
    oddsResult.hidden = false;
    tg?.HapticFeedback?.notificationOccurred?.("success");
    return;
  }

  const messages = {
    subscription_required: "Бесплатная попытка уже использована. Оформи подписку в разделе Профиль.",
    no_events: "Сейчас нет доступных событий. Попробуй чуть позже.",
    no_combo_found: `Не получилось собрать под x${targetOdds}. Попробуй другой коэффициент.`,
    unauthorized: "Не удалось подтвердить пользователя. Перезапусти мини-приложение.",
  };
  document.getElementById("express-error-text").textContent = messages[data.error] || "Что-то пошло не так.";
  oddsGenerating.hidden = true;
  oddsErrorBox.hidden = false;
  tg?.HapticFeedback?.notificationOccurred?.("error");
}

function renderExpressResult(data) {
  const picksContainer = document.getElementById("express-picks");
  picksContainer.innerHTML = data.combo.map((leg, i) => `
    <div class="pick-card" style="animation-delay:${i * 0.05}s">
      <div class="pick-card__league">${escapeHtml(leg.sport || "")}</div>
      <div class="pick-card__row">
        <span class="pick-card__match">${escapeHtml(leg.match)}</span>
        <span class="pick-card__odds">x${leg.odds}</span>
      </div>
      <div class="pick-card__pick">${escapeHtml(leg.outcome)}</div>
    </div>
  `).join("");

  document.getElementById("express-total").textContent = `x${data.total_odds}`;
}

// ==== Подписка ====
async function loadSubscription() {
  const container = document.getElementById("subscription-content");
  container.innerHTML = `<div class="empty-hint">Загрузка…</div>`;

  await loadAccount();
  if (account?.subscribed) {
    container.innerHTML = `
      <div class="plan-card plan-card--active">
        <div class="plan-card__name">Подписка активна</div>
        <div class="plan-card__price">до ${fmtDate(account.expires_at)}</div>
        <div class="plan-card__feature"><span>✓</span>Безлимит экспрессов</div>
      </div>
    `;
    return;
  }

  const { status, data } = await apiPost("/api/subscribe");
  if (status !== 200 || !data.ok) {
    container.innerHTML = `<div class="empty-hint">Не удалось создать счёт на оплату. Попробуй позже.</div>`;
    return;
  }

  container.innerHTML = `
    <div class="plan-card plan-card--active">
      <div class="plan-card__name">Подписка на ${data.days} дней</div>
      <div class="plan-card__price">${data.price} ${data.asset}</div>
      <div class="plan-card__feature"><span>✓</span>Безлимит экспрессов</div>
      <div class="plan-card__feature"><span>✓</span>Приоритетная поддержка</div>
    </div>
    <button class="btn-primary" id="pay-btn" style="margin-bottom:12px;">Оплатить</button>
    <button class="btn-secondary" id="check-pay-btn" style="width:100%;">Я оплатил, проверить</button>
    <div class="pay-status" id="pay-status"></div>
  `;

  document.getElementById("pay-btn").addEventListener("click", () => {
    tg?.openLink ? tg.openLink(data.pay_url) : window.open(data.pay_url, "_blank");
  });

  document.getElementById("check-pay-btn").addEventListener("click", async () => {
    const statusEl = document.getElementById("pay-status");
    statusEl.textContent = "Проверяю…";
    const res = await apiPost("/api/check_payment", { invoice_id: data.invoice_id });
    if (res.status === 200 && res.data.ok && res.data.paid) {
      statusEl.textContent = `✅ Оплачено! Активна до ${fmtDate(res.data.expires_at)}`;
      tg?.HapticFeedback?.notificationOccurred?.("success");
      await loadAccount();
      applyAccountToUI();
    } else {
      statusEl.textContent = "Оплата пока не поступила. Попробуй через минуту.";
    }
  });
}

// ==== Админка ====
async function loadAdmin() {
  const { status, data } = await apiPost("/api/admin_stats");
  if (status !== 200 || !data.ok) {
    document.getElementById("admin-grid").innerHTML = `<div class="empty-hint">Нет доступа</div>`;
    return;
  }

  document.getElementById("admin-grid").innerHTML = `
    <div class="admin-card"><div class="admin-card__label">Пользователей</div><div class="admin-card__value">${data.total_users}</div></div>
    <div class="admin-card"><div class="admin-card__label">Активны сегодня</div><div class="admin-card__value">${data.active_today}</div></div>
    <div class="admin-card"><div class="admin-card__label">Активны за неделю</div><div class="admin-card__value">${data.active_week}</div></div>
    <div class="admin-card"><div class="admin-card__label">Экспрессов всего</div><div class="admin-card__value">${data.total_express}</div></div>
  `;

  const topContainer = document.getElementById("admin-top-users");
  if (!data.top_users.length) {
    topContainer.innerHTML = `<div class="empty-hint">Пока нет данных</div>`;
  } else {
    topContainer.innerHTML = data.top_users.map((u) => `
      <div class="row-item">
        <span>${escapeHtml(u.username ? "@" + u.username : "id" + u.user_id)}</span>
        <span class="row-item__accent">${u.count} экспрессов</span>
      </div>
    `).join("");
  }
}

// ==== Старт ====
render();
loadDashboard();
