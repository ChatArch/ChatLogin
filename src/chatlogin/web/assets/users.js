(() => {
  "use strict";

  const root = document.querySelector(".chatlogin-users");
  if (!root) return;

  const english = document.documentElement.lang === "en";
  const words = (zh, en) => english ? en : zh;
  const byId = (id) => document.getElementById(id);
  const STALE = Symbol("stale private response");
  const state = { generation: 0, controller: null, csrf: null, user: null };

  const localURL = (value) => {
    if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || /[\\\s]/.test(value)) {
      throw new Error(words("页面配置不可用，请联系网站管理员。", "Page configuration is unavailable. Contact the site administrator."));
    }
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin || url.hash) {
      throw new Error(words("页面配置不可用，请联系网站管理员。", "Page configuration is unavailable. Contact the site administrator."));
    }
    return url;
  };

  const endpoint = Object.freeze({
    login: localURL(root.dataset.loginUrl),
    session: localURL(root.dataset.sessionUrl),
    logout: localURL(root.dataset.logoutUrl),
    users: localURL(root.dataset.usersUrl),
    profile: localURL(root.dataset.profileUrl),
    usersApi: localURL(root.dataset.usersApiUrl),
    profileApi: localURL(root.dataset.profileApiUrl),
    ownerTransferApi: localURL(root.dataset.ownerTransferApiUrl),
  });

  const pathOf = (url) => url.pathname + url.search;
  const setStatus = (message) => {
    const status = byId(root.dataset.page === "users" ? "cl-users-status" : "cl-profile-status");
    if (status) status.textContent = message || "";
  };
  const sameUser = (left, right) => left && right && left.user_id === right.user_id && left.role === right.role;
  const current = (generation) => state.generation === generation && state.controller && !state.controller.signal.aborted;

  const clearPrivateDOM = () => {
    const list = byId("cl-user-list");
    if (list) list.replaceChildren();
    for (const id of ["cl-profile-display-name", "cl-current-password", "cl-new-password", "cl-new-username", "cl-new-display-name", "cl-new-password", "cl-owner-password", "cl-owner-confirm", "cl-owner-target"]) {
      const field = byId(id);
      if (field && "value" in field) field.value = "";
    }
    for (const id of ["cl-current-user", "cl-profile-current-user"]) {
      const label = byId(id);
      if (label) label.textContent = words("会话不可用", "Session unavailable");
    }
  };

  const invalidate = (message) => {
    state.generation += 1;
    if (state.controller) state.controller.abort();
    state.controller = null;
    state.csrf = null;
    state.user = null;
    clearPrivateDOM();
    setStatus(message);
  };

  const beginGeneration = () => {
    if (state.controller) state.controller.abort();
    state.generation += 1;
    state.controller = new AbortController();
    return state.generation;
  };

  const loginDestination = () => {
    const target = root.dataset.page === "users" ? pathOf(endpoint.users) : pathOf(endpoint.profile);
    const destination = new URL(endpoint.login.href);
    destination.searchParams.set("next", target);
    return destination.pathname + destination.search;
  };

  const redirectToLogin = () => {
    window.location.assign(loginDestination());
  };

  const errorMessage = (status) => {
    if (status === 400) return words("提交内容无效，请检查后重试。", "The submitted information is invalid. Check it and try again.");
    if (status === 401) return words("会话已失效，请重新登录。", "Your session has expired. Sign in again.");
    if (status === 403) return words("你没有执行此操作的权限。", "You are not permitted to perform this action.");
    if (status === 404) return words("请求的账号不存在或已不可用。", "The requested account is unavailable.");
    if (status === 409) return words("当前账号状态已变化，请刷新后重试。", "The account changed. Refresh and try again.");
    if (status === 413) return words("提交内容过大。", "The submitted information is too large.");
    if (status === 503) return words("账号服务暂时繁忙，请稍后重试。", "The account service is busy. Try again shortly.");
    return words("账号服务暂时不可用，请稍后重试。", "The account service is temporarily unavailable. Try again shortly.");
  };

  const readJSON = async (response, generation) => {
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      throw new Error(words("账号服务响应异常，请稍后重试。", "The account service returned an invalid response. Try again shortly."));
    }
    if (!current(generation)) throw STALE;
    return payload;
  };

  const privateRequest = async (url, options, generation) => {
    if (!current(generation)) throw STALE;
    const request = options || {};
    const headers = new Headers(request.headers || {});
    const method = (request.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      if (!state.csrf) throw new Error(words("会话已失效，请重新登录。", "Your session has expired. Sign in again."));
      headers.set("X-CSRF-Token", state.csrf);
    }
    const response = await fetch(url.href, {
      ...request,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: state.controller.signal,
    });
    if (!current(generation)) throw STALE;
    if (response.status === 401) {
      invalidate(errorMessage(401));
      throw new Error(errorMessage(401));
    }
    if (!response.ok) throw new Error(errorMessage(response.status));
    return readJSON(response, generation);
  };

  const userApi = (userId) => {
    if (typeof userId !== "string" || !userId) throw new Error(words("账号标识无效。", "Invalid account identifier."));
    return new URL(`${endpoint.usersApi.pathname}/${encodeURIComponent(userId)}`, window.location.origin);
  };

  const setIdentity = (user) => {
    const label = [user.display_name || user.username || user.user_id, `(${user.role})`].join(" ");
    for (const id of ["cl-current-user", "cl-profile-current-user"]) {
      const node = byId(id);
      if (node) node.textContent = label;
    }
    const managementLink = byId("cl-profile-users-link");
    if (managementLink) managementLink.hidden = !["owner", "admin"].includes(user.role);
  };

  const setDisabled = (element, disabled, explanation) => {
    if (!element) return;
    element.disabled = Boolean(disabled);
    if (disabled && explanation) element.title = explanation;
    else element.removeAttribute("title");
  };

  const recordText = (record) => {
    const values = [record.username || record.user_id, record.display_name].filter(Boolean);
    return values.join(" · ") || record.user_id;
  };

  const updateCreationControls = () => {
    const role = byId("cl-new-role");
    const hint = byId("cl-create-user-hint");
    if (!role || !state.user) return;
    const adminOption = Array.from(role.options).find((option) => option.value === "admin");
    if (adminOption) adminOption.disabled = state.user.role !== "owner";
    if (state.user.role !== "owner" && role.value === "admin") role.value = "user";
    if (hint) hint.textContent = state.user.role === "owner"
      ? words("创建后请通过账号目录核对权限与状态。", "Review access and status in the account directory after creation.")
      : words("管理员只能创建普通用户；授予管理员权限需要 owner。", "Administrators can create regular users only; owner access is required to grant administrator access.");
  };

  const appendLabel = (parent, label, control) => {
    const wrapper = document.createElement("label");
    const text = document.createElement("span");
    text.textContent = label;
    wrapper.append(text, control);
    parent.append(wrapper);
    return wrapper;
  };

  const addRecord = (record, generation) => {
    const list = byId("cl-user-list");
    if (!list || !current(generation)) return;
    const article = document.createElement("article");
    article.className = "chatlogin-users__record";

    const heading = document.createElement("div");
    heading.className = "chatlogin-users__record-heading";
    const title = document.createElement("h3");
    title.className = "chatlogin-users__record-title";
    title.textContent = recordText(record);
    const meta = document.createElement("p");
    meta.className = "chatlogin-users__record-meta";
    const accountState = record.deleted === true
      ? words("已删除（保留记录）", "deleted (retained record)")
      : record.enabled ? words("已启用", "enabled") : words("已停用", "disabled");
    meta.textContent = `${record.role || "user"} · ${accountState}`;
    heading.append(title, meta);
    article.append(heading);

    const viewerOwner = state.user && state.user.role === "owner";
    const viewerIsTarget = state.user && state.user.user_id === record.user_id;
    const ordinaryTarget = record.role === "user";
    const deleted = record.deleted === true;
    const canEditDisplay = !deleted && Boolean(viewerOwner || viewerIsTarget);
    const canChangeRole = !deleted && Boolean(viewerOwner && record.role !== "owner");
    const canEnable = !deleted && Boolean((viewerOwner && record.role !== "owner") || (!viewerOwner && ordinaryTarget));
    const canPassword = !deleted && record.role !== "owner" && Boolean(viewerOwner || ordinaryTarget);
    const canDelete = !deleted && Boolean((viewerOwner && record.role !== "owner") || (!viewerOwner && ordinaryTarget));
    const explanation = deleted
      ? words("该账号已删除，仅保留安全记录，不能再修改。", "This account is deleted and retained only as a safe record; it cannot be changed.")
      : viewerOwner
      ? words("owner 不可直接降级、停用或删除；请显式交接。本人改密请前往个人账号。", "An owner cannot be directly demoted, disabled, or deleted; use explicit handoff. Change your own password in My profile.")
      : words("管理员只能管理普通用户及自己的显示名称。", "Administrators can manage regular users and their own display name only.");

    const controls = document.createElement("form");
    controls.className = "chatlogin-users__record-controls";
    controls.noValidate = true;
    const displayName = document.createElement("input");
    displayName.type = "text";
    displayName.value = typeof record.display_name === "string" ? record.display_name : "";
    displayName.autocomplete = "name";
    setDisabled(displayName, !canEditDisplay, explanation);
    appendLabel(controls, words("显示名称", "Display name"), displayName);

    const role = document.createElement("select");
    for (const [value, label] of [["user", words("普通用户", "User")], ["admin", words("管理员", "Administrator")], ["owner", words("Owner", "Owner")]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = value === record.role;
      if (value === "owner") option.disabled = true;
      role.append(option);
    }
    setDisabled(role, !canChangeRole, explanation);
    appendLabel(controls, words("角色", "Role"), role);

    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = record.enabled === true;
    setDisabled(enabled, !canEnable, explanation);
    const enabledLabel = appendLabel(controls, words("允许登录", "Allow sign-in"), enabled);
    enabledLabel.classList.add("chatlogin-users__enabled");

    const actions = document.createElement("div");
    actions.className = "chatlogin-users__record-actions";
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = words("保存", "Save");
    setDisabled(save, !(canEditDisplay || canChangeRole || canEnable), explanation);
    actions.append(save);

    const resetPassword = document.createElement("input");
    resetPassword.type = "password";
    resetPassword.autocomplete = "new-password";
    resetPassword.placeholder = words("设置新密码", "New password");
    resetPassword.setAttribute("aria-label", words("为此账号设置新密码", "Set a new password for this account"));
    setDisabled(resetPassword, !canPassword, explanation);
    actions.append(resetPassword);
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = words("重设密码", "Reset password");
    setDisabled(reset, !canPassword, explanation);
    actions.append(reset);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chatlogin-users__delete";
    remove.textContent = words("删除账号", "Delete account");
    setDisabled(remove, !canDelete, explanation);
    actions.append(remove);
    controls.append(actions);
    article.append(controls);

    const note = document.createElement("p");
    note.className = "chatlogin-users__readonly";
    note.textContent = record.role === "owner" || !(canEditDisplay || canChangeRole || canEnable || canPassword || canDelete) ? explanation : "";
    article.append(note);

    controls.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!current(generation) || save.disabled) return;
      await action(generation, async () => {
        const changes = {};
        if (canEditDisplay) changes.display_name = displayName.value;
        if (canChangeRole) changes.role = role.value;
        if (canEnable) changes.enabled = enabled.checked;
        await privateRequest(userApi(record.user_id), {
          method: "PATCH",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(changes),
        }, generation);
        setStatus(words("账号已更新。", "Account updated."));
        await loadUsers(generation);
      });
    });
    reset.addEventListener("click", async () => {
      if (!current(generation) || reset.disabled) return;
      const value = resetPassword.value;
      resetPassword.value = "";
      if (!value) {
        setStatus(words("请输入新密码。", "Enter a new password."));
        return;
      }
      await action(generation, async () => {
        await privateRequest(new URL(`${userApi(record.user_id).href}/password`), {
          method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({new_password: value}),
        }, generation);
        setStatus(words("密码已重设。", "Password reset."));
      });
    });
    remove.addEventListener("click", async () => {
      if (!current(generation) || remove.disabled) return;
      if (!window.confirm(words("确定要删除此账号吗？该操作会使其无法登录。", "Delete this account? It will no longer be able to sign in."))) return;
      await action(generation, async () => {
        await privateRequest(userApi(record.user_id), {method: "DELETE"}, generation);
        setStatus(words("账号已删除。", "Account deleted."));
        await loadUsers(generation);
      });
    });

    if (viewerOwner && record.role !== "owner" && record.enabled) {
      const handoff = document.createElement("button");
      handoff.type = "button";
      handoff.textContent = words("选择为交接目标", "Choose for ownership handoff");
      handoff.addEventListener("click", () => {
        const target = byId("cl-owner-target");
        const confirm = byId("cl-owner-confirm");
        if (target) target.value = record.user_id;
        if (confirm) confirm.value = "";
        if (confirm) confirm.focus();
        setStatus(words("请明确填写目标用户名并输入当前 owner 密码后确认。", "Explicitly type the target username and current owner password before confirming."));
      });
      actions.append(handoff);
    }
    list.append(article);
  };

  const loadUsers = async (generation) => {
    const payload = await privateRequest(endpoint.usersApi, {}, generation);
    if (!current(generation)) throw STALE;
    if (!payload || !Array.isArray(payload.users)) throw new Error(words("账号服务响应异常，请稍后重试。", "The account service returned an invalid response. Try again shortly."));
    const list = byId("cl-user-list");
    if (!list || !current(generation)) return;
    list.replaceChildren();
    if (!payload.users.length) {
      const empty = document.createElement("p");
      empty.className = "chatlogin-users__empty";
      empty.textContent = words("暂无可显示的账号。", "No accounts are available to display.");
      list.append(empty);
      return;
    }
    payload.users.forEach((record) => addRecord(record, generation));
  };

  const loadProfile = async (generation) => {
    const payload = await privateRequest(endpoint.profileApi, {}, generation);
    if (!current(generation)) throw STALE;
    if (!payload || !payload.user || typeof payload.user !== "object") throw new Error(words("账号服务响应异常，请稍后重试。", "The account service returned an invalid response. Try again shortly."));
    const field = byId("cl-profile-display-name");
    if (field) field.value = typeof payload.user.display_name === "string" ? payload.user.display_name : "";
    setIdentity({...state.user, ...payload.user});
  };

  const action = async (generation, operation) => {
    try {
      await operation();
    } catch (error) {
      if (error === STALE || !current(generation)) return;
      if (error && error.name === "AbortError") return;
      setStatus(error instanceof Error ? error.message : words("操作失败，请稍后重试。", "The action failed. Try again shortly."));
    }
  };

  const bindUsers = (generation) => {
    const refresh = byId("cl-refresh-users");
    if (refresh) refresh.addEventListener("click", () => action(generation, async () => {
      setStatus(words("正在刷新账号目录…", "Refreshing the account directory…"));
      await loadUsers(generation);
      setStatus("");
    }));
    const form = byId("cl-new-user-form");
    if (form) form.addEventListener("submit", (event) => action(generation, async () => {
      event.preventDefault();
      if (!current(generation)) return;
      const username = byId("cl-new-username");
      const displayName = byId("cl-new-display-name");
      const password = byId("cl-new-password");
      const role = byId("cl-new-role");
      const value = password ? password.value : "";
      if (!username || !password || !role || !value) {
        setStatus(words("请填写用户名和初始密码。", "Enter a username and initial password."));
        return;
      }
      password.value = "";
      await privateRequest(endpoint.usersApi, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({username: username.value, password: value, display_name: displayName ? displayName.value : "", role: role.value}),
      }, generation);
      form.reset();
      updateCreationControls();
      setStatus(words("账号已创建。", "Account created."));
      await loadUsers(generation);
    }));

    const transfer = byId("cl-owner-transfer-form");
    if (transfer) transfer.addEventListener("submit", (event) => action(generation, async () => {
      event.preventDefault();
      const target = byId("cl-owner-target");
      const confirm = byId("cl-owner-confirm");
      const password = byId("cl-owner-password");
      if (!target || !confirm || !password || !target.value || !confirm.value || !password.value) {
        setStatus(words("请填写交接目标、确认用户名和当前 owner 密码。", "Enter the target, confirmed username, and current owner password."));
        return;
      }
      const currentPassword = password.value;
      password.value = "";
      await privateRequest(endpoint.ownerTransferApi, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target_user_id: target.value, confirm_username: confirm.value, current_password: currentPassword}),
      }, generation);
      invalidate(words("所有权已交接。请使用新权限重新登录。", "Ownership transferred. Sign in again with the new account permissions."));
      redirectToLogin();
    }));

    const transferPanel = byId("cl-owner-transfer-panel");
    const transferButton = byId("cl-transfer-owner");
    const transferHint = byId("cl-owner-transfer-hint");
    const owner = state.user && state.user.role === "owner";
    if (transferPanel) transferPanel.hidden = false;
    setDisabled(transferButton, !owner, words("仅当前 owner 可以执行交接。", "Only the current owner can transfer ownership."));
    if (transferHint && !owner) transferHint.textContent = words("当前身份不是 owner，不能交接最高权限。", "The current identity is not the owner and cannot transfer ownership.");
    updateCreationControls();
  };

  const bindProfile = (generation) => {
    const profile = byId("cl-profile-form");
    if (profile) profile.addEventListener("submit", (event) => action(generation, async () => {
      event.preventDefault();
      const field = byId("cl-profile-display-name");
      if (!field) return;
      const payload = await privateRequest(endpoint.profileApi, {
        method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({display_name: field.value}),
      }, generation);
      if (payload && payload.user) setIdentity({...state.user, ...payload.user});
      setStatus(words("个人资料已保存。", "Profile saved."));
    }));
    const password = byId("cl-password-form");
    if (password) password.addEventListener("submit", (event) => action(generation, async () => {
      event.preventDefault();
      const currentPassword = byId("cl-current-password");
      const newPassword = byId("cl-new-password");
      if (!currentPassword || !newPassword || !currentPassword.value || !newPassword.value) {
        setStatus(words("请填写当前密码和新密码。", "Enter your current and new passwords."));
        return;
      }
      const currentValue = currentPassword.value;
      const newValue = newPassword.value;
      currentPassword.value = "";
      newPassword.value = "";
      await privateRequest(new URL(`${endpoint.profileApi.href}/password`), {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({current_password: currentValue, new_password: newValue}),
      }, generation);
      invalidate(words("密码已修改。请重新登录。", "Password changed. Sign in again."));
      redirectToLogin();
    }));
  };

  const bindLogout = (generation) => {
    const logout = byId("cl-logout");
    if (!logout) return;
    logout.addEventListener("click", () => action(generation, async () => {
      setDisabled(logout, true);
      try {
        await privateRequest(endpoint.logout, {method: "POST"}, generation);
      } finally {
        invalidate(words("已退出登录。", "Signed out."));
        redirectToLogin();
      }
    }));
  };

  const bootstrap = async () => {
    const previous = state.user;
    const generation = beginGeneration();
    setStatus(words("正在读取账号信息…", "Loading account information…"));
    try {
      const response = await fetch(endpoint.session.href, {
        credentials: "same-origin", cache: "no-store", redirect: "error", signal: state.controller.signal,
      });
      if (!current(generation)) return;
      if (!response.ok) throw new Error(errorMessage(response.status));
      const session = await readJSON(response, generation);
      if (!session || session.authenticated !== true || !session.user || typeof session.csrf_token !== "string") {
        invalidate(words("需要重新登录。", "Sign in is required."));
        redirectToLogin();
        return;
      }
      if (previous && !sameUser(previous, session.user)) clearPrivateDOM();
      state.user = session.user;
      state.csrf = session.csrf_token;
      setIdentity(session.user);
      if (root.dataset.page === "users" && !["owner", "admin"].includes(session.user.role)) {
        invalidate(words("当前身份无权访问用户管理。", "The current identity cannot access user management."));
        window.location.assign(pathOf(endpoint.profile));
        return;
      }
      bindLogout(generation);
      if (root.dataset.page === "users") {
        bindUsers(generation);
        await loadUsers(generation);
      } else {
        bindProfile(generation);
        await loadProfile(generation);
      }
      if (current(generation)) setStatus("");
    } catch (error) {
      if (error === STALE || !current(generation) || (error && error.name === "AbortError")) return;
      invalidate(error instanceof Error ? error.message : words("账号服务暂时不可用。", "The account service is temporarily unavailable."));
    }
  };

  bootstrap();
})();
