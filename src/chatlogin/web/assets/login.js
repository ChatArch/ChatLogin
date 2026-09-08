(() => {
  const root = document.querySelector(".chatlogin");
  if (!root) return;
  const form = root.querySelector("form");
  const status = root.querySelector(".chatlogin__status");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (status) status.textContent = "";
    const body = {
      username: form.elements.username.value,
      password: form.elements.password.value,
      next: root.dataset.next || "/",
    };
    const response = await fetch(root.dataset.loginUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    if (response.ok) {
      const payload = await response.json();
      window.location.assign(payload.next || "/");
      return;
    }
    if (status) status.textContent = "登录失败，请检查账号或密码。";
  });
})();
