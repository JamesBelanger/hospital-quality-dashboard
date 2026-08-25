"""
build_web.py — self-contained interactive web version of the dashboard (Plotly, JS inlined; no CDN).

Reads dashboard/extracts/*.csv → writes dashboard/web/index.html (and a lighter dashboard/web/figures.json).
Usage: python dashboard/build_web.py
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "dashboard" / "extracts"
OUT = ROOT / "dashboard" / "web"
OUT.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, TEAL, GRAY = "#2563eb", "#ea580c", "#0f766e", "#9ca3af"
FONT = dict(family="Inter, Segoe UI, Helvetica, Arial, sans-serif", size=12)
LAYOUT = dict(font=FONT, paper_bgcolor="white", plot_bgcolor="white", margin=dict(l=40, r=20, t=50, b=40))

sc = pd.read_csv(EX / "scorecard.csv")
bm = pd.read_csv(EX / "benchmarks.csv")
hc = pd.read_csv(EX / "hcahps.csv")
txn = pd.read_csv(EX / "tx_vs_national.csv")
hou = sc[sc.is_houston_area].copy()


# ---------- Panel 1: Houston scorecard (HTML table with data bars) ----------
COLS = [("readm_pn_pct", "Pneumonia readmission %", False), ("mort_hf_pct", "HF mortality %", False),
        ("hai_clabsi_sir", "CLABSI SIR", False), ("sepsis_bundle_pct", "Sepsis bundle %", True),
        ("recommend_pct", "Would recommend %", True), ("hcahps_star", "HCAHPS stars", True)]
tx_avg = {c: sc[c].mean() for c, _, _ in COLS}


def cell(v, col, higher_better):
    if pd.isna(v):
        return '<td class="na">—</td>'
    better = (v >= tx_avg[col]) if higher_better else (v <= tx_avg[col])
    rng = sc[col].dropna()
    w = 0 if rng.max() == rng.min() else 100 * (v - rng.min()) / (rng.max() - rng.min())
    return f'<td><span class="bar {"good" if better else "bad"}" style="width:{w:.0f}%"></span><span class="v">{v:g}</span></td>'


hou_sorted = hou.sort_values("recommend_pct", ascending=False, na_position="last")
rows_html = "\n".join(
    "<tr><td class='name'>" + f"{r.facility_name.title()}<br><small>{str(r.county).title()} · {r.hospital_ownership}</small></td>"
    + "".join(cell(getattr(r, c), c, hb) for c, _, hb in COLS) + "</tr>"
    for r in hou_sorted.itertuples())
head_html = "<th>Hospital</th>" + "".join(f"<th>{lbl} {'▲' if hb else '▼'}</th>" for _, lbl, hb in COLS)
table_html = f"""<table class="scorecard"><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table>
<p class="note">Bars scale to the Texas range; green = at/better than the Texas average, orange = worse. ▼ lower is better · ▲ higher is better. "—" = not reported (CMS suppresses small denominators).</p>"""

# ---------- Panel 2: readmission dot plot vs benchmarks ----------
r = bm[bm.measure_id == "READM_30_PN"].dropna(subset=["score"]).sort_values("score")
nat, tx = r.national_avg.iloc[0], r.state_avg.iloc[0]
fig2 = go.Figure()
for flag, name, color, size in [(False, "Other Texas hospitals", GRAY, 7), (True, "Houston-area hospitals", BLUE, 11)]:
    d = r[r.is_houston_area == flag]
    fig2.add_trace(go.Scatter(x=d.score, y=[0.5 + 0.9 * (i % 7) / 7 for i in range(len(d))] if not flag else [1.6 + 0.9 * (i % 7) / 7 for i in range(len(d))],
                              mode="markers", name=name, marker=dict(color=color, size=size, opacity=0.85, line=dict(width=1, color="white")),
                              text=d.facility_name.str.title() + "<br>" + d.county.astype(str).str.title(), customdata=(d.national_pct_rank * 100).round(0),
                              hovertemplate="%{text}<br>Readmission: %{x:.1f}%<br>National percentile: %{customdata:.0f}<extra></extra>"))
for x, lbl, col in [(nat, f"National avg {nat:.1f}%", "black"), (tx, f"Texas avg {tx:.1f}%", TEAL)]:
    fig2.add_vline(x=x, line=dict(color=col, dash="dash", width=1.5), annotation_text=lbl, annotation_position="top", annotation_font_color=col)
best = r[r.is_houston_area].iloc[0]
fig2.add_annotation(x=best.score, y=2.6, text=f"Best Houston-area: {best.facility_name.title()} ({best.score:.1f}%)", showarrow=True, arrowhead=2, ax=120, ay=-30, font=dict(size=11))
fig2.update_layout(**LAYOUT, height=340, title="30-day pneumonia readmission rate — Texas hospitals vs benchmarks (lower is better)",
                   xaxis_title="Readmission rate (%)", yaxis=dict(visible=False, range=[0, 3]), legend=dict(orientation="h", y=-0.25))

# ---------- Panel 3: HCAHPS heatmap (Houston-area) ----------
QLABEL = {"H_RECMND_DY": "Would recommend", "H_HSP_RATING_9_10": "Rated 9–10", "H_COMP_1_A_P": "Nurses communicated",
          "H_COMP_2_A_P": "Doctors communicated", "H_COMP_3_A_P": "Staff responsive", "H_COMP_5_A_P": "Medicines explained",
          "H_COMP_6_Y_P": "Discharge info", "H_COMP_7_SA": "Care transition", "H_CLEAN_HSP_A_P": "Room clean", "H_QUIET_HSP_A_P": "Quiet at night"}
h = hc[hc.is_houston_area].pivot_table(index="facility_name", columns="measure_id", values="top_box_pct")
h = h.reindex(columns=[c for c in QLABEL if c in h.columns]).dropna(how="all")
h = h.loc[h["H_RECMND_DY"].sort_values(ascending=False, na_position="last").index] if "H_RECMND_DY" in h else h
fig3 = go.Figure(go.Heatmap(z=h.values, x=[QLABEL[c] for c in h.columns], y=[n.title() for n in h.index],
                            colorscale="Blues", zmin=40, zmax=95, colorbar=dict(title="Top-box %"),
                            hovertemplate="%{y}<br>%{x}: %{z:.0f}%<extra></extra>"))
fig3.update_layout(**LAYOUT, height=max(420, 18 * len(h) + 120), title="Patient experience (HCAHPS top-box %) — Houston-area hospitals",
                   xaxis=dict(side="top", tickangle=-30), yaxis=dict(autorange="reversed", tickfont=dict(size=10)))

# ---------- Panel 4: Texas vs national ----------
t = txn.sort_values("tx_share_beating_pct", ascending=True)
MLABEL = {"READM_30_PN": "Pneumonia readmission", "READM_30_HF": "HF readmission", "MORT_30_HF": "HF mortality", "MORT_30_PN": "Pneumonia mortality",
          "HAI_1_SIR": "Central-line infections", "HAI_2_SIR": "Catheter UTIs", "SEP_1": "Sepsis bundle", "OP_22": "ED left without being seen",
          "H_RECMND_DY": "Would recommend", "H_HSP_RATING_9_10": "Rated 9–10", "H_STAR_RATING": "HCAHPS star rating"}
fig4 = go.Figure(go.Bar(x=t.tx_share_beating_pct, y=[MLABEL.get(m, m) for m in t.measure_id], orientation="h",
                        marker_color=[TEAL if v >= 50 else ORANGE for v in t.tx_share_beating_pct],
                        customdata=list(zip(t.tx_avg, t.national_avg, t.tx_hospitals)),
                        hovertemplate="%{y}<br>%{x:.0f}% of Texas hospitals beat the national average<br>TX avg %{customdata[0]} vs national %{customdata[1]} (n=%{customdata[2]})<extra></extra>"))
fig4.add_vline(x=50, line=dict(color="black", dash="dot", width=1))
fig4.update_layout(**LAYOUT, height=380, title="Share of Texas hospitals beating the national average, by measure",
                   xaxis=dict(title="% of Texas hospitals", range=[0, 100]), yaxis=dict(tickfont=dict(size=11)))

# ---------- assemble ----------
cfg = dict(displayModeBar=False, responsive=True)
figs = {k: f for k, f in [("fig2", fig2), ("fig3", fig3), ("fig4", fig4)]}
divs = {k: pio.to_html(f, full_html=False, include_plotlyjs=(k == "fig2"), config=cfg, div_id=k) for k, f in figs.items()}
(OUT / "figures.json").write_text(json.dumps({k: json.loads(f.to_json()) for k, f in figs.items()}), encoding="utf-8")

n_tx, n_hou = int(sc.shape[0]), int(hou.shape[0])
html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Houston Hospital Quality Explorer</title>
<style>
body{{font:14px/1.5 Inter,"Segoe UI",Helvetica,Arial,sans-serif;color:#111;margin:0;background:#fff}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 16px}} h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:18px;margin:36px 0 8px}}
.sub{{color:#555;margin:0 0 18px}} .findings{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:18px 0}}
.f{{border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;background:#f9fafb}} .f b{{display:block;font-size:22px;color:{TEAL}}}
table.scorecard{{width:100%;border-collapse:collapse;font-size:12.5px}} .scorecard th{{text-align:left;padding:8px 6px;border-bottom:2px solid #ddd;background:#f3f4f6;position:sticky;top:0}}
.scorecard td{{padding:6px;border-bottom:1px solid #eee;position:relative;min-width:90px}} .scorecard td.name{{min-width:220px;font-weight:600}} .scorecard td.name small{{font-weight:400;color:#666}}
.scorecard .bar{{position:absolute;left:0;top:6px;bottom:6px;opacity:.18;border-radius:3px}} .bar.good{{background:{TEAL}}} .bar.bad{{background:{ORANGE}}} .scorecard .v{{position:relative}} td.na{{color:#aaa;text-align:center}}
.tablewrap{{overflow-x:auto;max-height:560px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:8px}} .note{{color:#666;font-size:12px}}
footer{{color:#666;font-size:12px;margin-top:40px;border-top:1px solid #eee;padding-top:12px}}
</style></head><body><div class="wrap">
<h1>Houston Hospital Quality Explorer</h1>
<p class="sub">CMS Care Compare, latest release (data modified 2026-07-22) · {n_tx} Texas hospitals, {n_hou} in the five-county Houston area · Postgres + SQL + Tableau Public + Plotly · <a href="https://github.com/JamesBelanger/hospital-quality-dashboard">source</a></p>
<div class="findings">
<div class="f"><b>0.4th</b>national percentile: Houston Methodist Hospital's heart-failure mortality (6.0%) — best in the Houston area.</div>
<div class="f"><b>10 of 11</b>key measures where more than half of Texas hospitals beat the national average; the exception is the HCAHPS star rating (40%).</div>
<div class="f"><b>66</b>Texas hospitals beat the state on pneumonia readmission yet fall below it on "would recommend" — clinically strong, experientially weak.</div>
<div class="f"><b>90 / 168</b>measures are missing for over half of Texas hospitals; the hospital-wide readmission measure is unscored everywhere this release.</div>
</div>
<h2>1 · Houston-area scorecard</h2><div class="tablewrap">{table_html}</div>
<h2>2 · Readmission vs benchmarks</h2>{divs['fig2']}
<h2>3 · Patient experience</h2>{divs['fig3']}
<h2>4 · Texas vs national</h2>{divs['fig4']}
<footer>Method: six CMS Care Compare datasets → tidy fact table in Postgres (Supabase) → SQL views for benchmarks (state/national averages and percentiles computed with window functions, not loaded from CMS benchmark files) → CSV extracts → Tableau Public + this Plotly page. Limitations: one reporting period per measure in this release (no trends yet); CMS suppresses small-denominator scores; "higher is better" is a documented heuristic per measure. Built by James Belanger, Aug 2026.</footer>
</div></body></html>"""
(OUT / "index.html").write_text(html, encoding="utf-8")
print(f"wrote {OUT/'index.html'} ({(OUT/'index.html').stat().st_size/1e6:.1f} MB) and figures.json; Houston rows in scorecard: {n_hou}")
