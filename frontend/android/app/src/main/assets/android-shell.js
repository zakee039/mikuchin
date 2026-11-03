/* Injected by Mikuchin Android WebView client at runtime. frontend/web on disk remains untouched. */
(function () {
  "use strict";
  if (window.__mikuchinAndroidShellLoaded) return;
  window.__mikuchinAndroidShellLoaded = true;

  // Enforce original light theme
  try {
    localStorage.setItem("strata.theme", "light");
  } catch {}
  document.documentElement.dataset.theme = "light";

  const TAB_TITLES = {
    chat: "Mikuchin",
    images: "图像",
    characters: "角色",
    settings: "设置",
    monitor: "监控",
    about: "关于"
  };

  function setDrawerOpen(open) {
    const sidebar = document.getElementById("session-sidebar");
    const backdrop = document.getElementById("session-backdrop");
    const ctrlBtn = document.getElementById("mk-android-ctrl-btn");
    if (!sidebar || !backdrop) return;
    sidebar.hidden = false;
    sidebar.classList.remove("collapsed");
    sidebar.classList.toggle("mobile-open", open);
    backdrop.hidden = !open;
    if (ctrlBtn) ctrlBtn.setAttribute("aria-expanded", String(open));
  }

  function updateTopBarAndNav() {
    document.documentElement.dataset.theme = "light";
    const activeTab = typeof tab !== "undefined" ? tab : "chat";
    document.body.dataset.activeTab = activeTab;
    const titleEl = document.getElementById("mk-android-title");
    if (titleEl) {
      if (activeTab === "chat") {
        const selected = document.querySelector("#session-history .session-row.selected .session-title");
        titleEl.textContent = selected ? selected.textContent : "Mikuchin";
      } else {
        titleEl.textContent = TAB_TITLES[activeTab] || "Mikuchin";
      }
    }
    document.querySelectorAll(".mk-android-nav-btn").forEach((btn) => {
      if (btn.dataset.targetTab === activeTab) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    if (activeTab === "settings") {
      refreshTailscaleSettingsCard();
    }
  }

  let latestAuthUrl = "";

  function renderTailscaleSettingsCard(raw) {
    const stateEl = document.getElementById("mk-ts-state");
    const nodeEl = document.getElementById("mk-ts-node");
    const ipEl = document.getElementById("mk-ts-ip");
    const authBtn = document.getElementById("mk-ts-open-auth");
    if (!stateEl || !nodeEl || !ipEl || !raw) return;

    let st = raw;
    if (typeof raw === "string") {
      try { st = JSON.parse(raw); } catch { return; }
    }
    const state = st.state || "Stopped";
    latestAuthUrl = st.authUrl || "";
    nodeEl.textContent = st.hostname || "mikuchin-android";
    ipEl.textContent = st.tailscaleIp || "—";

    if (state === "Running") {
      stateEl.textContent = "已连接";
    } else if (state === "NeedsLogin" || latestAuthUrl) {
      stateEl.textContent = "等待授权";
    } else if (state === "Starting") {
      stateEl.textContent = "连接中...";
    } else if (state === "Error") {
      stateEl.textContent = "失败" + (st.error ? " (" + st.error + ")" : "");
    } else {
      stateEl.textContent = "未连接";
    }

    if (authBtn) {
      authBtn.style.display = latestAuthUrl && state !== "Running" ? "inline-flex" : "none";
    }
  }

  function refreshTailscaleSettingsCard() {
    if (window.MikuchinAndroid && window.MikuchinAndroid.getTailscaleStatus) {
      renderTailscaleSettingsCard(window.MikuchinAndroid.getTailscaleStatus());
    }
  }

  window.onTailscaleStatus = (statusJson) => {
    renderTailscaleSettingsCard(statusJson);
  };

  function initAndroidShell() {
    document.documentElement.dataset.theme = "light";
    const darkToggle = document.getElementById("dark-toggle");
    if (darkToggle) {
      const toggleRow = darkToggle.closest(".st-toggle-row");
      if (toggleRow) toggleRow.style.display = "none";
    }

    const main = document.querySelector("main");
    const sidebar = document.getElementById("session-sidebar");
    const backdrop = document.getElementById("session-backdrop");
    if (!main || !sidebar || !backdrop) return;

    // 1. Lift #session-backdrop and #session-sidebar to <main> so the drawer works across all views
    if (sidebar.parentElement !== main) {
      main.insertBefore(backdrop, main.firstChild);
      main.insertBefore(sidebar, backdrop.nextSibling);
    }
    sidebar.hidden = false;

    // 2. Create persistent top-left control bar above <main>
    if (!document.getElementById("mk-android-topbar")) {
      const topbar = document.createElement("div");
      topbar.id = "mk-android-topbar";
      topbar.innerHTML =
        '<button type="button" id="mk-android-ctrl-btn" aria-label="打开控制栏" aria-expanded="false">☰ <span data-i18n-ignore>历史</span></button>' +
        '<span id="mk-android-title" data-i18n-ignore>Mikuchin</span>' +
        '<button type="button" id="mk-android-new-btn" data-i18n-ignore>＋ 新对话</button>';
      main.parentNode.insertBefore(topbar, main);

      document.getElementById("mk-android-ctrl-btn").onclick = () => {
        setDrawerOpen(!sidebar.classList.contains("mobile-open"));
      };
      document.getElementById("mk-android-new-btn").onclick = () => {
        if (typeof showTab === "function") showTab("chat");
        document.getElementById("new-btn")?.click();
        setDrawerOpen(false);
      };
    }

    backdrop.onclick = () => setDrawerOpen(false);
    const toggleBtn = document.getElementById("sidebar-toggle");
    if (toggleBtn) toggleBtn.onclick = () => setDrawerOpen(false);

    // 3. Create bottom 5 navigation buttons inside #session-sidebar: 图像, 角色, 设置, 监控, 关于 (borderless)
    if (!document.getElementById("mk-android-drawer-nav")) {
      const nav = document.createElement("nav");
      nav.id = "mk-android-drawer-nav";
      nav.setAttribute("aria-label", "功能导航");
      const items = [
        ["images", "i-image", "图像"],
        ["characters", "i-character", "角色"],
        ["settings", "i-settings", "设置"],
        ["monitor", "i-activity", "监控"],
        ["about", "i-info", "关于"]
      ];
      nav.innerHTML = items.map(([id, icon, label]) =>
        `<button type="button" class="mk-android-nav-btn" data-target-tab="${id}">` +
        `<svg class="st-icon st-icon--sm"><use href="web/sprite.svg#${icon}"/></svg>` +
        `<span data-i18n-ignore>${label}</span></button>`
      ).join("");
      sidebar.appendChild(nav);

      nav.querySelectorAll(".mk-android-nav-btn").forEach((btn) => {
        btn.onclick = () => {
          const target = btn.dataset.targetTab;
          if (target && typeof showTab === "function") showTab(target);
          setDrawerOpen(false);
          updateTopBarAndNav();
        };
      });
    }

    // 4. Clicking any historical chat in #session-history switches back to Chat view and closes drawer
    const histBox = document.getElementById("session-history");
    if (histBox && !histBox.dataset.androidBound) {
      histBox.dataset.androidBound = "1";
      histBox.addEventListener("click", (e) => {
        const titleBtn = e.target.closest(".session-title");
        if (titleBtn) {
          if (typeof showTab === "function") showTab("chat");
          setDrawerOpen(false);
          setTimeout(updateTopBarAndNav, 120);
        }
      });
    }

    const newBtn = document.getElementById("new-btn");
    if (newBtn && !newBtn.dataset.androidBound) {
      newBtn.dataset.androidBound = "1";
      newBtn.addEventListener("click", () => {
        if (typeof showTab === "function") showTab("chat");
        setDrawerOpen(false);
        setTimeout(updateTopBarAndNav, 120);
      });
    }

    // 5. Wrap showTab so topbar & active nav button stay synced
    if (typeof window.showTab === "function" && !window.showTab.__androidWrapped) {
      const origShowTab = window.showTab;
      const wrapped = function (name) {
        const res = origShowTab.apply(this, arguments);
        updateTopBarAndNav();
        return res;
      };
      wrapped.__androidWrapped = true;
      window.showTab = wrapped;
    }

    // 6. Add 接口 & Reconnect / Disconnect controls + Tailscale management card to Settings (#view-settings)
    const apiKeyInput = document.getElementById("api-key");
    if (apiKeyInput && !document.getElementById("mk-android-endpoint")) {
      const card = apiKeyInput.closest(".st-card");
      const keyField = apiKeyInput.closest(".st-field");
      if (card && keyField) {
        const epField = document.createElement("div");
        epField.className = "st-field";
        epField.innerHTML =
          '<label class="st-label" for="mk-android-endpoint" data-i18n-ignore>接口</label>' +
          '<input class="st-input" id="mk-android-endpoint" type="text" inputmode="url" autocapitalize="none" spellcheck="false" autocomplete="off">';
        card.insertBefore(epField, keyField);

        const epInput = document.getElementById("mk-android-endpoint");
        epInput.value = (window.MikuchinAndroid && window.MikuchinAndroid.getSavedEndpoint()) || location.origin;

        const actions = document.createElement("div");
        actions.className = "mk-android-conn-actions";
        actions.innerHTML =
          '<button type="button" class="st-btn st-btn--primary" id="mk-android-reconnect" data-i18n-ignore>保存并重连</button>' +
          '<button type="button" class="st-btn st-btn--secondary" id="mk-android-disconnect" data-i18n-ignore>断开连接</button>';
        keyField.insertAdjacentElement("afterend", actions);

        document.getElementById("mk-android-reconnect").onclick = () => {
          const ep = epInput.value.trim();
          const key = apiKeyInput.value.trim();
          if (window.MikuchinAndroid) window.MikuchinAndroid.connectEndpoint(ep, key);
        };
        document.getElementById("mk-android-disconnect").onclick = () => {
          if (window.MikuchinAndroid) window.MikuchinAndroid.disconnect();
        };

        // Tailscale management section
        const tsCard = document.createElement("div");
        tsCard.className = "st-card";
        tsCard.id = "mk-android-ts-card";
        tsCard.innerHTML =
          '<div class="st-card__title" data-i18n-ignore>Tailscale 网络</div>' +
          '<div class="mk-ts-kv"><span data-i18n-ignore>节点名</span><span id="mk-ts-node" data-i18n-ignore>mikuchin-android</span></div>' +
          '<div class="mk-ts-kv"><span data-i18n-ignore>Tailscale IP</span><span id="mk-ts-ip" data-i18n-ignore>—</span></div>' +
          '<div class="mk-ts-kv"><span data-i18n-ignore>连接状态</span><span id="mk-ts-state" data-i18n-ignore>未连接</span></div>' +
          '<div class="mk-android-conn-actions">' +
          '<button type="button" class="st-btn st-btn--primary" id="mk-ts-reconnect" data-i18n-ignore>重新连接</button>' +
          '<button type="button" class="st-btn st-btn--secondary" id="mk-ts-open-auth" style="display:none" data-i18n-ignore>打开授权页</button>' +
          '<button type="button" class="st-btn st-btn--secondary" id="mk-ts-logout" data-i18n-ignore>退出登录</button>' +
          '</div>';
        card.insertAdjacentElement("afterend", tsCard);

        document.getElementById("mk-ts-reconnect").onclick = () => {
          if (window.MikuchinAndroid && window.MikuchinAndroid.reconnectTailscale) {
            renderTailscaleSettingsCard(window.MikuchinAndroid.reconnectTailscale());
          }
        };
        document.getElementById("mk-ts-open-auth").onclick = () => {
          if (latestAuthUrl && window.MikuchinAndroid && window.MikuchinAndroid.openAuthUrl) {
            window.MikuchinAndroid.openAuthUrl(latestAuthUrl);
          }
        };
        document.getElementById("mk-ts-logout").onclick = () => {
          if (window.MikuchinAndroid && window.MikuchinAndroid.logoutTailscale) {
            renderTailscaleSettingsCard(window.MikuchinAndroid.logoutTailscale());
          }
        };

        refreshTailscaleSettingsCard();
      }
    }

    updateTopBarAndNav();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAndroidShell);
  } else {
    initAndroidShell();
  }
})();
