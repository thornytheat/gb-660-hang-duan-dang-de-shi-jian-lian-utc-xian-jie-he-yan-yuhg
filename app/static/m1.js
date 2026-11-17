(function () {
  const input = document.querySelector("#csv");
  const out = document.querySelector("#result");
  const feedback = document.querySelector("#feedback");
  if (!input) return;
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    feedback.textContent = "导入中";
    try {
      const text = await file.text();
      const response = await fetch("/api/legs/import", {
        method: "POST",
        headers: { "content-type": "text/csv" },
        body: text,
      });
      const data = await response.json();
      out.textContent = JSON.stringify(data, null, 2);
      feedback.textContent = response.ok
        ? `已导入 ${data.accepted} 条，隔离 ${data.quarantined} 条`
        : "导入失败";
    } catch (error) {
      out.textContent = error.message;
      feedback.textContent = "导入失败";
    }
  });
})();
