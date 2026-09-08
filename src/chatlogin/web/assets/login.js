(() => {
  const root = document.querySelector(".chatlogin");
  if (!root) return;
  const form = root.querySelector("form");
  const status = root.querySelector(".chatlogin__status");
  if (!form) return;
  let submitting = false;
  const localURL = (value) => {
    if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || /[\\\s]/.test(value)) {
      throw new Error("登录配置不可用，请联系网站管理员。");
    }
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin) throw new Error("登录配置不可用，请联系网站管理员。");
    return url.href;
  };
  const failure = (response) => {
    if (response.status === 401) return "登录失败，请检查账号或密码。";
    if (response.status === 429) return "登录尝试过于频繁，请稍后重试。";
    if (response.status === 403) return "会话已变化，请重新尝试登录。";
    return "登录服务暂时不可用，请稍后重试。";
  };
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    const buttons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
    const disabled = buttons.map(button => button.disabled);
    buttons.forEach(button => { button.disabled = true; });
    form.setAttribute("aria-busy", "true");
    if (status) status.textContent = "正在登录…";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      // Fetch fresh CSRF even with an existing HttpOnly session cookie.
      // Keep it only in this submission's memory; never persist credentials.
      const sessionResponse = await fetch(localURL(root.dataset.sessionUrl), {
        credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal,
      });
      if (!sessionResponse.ok) throw new Error(failure(sessionResponse));
      const session = await sessionResponse.json();
      const headers = {"Content-Type": "application/json"};
      if (session && typeof session.csrf_token === "string") headers["X-CSRF-Token"] = session.csrf_token;
      const response = await fetch(localURL(root.dataset.loginUrl), {
        method: "POST", headers, credentials: "same-origin", cache: "no-store",
        redirect: "error", signal: controller.signal,
        body: JSON.stringify({
          username: form.elements.username.value,
          password: form.elements.password.value,
          next: root.dataset.next || "/",
        }),
      });
      if (!response.ok) throw new Error(failure(response));
      const payload = await response.json();
      form.elements.password.value = "";
      window.location.assign(localURL(payload.next || "/"));
    } catch (error) {
      if (status) status.textContent = error instanceof TypeError || error.name === "AbortError"
        ? "网络连接失败或超时，请检查网络后重试。"
        : error instanceof SyntaxError ? "登录服务响应异常，请稍后重试。" : error.message;
    } finally {
      clearTimeout(timer);
      submitting = false;
      buttons.forEach((button, index) => { button.disabled = disabled[index]; });
      form.removeAttribute("aria-busy");
    }
  });
})();
