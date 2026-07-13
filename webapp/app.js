// ==== Настройка ====
// Замени на публичный домен своего бэкенда на Railway, например:
// const API_BASE = "https://expressbot-production.up.railway.app";
const API_BASE = "https://ЗАМЕНИ_НА_СВОЙ_RAILWAY_ДОМЕН";

// ==== Telegram WebApp init ====
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("#08090d");
  tg.setBackgroundColor?.("#08090d");
}

const initData = tg?.initData || "";

// ==== Утилиты переходов между экранами ====
const screens = {
  picker: document.getElementById("screen-picker"),
  loading: document.getElementById("screen-loading"),
  result: document.getElementById("screen-result"),
  error: document.getElementById("screen-error"),
};

function showScreen(name) {
  Object.values(screens).forEach((el) => {
    el.classList.remove("is-active");
    el.hidden = true;
  });
  const target = screens[name];
  target.hidden = false;
  // небольшая задержка нужна, чтобы браузер применил hidden=false
  // до включения transition-класса — иначе анимация не сыграет
  requestAnimationFrame(() => {
    requestAnimationFrame(() => target.classList.add("is-active"));
  });
}

// ==== API-клиент ====
async function apiPost(path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initData, ...body }),
  });
  const data = await resp.json().catch(() => ({}));
  return { status: resp.status, data };
}

// ==== Экран выбора коэффициента ====
const oddsGrid = document.getElementById("odds-grid");
const customBtn = document.getElementById("custom-btn");
const customInput = document.getElementById("custom-input");
const customValue = document.getElementById("custom-value");
const customSubmit = document.getElementById("custom-submit");
const accountLine = document.getElementById("account-line");

oddsGrid.querySelectorAll(".odds-btn[data-odds]").forEach((btn) => {
  btn.addEventListener("click", () => {
    tg?.HapticFeedback?.impactOccurred?.("light");
    requestExpress(parseFloat(btn.dataset.odds));
  });
});

customBtn.addEventListener("click", () => {
  tg?.HapticFeedback?.impactOccurred?.("light");
  customInput.hidden = !customInput.hidden;
  if (!customInput.hidden) customValue.focus();
});

customSubmit.addEventListener("click", () => {
  const val = parseFloat(customValue.value.replace(",", "."));
  if (!val || val <= 1) {
    customValue.focus();
    return;
  }
  requestExpress(val);
});

// ==== Экран результата ====
const resultCount = document.getElementById("result-count");
const resultTotal = document.getElementById("result-total");
const legsContainer = document.getElementById("legs");
document.getElementById("new-express-btn").addEventListener("click", () => showScreen("picker"));

// ==== Экран ошибки ====
const errorText = document.getElementById("error-text");
let lastTargetOdds = null;
document.getElementById("error-retry-btn").addEventListener("click", () => {
  if (lastTargetOdds) requestExpress(lastTargetOdds);
  else showScreen("picker");
});

// ==== Основной поток ====
async function requestExpress(targetOdds) {
  lastTargetOdds = targetOdds;
  showScreen("loading");

  const { status, data } = await apiPost("/api/express", { target_odds: targetOdds });

  if (status === 200 && data.ok) {
    renderResult(data);
    showScreen("result");
    tg?.HapticFeedback?.notificationOccurred?.("success");
    return;
  }

  const messages = {
    subscription_required: "Бесплатная попытка уже использована. Оформи подписку командой /subscribe в чате с ботом.",
    no_events: "Сейчас нет доступных событий. Попробуй чуть позже.",
    no_combo_found: `Не получилось собрать под x${targetOdds}. Попробуй другой коэффициент.`,
    unauthorized: "Не удалось подтвердить пользователя. Перезапусти мини-приложение из чата с ботом.",
  };
  errorText.textContent = messages[data.error] || "Что-то пошло не так. Попробуй ещё раз.";
  showScreen("error");
  tg?.HapticFeedback?.notificationOccurred?.("error");
}

function renderResult(data) {
  resultCount.textContent = `${data.combo.length} событий`;
  resultTotal.textContent = `x${data.total_odds}`;

  legsContainer.innerHTML = "";
  data.combo.forEach((leg, i) => {
    const card = document.createElement("div");
    card.className = "leg-card";
    card.style.animationDelay = `${i * 0.05}s`;
    card.innerHTML = `
      <div class="leg-card__sport">${escapeHtml(leg.sport || "")}</div>
      <div class="leg-card__match">${escapeHtml(leg.match)}</div>
      <div class="leg-card__detail">
        <span>${escapeHtml(leg.outcome)}</span>
        <span class="leg-card__odds">x${leg.odds}</span>
      </div>
    `;
    legsContainer.appendChild(card);
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ==== Загрузка информации об аккаунте на старте ====
async function loadAccount() {
  if (!initData) {
    accountLine.textContent = "Открой мини-приложение из Telegram-бота";
    return;
  }
  const { status, data } = await apiPost("/api/account", {});
  if (status === 200 && data.ok) {
    if (data.subscribed) {
      accountLine.innerHTML = `Подписка активна до <strong>${new Date(data.expires_at).toLocaleDateString("ru-RU")}</strong>`;
    } else if (data.free_trial_remaining > 0) {
      accountLine.innerHTML = `Доступна <strong>${data.free_trial_remaining}</strong> бесплатная попытка`;
    } else {
      accountLine.innerHTML = `Оформи подписку через /subscribe в чате с ботом`;
    }
  }
}

// ==== Старт ====
showScreen("picker");
loadAccount();
