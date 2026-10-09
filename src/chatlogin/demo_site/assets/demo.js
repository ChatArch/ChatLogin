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
    const mode=workspace.dataset.mode;
    const output=workspace.querySelector(".action-output");
    const dataOutput=workspace.querySelector(".data-output");
    const expectedUser=workspace.dataset.state==="authenticated" ? workspace.dataset.userId : null;
    let csrf=null, generation=0, invalidating=false;
    const clearPrivate=(message)=>{
      generation++; invalidating=true; output.textContent=""; if(dataOutput)dataOutput.textContent="";
      const name=workspace.querySelector("[data-identity-name]");if(name)name.textContent=message;
      const account=workspace.querySelector("[data-identity-account]");if(account)account.textContent="—";
      workspace.querySelector("[data-identity-details]")?.replaceChildren();
    };
    const identityChanged=()=>{if(invalidating)return;clearPrivate("登录身份已变化");location.reload();};
    const session=async()=>{
      const response=await fetch(`/demo/${mode}/session`,{credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok)throw new Error("无法读取当前会话，请稍后重试。");
      const body=await response.json();
      const actualUser=body.authenticated ? body.user.user_id : null;
      if(actualUser!==expectedUser){identityChanged();throw new Error("登录身份已变化");}
      csrf=body.authenticated?body.csrf_token:null;return body;
    };
    const show=(target,label,response,body)=>{target.textContent=`${label}\nHTTP ${response.status}\n${JSON.stringify(body,null,2)}`;};
    const run=async(target,label,path,method="GET",badCSRF=false)=>{
      if(invalidating)return;
      const epoch=generation;
      try{
        await session();if(epoch!==generation)return;
        const headers={};if(method!=="GET")headers["X-CSRF-Token"]=badCSRF?"intentional-failure":csrf||"";
        const response=await fetch(path,{method,credentials:"same-origin",cache:"no-store",redirect:"error",headers});
        const body=await response.json();if(epoch!==generation)return;
        const returnedUser=body.user_id || body.user?.user_id;
        if(returnedUser && returnedUser!==expectedUser){identityChanged();return;}
        show(target,label,response,body);
      }catch(error){if(epoch===generation)target.textContent=error.message||"请求失败，请重试。";}
    };
    const resource=(key)=>{
      const id=workspace.dataset[key];
      if(!id){dataOutput.textContent="请先登录演示用户A或B，再验证数据隔离。";return null;}
      return `/api/demo/${mode}/records/${encodeURIComponent(id)}`;
    };
    workspace.querySelector("[data-own-records]")?.addEventListener("click",()=>run(dataOutput,"读取本人数据",`/api/demo/${mode}/records`));
    workspace.querySelector("[data-touch-own]")?.addEventListener("click",()=>{const path=resource("myRecord");if(path)run(dataOutput,"修改本人样例（修订号+1）",path+"/touch","POST");});
    workspace.querySelector("[data-read-other]")?.addEventListener("click",()=>{const path=resource("otherRecord");if(path)run(dataOutput,"以当前身份读取另一用户数据",path);});
    workspace.querySelector("[data-touch-other]")?.addEventListener("click",()=>{const path=resource("otherRecord");if(path)run(dataOutput,"以当前身份修改另一用户数据",path+"/touch","POST");});
    workspace.querySelector("[data-protected]")?.addEventListener("click",()=>run(output,"受保护读取",`/api/demo/${mode}/protected`));
    workspace.querySelector("[data-csrf]")?.addEventListener("click",()=>run(output,"CSRF保护操作",`/api/demo/${mode}/csrf-check`,"POST"));
    workspace.querySelector("[data-bad-csrf]")?.addEventListener("click",()=>run(output,"故意失败的CSRF",`/api/demo/${mode}/csrf-check`,"POST",true));
    workspace.querySelector("[data-logout]")?.addEventListener("click",async()=>{
      if(invalidating)return;const epoch=generation;
      try{
        await session();if(epoch!==generation)return;
        const response=await fetch(`/demo/${mode}/logout`,{method:"POST",credentials:"same-origin",cache:"no-store",redirect:"error",headers:{"X-CSRF-Token":csrf||""}});
        const body=await response.json();if(epoch!==generation)return;
        if(response.ok){clearPrivate("已退出");show(output,"退出",response,body);setTimeout(()=>location.reload(),150);}
        else show(output,"退出失败",response,body);
      }catch(error){if(epoch===generation)output.textContent=error.message||"退出失败，请重试。";}
    });
    session().catch(error=>{if(!invalidating)output.textContent=error.message;});
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
