document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("action-btn");
  const result = document.getElementById("result-text");
  let clicks = 0;

  if (btn && result) {
    btn.addEventListener("click", () => {
      clicks += 1;
      result.textContent = `Action triggered successfully! Click count: ${clicks}`;
    });
  }
});
