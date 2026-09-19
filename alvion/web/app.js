"use strict";
/* ALVION — front end. No build step; talks to the FastAPI backend. */
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// credits: small totals keep their decimals so 0.15 never shows as "0"
const cr = n => { n = +n || 0; return n >= 10 ? String(Math.round(n)) : n >= 1 ? n.toFixed(1).replace(/\.0$/, "") : n ? n.toFixed(2).replace(/0$/, "") : "0"; };
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i class=\"muted\">$1</i>");
const ic = (n, cls = "") => `<svg class="ic ${cls}"><use href="#i-${n}"/></svg>`;
const STUDIO_IMG = { avatar: "studio-avatar", ugc: "studio-ugc", product: "studio-product",
  cinematic: "studio-cinematic", motion: "studio-motion", explainer: "studio-explainer", silent: "studio-silent" };
const STUDIO_IC = { avatar: "user-round", ugc: "smartphone", product: "package", cinematic: "clapperboard",
  motion: "zap", explainer: "mic", silent: "type" };

let ME = null, INTENTS = [], VIEW = { name: "home" }, POLL = null;

async function api(path, opts = {}) {
  const o = { credentials: "same-origin", ...opts };
  if (o.body && !(o.body instanceof FormData)) o.headers = { "Content-Type": "application/json" };
  const res = await fetch(path, o);
  let d = null; try { d = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error((d && d.detail) || res.statusText);
  return d;
}
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });
let toastT = null;
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.add("hidden"), bad ? 5500 : 2600);
}
const ago = ts => { const d = Date.now() / 1000 - ts;
  return d < 60 ? "just now" : d < 3600 ? Math.floor(d / 60) + "m ago" : d < 86400 ? Math.floor(d / 3600) + "h ago" : Math.floor(d / 86400) + "d ago"; };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

const STATE = {
  draft: ["Draft", "wait"], planning: ["Planning", "busy"], plan_review: ["Review plan", "wait"],
  generating_images: ["Making images", "busy"], images_review: ["Review images", "wait"],
  generating_clips: ["Making clips", "busy"], clips_review: ["Review clips", "wait"],
  edit_setup: ["Edit", "wait"], rendering: ["Rendering", "busy"], completed: ["Ready", "good"],
  failed: ["Failed", "bad"], canceled: ["Canceled", ""],
};
const pill = s => { const [l, c] = STATE[s] || [s, ""]; return `<span class="pill ${c}">${esc(l)}</span>`; };

/* ═════════════ model picker (Higgsfield-style popover) ═════════════ */
const mbadge = o => `<div class="mbadge ${esc((o.badge || "?").toLowerCase())}">${esc(o.badge || "?")}</div>`;
let PICKER = null;
function closePicker() { if (PICKER) { PICKER.remove(); PICKER = null; } }
function openPicker(anchor, { title, sub, options, selected, recommended, unit, onPick }) {
  closePicker();
  const el = document.createElement("div");
  el.className = "picker";
  el.innerHTML = `<div class="ph"><b>${esc(title)}</b><span>${esc(sub || "")}</span></div>` + options.map(o => `
    <div class="pm ${o.id === selected ? "on" : ""}" data-pick="${esc(o.id)}">${mbadge(o)}
      <div class="mid"><div class="nm">${esc(o.name)}<span class="pv">${esc(o.provider)}</span>
        ${o.id === recommended ? `<span class="tag rec">Recommended</span>` : ""}
        ${o.audio ? `<span class="tag aud">Audio</span>` : ""}${o.end_frame ? `<span class="tag end">End frame</span>` : ""}</div>
        <div class="bl">${esc(o.blurb)}</div>${o.watch ? `<div class="wt">${esc(o.watch)}</div>` : ""}
        ${o.resolution_note ? `<div class="wt" style="color:var(--warn)">${esc(o.resolution_note)}</div>` : ""}</div>
      <div class="pr">${o.price != null ? `${(+o.price).toFixed(o.price < 1 ? 2 : 1)}` : ""}<small>${esc(unit || "credits")}</small></div></div>`).join("");
  document.body.appendChild(el);
  const r = anchor.getBoundingClientRect(), h = el.offsetHeight, w = el.offsetWidth;
  let top = r.bottom + 8; if (top + h > innerHeight - 12) top = Math.max(12, r.top - h - 8);
  let left = Math.min(r.left, innerWidth - w - 12);
  el.style.top = top + "px"; el.style.left = Math.max(12, left) + "px";
  el.querySelectorAll("[data-pick]").forEach(p => p.onclick = e => { e.stopPropagation(); closePicker(); onPick(p.dataset.pick); });
  PICKER = el;
  setTimeout(() => document.addEventListener("click", function h(e) { if (!el.contains(e.target)) { closePicker(); document.removeEventListener("click", h); } }), 0);
}
const roleOpts = role => (role.options || []).map(o => Object.assign({}, o, { price: o.price_5s != null ? o.price_5s : o.price,
  audio: (window.CATALOG && CATALOG.video.find(v => v.id === o.id) || {}).audio,
  end_frame: (window.CATALOG && CATALOG.video.find(v => v.id === o.id) || {}).end_frame }));
function roleCard(key, role, selectedId) {
  const o = roleOpts(role).find(x => x.id === selectedId) || roleOpts(role)[0] || {};
  return `<div class="rolecard" data-role="${esc(key)}">${mbadge(o)}<div class="grow">
    <div class="rl">${esc(role.label)}</div><div class="rn">${esc(o.name || "—")}</div>
    <div class="rh">${esc(role.hint)}${selectedId === role.suggested ? " · recommended" : ""}</div></div>
    <div class="pr" style="text-align:right;color:var(--amber);font-weight:750;font-size:12.5px">${o.price != null ? (+o.price).toFixed(o.price < 1 ? 2 : 1) : ""}
      <div class="muted" style="font-size:10.5px;font-weight:500">${key === "frames" ? "per image" : "per 5s"}</div></div>${ic("chevron-down", "sm")}</div>`;
}

/* ═════════════ boot ═════════════ */
(async function loadSprite() {
  try { $("#sprite").innerHTML = await (await fetch("/static/icons.svg?v=" + Date.now().toString(36).slice(0, 5))).text(); } catch (_) {}
})();

let authMode = "login";
$("#auth-swap").onclick = () => {
  authMode = authMode === "login" ? "register" : "login";
  const r = authMode === "register";
  $("#auth-title").textContent = r ? "Create your studio" : "Welcome back";
  $("#auth-sub").textContent = r ? "Brands, projects and every ad you make live here." : "Sign in to your studio.";
  $("#auth-submit").textContent = r ? "Create account" : "Sign in";
  $("#auth-swap-text").textContent = r ? "Already have an account?" : "New to ALVION?";
  $("#auth-swap").textContent = r ? "Sign in" : "Create an account";
  $("#auth-err").textContent = "";
};
$("#auth-form").onsubmit = async e => {
  e.preventDefault(); $("#auth-err").textContent = "";
  const b = $("#auth-submit"); b.disabled = true;
  try { await post("/api/auth/" + authMode, { email: $("#auth-email").value, password: $("#auth-password").value }); await boot(); }
  catch (err) { $("#auth-err").textContent = err.message; }
  finally { b.disabled = false; }
};
$("#logout").onclick = async () => { await post("/api/auth/logout"); location.reload(); };

async function boot() {
  try { ME = await api("/api/me"); }
  catch (_) { $("#auth").classList.remove("hidden"); $("#app").classList.add("hidden"); return; }
  $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#avatar-btn").textContent = ME.user.email[0].toUpperCase();
  $("#user-email").textContent = ME.user.email;
  INTENTS = (await api("/api/intents")).intents;
  window.CATALOG = await api("/api/catalog");
  $("#create-menu").innerHTML = `<div class="dd-head">Start a new ad in a studio</div>` + INTENTS.map(i => `
    <div class="dd-studio" data-studio="${esc(i.key)}"><img src="/static/img/${STUDIO_IMG[i.key]}.jpg" alt="">
      <div><b>${esc(i.label)}</b><span>${esc(i.video_label)}</span></div></div>`).join("");
  renderTop();
  const v = new URLSearchParams(location.search).get("view");
  if (v) history.replaceState(null, "", "/");
  go(v === "connections" ? "connections" : "home");
}
function renderTop() {
  const c = ME.connected || {};
  $("#conn").innerHTML = [["anthropic", "Claude"], ["higgsfield", "Higgsfield"]].map(([k, l]) =>
    `<div class="conn-chip" data-go="connections"><span class="dot ${c[k] ? "on" : ""}"></span>${l}</div>`).join("");
  $("#credits").textContent = cr(ME.credits_spent);
}

document.addEventListener("click", e => {
  const dd = e.target.closest(".dd");
  $$(".dd.open").forEach(d => { if (d !== dd) d.classList.remove("open"); });
  if (e.target.closest("#create-dd") || e.target.closest("#avatar-btn")) { dd.classList.toggle("open"); return; }
  const st = e.target.closest("[data-studio]");
  if (st && st.closest("#create-menu")) { dd && dd.classList.remove("open"); openWizard(null, st.dataset.studio); return; }
  const g = e.target.closest("[data-go]");
  if (g) { $$(".dd.open").forEach(d => d.classList.remove("open")); go(g.dataset.go, g.dataset.id); return; }
  if (e.target.closest("[data-close]")) closeModal();
});
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeModal(); if (W) closeWizard(); } });

function go(name, id) {
  if (POLL) { clearInterval(POLL); POLL = null; }
  VIEW = { name, id };
  $$(".navlink").forEach(b => b.classList.toggle("active", b.dataset.go === name));
  window.scrollTo(0, 0);
  ({ home: viewHome, brands: viewBrands, brand: viewBrand, project: viewProject, video: viewVideo,
     library: viewLibrary, connections: viewConnections }[name] || viewHome)(id);
}

