(() => {
  const root = document.querySelector(".chatlogin");
  const form = root?.querySelector("form");
  if (!root || !form) return;
  const match = root.dataset.loginUrl?.match(/^\/demo\/([a-z]+)\/login$/);
  const mode = match?.[1];
  if (mode && (!root.dataset.next || root.dataset.next === "/")) root.dataset.next = `/workspace/${mode}`;
  const box = document.createElement("div");
  box.className = "demo-fill";
  box.innerHTML = '<strong>公开演示账号</strong><span>demo / chatlogin-demo · 无业务权限 · 5 分钟会话</span><button type="button" title="Fill Demo">填入 Demo</button>';
  box.querySelector("button").addEventListener("click", () => {
    form.elements.username.value = "demo";
    form.elements.password.value = "chatlogin-demo";
    form.elements.username.focus();
  });
  form.append(box);
})();
