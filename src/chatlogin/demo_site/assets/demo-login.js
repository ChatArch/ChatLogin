(() => {
  const root = document.querySelector(".chatlogin") || document.querySelector("#headless-login");
  const form = root?.querySelector("form");
  if (!root || !form) return;
  const match = root.dataset.loginUrl?.match(/^\/demo\/([a-z]+)\/login$/);
  const mode = match?.[1] || root.dataset.mode;
  if (root.matches(".chatlogin") && mode && (!root.dataset.next || root.dataset.next === "/")) root.dataset.next = `/workspace/${mode}`;
  if (root.matches(".chatlogin") && window.self === window.top && !document.querySelector(".back-link")) {
    document.body.classList.add("demo-standalone");
    const nav=document.createElement("nav"); nav.className="demo-context";
    const back=document.createElement("a"); back.href="/#live"; back.textContent="← 返回登录体验";
    const label=document.createElement("span"); label.textContent="公开合成账号 · 无业务权限";
    nav.append(back,label); root.before(nav);
  }
  const box=document.createElement("div"); box.className="demo-fill";
  const picker=document.createElement("select"); picker.dataset.demoUser=""; picker.setAttribute("aria-label","选择公开演示账号"); picker.disabled=true;
  const loading=document.createElement("option"); loading.textContent="正在加载演示账号"; picker.append(loading);
  const hint=document.createElement("span"); hint.setAttribute("aria-live","polite"); hint.textContent="两组公开合成用户，仅供隔离验证。";
  const button=document.createElement("button"); button.type="button"; button.title="Fill Demo"; button.dataset.fillDemo=""; button.textContent="填入 Demo"; button.disabled=true;
  box.append(picker,hint,button); form.prepend(box);
  let accounts=new Map();
  const selected=()=>accounts.get(picker.value);
  const describe=()=>{const account=selected(); if(account) hint.textContent=`${account.username} / ${account.password}`;};
  const fill=()=>{const account=selected(); if(!account)return; form.elements.username.value=account.username; form.elements.password.value=account.password; describe();};
  picker.addEventListener("change",fill); button.addEventListener("click",fill);
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),10000);
  fetch("/api/demo/accounts",{credentials:"same-origin",cache:"no-store",redirect:"error",signal:controller.signal})
    .then(async response=>{
      if(!response.ok)throw new Error("accounts unavailable");
      const body=await response.json();
      if(body.synthetic!==true || !Array.isArray(body.accounts) || !body.accounts.length || body.accounts.length>16 || !body.accounts.every(a=>typeof a.username==="string"&&typeof a.password==="string"&&typeof a.label==="string"))throw new Error("invalid demo metadata");
      accounts=new Map(body.accounts.map(account=>[account.username,account])); picker.replaceChildren();
      for(const account of accounts.values()){const option=document.createElement("option");option.value=account.username;option.textContent=account.label;picker.append(option);}
      picker.disabled=false;button.disabled=false;describe();
    }).catch(()=>{hint.textContent="演示账号暂时无法加载，请刷新后重试。";})
    .finally(()=>clearTimeout(timer));
})();