/* ═════════════ home ═════════════ */
const studioCard = (i, sel) => `<div class="studio ${sel ? "sel" : ""}" data-studio="${esc(i.key)}">
  <img src="/static/img/${STUDIO_IMG[i.key]}.jpg" alt="" loading="lazy">
  <span class="go btn primary sm">${ic("arrow-right", "sm")}Start</span>
  <div class="studio-body"><b>${esc(i.label)}</b><p>${esc(i.blurb)}</p>
    <span class="model-tag">${ic(STUDIO_IC[i.key], "sm")}${esc(i.video_label)}</span></div></div>`;

async function viewHome() {
  const [{ projects }, { brands }, { videos }] = await Promise.all([api("/api/projects"), api("/api/brands"), api("/api/videos")]);
  const c = ME.connected || {}, missing = [!c.anthropic && "Claude", !c.higgsfield && "Higgsfield"].filter(Boolean);
  $("#main").innerHTML = `
  <section class="hero">
    <img src="/static/img/hero.jpg" alt="">
    <div class="hero-body">
      <span class="kicker">${ic("sparkles", "sm")} AI ad studio</span>
      <h1>Brief in.<br><span class="grad">Finished ad out.</span></h1>
      <p>Drop in the assets and the script. ALVION plans every shot, picks the right model for each one,
         generates it, and cuts the ad — and asks before it spends a single credit.</p>
      <div class="row"><button class="btn primary lg" id="hero-new">${ic("wand-sparkles")}Create an ad</button>
        <button class="btn ghost lg" data-go="library">${ic("library")}Open library</button></div>
    </div>
    <div class="hero-stats">
      <div class="float-chip">${ic("gauge")}Picks Kling, Seedance or Veo per shot</div>
      <div class="float-chip">${ic("shield-check")}Approve images, clips and cost</div>
      <div class="float-chip">${ic("scissors")}Cuts on measured speech</div>
    </div>
  </section>

  ${missing.length ? `<div class="card sec" style="margin-top:18px;border-color:rgba(255,176,32,.35);background:linear-gradient(135deg,rgba(255,176,32,.08),transparent 60%)">
    <div class="spread"><div class="row">${ic("plug", "lg")}<div><h3>Connect ${missing.join(" and ")}</h3>
      <p class="muted sm">Until then ALVION runs on a free offline preview so you can try the whole flow.</p></div></div>
      <button class="btn ghost" data-go="connections">Connect now</button></div></div>` : ""}

  <div class="sec"><div class="sec-head"><div><h2>Studios</h2>
    <p class="muted sm">Pick what you're making. ALVION chooses the models and tells you why.</p></div></div>
    <div class="studios">${INTENTS.map(i => studioCard(i)).join("")}</div></div>

  <div class="sec grid g-2">
    <div class="card"><div class="spread" style="margin-bottom:12px"><h3>Recent projects</h3>
      <button class="btn quiet sm" id="np">${ic("folder-plus", "sm")}New</button></div>
      ${projects.length ? `<div class="stack">${projects.slice(0, 5).map(p => `
        <div class="spread" style="cursor:pointer" data-go="project" data-id="${esc(p.id)}">
          <div class="row">${ic("folder")}<div><div style="font-weight:700">${esc(p.name)}</div>
            <div class="muted xs">${esc(p.brand_name || "No brand")} · ${plural(p.video_count, "video")}</div></div></div>
          <span class="muted xs">${ago(p.created_at)}</span></div>`).join("")}</div>`
        : `<p class="muted sm">Projects are folders of videos — one campaign, one launch.</p>`}</div>
    <div class="card"><div class="spread" style="margin-bottom:12px"><h3>Latest videos</h3>
      <button class="btn quiet sm" data-go="library">${ic("library", "sm")}Library</button></div>
      ${videos.length ? `<div class="stack">${videos.slice(0, 5).map(v => `
        <div class="spread" style="cursor:pointer" data-go="video" data-id="${esc(v.id)}">
          <div class="row">${ic("film")}<div><div style="font-weight:700">${esc(v.title)}</div>
            <div class="muted xs">${esc(v.project_name || "")}</div></div></div>${pill(v.state)}</div>`).join("")}</div>`
        : `<p class="muted sm">Nothing yet — pick a studio above.</p>`}</div></div>

  <div class="sec"><div class="sec-head"><h2>Brands</h2><button class="btn quiet sm" data-go="brands">All brands</button></div>
    <div class="grid g-auto">${brands.map(brandTile).join("")}
      <div class="tile new" id="nb">${ic("plus", "lg")}New brand</div></div></div>`;
  $("#hero-new").onclick = () => openWizard(null, null);
  $("#np").onclick = () => newProjectModal();
  $("#nb").onclick = () => newBrandModal();
  $$(".studios [data-studio]").forEach(s => s.onclick = () => openWizard(null, s.dataset.studio));
}
const brandTile = b => `<div class="tile" data-go="brand" data-id="${esc(b.id)}"><div class="bar"></div>
  <div class="row"><div class="brand-ico">${esc(b.name[0] || "?")}</div><div>
  <div class="tile-title">${esc(b.name)}</div><div class="muted xs">${esc(b.tagline || "No tagline")}</div></div></div>
  <div class="tile-meta" style="margin-top:12px"><span>${ic("folder", "sm")} ${plural(b.project_count, "project")}</span>
  <span>${ic("images", "sm")} ${plural(b.asset_count, "asset")}</span></div></div>`;

/* ═════════════ brands ═════════════ */
async function viewBrands() {
  const { brands } = await api("/api/brands");
  $("#main").innerHTML = `<div class="page-head"><div class="grow"><h1>Brands</h1>
    <p>Each brand keeps its product facts and assets, reused by every video you make for it.</p></div>
    <button class="btn primary" id="nb">${ic("plus")}New brand</button></div>
    ${brands.length ? `<div class="grid g-auto">${brands.map(brandTile).join("")}</div>`
      : `<div class="empty">${ic("layers")}<h3>No brands yet</h3><p>A brand holds the product truth and reference images.</p>
         <button class="btn primary" style="margin-top:16px" id="nb2">${ic("plus")}Create a brand</button></div>`}`;
  $("#nb").onclick = () => newBrandModal(); if ($("#nb2")) $("#nb2").onclick = () => newBrandModal();
}

async function viewBrand(id) {
  const b = await api("/api/brands/" + id);
  $("#main").innerHTML = `
    <div class="crumb"><button data-go="brands">Brands</button>${ic("chevron-right", "sm")}<span>${esc(b.name)}</span></div>
    <div class="page-head"><div class="grow row"><div class="brand-ico" style="width:52px;height:52px;font-size:22px">${esc(b.name[0])}</div>
      <div><h1>${esc(b.name)}</h1><p style="margin-top:4px">${esc(b.tagline || "")}</p></div></div>
      <button class="btn ghost" id="eb">${ic("pencil")}Edit</button>
      <button class="btn primary" id="np">${ic("folder-plus")}New project</button></div>
    <div class="grid g-2">
      <div class="card"><h3>${ic("info", "sm")} Product truth</h3>
        <p class="muted sm" style="white-space:pre-wrap">${esc(b.details || "No product details yet. This is the only source of product truth ALVION uses — anything not written here will not appear in an ad.")}</p></div>
      <div class="card"><h3>${ic("folder", "sm")} Projects</h3>
        ${b.projects.length ? `<div class="stack">${b.projects.map(p => `<div class="spread" style="cursor:pointer" data-go="project" data-id="${esc(p.id)}">
          <b>${esc(p.name)}</b><span class="muted xs">${plural(p.video_count, "video")}</span></div>`).join("")}</div>`
          : `<p class="muted sm">No projects yet.</p>`}</div></div>
    <div class="card sec"><div class="spread" style="margin-bottom:14px"><div><h3>${ic("images", "sm")} Brand assets</h3>
      <p class="muted sm">Product shots, logos, characters. Attach them to any video for this brand.</p></div>
      <div class="row"><button class="btn ghost sm" id="al">${ic("link", "sm")}Add link</button>
      <button class="btn ghost sm" id="au">${ic("upload", "sm")}Upload</button></div></div>
      <input type="file" id="bf" accept="image/*" multiple class="hidden">
      ${b.assets.length ? `<div class="assetgrid" style="margin-bottom:14px">${b.assets.map(a => `<div class="asset">
        ${a.path ? `<img src="/api/brand-assets/${esc(a.id)}/file" alt="">` : `<div class="linkbox">${ic("link", "lg")}</div>`}
        <div class="cap">${esc(a.name)}</div><button class="x" data-del="${esc(a.id)}">${ic("x", "sm")}</button></div>`).join("")}</div>` : ""}
      <div class="drop" id="drop">${ic("upload")}<b>Drop images here</b><span>or click to upload</span></div></div>`;
  $("#np").onclick = () => newProjectModal(id);
  $("#eb").onclick = () => editBrandModal(b);
  $("#al").onclick = () => linkModal(`/api/brands/${id}/links`, () => viewBrand(id));
  $("#au").onclick = () => $("#bf").click();
  const drop = $("#drop");
  drop.onclick = () => $("#bf").click();
  $("#bf").onchange = e => uploadMany(`/api/brands/${id}/assets`, e.target.files, () => viewBrand(id), { kind: "reference" });
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over");
    uploadMany(`/api/brands/${id}/assets`, e.dataTransfer.files, () => viewBrand(id), { kind: "reference" }); };
  $$("[data-del]").forEach(x => x.onclick = async ev => { ev.stopPropagation();
    await api("/api/brand-assets/" + x.dataset.del, { method: "DELETE" }); viewBrand(id); });
}

async function uploadMany(url, files, done, extra = {}) {
  if (!files || !files.length) return;
  toast(`Uploading ${plural(files.length, "file")}…`);
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f); fd.append("name", f.name);
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
    try { await api(url, { method: "POST", body: fd }); } catch (e) { toast(e.message, true); }
  }
  toast("Uploaded."); done && done();
}

