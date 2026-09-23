(() => {
  const navButton = document.querySelector(".nav-toggle");
  const nav = document.querySelector("#site-nav");
  navButton?.addEventListener("click", () => {
    const open = nav.toggleAttribute("data-open");
    navButton.setAttribute("aria-expanded", String(open));
  });
  nav?.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => {
    nav.removeAttribute("data-open");
    navButton?.setAttribute("aria-expanded", "false");
  }));
  const headless = document.querySelector("#headless-login");
  if (headless) {
    const form = headless.querySelector("form");
    const status = headless.querySelector(".form-status");
    headless.querySelector("[data-fill-demo]")?.addEventListener("click", (event) => {
      form.elements.username.value = event.currentTarget.dataset.username;
      form.elements.password.value = event.currentTarget.dataset.password;
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); status.textContent = "校验中…";
      try {
        const current = await fetch("/demo/async/session", {credentials:"same-origin"});
        if (!current.ok) throw new Error("无法读取当前会话");
        const session = await current.json();
        const headers = {"Content-Type":"application/json"};
        if (session.authenticated && session.csrf_token) headers["X-CSRF-Token"] = session.csrf_token;
        const response = await fetch("/demo/async/login", {method:"POST",credentials:"same-origin",headers,body:JSON.stringify({username:form.elements.username.value,password:form.elements.password.value,next:headless.dataset.return})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "登录失败");
        location.assign(data.next);
      } catch (error) { status.textContent = error.message; form.elements.password.value = ""; }
    });
  }

  const workspace = document.querySelector("[data-workspace]");
  if (workspace) {
    const mode = workspace.dataset.mode;
    const output = workspace.querySelector(".action-output");
    let csrf = null;
    const show = (label, response, body) => { output.textContent = `${label}\nHTTP ${response.status}\n${JSON.stringify(body, null, 2)}`; };
    const session = async () => {
      const response = await fetch(`/demo/${mode}/session`, {credentials:"same-origin"});
      const body = await response.json(); csrf = body.authenticated ? body.csrf_token : null; return body;
    };
    session().catch(() => { output.textContent = "无法读取会话"; });
    workspace.querySelector("[data-protected]").addEventListener("click", async () => { const r=await fetch(`/api/demo/${mode}/protected`,{credentials:"same-origin"}); show("Protected read",r,await r.json()); });
    workspace.querySelector("[data-csrf]").addEventListener("click", async () => { await session(); const r=await fetch(`/api/demo/${mode}/csrf-check`,{method:"POST",credentials:"same-origin",headers:{"X-CSRF-Token":csrf||""}}); show("CSRF-protected action",r,await r.json()); });
    workspace.querySelector("[data-bad-csrf]").addEventListener("click", async () => { const r=await fetch(`/api/demo/${mode}/csrf-check`,{method:"POST",credentials:"same-origin",headers:{"X-CSRF-Token":"intentional-failure"}}); show("Intentional CSRF failure",r,await r.json()); });
    workspace.querySelector("[data-logout]").addEventListener("click", async () => { await session(); const r=await fetch(`/demo/${mode}/logout`,{method:"POST",credentials:"same-origin",headers:{"X-CSRF-Token":csrf||""}}); const b=await r.json(); show("Logout",r,b); if(r.ok) setTimeout(()=>location.reload(),450); });
  }

  const playground = document.querySelector("[data-playground]");
  if (playground) {
    const frame = playground.querySelector("iframe");
    const config = playground.querySelector("[data-config]");
    const openPreview = playground.querySelector("[data-open-preview]");
    const values = () => ({palette:playground.querySelector('[name="palette"]').value, layout:playground.querySelector('[name="layout"]').value, appearance:playground.querySelector('[name="appearance"]').value, guest:playground.querySelector('[name="guest"]').checked});
    const snippet = (v) => `LoginUI(\n    palette="${v.palette}",\n    layout="${v.layout}",\n    appearance="${v.appearance}",${v.guest?'\n    guest_url="/guest",':''}\n)`;
    const previewURL = (v) => `/playground/preview?palette=${v.palette}&layout=${v.layout}&appearance=${v.appearance}&guest=${v.guest?1:0}`;
    const paint = (v) => {
      const root = frame.contentDocument?.querySelector(".chatlogin");
      if (!root) return false;
      root.dataset.palette=v.palette; root.dataset.layout=v.layout; root.dataset.appearance=v.appearance;
      let guest = root.querySelector(".chatlogin__guest");
      if (v.guest && !guest) {
        guest=frame.contentDocument.createElement("a"); guest.className="chatlogin__guest"; guest.href="/guest?mode=password"; guest.textContent="以访客身份继续";
        root.querySelector(".chatlogin__form-panel").append(guest);
      } else if (!v.guest && guest) { guest.remove(); }
      return true;
    };
    const update = () => {
      const v=values(); config.textContent=snippet(v); openPreview.href=previewURL(v);
      if (!paint(v)) frame.src=previewURL(v);
    };
    frame.addEventListener("load",()=>paint(values()));
    playground.querySelectorAll("select,input").forEach(control=>control.addEventListener("change",update));
    config.textContent=snippet(values()); openPreview.href=previewURL(values());
    playground.querySelector("[data-copy]").addEventListener("click",async()=>{
      try { await navigator.clipboard.writeText(config.textContent); playground.querySelector(".copy-status").textContent="已复制"; }
      catch { playground.querySelector(".copy-status").textContent="请展开代码手动复制"; }
    });
  }
})();
