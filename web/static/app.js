// Habitta ia — interacciones ligeras
document.querySelectorAll(".score-ring").forEach((el) => {
  const score = parseInt(el.dataset.score || "0", 10);
  if (score >= 65) el.style.background = "#16a34a";
  else if (score < 45) el.style.background = "#dc2626";
});