/* ═════════════ project / library ═════════════ */
const vidCard = v => `<div class="vidcard" data-go="video" data-id="${esc(v.id)}">
  <div class="vthumb">${v.thumb_id ? `<img src="/api/videos/${esc(v.id)}/asset/${esc(v.thumb_id)}" alt="" loading="lazy">`
    : `<span class="ph">${ic("film", "lg")}</span>`}<span class="badge">${pill(v.state)}</span></div>
  <div class="vbody"><div class="t">${esc(v.title)}</div><div class="m">${esc(v.project_name || "")} · ${ago(v.created_at)}</div></div></div>`;

async function viewProject(id) {
  const p = await api("/api/projects/" + id);
  $("#main").innerHTML = `
    <div class="crumb">${p.brand_id ? `<button data-go="brand" data-id="${esc(p.brand_id)}">${esc(p.brand_name)}</button>${ic("chevron-right", "sm")}` : ""}<span>${esc(p.name)}</span></div>
    <div class="page-head"><div class="grow"><h1>${esc(p.name)}</h1><p>${esc(p.note || "")}</p></div>
      <button class="btn primary" id="nv">${ic("plus")}New video</button></div>
    ${p.videos.length ? `<div class="grid g-vid">${p.videos.map(vidCard).join("")}</div>`
      : `<div class="empty">${ic("clapperboard")}<h3>No videos in this project</h3><p>Pick a studio, drop in the assets and script.</p>
         <button class="btn primary" style="margin-top:16px" id="nv2">${ic("wand-sparkles")}Create the first video</button></div>`}`;
  const open = () => openWizard(p, null); $("#nv").onclick = open; if ($("#nv2")) $("#nv2").onclick = open;
}

async function viewLibrary() {
  const { videos } = await api("/api/videos");
  $("#main").innerHTML = `<div class="page-head"><div class="grow"><h1>Library</h1>
    <p>Every video across every brand and project.</p></div></div>
    ${videos.length ? `<div class="grid g-vid">${videos.map(vidCard).join("")}</div>`
      : `<div class="empty">${ic("library")}<h3>Your library is empty</h3><p>Videos you make show up here.</p></div>`}`;
}

/* ═════════════ connections ═════════════ */
window.addEventListener("message", e => {
  if (e.data && e.data.type === "alvion-connect") {
    toast(e.data.ok ? "Higgsfield connected." : "Higgsfield wasn't connected.", !e.data.ok);
    refreshMe().then(() => { if (VIEW.name === "connections") viewConnections(); });
  }
});
async function refreshMe() { ME = await api("/api/me"); renderTop(); }
function popup(url, name) {
  const w = 520, h = 720, x = screenX + (outerWidth - w) / 2, y = screenY + (outerHeight - h) / 2;
  const win = window.open(url, name, `width=${w},height=${h},left=${x},top=${y}`);
  if (!win) toast("Your browser blocked the popup — allow popups for ALVION and try again.", true);
  return win;
}

