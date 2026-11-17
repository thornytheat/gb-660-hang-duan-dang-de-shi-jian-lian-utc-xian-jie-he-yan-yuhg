document.querySelectorAll(".ledger tbody tr").forEach((row) => {
  row.tabIndex = 0;
  row.addEventListener("keydown", (event) => {
    if(event.key === "Enter") row.classList.toggle("is-active");
  });
});

