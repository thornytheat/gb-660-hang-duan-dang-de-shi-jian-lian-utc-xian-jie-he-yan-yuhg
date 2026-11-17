const ui = {running: false};
const run = document.querySelector("#run");
const out = document.querySelector("#result");
const feedback = document.querySelector("#feedback");
async function execute(){
  if(ui.running) return;
  ui.running = true; feedback.textContent = "运行中"; run.disabled = true;
  try{
    const response = await fetch(document.body.dataset.endpoint, {method:"POST", headers:{"content-type":"application/json"}, body:"{}"});
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail?.message || "请求失败");
    out.textContent = JSON.stringify(data, null, 2); feedback.textContent = "已完成";
  }catch(error){ out.textContent = error.message; feedback.textContent = "失败，可重试"; }
  finally{ ui.running = false; run.disabled = false; }
}
run?.addEventListener("click", execute);