async function viewConnections() {
  const st = await api("/api/connect/status");
  const hf = st.higgsfield, cl = st.claude;
  $("#main").innerHTML = `<div class="page-head"><div class="grow"><h1>Connections</h1>
    <p>Sign in once. ALVION runs on your own accounts — your plan, your credits, your usage.</p></div></div>
    <div class="grid g-2">
      <div class="conn-card ${hf.connected ? "live" : ""}">
        <div class="top"><div class="conn-logo hf">H</div><div class="grow"><h2 style="font-size:19px">Higgsfield</h2>
          <p class="muted sm">Generates every image and clip, on the models ALVION picks per shot.</p></div>
          <span class="pill ${hf.connected ? "good" : ""}">${hf.connected ? "Connected" : "Not connected"}</span></div>
        ${hf.connected ? `<div class="acct">${ic("user-round")}<div class="grow"><b>${esc(hf.email || "Higgsfield account")}</b>
            <div class="muted xs">${esc(hf.plan || "")}${hf.credits != null ? ` · ${Math.round(hf.credits)} credits` : ""}</div></div>
            <button class="btn ghost sm" id="hf-bal">${ic("refresh-cw", "sm")}Balance</button></div>
          <button class="btn danger sm" id="hf-off" style="align-self:flex-start">Disconnect</button>`
        : `<button class="bigconnect" id="hf-on"><span class="dotlogo" style="background:#d7ff3a">H</span>Continue with Higgsfield</button>
          <div class="steps-mini"><div><i>1</i>A Higgsfield window opens — if you're already logged in, it's one click.</div>
            <div><i>2</i>Approve ALVION's access to your account.</div>
            <div><i>3</i>The window closes and ALVION is connected. No keys to copy.</div></div>`}
      </div>
      <div class="conn-card ${cl.connected ? "live" : ""}">
        <div class="top"><div class="conn-logo an">A</div><div class="grow"><h2 style="font-size:19px">Claude</h2>
          <p class="muted sm">Plans the ad, writes every prompt, and rewrites one when you ask for a change.</p></div>
          <span class="pill ${cl.connected ? "good" : ""}">${cl.connected ? "Connected" : "Not connected"}</span></div>
        ${cl.connected ? `<div class="acct">${ic("sparkles")}<div class="grow"><b>${esc(cl.via || "Anthropic")}</b>
            <div class="muted xs">Claude API · billed to the Anthropic account you signed in with</div></div></div>
          <button class="btn danger sm" id="cl-off" style="align-self:flex-start">Disconnect</button>`
        : `<button class="bigconnect" id="cl-on"><span class="dotlogo" style="background:#d97757;color:#1a0d06">A</span>Sign in with Anthropic</button>
          <p class="muted xs">Same sign-in Claude Code uses. A Claude.ai Pro/Max subscription can't be connected to other apps —
            Anthropic doesn't allow it — so ALVION uses your Anthropic API account. <button class="linkbtn xs" id="cl-key">Use an API key instead</button></p>`}
      </div>
    </div>
    <div class="card sec"><h3>${ic("shield-check", "sm")} Spend limit</h3>
      <p class="muted sm">ALVION always shows the cost and waits for you. This is an extra hard stop per video.</p>
      <div class="row" style="align-items:flex-end"><label style="flex:1;max-width:260px">Max credits per video
        <input id="ceil" type="number" min="0" step="10" value="${ME.user.credit_ceiling ?? ""}" placeholder="No limit"></label>
        <button class="btn ghost" id="save-ceil">Save</button></div></div>`;
  $("#hf-on") && ($("#hf-on").onclick = () => popup("/oauth/higgsfield/start", "alvion-hf"));
  $("#hf-off") && ($("#hf-off").onclick = async () => { await api("/api/credentials/higgsfield", { method: "DELETE" }); await refreshMe(); viewConnections(); });
  $("#hf-bal") && ($("#hf-bal").onclick = async () => { try { const b = await api("/api/higgsfield/balance");
    toast(`${Math.round(b.credits ?? 0)} credits · ${b.plan || b.subscription || ""}`); } catch (e) { toast(e.message, true); } });
  $("#cl-on") && ($("#cl-on").onclick = () => claudeSignIn(cl));
  $("#cl-key") && ($("#cl-key").onclick = () => claudeKeyModal());
  $("#cl-off") && ($("#cl-off").onclick = async () => { await api("/api/credentials/anthropic", { method: "DELETE" }); await refreshMe(); viewConnections(); });
  $("#save-ceil").onclick = async () => { const v = $("#ceil").value;
    await post("/api/me", { credit_ceiling: v === "" ? null : Number(v) }); await refreshMe(); toast("Saved."); };
}

let CLPOLL = null;
function claudeSignIn(cl) {
  const stepHtml = (a, b, c) => `<div class="steps-mini" style="margin:14px 0">
      <div class="${a}"><i>${a === "done" ? "✓" : 1}</i>Install Anthropic's official sign-in tool (one time, ~10 MB, checksum-verified)</div>
      <div class="${b}"><i>${b === "done" ? "✓" : 2}</i>Approve ALVION in the Anthropic window</div>
      <div class="${c}"><i>${c === "done" ? "✓" : 3}</i>Connected — ALVION detects it by itself</div></div>`;
  const stop = () => { clearInterval(CLPOLL); CLPOLL = null; };
  const waitFor = () => {
    stop();
    CLPOLL = setInterval(async () => { try { const r = await api("/api/connect/claude/poll");
      if (r.connected) { stop(); closeModal(); toast("Claude connected."); await refreshMe(); viewConnections(); } } catch (_) {} }, 2000);
  };
  const signIn = async () => {
    openModal(`<h2>Sign in with Anthropic</h2>${stepHtml("done", "now", "")}
      <div class="card" style="padding:14px;background:var(--bg2)"><div class="row"><span class="spin"></span>
        <span>An Anthropic sign-in page just opened in your browser. Approve it there.</span></div></div>
      <div class="row" style="margin-top:14px"><button class="btn ghost sm" id="c-pop">${ic("square-play", "sm")}Open it in a popup instead</button>
        <button class="btn quiet sm" data-close>Cancel</button></div><div id="c-code"></div>`);
    $("[data-close]") && $$("[data-close]").forEach(b => b.addEventListener("click", stop));
    try { await post("/api/connect/claude/login", { mode: "browser" }); waitFor(); }
    catch (e) { toast(e.message, true); }
    $("#c-pop").onclick = async () => {
      const r = await post("/api/connect/claude/login", { mode: "popup" });
      if (r.url) popup(r.url, "alvion-anthropic");
      $("#c-code").innerHTML = `<label>Paste the code Anthropic shows<input id="c-codev" placeholder="code#state"></label>
        <button class="btn primary block" style="margin-top:10px" id="c-send">Finish sign-in</button>`;
      $("#c-send").onclick = async () => { try { await post("/api/connect/claude/code", { code: $("#c-codev").value }); waitFor(); toast("Checking…"); }
        catch (e) { toast(e.message, true); } };
    };
  };
  if (cl.ant_installed) return signIn();
  openModal(`<h2>Sign in with Anthropic</h2>${stepHtml("now", "", "")}
    <p class="muted sm">ALVION uses Anthropic's own sign-in tool, <code>ant</code>, from github.com/anthropics. It's downloaded once and
      only installed if its checksum matches the one Anthropic publishes.</p>
    <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button>
      <button class="btn primary" id="c-inst">${ic("download")}Install & continue</button></div>`);
  $("#c-inst").onclick = async e => { e.target.disabled = true; e.target.innerHTML = `<span class="spin"></span>Installing…`;
    try { const r = await post("/api/connect/claude/install"); toast(`Installed ${r.version}, checksum verified.`); signIn(); }
    catch (er) { toast(er.message, true); e.target.disabled = false; e.target.textContent = "Try again"; } };
}

function claudeKeyModal() {
  openModal(`<h2>Use an API key</h2><p class="muted sm">Create one at console.anthropic.com → API keys. ALVION verifies it and
    stores it encrypted on this machine.</p>
    <div class="row" style="margin-top:10px"><button class="btn ghost sm" id="k-open">${ic("square-play", "sm")}Open Anthropic Console</button></div>
    <label>API key<input id="k-v" type="password" placeholder="sk-ant-…" autocomplete="off"></label>
    <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="k-save">Connect</button></div>`);
  $("#k-open").onclick = () => popup("https://console.anthropic.com/settings/keys", "alvion-console");
  $("#k-save").onclick = async e => { e.target.disabled = true;
    try { await post("/api/credentials", { provider: "anthropic", api_key: $("#k-v").value }); closeModal(); toast("Claude connected.");
      await refreshMe(); viewConnections(); } catch (er) { toast(er.message, true); e.target.disabled = false; } };
}

/* ═════════════ modals ═════════════ */
function openModal(h) { $("#modal-card").innerHTML = h; $("#modal").classList.remove("hidden"); const f = $("#modal-card input"); f && f.focus(); }
function closeModal() { $("#modal").classList.add("hidden"); }
function confirmSpend({ title, what, amount, rows, live, quote, kind }) {
  return new Promise(resolve => {
    openModal(`<div class="row" style="gap:12px;margin-bottom:6px"><div class="brand-ico">${ic("coins")}</div><h2>${esc(title)}</h2></div>
      <p class="muted sm">${esc(what)}</p>
      <div class="card" style="margin-top:16px;padding:16px;background:var(--bg2)">
        <div class="spread"><span class="muted sm">Estimated cost</span>
          <span style="font-size:30px;font-weight:800;letter-spacing:-1px" class="grad">~${cr(amount)}</span></div>
        <div class="muted xs" style="margin-top:4px">credits, including a 25% allowance for one re-roll in four</div>
        ${rows && rows.length ? `<div class="stack" style="gap:6px;margin-top:14px">${rows.map(r => `<div class="spread xs muted">
          <span>${esc(r[0])}</span><span class="mono">${esc(r[1])}</span></div>`).join("")}</div>` : ""}</div>
      ${live ? (quote ? `<button class="btn ghost sm" id="cs-quote" style="margin-top:12px">${ic("coins", "sm")}Get Higgsfield's exact quote</button>` : "")
        : `<p class="muted xs" style="margin-top:12px">${ic("info", "sm")} Higgsfield isn't connected — this runs on the free offline preview.</p>`}
      <div class="modal-actions"><button class="btn ghost" id="cs-no">Not yet</button>
        <button class="btn primary" id="cs-yes">${ic("check")}Approve & generate</button></div>`);
    $("#cs-quote") && ($("#cs-quote").onclick = async ev => {
      ev.target.disabled = true; ev.target.innerHTML = `<span class="spin"></span>Asking Higgsfield…`;
      try { const q = await post(`/api/videos/${J.id}/quote`);
        const amt = kind === "clips" ? q.clips : q.images;
        $("#modal-card .grad").textContent = "~" + cr(amt);
        ev.target.outerHTML = `<p class="ok xs" style="margin-top:12px">${ic("badge-check", "sm")} Exact per-shot quotes from Higgsfield, plus the 25% allowance.</p>`;
      } catch (er) { toast(er.message, true); ev.target.disabled = false; ev.target.textContent = "Try the quote again"; } });
    $("#cs-no").onclick = () => { closeModal(); resolve(false); };
    $("#cs-yes").onclick = () => { closeModal(); resolve(true); };
  });
}
function newBrandModal(after) {
  openModal(`<h2>New brand</h2><p class="muted sm">Its product facts and assets are reused by every video.</p>
    <label>Brand name<input id="m1" placeholder="EVOLV"></label>
    <label>Tagline <span class="muted">(optional)</span><input id="m2" placeholder="Vitalize your life"></label>
    <label>Product truth<textarea id="m3" rows="6" placeholder="Exactly what the product looks like — colour, shape, logo placement. The offer, the guarantee, the claims you may make. Anything not here will not appear."></textarea></label>
    <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="mgo">Create brand</button></div>`);
  $("#mgo").onclick = async () => { try {
    const r = await post("/api/brands", { name: $("#m1").value, tagline: $("#m2").value, details: $("#m3").value });
    closeModal(); toast("Brand created."); after ? after(r.brand) : go("brand", r.brand.id);
  } catch (e) { toast(e.message, true); } };
}
function editBrandModal(b) {
  openModal(`<h2>Edit brand</h2><label>Name<input id="m1" value="${esc(b.name)}"></label>
    <label>Tagline<input id="m2" value="${esc(b.tagline || "")}"></label>
    <label>Product truth<textarea id="m3" rows="8">${esc(b.details || "")}</textarea></label>
    <div class="modal-actions"><button class="btn danger" id="mdel">Delete</button><button class="btn ghost" data-close>Cancel</button>
      <button class="btn primary" id="mgo">Save</button></div>`);
  $("#mgo").onclick = async () => { await post("/api/brands/" + b.id, { name: $("#m1").value, tagline: $("#m2").value, details: $("#m3").value });
    closeModal(); toast("Saved."); viewBrand(b.id); };
  $("#mdel").onclick = async () => { if (!confirm(`Delete ${b.name} and everything in it?`)) return;
    await api("/api/brands/" + b.id, { method: "DELETE" }); closeModal(); go("brands"); };
}
function linkModal(url, done) {
  openModal(`<h2>Add a link</h2><p class="muted sm">A product page, a direct image link, a reference ad.</p>
    <label>Link<input id="m1" placeholder="https://…"></label><label>What is it?<input id="m2" placeholder="Product page"></label>
    <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="mgo">Add</button></div>`);
  $("#mgo").onclick = async () => { try { await post(url, { link: $("#m1").value, name: $("#m2").value });
    closeModal(); toast("Link added."); done && done(); } catch (e) { toast(e.message, true); } };
}
async function newProjectModal(brandId, after) {
  const { brands } = await api("/api/brands");
  openModal(`<h2>New project</h2><p class="muted sm">A folder of videos — one campaign, one launch, one batch.</p>
    <label>Project name<input id="m1" placeholder="Q4 — beach angle"></label>
    <label>Brand<select id="m2"><option value="">No brand</option>${brands.map(b =>
      `<option value="${esc(b.id)}" ${b.id === brandId ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label>
    <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="mgo">Create project</button></div>`);
  $("#mgo").onclick = async () => { try {
    const r = await post("/api/projects", { name: $("#m1").value, brand_id: $("#m2").value });
    closeModal(); toast("Project created."); after ? after(r.project) : go("project", r.project.id);
  } catch (e) { toast(e.message, true); } };
}

/* ═════════════ wizard ═════════════ */
let W = null;
async function openWizard(project, kind) {
  let full = project && project.id ? await api("/api/projects/" + project.id) : null;
  const projects = full ? [] : (await api("/api/projects")).projects;
  W = { project: full, projects, kind: kind || null, title: "", script: "", mode: "exact",
        assets: new Set(), files: [], links: [], aspect: "9:16", duration: 30, resolution: "720p",
        budget: false, models: {}, platform: "tiktok", step: 0 };
  W.steps = (full ? [] : ["Project"]).concat(["Studio", "Assets & script", "Models & format"]);
  if (W.kind && !full) W.step = 0;
  else if (W.kind && full) W.step = 1;
  $("#wizard").classList.remove("hidden"); drawWizard();
}
function closeWizard() { $("#wizard").classList.add("hidden"); W = null; }
$("#wiz-close").onclick = closeWizard;
$("#wiz-back").onclick = () => { if (W.step > 0) { W.step--; drawWizard(); } };
$("#wiz-next").onclick = () => nextStep();
const stepName = () => W.steps[W.step];

function drawWizard() {
  $("#wiz-steps").innerHTML = W.steps.map((s, i) => `<div class="wiz-dot ${i === W.step ? "on" : i < W.step ? "past" : ""}">
    <i>${i < W.step ? "✓" : i + 1}</i>${esc(s)}</div>`).join("");
  $("#wiz-back").style.visibility = W.step ? "visible" : "hidden";
  const last = W.step === W.steps.length - 1;
  $("#wiz-next").innerHTML = last ? `${ic("sparkles")}Plan this ad` : `Continue${ic("arrow-right")}`;
  ({ "Project": wizProject, "Studio": wizStudio, "Assets & script": wizAssets, "Models & format": wizFormat }[stepName()])();
}

function wizProject() {
  $("#wiz-hint").textContent = "Projects are folders — one campaign, one launch.";
  $("#wiz-body").innerHTML = `<div class="wiz-inner"><h1>Which project is this for?</h1>
    <p class="muted">Pick a folder, or make a new one.</p>
    <div class="grid g-auto">${W.projects.map(p => `<div class="tile ${W.project && W.project.id === p.id ? "sel" : ""}" data-pp="${esc(p.id)}"
      style="${W.project && W.project.id === p.id ? "border-color:var(--coral);box-shadow:0 0 0 3px rgba(255,94,58,.3)" : ""}">
      <div class="row">${ic("folder")}<div><div class="tile-title">${esc(p.name)}</div>
      <div class="muted xs">${esc(p.brand_name || "No brand")} · ${plural(p.video_count, "video")}</div></div></div></div>`).join("")}
      <div class="tile new" id="wnp">${ic("folder-plus", "lg")}New project</div></div></div>`;
  $$("[data-pp]").forEach(t => t.onclick = async () => { W.project = await api("/api/projects/" + t.dataset.pp); wizProject(); });
  $("#wnp").onclick = () => newProjectModal(null, async p => { W.project = await api("/api/projects/" + p.id);
    W.projects = (await api("/api/projects")).projects; wizProject(); });
}

function wizStudio() {
  $("#wiz-hint").textContent = "This one answer decides the models and the structure.";
  $("#wiz-body").innerHTML = `<div class="wiz-inner"><h1>What are you making?</h1>
    <p class="muted">ALVION picks the right model for it — you never choose one.</p>
    <div class="studios">${INTENTS.map(i => studioCard(i, W.kind === i.key)).join("")}</div></div>`;
  $$("#wiz-body [data-studio]").forEach(s => s.onclick = () => { W.kind = s.dataset.studio; wizStudio(); });
}

function wizAssets() {
  const brandAssets = (W.project && W.project.brand_assets) || [];
  $("#wiz-hint").textContent = "Upload everything you have — ALVION uses it as reference.";
  $("#wiz-body").innerHTML = `<div class="wiz-inner"><h1>Assets & script</h1>
    <p class="muted">Drop in product shots, reference images, links and the script.</p>
    <div class="split">
      <div>
        <label>Title<input id="w-title" value="${esc(W.title)}" placeholder="Beach hook — false complaint"></label>
        <label>Script or idea<textarea id="w-script" rows="11" placeholder="Paste the client script, or describe the ad you want.">${esc(W.script)}</textarea></label>
        <div class="toggle-row"><div class="seg" id="w-mode">
          <button data-m="exact" class="${W.mode === "exact" ? "on" : ""}">Exact script — don't change a word</button>
          <button data-m="idea" class="${W.mode === "idea" ? "on" : ""}">Just an idea — write it for me</button></div></div>
      </div>
      <div>
        <label>Upload images, audio or video</label>
        <div class="drop" id="w-drop" style="margin-top:7px">${ic("upload")}<b>Drop files here</b><span>or click to choose</span></div>
        <input type="file" id="w-file" multiple class="hidden" accept="image/*,audio/*,video/*">
        ${W.files.length ? `<div class="stack" style="margin-top:10px;gap:6px">${W.files.map((f, i) => `<div class="render-row">
          ${ic(f.type.startsWith("image") ? "image" : f.type.startsWith("audio") ? "audio-waveform" : "film", "sm")}
          <span class="grow">${esc(f.name)}</span><button class="iconbtn" data-rf="${i}">${ic("x", "sm")}</button></div>`).join("")}</div>` : ""}
        <label>Links</label>
        <div class="row" style="margin-top:7px;flex-wrap:nowrap"><input id="w-link" placeholder="https://… product page, image or reference ad" style="margin:0">
          <button class="btn ghost" id="w-addlink">${ic("plus", "sm")}Add</button></div>
        ${W.links.length ? `<div class="stack" style="margin-top:8px;gap:6px">${W.links.map((l, i) => `<div class="render-row">${ic("link", "sm")}
          <span class="grow ellipsis" style="overflow:hidden;text-overflow:ellipsis">${esc(l)}</span><button class="iconbtn" data-rl="${i}">${ic("x", "sm")}</button></div>`).join("")}</div>` : ""}
        ${brandAssets.length ? `<label>From ${esc(W.project.brand_name)} <span class="muted">— tap to attach (${W.assets.size})</span></label>
          <div class="assetgrid" style="margin-top:8px">${brandAssets.map(a => `<div class="asset ${W.assets.has(a.id) ? "sel" : ""}" data-pick="${esc(a.id)}">
            ${a.path ? `<img src="/api/brand-assets/${esc(a.id)}/file" alt="">` : `<div class="linkbox">${ic("link")}</div>`}
            <div class="cap">${esc(a.name)}</div></div>`).join("")}</div>` : ""}
      </div></div></div>`;
  $("#w-title").oninput = e => W.title = e.target.value;
  $("#w-script").oninput = e => W.script = e.target.value;
  $$("#w-mode button").forEach(b => b.onclick = () => { W.mode = b.dataset.m; wizAssets(); });
  const drop = $("#w-drop");
  drop.onclick = () => $("#w-file").click();
  $("#w-file").onchange = e => { W.files.push(...e.target.files); wizAssets(); };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); W.files.push(...e.dataTransfer.files); wizAssets(); };
  $$("[data-rf]").forEach(b => b.onclick = () => { W.files.splice(+b.dataset.rf, 1); wizAssets(); });
  $$("[data-rl]").forEach(b => b.onclick = () => { W.links.splice(+b.dataset.rl, 1); wizAssets(); });
  $("#w-addlink").onclick = () => { const v = $("#w-link").value.trim();
    if (!/^https?:\/\//.test(v)) return toast("Give a full http(s) link.", true); W.links.push(v); wizAssets(); };
  $$("[data-pick]").forEach(el => el.onclick = () => { const id = el.dataset.pick;
    W.assets.has(id) ? W.assets.delete(id) : W.assets.add(id); wizAssets(); });
}

async function wizFormat() {
  $("#wiz-hint").textContent = "ALVION suggests a model for each kind of shot. Switch any of them — prices update live.";
  const seg = (id, items, cur) => `<div class="seg" id="${id}">${items.map(([v, l]) =>
    `<button data-v="${v}" class="${cur === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const hasRef = W.assets.size > 0 || W.files.some(f => f.type.startsWith("image"));
  let c;
  try { c = await post("/api/router/preview", { video_kind: W.kind, resolution: W.resolution, has_reference: hasRef, budget: W.budget, models: W.models }); }
  catch (e) { $("#wiz-body").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  W.choice = c;
  const pick = k => W.models[k] || c.roles[k].suggested;
  $("#wiz-body").innerHTML = `<div class="wiz-inner"><h1>Models & format</h1>
    <p class="muted">Each kind of shot goes to the model that's best at it. Tap any card to choose a different one.</p>
    <div class="composer">
      <div class="roles">${Object.entries(c.roles).map(([k, r]) => roleCard(k, r, pick(k))).join("")}</div>
      <div class="chiprow">
        <span class="chip static"><span class="k">Quality</span></span>${seg("f-r", [["720p", "720p"], ["1080p", "1080p"]], W.resolution)}
        <span class="chip static" style="margin-left:6px"><span class="k">Aspect</span></span>${seg("f-a", [["9:16", "9:16"], ["4:5", "4:5"], ["1:1", "1:1"], ["16:9", "16:9"]], W.aspect)}
      </div>
      <div class="chiprow">
        <span class="chip static"><span class="k">Runs on</span></span>${seg("f-p", [["tiktok", "TikTok"], ["reels", "Reels"], ["shorts", "Shorts"], ["meta", "Meta"]], W.platform)}
        <label class="chip" style="margin:0"><span class="k">Length</span><input id="f-d" type="number" min="5" max="120" value="${W.duration}"
          style="width:52px;margin:0;padding:2px 6px;background:transparent;border:none;font-weight:700">s</label>
        <label class="switch" style="margin:0 0 0 auto"><input type="checkbox" id="f-b" ${W.budget ? "checked" : ""}><span class="sw"></span>Budget mode</label>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><h3>${ic("wand", "sm")} Why these</h3>
      <ul class="why">${c.reasons.map(r => `<li>${md(r)}</li>`).join("")}</ul></div></div>`;
  $$("#wiz-body [data-role]").forEach(el => el.onclick = e => {
    const k = el.dataset.role, r = c.roles[k];
    openPicker(el, { title: r.label, sub: k === "frames" ? "credits per image" : "credits per 5s at " + W.resolution,
      options: roleOpts(r), selected: pick(k), recommended: r.suggested, unit: k === "frames" ? "per image" : "per 5s",
      onPick: id => { W.models[k] = id; wizFormat(); } });
    e.stopPropagation();
  });
  $$("#f-r button").forEach(b => b.onclick = () => { W.resolution = b.dataset.v; wizFormat(); });
  $$("#f-a button").forEach(b => b.onclick = () => { W.aspect = b.dataset.v; wizFormat(); });
  $$("#f-p button").forEach(b => b.onclick = () => { W.platform = b.dataset.v; wizFormat(); });
  $("#f-d").oninput = e => W.duration = Number(e.target.value) || 30;
  $("#f-b").onchange = e => { W.budget = e.target.checked; W.models = {}; wizFormat(); };
}

async function nextStep() {
  const s = stepName();
  if (s === "Project" && !W.project) return toast("Pick a project, or create one.", true);
  if (s === "Studio" && !W.kind) return toast("Pick what you're making.", true);
  if (s === "Assets & script" && !W.script.trim()) return toast("Give ALVION a script or an idea.", true);
  if (W.step < W.steps.length - 1) { W.step++; return drawWizard(); }
  const btn = $("#wiz-next"); btn.disabled = true; btn.innerHTML = `<span class="spin"></span>Setting up…`;
  try {
    const r = await post(`/api/projects/${W.project.id}/videos`, { title: W.title, asset_ids: Array.from(W.assets),
      params: { video_kind: W.kind, aspect_ratio: W.aspect, resolution: W.resolution, budget: W.budget,
                models: Object.assign({}, ...Object.entries((W.choice || { roles: {} }).roles).map(([k, r]) => ({ [k]: W.models[k] || r.suggested }))),
                target_duration: W.duration, platform: W.platform, script: W.script, script_mode: W.mode } });
    for (const f of W.files) { const fd = new FormData(); fd.append("file", f);
      await api(`/api/videos/${r.job_id}/assets`, { method: "POST", body: fd }); }
    for (const l of W.links) await post(`/api/videos/${r.job_id}/links`, { link: l });
    await post(`/api/videos/${r.job_id}/plan`);
    closeWizard(); go("video", r.job_id);
  } catch (e) { toast(e.message, true); btn.disabled = false; btn.innerHTML = `${ic("sparkles")}Plan this ad`; }
}

/* ═════════════ video workspace ═════════════ */
const STAGES = [["plan", "Plan", "layout-grid"], ["images", "Images", "image"], ["clips", "Clips", "video"],
                ["edit", "Edit", "scissors"], ["export", "Export", "download"]];
const stageOf = s => ({ draft: "plan", planning: "plan", plan_review: "plan", generating_images: "images",
  images_review: "images", generating_clips: "clips", clips_review: "clips", edit_setup: "edit",
  rendering: "edit", completed: "export" }[s] || "plan");
let J = null, SEEN = 0, MEMO = {}, FB = {}, PICK = null, LOGOPEN = false;

async function viewVideo(id) {
  SEEN = 0; MEMO = {}; FB = {}; PICK = null;
  $("#main").innerHTML = `<div class="empty"><span class="spin"></span></div>`;
  await paint(id, true);
  POLL = setInterval(() => paint(id, false), 2500);
}

async function paint(id, fresh) {
  try { J = await api("/api/videos/" + id); } catch (_) { return; }
  const cur = stageOf(J.state), view = PICK || cur;
  if (fresh || !$("#ws")) {
    $("#main").innerHTML = `<div id="ws">
      <div class="crumb">${J.project ? `<button data-go="project" data-id="${esc(J.project.id)}">${esc(J.project.name)}</button>${ic("chevron-right", "sm")}` : ""}<span>${esc(J.title)}</span></div>
      <div class="page-head"><div class="grow"><h1>${esc(J.title)}</h1>
        <div class="row" style="margin-top:8px" id="ws-meta"></div></div>
        <button class="btn ghost sm" id="ws-log">${ic("message-square-text", "sm")}Activity</button></div>
      <div class="stepper" id="ws-steps"></div>
      <div id="ws-stage"></div>
      <div class="drawer ${LOGOPEN ? "" : "hidden"}" id="ws-drawer"><div class="log" id="ws-logbox"></div></div>
      <div id="ws-bar"></div></div>`;
    $("#ws-log").onclick = () => { LOGOPEN = !LOGOPEN; $("#ws-drawer").classList.toggle("hidden", !LOGOPEN); };
    MEMO = {};
  }
  const kind = INTENTS.find(i => i.key === J.params.video_kind);
  $("#ws-meta").innerHTML = `${J.running ? `<span class="pill busy"><span class="spin" style="width:10px;height:10px"></span>Working</span>` : pill(J.state)}
    <span class="muted sm">${esc(kind ? kind.label : "")} · ${esc(J.params.aspect_ratio)} · ${esc(J.params.quality)}</span>
    ${J.credits_spent ? `<span class="cost">${ic("coins", "sm")}${J.credits_spent.toFixed(0)} spent</span>` : ""}
    ${J.error ? `<span class="pill bad">${esc(J.error).slice(0, 80)}</span>` : ""}`;
  const ci = STAGES.findIndex(s => s[0] === cur);
  $("#ws-steps").innerHTML = STAGES.map(([k, l, icon], i) => `<button class="step ${i < ci ? "done" : i === ci ? "now" : ""}"
    ${i <= ci ? `data-stage="${k}"` : "disabled"} style="cursor:${i <= ci ? "pointer" : "default"};${view === k && k !== cur ? "border-color:var(--line2)" : ""}">
    <i>${i < ci ? "✓" : ic(icon, "sm")}</i>${l}</button>`).join("");
  $$("[data-stage]").forEach(b => b.onclick = () => { PICK = b.dataset.stage === cur ? null : b.dataset.stage; MEMO = {}; paint(id, false); });

  if (view === "plan") paintPlan();
  else if (view === "images" || view === "clips") paintBoard(view);
  else paintEdit();
  paintLog(id);
  if (["completed", "failed", "canceled"].includes(J.state) && !J.running && POLL) { /* keep polling light */ }
}

async function paintLog(id) {
  const { events } = await api(`/api/videos/${id}/events?after=${SEEN}`);
  if (!events.length) return;
  $("#ws-logbox").insertAdjacentHTML("beforeend", events.map(e => { SEEN = Math.max(SEEN, e.id);
    return `<div class="${esc(e.level)}"><time>${new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>${esc(e.message)}</div>`; }).join(""));
  $("#ws-logbox").scrollTop = 1e9;
}

function bar(html) { if (MEMO.bar === html) return; MEMO.bar = html; $("#ws-bar").innerHTML = html ? `<div class="actionbar">${html}</div>` : ""; }

/* ---- plan ---- */
function paintPlan() {
  const p = J.plan, sig = "plan|" + J.state + "|" + (p ? p.clips.length : 0) + "|" + JSON.stringify(J.params.models || {}) + (J.params.resolution || "");
  if (MEMO.stage === sig) return; MEMO.stage = sig;
  if (!p) {
    $("#ws-stage").innerHTML = `<div class="card" style="padding:40px;text-align:center">
      <span class="spin" style="width:28px;height:28px"></span><h3 style="margin-top:14px">ALVION is planning</h3>
      <p class="muted sm">Splitting the script into shots, choosing coverage, writing every prompt.</p></div>
      <div class="storyboard" style="margin-top:16px">${[0, 1, 2, 3].map(() => `<div class="shot"><div class="shot-media shimmer" style="aspect-ratio:9/16"></div></div>`).join("")}</div>`;
    return bar("");
  }
  const kr = p.kill_room || {}, keys = [["stop", "Stop"], ["hold", "Hold"], ["product_clarity", "Product clarity"], ["visual_proof", "Visual proof"],
    ["desire", "Desire"], ["rememberability", "Memorable"], ["action", "Action"], ["renderability", "Renderable"]];
  const total = keys.reduce((a, [k]) => a + (+kr[k] || 0), 0), ch = J.params.model_choice || {}, est = J.estimate || {};
  $("#ws-stage").innerHTML = `
    <div class="plan-top">
      <div class="card"><h3>${ic("sparkles", "sm")} The idea</h3>
        <p style="font-weight:700;font-size:16px">${esc(p.premise || "")}</p>
        <p class="muted sm" style="margin:6px 0 14px">${esc(p.angle || "")}</p>
        <dl class="kv"><dt>Category</dt><dd>${esc(p.category || "—")}</dd><dt>Hook runs on</dt><dd>${esc(p.hook_mechanism || "—")}</dd>
          <dt>Length</dt><dd>${plural(p.clips.length, "shot")} · ${p.total_duration || 0}s</dd>
          ${p.script_coverage ? `<dt>Script</dt><dd>${p.script_coverage.missing.length ? `<span style="color:var(--err)">${p.script_coverage.missing.length} word(s) missing</span>` : `<span style="color:var(--ok)">Every word kept</span>`}</dd>` : ""}</dl>
        ${(p.warnings || []).length ? `<div class="flags" style="margin-top:14px">${p.warnings.map(w => `<div class="flag warn">${ic("triangle-alert")}${esc(w)}</div>`).join("")}</div>` : ""}</div>
      <div class="card"><div class="spread"><h3>${ic("gauge", "sm")} Kill room</h3>
        <span class="pill ${kr.verdict === "produce" ? "good" : kr.verdict === "rebuild" ? "bad" : "wait"}">${esc((kr.verdict || "—").toUpperCase())} · ${total}/40</span></div>
        <p class="muted sm" style="margin-bottom:12px">${esc(kr.fatal_weakness || "")}</p>
        <div class="scores">${keys.map(([k, l]) => `<div class="score"><span>${l}</span><div class="track"><div class="fill ${(+kr[k] || 0) < 3 ? "low" : ""}"
          style="width:${(+kr[k] || 0) * 20}%"></div></div><b>${+kr[k] || 0}</b></div>`).join("")}</div></div></div>
    <div class="card sec" style="margin-top:14px"><div class="spread" style="margin-bottom:12px">
      <h3 style="margin:0">${ic("wand", "sm")} Models for this video</h3>
      <div class="row"><span class="muted xs">Quality</span><div class="seg" id="p-res">${["720p", "1080p"].map(r =>
        `<button data-v="${r}" class="${(J.params.resolution || "720p") === r ? "on" : ""}">${r}</button>`).join("")}</div></div></div>
      <div class="roles">${Object.entries(ch.roles || {}).map(([k, r]) => roleCard(k, r, (J.params.models || {})[k] || r.suggested)).join("")}</div>
      <ul class="why">${(ch.reasons || []).map(r => `<li>${md(r)}</li>`).join("")}</ul></div>
    <h2 class="sec" style="margin-bottom:12px">Shot list</h2>
    <div class="storyboard">${J.shots.map(s => `<div class="shot"><div class="shot-body">
      <div class="shot-id"><b>${esc(s.clip_id)}</b>${esc(s.plan_role || "")} · ${s.duration}s</div>
      <div>${modelChip(s)}</div>
      <div class="muted xs">${ic("video", "sm")} ${esc(s.shot || "")}</div>
      ${s.location ? `<div class="muted xs">${ic("house", "sm")} ${esc(s.location)}</div>` : ""}
      ${s.dialogue ? `<div class="shot-line">“${esc(s.dialogue)}”</div>` : `<div class="muted xs">No dialogue — B-roll</div>`}
      <details class="prompt"><summary>Image prompt</summary><pre>${esc(s.image_prompt || "")}</pre></details>
      <details class="prompt"><summary>Video prompt</summary><pre>${esc(s.video_prompt || "")}</pre></details></div></div>`).join("")}</div>`;
  $$("#ws-stage [data-role]").forEach(el => el.onclick = e => {
    e.stopPropagation();
    const k = el.dataset.role, r = ch.roles[k];
    openPicker(el, { title: r.label, sub: k === "frames" ? "credits per image" : "credits per 5s at " + (J.params.resolution || "720p"),
      options: roleOpts(r), selected: (J.params.models || {})[k] || r.suggested, recommended: r.suggested,
      unit: k === "frames" ? "per image" : "per 5s",
      onPick: async id => { await post(`/api/videos/${J.id}/models`, { [k]: id }); MEMO = {}; paint(J.id); toast("Model switched — cost updated."); } });
  });
  wireModelChips($("#ws-stage"));
  $$("#p-res button").forEach(b => b.onclick = async () => {
    await post(`/api/videos/${J.id}/models`, { resolution: b.dataset.v }); MEMO = {}; paint(J.id); });
  if (J.state === "plan_review") {
    bar(`<span class="info">${plural(J.shots.length, "image")} to make · <span class="cost">${ic("coins", "sm")}~${cr(est.images)} credits</span>${est.live ? "" : " <span class='muted'>(offline preview — free)</span>"}</span>
      <button class="btn ghost sm" id="b-replan">${ic("refresh-cw", "sm")}Re-plan</button>
      <button class="btn primary" id="b-imgs">${ic("image")}Generate images</button>`);
    $("#b-replan").onclick = async () => { await post(`/api/videos/${J.id}/replan`); MEMO = {}; };
    $("#b-imgs").onclick = async e => {
      const ok = await confirmSpend({ title: "Generate the images", amount: est.images || 0, live: est.live,
        what: `${plural(J.shots.length, "start frame")} on ${est.frames_model_name || "the frames model"}. You review every one before any video is made.`,
        rows: (est.rows || []).map(r => [`${r.id} · frame on ${est.frames_model_name || ""}`, `${r.image_credits} cr`]), quote: true });
      if (!ok) return;
      e.target.disabled = true;
      try { await post(`/api/videos/${J.id}/images`, { confirm: true }); PICK = null; MEMO = {}; } catch (er) { toast(er.message, true); e.target.disabled = false; } };
  } else bar("");
}

/* ---- per-shot model chip ---- */
function modelChip(s) {
  const m = (CATALOG.video.find(v => v.id === s.model_used) || {});
  return `<button class="chip" data-mchip="${esc(s.id)}" title="Model for this shot">
    <span class="mb">${esc(m.badge || "?")}</span>${esc(m.name || s.model_used)}${s.model ? "" : `<span class="k">${s.role === "talking" ? "talking" : "b-roll"}</span>`}${ic("chevron-down", "sm")}</button>`;
}
function wireModelChips(root) {
  (root || document).querySelectorAll("[data-mchip]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const s = J.shots.find(x => x.id === b.dataset.mchip); if (!s) return;
    const roles = (J.params.model_choice || {}).roles || {};
    const role = roles[s.role] || roles.broll || Object.values(roles)[0];
    const hasClip = !!s.clip && ["ready", "approved", "failed"].includes(s.clip_status);
    openPicker(b, { title: "Model for " + s.clip_id, sub: hasClip ? "switching regenerates this clip" : "credits per 5s",
      options: roleOpts(role), selected: s.model_used, recommended: role.suggested, unit: "per 5s",
      onPick: async id => {
        if (hasClip) { await post(`/api/videos/${J.id}/shots/${s.id}/clip/revise`, { model: id }); toast(`Regenerating ${s.clip_id} on the new model.`); }
        else { await post(`/api/videos/${J.id}/shots/${s.id}/model`, { model: id }); toast(`${s.clip_id} will use the new model.`); }
        MEMO = {}; paint(J.id);
      } });
  });
}

/* ---- storyboard: images & clips ---- */
function shotCard(s, mode) {
  const ratio = (J.params.aspect_ratio || "9:16").replace(":", "/");
  const st = mode === "images" ? s.image_status : s.clip_status;
  const ver = mode === "images" ? s.image_version : s.clip_version;
  const busy = st === "generating";
  const pc = { pending: ["Waiting", ""], generating: ["Generating", "busy"], ready: ["Needs review", "wait"],
               approved: ["Approved", "good"], failed: ["Failed", "bad"] }[st] || [st, ""];
  const q = s.qc || {}, qf = q.flags || [];
  let media;
  if (mode === "images") media = s.image ? `<img src="${s.image}" alt="">` : `<div class="ph">${ic("image", "lg")}Not generated</div>`;
  else media = s.clip ? `<video src="${s.clip}" ${s.image ? `poster="${s.image}"` : ""} controls playsinline preload="metadata"></video>`
    : s.image ? `<img src="${s.image}" alt="" style="opacity:.45">` : `<div class="ph">${ic("video", "lg")}</div>`;
  const canAct = st === "ready" || st === "approved" || st === "failed";
  const fbOpen = FB[s.id] !== undefined;
  return `<div class="shot ${st === "approved" ? "approved" : ""} ${mode === "clips" && q.verdict === "fail" ? "flag-fail" : ""}" id="shot-${s.id}">
    <div class="shot-media ${busy && !s.image ? "shimmer" : ""}" style="aspect-ratio:${ratio}">${media}
      <div class="tag"><span class="pill ${pc[1]}">${pc[0]}</span></div>${ver ? `<div class="ver"><span class="pill">v${ver}</span></div>` : ""}
      ${busy ? `<div class="gen"><span class="spin" style="width:24px;height:24px"></span>${mode === "images" ? "Generating image" : "Generating clip"}</div>` : ""}</div>
    <div class="shot-body">
      <div class="shot-id"><b>${esc(s.clip_id)}</b>${esc(s.plan_role || "")} · ${s.duration}s</div>
      <div>${modelChip(s)}</div>
      ${s.dialogue ? `<div class="shot-line">“${esc(s.dialogue)}”</div>` : `<div class="muted xs">B-roll · no dialogue</div>`}
      ${mode === "clips" && s.clip ? `<div class="flags">${qf.length ? qf.map(f => `<div class="flag ${f.level}">${ic(f.level === "fail" ? "triangle-alert" : "info")}${esc(f.text)}</div>`).join("")
        : q.verdict ? `<div class="flag clean">${ic("circle-check")}QC clean — drift ${q.metrics && q.metrics.drift != null ? q.metrics.drift : "–"}${q.metrics && q.metrics.script_match != null ? ", script " + Math.round(q.metrics.script_match * 100) + "%" : ""}</div>` : ""}</div>` : ""}
      ${s.error ? `<div class="flag fail">${ic("triangle-alert")}${esc(s.error)}</div>` : ""}
      ${fbOpen ? `<div class="fb"><textarea data-fbt="${s.id}" placeholder="${mode === "images" ? "What should change? e.g. the tank looks too bright — make it darker" : "What's wrong? e.g. hard cut at the end, the background shifts"}">${esc(FB[s.id])}</textarea>
        <div class="row"><button class="btn ghost sm" data-fbx="${s.id}">Cancel</button>
        <button class="btn primary sm" data-fbs="${s.id}" style="flex:1">${ic("send", "sm")}Apply change</button></div></div>`
      : canAct ? `<div class="shot-actions">
        ${st !== "approved" && st !== "failed" ? `<button class="btn ok sm" data-ok="${s.id}">${ic("check", "sm")}Approve</button>` : ""}
        ${st === "approved" ? `<button class="btn quiet sm" data-unok="${s.id}" disabled>${ic("badge-check", "sm")}Approved</button>` : ""}
        <button class="btn ghost sm" data-fb="${s.id}">${ic("pencil", "sm")}Change</button>
        ${mode === "images" ? `<button class="iconbtn" title="Regenerate" data-re="${s.id}">${ic("refresh-cw", "sm")}</button>` : ""}</div>` : ""}
    </div></div>`;
}

function paintBoard(mode) {
  const shots = J.shots;
  if (!$("#board") || MEMO.stage !== "board-" + mode) {
    MEMO = { stage: "board-" + mode };
    $("#ws-stage").innerHTML = `<div class="spread" style="margin-bottom:14px"><div><h2>${mode === "images" ? "Images" : "Clips"}</h2>
      <p class="muted sm">${mode === "images" ? "One start frame per shot. Approve it, or say exactly what to change — ALVION edits that image and keeps everything else."
        : "Watch each clip. ALVION already checked drift, dialogue and cut points — flags show what to look at. Voice, lip sync and hands need your eyes."}</p></div></div>
      <div class="storyboard" id="board"></div>`;
  }
  // keyed per-card render — a card only redraws when its own state changes
  const board = $("#board");
  shots.forEach(s => {
    const sig = [mode, s.image_status, s.image_version, s.clip_status, s.clip_version, s.error, s.model_used, FB[s.id] !== undefined, JSON.stringify(s.qc && s.qc.flags)].join("|");
    if (MEMO["c" + s.id] === sig) return;
    MEMO["c" + s.id] = sig;
    const html = shotCard(s, mode), old = $("#shot-" + s.id);
    if (old) old.outerHTML = html; else board.insertAdjacentHTML("beforeend", html);
    wireCard(s, mode);
  });
  const key = mode === "images" ? "image_status" : "clip_status";
  const approved = shots.filter(s => s[key] === "approved").length, ready = shots.filter(s => s[key] === "ready").length;
  const busy = shots.some(s => s[key] === "generating") || J.running;
  const est = J.estimate || {};
  if (mode === "images" && stageOf(J.state) === "images") {
    bar(`<span class="info"><b>${approved}</b> of ${shots.length} approved${busy ? " · generating…" : ""}</span>
      ${ready ? `<button class="btn ghost sm" id="b-all">${ic("check", "sm")}Approve all ${ready}</button>` : ""}
      <button class="btn primary" id="b-next" ${approved === shots.length && !busy ? "" : "disabled"}>${ic("video")}Generate clips
        <span class="cost" style="color:#1a0d06">~${cr(est.clips)}</span></button>`);
    $("#b-all") && ($("#b-all").onclick = async () => { await post(`/api/videos/${J.id}/images/approve-all`); MEMO = {}; paint(J.id); });
    $("#b-next").onclick = async e => {
      const ok = await confirmSpend({ title: "Generate the clips", amount: est.clips || 0, live: est.live,
        what: `${plural(shots.length, "clip")}, ${Math.round(est.video_seconds || 0)}s of video on ${[...new Set((est.rows || []).map(r => r.model_name))].join(" + ") || "the video models"}. This is the expensive step.`,
        rows: (est.rows || []).map(r => [`${r.id} · ${r.seconds}s on ${r.model_name} ${r.resolution}`, `${r.video_credits} cr`]), quote: true, kind: "clips" });
      if (!ok) return;
      e.target.disabled = true;
      try { await post(`/api/videos/${J.id}/clips`, { confirm: true }); PICK = null; MEMO = {}; paint(J.id); } catch (er) { toast(er.message, true); e.target.disabled = false; } };
  } else if (mode === "clips" && stageOf(J.state) === "clips") {
    bar(`<span class="info"><b>${approved}</b> of ${shots.length} approved${busy ? " · generating…" : ""}</span>
      ${ready ? `<button class="btn ghost sm" id="b-all">${ic("check", "sm")}Approve all ${ready}</button>` : ""}
      <button class="btn primary" id="b-next" ${approved + ready === shots.length && !busy && approved === shots.length ? "" : "disabled"}>${ic("scissors")}Continue to edit</button>`);
    $("#b-all") && ($("#b-all").onclick = async () => { await post(`/api/videos/${J.id}/clips/approve-all`); MEMO = {}; paint(J.id); });
    $("#b-next").onclick = async () => { await post(`/api/videos/${J.id}/clips/approve-all`); PICK = null; MEMO = {}; paint(J.id); };
  } else bar("");
}

function wireCard(s, mode) {
  const root = $("#shot-" + s.id); if (!root) return;
  wireModelChips(root);
  const kind = mode === "images" ? "image" : "clip";
  const q = sel => root.querySelector(sel);
  q("[data-ok]") && (q("[data-ok]").onclick = async () => { await post(`/api/videos/${J.id}/shots/${s.id}/${kind}/approve`); paint(J.id); });
  q("[data-fb]") && (q("[data-fb]").onclick = () => { FB[s.id] = ""; paint(J.id); setTimeout(() => { const t = $(`[data-fbt="${s.id}"]`); t && t.focus(); }, 30); });
  q("[data-re]") && (q("[data-re]").onclick = async () => { await post(`/api/videos/${J.id}/shots/${s.id}/image/regenerate`); toast("Regenerating " + s.clip_id); paint(J.id); });
  q("[data-fbt]") && (q("[data-fbt]").oninput = e => FB[s.id] = e.target.value);
  q("[data-fbx]") && (q("[data-fbx]").onclick = () => { delete FB[s.id]; paint(J.id); });
  q("[data-fbs]") && (q("[data-fbs]").onclick = async () => {
    const text = (FB[s.id] || "").trim(); if (!text) return toast("Say what should change.", true);
    try { await post(`/api/videos/${J.id}/shots/${s.id}/${kind}/revise`, { feedback: text });
      delete FB[s.id]; toast(`Revising ${s.clip_id} — ALVION will remember this for the other shots.`); paint(J.id);
    } catch (e) { toast(e.message, true); } });
}

/* ---- edit room ---- */
const EDIT_Q = [
  ["captions", "Captions", "How words appear on screen.", [["karaoke", "Word by word", "Active word highlighted"], ["bold", "Bold", "Heavy DTC stroke"], ["clean", "Clean", "Plain white"], ["none", "None", "No captions"]]],
  ["pacing", "Pacing", "How hard ALVION trims the pauses.", [["fast", "Fast", "Jump cuts on every pause"], ["tight", "Tight", "Long pauses only"], ["natural", "Natural", "Keep the rhythm"]]],
  ["look", "Look", "Making generated footage read as camera footage.", [["phone", "Phone", "Light grain, no grade"], ["film", "Film", "Grain, warmth, vignette"], ["none", "Raw", "As generated"]]],
  ["transitions", "Cuts", "Between different clips.", [["cut", "Hard cuts", "With J-cut audio"], ["smooth", "Smooth", "Short crossfades"]]],
  ["platform", "Platform", "Keeps captions clear of the app's buttons.", [["tiktok", "TikTok"], ["reels", "Reels"], ["shorts", "Shorts"], ["meta", "Meta"], ["youtube", "YouTube"]]],
];
const MOODS = [["none", "No music"], ["drive", "Drive"], ["warm", "Warm"], ["tense", "Tense"], ["uplift", "Uplift"]];
let ED = null;

function paintEdit() {
  const approved = J.shots.filter(s => s.clip_status === "approved");
  const finals = (J.finals || []).filter(f => f.kind === "final").sort((a, b) => ((b.meta || {}).version || 0) - ((a.meta || {}).version || 0));
  const rendering = J.state === "rendering" || (J.running && J.state === "rendering");
  const sig = ["edit", J.state, finals.length, rendering].join("|");
  if (!ED || ED.job !== J.id) ED = Object.assign({ job: J.id }, JSON.parse(JSON.stringify(J.edit || {})));
  if (MEMO.stage === sig) return; MEMO.stage = sig;
  const last = finals[0], total = approved.reduce((a, s) => a + (+s.duration || 0), 0) || 1;
  const textless = (J.finals || []).filter(f => f.kind === "final_textless");
  const m = ED.music || {};
  $("#ws-stage").innerHTML = `<div class="editroom">
    <div class="player">${last ? `<video src="${last.url}" controls playsinline></video>
      <div class="meta"><span>v${(last.meta || {}).version} · ${((last.meta || {}).duration || 0).toFixed(1)}s</span>
      <span>${(last.meta || {}).loudness ? (last.meta.loudness.lufs).toFixed(1) + " LUFS" : ""}</span></div>`
      : approved[0] && approved[0].clip ? `<video src="${approved[0].clip}" controls playsinline></video><div class="meta"><span>Clip preview — not rendered yet</span></div>`
      : `<div class="empty" style="border:none">${ic("film")}No clips approved</div>`}</div>
    <div class="card">
      <div class="spread"><h2>Edit</h2>${rendering ? `<span class="pill busy"><span class="spin" style="width:10px;height:10px"></span>Rendering</span>` : ""}</div>
      <p class="muted sm">A few choices, then ALVION cuts it. Change any answer and re-render — generations are never redone.</p>
      ${EDIT_Q.map(([k, t, h, opts]) => `<div class="q"><h4>${t}</h4><div class="hint">${h}</div><div class="opts">${opts.map(([v, l, sub]) =>
        `<button class="opt ${ED[k] === v ? "on" : ""}" data-ek="${k}" data-ev="${v}"><span>${l}${sub ? `<small>${sub}</small>` : ""}</span></button>`).join("")}</div></div>`).join("")}
      <div class="q"><h4>Music</h4><div class="hint">Generated, royalty-free, enters after the hook and ducks under the voice.</div>
        <div class="opts">${MOODS.map(([v, l]) => `<button class="opt ${(v === "none" ? m.mode === "none" : m.mode !== "none" && m.mood === v) ? "on" : ""}" data-mood="${v}">${ic(v === "none" ? "x" : "music", "sm")}${l}</button>`).join("")}</div></div>
      <div class="q"><h4>Finishing</h4><div class="stack" style="gap:10px;margin-top:8px">
        ${[["punch_in", "Punch-in zooms on jump cuts"], ["jcut", "Sound arrives before picture (J-cuts)"], ["silence_beat", "One beat of silence before the CTA"], ["textless", "Also export a textless copy for CapCut"]]
          .map(([k, l]) => `<label class="switch" style="margin:0"><input type="checkbox" data-sw="${k}" ${ED[k] ? "checked" : ""}><span class="sw"></span>${l}</label>`).join("")}</div></div>
      <button class="btn primary block lg" id="b-render" style="margin-top:18px" ${rendering || !approved.length ? "disabled" : ""}>
        ${rendering ? `<span class="spin"></span>Rendering…` : `${ic("scissors")}${last ? "Re-render" : "Render the ad"}`}</button>
      ${finals.length ? `<div class="renders">${finals.map(f => { const tl = textless.find(t => (t.meta || {}).version === (f.meta || {}).version);
        return `<div class="render-row">${ic("film", "sm")}<span class="grow">v${(f.meta || {}).version} · ${((f.meta || {}).duration || 0).toFixed(1)}s · ${(f.meta || {}).width}×${(f.meta || {}).height}</span>
        <a class="btn ghost sm" href="${f.url}" download>${ic("download", "sm")}MP4</a>${tl ? `<a class="btn quiet sm" href="${tl.url}" download>Textless</a>` : ""}</div>`; }).join("")}</div>` : ""}
    </div></div>
    <div class="timeline">${approved.map(s => `<div class="tl-clip ${s.mute ? "mute" : ""}" style="width:${Math.max(52, (s.duration / total) * 900)}px;background-image:url('${s.image || ""}')"><span>${esc(s.clip_id)} · ${s.duration}s</span></div>`).join("")}</div>
    <p class="muted xs" style="margin-top:8px">ALVION measures timing, silence and loudness. It can't hear voice quality or judge lip sync — watch it before you ship.</p>`;
  $$("[data-ek]").forEach(b => b.onclick = () => { ED[b.dataset.ek] = b.dataset.ev; MEMO.stage = ""; paintEdit(); });
  $$("[data-mood]").forEach(b => b.onclick = () => { const v = b.dataset.mood;
    ED.music = v === "none" ? Object.assign({}, m, { mode: "none" }) : Object.assign({}, m, { mode: "generated", mood: v }); MEMO.stage = ""; paintEdit(); });
  $$("[data-sw]").forEach(c => c.onchange = () => { ED[c.dataset.sw] = c.checked; });
  $("#b-render").onclick = async e => { e.target.disabled = true;
    const b = {}; ["captions", "pacing", "look", "transitions", "platform", "punch_in", "jcut", "silence_beat", "textless"].forEach(k => b[k] = ED[k]);
    b.music = ED.music;
    try { await post(`/api/videos/${J.id}/render`, b); toast("Rendering — this takes about a minute."); PICK = null; MEMO = {}; paint(J.id); }
    catch (er) { toast(er.message, true); e.target.disabled = false; } };
  bar("");
}

boot();
