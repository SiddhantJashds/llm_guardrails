// Thin wrappers over the vendored Chart.js (window.Chart, loaded from
// static/vendor/chart.umd.min.js). Charts are created once per view and
// updated in place on every poll -- no destroy/recreate flicker.
import { cssVar } from "./ui.js";

function baseOptions() {
  const muted = cssVar("--ink-3");
  const grid = cssVar("--gridline");
  const font = { family: cssVar("--font-ui"), size: 12 };
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: cssVar("--ink"),
        titleColor: cssVar("--surface"),
        bodyColor: cssVar("--surface"),
        titleFont: font,
        bodyFont: font,
        padding: 8,
        boxPadding: 4,
      },
    },
    scales: {
      x: { grid: { display: false }, border: { color: cssVar("--baseline") }, ticks: { color: muted, font, maxRotation: 0, autoSkipPadding: 12 } },
      y: { grid: { color: grid }, border: { display: false }, ticks: { color: muted, font, precision: 0 }, beginAtZero: true },
    },
  };
}

function guard() {
  if (typeof window.Chart === "undefined") {
    throw new Error("Chart.js didn't load (dashboard/static/vendor/chart.umd.min.js).");
  }
}

/** series: [{ label, data, color }] stacked bars sharing `labels`. */
export function stackedBars(canvas, { labels, series }) {
  guard();
  const toDatasets = (s) =>
    s.map((x) => ({ label: x.label, data: x.data, backgroundColor: x.color, borderColor: cssVar("--surface"), borderWidth: { top: 1 }, borderRadius: 2, borderSkipped: "bottom", maxBarThickness: 28 }));
  const options = baseOptions();
  options.scales.x.stacked = true;
  options.scales.y.stacked = true;
  const chart = new window.Chart(canvas, { type: "bar", data: { labels, datasets: toDatasets(series) }, options });
  return {
    update({ labels: l, series: s }) {
      chart.data.labels = l;
      chart.data.datasets = toDatasets(s);
      chart.update("none");
    },
    destroy: () => chart.destroy(),
  };
}

/** series: [{ label, data, color, dashed? }] lines sharing `labels`. */
export function lines(canvas, { labels, series, yMin, yMax, stepped = false }) {
  guard();
  const toDatasets = (s) =>
    s.map((x) => ({
      label: x.label,
      data: x.data,
      borderColor: x.color,
      backgroundColor: x.color,
      borderWidth: 2,
      borderDash: x.dashed ? [5, 4] : undefined,
      pointRadius: x.dashed ? 0 : 3,
      pointHoverRadius: 5,
      pointBorderColor: cssVar("--surface"),
      pointBorderWidth: 1.5,
      stepped: x.dashed ? false : stepped,
      tension: 0,
      spanGaps: true,
    }));
  const options = baseOptions();
  if (yMin !== undefined) options.scales.y.min = yMin;
  if (yMax !== undefined) options.scales.y.max = yMax;
  const chart = new window.Chart(canvas, { type: "line", data: { labels, datasets: toDatasets(series) }, options });
  return {
    update({ labels: l, series: s }) {
      chart.data.labels = l;
      chart.data.datasets = toDatasets(s);
      chart.update("none");
    },
    destroy: () => chart.destroy(),
  };
}
