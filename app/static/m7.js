const rev = {
  out: document.querySelector("#result"),
  feedback: document.querySelector("#feedback"),
  state: document.querySelector("#state"),
  batches: document.querySelector("#kpi-batches"),
  revoke: document.querySelector("#kpi-revoke"),
  adjudicate: document.querySelector("#kpi-adjudicate"),
  retain: document.querySelector("#kpi-retain"),
  bar: document.querySelector("#balance-bar"),
  before: document.querySelector("#before"),
  after: document.querySelector("#after"),
  label: document.querySelector("#balance-label"),
  current: null,
};

function show(data){
  rev.out.textContent = JSON.stringify(data, null, 2);
}

async function api(path, body){
  const options = body === undefined
    ? {}
    : {method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const data = await response.json();
  if(!response.ok){
    const detail = data.detail || {};
    throw new Error(detail.code ? `${detail.code}: ${detail.message}` : "请求失败");
  }
  return data;
}

function setCounts(counts){
  rev.revoke.textContent = counts.revoke ?? 0;
  rev.adjudicate.textContent = counts.adjudicate ?? 0;
  rev.retain.textContent = (counts.retain ?? 0) + (counts.restore ?? 0);
}

function renderCases(cases){
  const body = document.querySelector("#cases");
  if(!body) return;
  const open = cases.filter((item) => item.status === "OPEN");
  const count = document.querySelector("#open-count");
  if(count) count.textContent = `${open.length} 条`;
  body.textContent = "";
  open.forEach((item) => {
    const row = document.createElement("tr");
    const key = document.createElement("td");
    key.textContent = item.business_key;
    const versions = document.createElement("td");
    versions.textContent = item.candidates
      .map((candidate) => `${candidate.batch_id} · ${candidate.payload.departure_local}`)
      .join(" / ");
    const decide = document.createElement("td");
    ["KEEP_SOURCE", "KEEP_LATER", "DEFER"].forEach((decision) => {
      const button = document.createElement("button");
      button.className = "btn";
      button.textContent = decision;
      button.addEventListener("click", () => resolveCase(item, decision));
      decide.appendChild(button);
    });
    row.append(key, versions, decide);
    body.appendChild(row);
  });
}

async function resolveCase(item, decision){
  try{
    const chosen = decision === "KEEP_LATER"
      ? item.candidates[item.candidates.length - 1].leg_id
      : null;
    const result = await api(
      `/api/revocations/adjudications/${encodeURIComponent(item.adjudication_id)}/resolve`,
      {decision, chosen_leg_id: chosen}
    );
    show(result);
    rev.feedback.textContent = `已裁决 ${decision}`;
    rev.current = null;
    await previewLatest();
  }catch(error){
    rev.out.textContent = error.message;
    rev.feedback.textContent = "裁决失败";
  }
}

async function loadCases(){
  const data = await api("/api/revocations/adjudications");
  renderCases(data.items || []);
  return data;
}

async function loadBatches(){
  const data = await api("/api/revocations/batches");
  rev.batches.textContent = data.items.length;
  show(data);
  const active = data.items.filter((item) => item.status === "ACTIVE");
  if(!active.length){
    rev.state.textContent = "无可撤销批次";
    return null;
  }
  // Deliberately pick the oldest import still ACTIVE: it is the one whose
  // revocation actually exercises source tracking against later batches.
  const oldest = active[active.length - 1];
  rev.feedback.textContent = "已载入批次";
  return oldest;
}

async function previewLatest(){
  const latest = await loadBatches();
  if(!latest) return;
  const preview = await api(`/api/revocations/batches/${encodeURIComponent(latest.batch_id)}/preview`, {});
  setCounts(preview.counts);
  rev.state.textContent = preview.status;
  rev.current = preview;
  show(preview);
  await loadCases();
  rev.feedback.textContent = "预演完成";
  return preview;
}

async function execute(){
  const preview = rev.current || (await previewLatest());
  if(!preview) return;
  const job = await api(`/api/revocations/previews/${encodeURIComponent(preview.preview_id)}/execute`, {});
  const readback = await api(`/api/revocations/jobs/${encodeURIComponent(job.job_id)}`);
  const cons = readback.conservation;
  const total = Math.max(cons.before, 1);
  rev.bar.style.width = `${Math.round((cons.after / total) * 100)}%`;
  rev.before.textContent = `执行前 ${cons.before}`;
  rev.after.textContent = `执行后 ${cons.after}`;
  rev.label.textContent = cons.balanced && cons.accounted ? "守恒" : "差异";
  rev.state.textContent = job.status;
  show(readback);
  rev.feedback.textContent = job.status === "DONE" ? "已切换" : "可续跑";
}

const action = document.querySelector("#rev-run");
action?.addEventListener("click", async () => {
  try{
    rev.feedback.textContent = "运行中";
    action.disabled = true;
    if(rev.current) await execute();
    else await previewLatest();
  }catch(error){
    rev.state.textContent = "失败";
    rev.out.textContent = error.message;
    rev.feedback.textContent = "失败，可重试";
  }finally{
    action.disabled = false;
  }
});

loadBatches().catch((error) => { rev.out.textContent = error.message; });
loadCases().catch(() => {});
