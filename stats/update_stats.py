#!/usr/bin/env python3
"""Aggiorna le statistiche di download di YTAudio.

Legge le release via API GitHub (solo conteggio cumulativo per asset), accoda uno snapshot
giornaliero in stats.json per ricostruire l'andamento nel tempo, poi rigenera index.html.
Nessun server, nessun database: tutto versionato nel repo e pubblicato su GitHub Pages.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO = os.environ.get("STATS_REPO", "emlafza/ytaudio-releases")
HERE = Path(__file__).resolve().parent
STATS = HERE / "stats.json"
INDEX = HERE / "index.html"


def fetch_releases():
    url = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
    headers = {"User-Agent": "ytaudio-stats", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def version_of(tag: str) -> str:
    return re.sub(r"^v", "", tag)


def collect(releases):
    """Download cumulativi per versione (somma degli asset .apk della release)."""
    per_version = {}
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        apks = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".apk")]
        if not apks:
            continue
        per_version[version_of(rel["tag_name"])] = sum(a.get("download_count", 0) for a in apks)
    return per_version


def load_history():
    if STATS.exists():
        return json.loads(STATS.read_text())
    return {"snapshots": []}


def update_history(history, per_version):
    today = date.today().isoformat()
    total = sum(per_version.values())
    snap = {"date": today, "total": total, "versions": per_version}
    snaps = history["snapshots"]
    # Una sola riga al giorno: sostituisce quella odierna se già presente
    if snaps and snaps[-1]["date"] == today:
        snaps[-1] = snap
    else:
        snaps.append(snap)
    history["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return history


def render_html(history):
    data_json = json.dumps(history, ensure_ascii=False)
    updated = history.get("updated_at", "")
    return HTML_TEMPLATE.replace("/*DATA*/", data_json).replace("{{UPDATED}}", updated)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>YTAudio · Statistiche download</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #14141f; color: #e6e1e9; }
  header { padding: 24px 20px 8px; }
  h1 { margin: 0; font-size: 20px; }
  .sub { color: #9a95a6; font-size: 13px; margin-top: 4px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; padding: 16px 20px; }
  .card { background: #1e1e2e; border-radius: 12px; padding: 16px 20px; min-width: 150px; }
  .card .n { font-size: 28px; font-weight: 700; color: #bb86fc; }
  .card .l { font-size: 12px; color: #9a95a6; margin-top: 2px; }
  .panel { background: #1e1e2e; border-radius: 12px; margin: 8px 20px 20px; padding: 16px; }
  .panel h2 { font-size: 14px; margin: 0 0 12px; color: #c9c4d4; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #2a2a40; }
  th { color: #9a95a6; font-weight: 600; }
  td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
  .bar { height: 8px; background: #bb86fc; border-radius: 4px; }
  footer { color: #6e6a7a; font-size: 12px; padding: 0 20px 28px; }
  .empty { color: #9a95a6; font-size: 14px; }
</style>
</head>
<body>
<header>
  <h1>YTAudio · Statistiche download</h1>
  <div class="sub">Aggiornato: <span id="updated">—</span></div>
</header>

<div class="cards">
  <div class="card"><div class="n" id="c-total">0</div><div class="l">download totali</div></div>
  <div class="card"><div class="n" id="c-versions">0</div><div class="l">versioni</div></div>
  <div class="card"><div class="n" id="c-latest">—</div><div class="l">ultima versione</div></div>
  <div class="card"><div class="n" id="c-days">0</div><div class="l">giorni di storico</div></div>
</div>

<div class="panel">
  <h2>Download per versione</h2>
  <canvas id="byVersion" height="120"></canvas>
</div>

<div class="panel">
  <h2>Andamento totale nel tempo</h2>
  <canvas id="overTime" height="120"></canvas>
  <div id="overTimeEmpty" class="empty" style="display:none">Lo storico si popola a partire dal primo snapshot.</div>
</div>

<div class="panel">
  <h2>Classifica versioni</h2>
  <table id="rank"><thead><tr><th>Versione</th><th class="n">Download</th><th class="n">%</th><th>Quota</th></tr></thead><tbody></tbody></table>
</div>

<footer>Fonte: GitHub Releases API. I conteggi sono cumulativi; l'andamento è ricostruito dagli snapshot giornalieri.</footer>

<script>
const DATA = /*DATA*/;
const snaps = DATA.snapshots || [];
const purple = "#bb86fc";
const grid = "#2a2a40";

const latest = snaps[snaps.length - 1] || { versions: {}, total: 0 };
const versions = Object.keys(latest.versions).sort(cmpVer);
const counts = versions.map(v => latest.versions[v]);
const total = latest.total || 0;

document.getElementById("updated").textContent = DATA.updated_at || "—";
document.getElementById("c-total").textContent = total.toLocaleString("it-IT");
document.getElementById("c-versions").textContent = versions.length;
document.getElementById("c-latest").textContent = versions.length ? versions[versions.length - 1] : "—";
document.getElementById("c-days").textContent = snaps.length;

function cmpVer(a, b) {
  const pa = a.split(".").map(Number), pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

Chart.defaults.color = "#9a95a6";
Chart.defaults.borderColor = grid;

new Chart(document.getElementById("byVersion"), {
  type: "bar",
  data: { labels: versions, datasets: [{ data: counts, backgroundColor: purple, borderRadius: 4 }] },
  options: { plugins: { legend: { display: false } },
             scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
});

const otEl = document.getElementById("overTime");
if (snaps.length >= 2) {
  new Chart(otEl, {
    type: "line",
    data: { labels: snaps.map(s => s.date),
            datasets: [{ data: snaps.map(s => s.total), borderColor: purple,
                         backgroundColor: "rgba(187,134,252,.15)", fill: true, tension: .25, pointRadius: 2 }] },
    options: { plugins: { legend: { display: false } },
               scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
  });
} else {
  otEl.style.display = "none";
  document.getElementById("overTimeEmpty").style.display = "block";
}

const tbody = document.querySelector("#rank tbody");
versions.slice().sort((a, b) => latest.versions[b] - latest.versions[a]).forEach(v => {
  const n = latest.versions[v];
  const pct = total ? (n / total * 100) : 0;
  const tr = document.createElement("tr");
  tr.innerHTML = `<td>${v}</td><td class="n">${n.toLocaleString("it-IT")}</td>` +
    `<td class="n">${pct.toFixed(1)}%</td>` +
    `<td><div class="bar" style="width:${Math.max(pct, 1)}%"></div></td>`;
  tbody.appendChild(tr);
});
</script>
</body>
</html>
"""


def main():
    try:
        releases = fetch_releases()
    except Exception as e:  # noqa: BLE001
        print(f"Errore nel recupero delle release: {e}", file=sys.stderr)
        return 1
    per_version = collect(releases)
    history = update_history(load_history(), per_version)
    STATS.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n")
    INDEX.write_text(render_html(history))
    print(f"Versioni: {len(per_version)} | totale download: {sum(per_version.values())} | "
          f"snapshot: {len(history['snapshots'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
