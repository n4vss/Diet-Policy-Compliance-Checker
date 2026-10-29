const MEALS = ["breakfast", "lunch", "snack", "dinner"];
const $ = (id) => document.getElementById(id);
const state = { foods: [], policies: [], samples: [], plan: {} };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  const body = await r.json();
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Request was not valid. Check the plan and policy JSON.");
  return body;
};
const emptyPlan = () => Object.fromEntries(MEALS.map((m) => [m, []]));

function renderMeals() {
  $("meals").innerHTML = MEALS.map((m) => `
    <div class="meal"><h3>${m}</h3>
      ${state.plan[m].map((it, i) => {
        const f = state.foods.find((x) => x.id === it.food_id);
        return `<div class="item"><span>${esc(it.servings)} × ${esc(f.name)}</span>
          <button type="button" data-rm="${m}:${i}" aria-label="Remove ${esc(f.name)} from ${m}">×</button></div>`;
      }).join("") || '<p class="muted">No food added yet.</p>'}
      <div class="add">
        <select aria-label="Food for ${m}" data-food="${m}">${state.foods.map((f) => `<option value="${f.id}">${esc(f.name)} (${esc(f.serving)})</option>`).join("")}</select>
        <input type="number" min="0.5" max="20" step="0.5" value="1" aria-label="Servings for ${m}" data-srv="${m}">
        <button type="button" data-add="${m}">Add</button>
      </div></div>`).join("");
}

async function showPolicy() {
  const p = await api(`/api/policies/${$("policy").value}`);
  $("policy-desc").textContent = p.description || "";
  $("rule-list").innerHTML = p.rules.map((r) => `<li><b>${esc(r.title)}</b> (${r.severity})</li>`).join("");
  $("policy-json").value = JSON.stringify(p, null, 2);
  $("use-custom").checked = false;
}

function renderReport(r) {
  const label = { COMPLIANT: "Compliant", COMPLIANT_WITH_WARNINGS: "Compliant with warnings", NON_COMPLIANT: "Not compliant" }[r.verdict];
  const t = r.totals;
  const totals = [["Energy", t.kcal, "kcal"], ["Sodium", t.sodium_mg, "mg"], ["Carbs", t.carbs_g, "g"], ["Fibre", t.fiber_g, "g"],
    ["Added sugar", t.added_sugar_g, "g"], ["Sat. fat", t.sat_fat_g, "g"]];
  $("report").hidden = false;
  $("report").innerHTML = `
    <div class="verdict ${r.verdict}"><div class="score">${r.score}%</div>
      <div><strong>${label}</strong><br>${esc(r.policy.name)}: ${r.summary.pass} passed, ${r.summary.warn} near limit, ${r.summary.fail} failed</div></div>
    <ul class="totals">${totals.map(([n, v, u]) => `<li>${n}<b>${v} ${u}</b></li>`).join("")}</ul>
    ${r.results.map((x) => `
      <article class="result ${x.status}">
        <h3><span>${esc(x.title)}</span><span><span class="badge ${x.status}">${{ pass: "Pass", warn: "Near limit", fail: "Fail", na: "Not applicable" }[x.status]}</span> <small class="muted">${x.severity}</small></span></h3>
        ${x.checks.map((c) => `<p class="check"><b>${esc(c.target)}:</b> ${esc(c.actual)} ${esc(c.unit)} (limit ${esc(c.limit)})
          ${c.contributors ? `<br><span class="muted">Main sources: ${c.contributors.map((k) => esc(k.food) + (k.amount != null ? ` ${k.amount}` : "")).join(", ")}</span>` : ""}</p>`).join("")}
        ${x.evidence ? `<p class="why">Basis: ${esc(x.evidence)}</p>` : ""}
      </article>`).join("")}`;
  $("report").scrollIntoView({ block: "start" });
}

async function validate() {
  const body = { plan: state.plan };
  try {
    if ($("use-custom").checked) body.policy = JSON.parse($("policy-json").value);
    else body.policy_id = $("policy").value;
    renderReport(await api("/api/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
  } catch (e) {
    $("report").hidden = false;
    $("report").innerHTML = `<p class="err">Could not validate: ${esc(e.message)}</p>`;
  }
}

async function init() {
  [state.foods, state.policies, state.samples] = await Promise.all([api("/api/foods"), api("/api/policies"), api("/api/samples")]);
  state.plan = emptyPlan();
  $("policy").innerHTML = state.policies.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  $("sample").innerHTML += state.samples.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join("");
  $("policy").onchange = showPolicy;
  $("validate").onclick = validate;
  $("clear").onclick = () => { state.plan = emptyPlan(); renderMeals(); $("report").hidden = true; };
  $("sample").onchange = async (e) => {
    if (e.target.value === "") return;
    const s = state.samples[+e.target.value];
    state.plan = { ...emptyPlan(), ...s.plan };
    $("policy").value = s.policy_id;
    await showPolicy();
    renderMeals();
    validate();
  };
  $("meals").onclick = (e) => {
    const add = e.target.dataset.add, rm = e.target.dataset.rm;
    if (add) {
      const srv = parseFloat(document.querySelector(`[data-srv="${add}"]`).value) || 1;
      state.plan[add].push({ food_id: document.querySelector(`[data-food="${add}"]`).value, servings: srv });
      renderMeals();
    } else if (rm) {
      const [m, i] = rm.split(":");
      state.plan[m].splice(+i, 1);
      renderMeals();
    }
  };
  await showPolicy();
  renderMeals();
}
init().catch((e) => { document.body.insertAdjacentHTML("beforeend", `<p class="err">Could not load data: ${esc(e.message)}</p>`); });
