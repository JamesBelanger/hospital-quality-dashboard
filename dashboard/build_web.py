"""
build_web.py — self-contained interactive web version of the dashboard (Plotly, JS inlined; no CDN).

Design system (data-viz method, reference palette): system sans, paper/ink chrome, hairline solid grid,
emphasis form (one blue + gray), one sequential blue ramp, thin rounded bars, one hero figure, selective labels.

Reads dashboard/extracts/*.csv → writes dashboard/web/index.html (+ figures.json).
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

# ---- tokens (reference palette, light) ----
SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE = "#2a78d6"            # series-1 / emphasis
DEEMPH = "#c3c2b7"          # de-emphasis gray for context marks
SEQ = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'

def base_layout(height, title=None, subtitle=None):
    lay = dict(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=12, color=INK2),
        margin=dict(l=8, r=16, t=64 if title else 16, b=44),
        hoverlabel=dict(bgcolor=INK, bordercolor=INK, font=dict(family=FONT, size=12, color="#ffffff")),
        xaxis=dict(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=AXIS, tickfont=dict(size=11, color=MUTED), title_font=dict(size=11, color=MUTED)),
        yaxis=dict(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=AXIS, tickfont=dict(size=11, color=MUTED), title_font=dict(size=11, color=MUTED)),
        showlegend=False,
    )
    if title:
        t = f"<b>{title}</b>" + (f"<br><span style='font-size:12px;color:{INK2}'>{subtitle}</span>" if subtitle else "")
        lay["title"] = dict(text=t, x=0, xanchor="left", y=0.98, yanchor="top", font=dict(size=15, color=INK))
    return lay

sc = pd.read_csv(EX / "scorecard.csv")
bm = pd.read_csv(EX / "benchmarks.csv")
hc = pd.read_csv(EX / "hcahps.csv")
txn = pd.read_csv(EX / "tx_vs_national.csv")
hou = sc[sc.is_houston_area].copy()
n_tx, n_hou = int(sc.shape[0]), int(hou.shape[0])

# ================= Panel 1 — scorecard (HTML table; emphasis: better-than-Texas gets the blue bar) =================
COLS = [("readm_pn_pct", "Pneumonia readmission", "%", False), ("mort_hf_pct", "Heart-failure mortality", "%", False),
        ("hai_clabsi_sir", "Central-line infections", "SIR", False), ("sepsis_bundle_pct", "Sepsis bundle", "%", True),
        ("recommend_pct", "Would recommend", "%", True), ("hcahps_star", "Patient-experience stars", "", True)]
tx_avg = {c: sc[c].mean() for c, *_ in COLS}
rng = {c: (sc[c].min(), sc[c].max()) for c, *_ in COLS}

def cell(v, col, hb):
    if pd.isna(v):
        return '<td class="na">–</td>'
    lo, hi = rng[col]
    w = 0 if hi == lo else 100 * (v - lo) / (hi - lo)
    if not hb:  # lower is better → longer bar = better; flip the fill so the eye reads "more bar = better"
        w = 100 - w
    better = (v >= tx_avg[col]) if hb else (v <= tx_avg[col])
    return f'<td><span class="bar {"emph" if better else "ctx"}" style="width:{max(w,2):.0f}%"></span><span class="v">{v:g}</span></td>'

hou_sorted = hou.sort_values("recommend_pct", ascending=False, na_position="last")
rows_html = "\n".join(
    "<tr><th scope='row'>" + f"{r.facility_name.title()}<span class='meta'>{str(r.county).title()} County · {r.hospital_ownership}</span></th>"
    + "".join(cell(getattr(r, c), c, hb) for c, _, _, hb in COLS) + "</tr>"
    for r in hou_sorted.itertuples())
head_html = "<th>Hospital</th>" + "".join(
    f"<th><span class='h'>{lbl}</span><span class='dir'>{'higher is better' if hb else 'lower is better'}{(' · ' + unit) if unit else ''}</span></th>"
    for _, lbl, unit, hb in COLS)
table_html = f"""<div class="tablewrap"><table class="scorecard"><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table></div>
<p class="caption"><span class="key emph"></span> at or better than the Texas average &nbsp; <span class="key ctx"></span> worse than the Texas average &nbsp; · &nbsp; bar length = position within the Texas range, oriented so longer is always better &nbsp; · &nbsp; “–” = not reported (CMS suppresses small denominators)</p>"""

# ================= Panel 2 — readmission dot plot (emphasis: Houston blue, other Texas gray) =================
r = bm[bm.measure_id == "READM_30_PN"].dropna(subset=["score"]).sort_values("score").reset_index(drop=True)
nat, tx = float(r.national_avg.iloc[0]), float(r.state_avg.iloc[0])
def jitter(n, base):  # deterministic strip jitter so overlapping dots separate
    return [base + 0.12 * ((i * 7) % 5 - 2) for i in range(n)]
fig2 = go.Figure()
oth = r[~r.is_houston_area]; hs = r[r.is_houston_area]
fig2.add_trace(go.Scatter(x=oth.score, y=jitter(len(oth), 1.0), mode="markers", name="Other Texas hospitals",
                          marker=dict(color=DEEMPH, size=8, line=dict(width=2, color=SURFACE)),
                          text=oth.facility_name.str.title(), customdata=(oth.national_pct_rank * 100).round(0),
                          hovertemplate="%{text}<br>Readmission %{x:.1f}%  ·  national percentile %{customdata:.0f}<extra></extra>"))
fig2.add_trace(go.Scatter(x=hs.score, y=jitter(len(hs), 2.0), mode="markers", name="Houston-area hospitals",
                          marker=dict(color=BLUE, size=10, line=dict(width=2, color=SURFACE)),
                          text=hs.facility_name.str.title(), customdata=(hs.national_pct_rank * 100).round(0),
                          hovertemplate="%{text}<br>Readmission %{x:.1f}%  ·  national percentile %{customdata:.0f}<extra></extra>"))
for x, lbl in [(nat, f"National average {nat:.1f}%"), (tx, f"Texas average {tx:.1f}%")]:
    fig2.add_shape(type="line", x0=x, x1=x, y0=0.4, y1=2.75, line=dict(color=INK2, width=1))
    fig2.add_annotation(x=x, y=2.8, text=lbl, showarrow=False, yanchor="bottom", font=dict(size=11, color=INK2), xanchor="left", xshift=4)
best = hs.iloc[0]
fig2.add_annotation(x=best.score, y=2.0 + 0.12 * ((0 * 7) % 5 - 2), text=f"{best.facility_name.title()}  {best.score:.1f}%", showarrow=True,
                    arrowhead=0, arrowwidth=1, arrowcolor=INK2, ax=60, ay=-42, font=dict(size=11, color=INK), xanchor="left")
lay = base_layout(360, "Pneumonia readmission rate, 30-day", f"{len(r)} Texas hospitals · lower is better · Houston-area hospitals in blue, the rest of Texas in gray")
lay["xaxis"].update(title="Readmission rate (%)", ticksuffix="%", showgrid=True)
lay["yaxis"].update(visible=False, range=[0.3, 3.2])
lay["showlegend"] = True
lay["legend"] = dict(orientation="h", x=0, y=-0.18, font=dict(size=11, color=INK2), itemsizing="constant")
fig2.update_layout(**lay)

# ================= Panel 3 — HCAHPS heatmap (one sequential hue, no per-cell numbers) =================
QLABEL = {"H_RECMND_DY": "Would recommend", "H_HSP_RATING_9_10": "Rated 9–10", "H_COMP_1_A_P": "Nurses communicated", "H_COMP_2_A_P": "Doctors communicated",
          "H_COMP_3_A_P": "Staff responsive", "H_COMP_5_A_P": "Medicines explained", "H_COMP_6_Y_P": "Discharge information", "H_COMP_7_SA": "Care transition",
          "H_CLEAN_HSP_A_P": "Room clean", "H_QUIET_HSP_A_P": "Quiet at night"}
h = hc[hc.is_houston_area].pivot_table(index="facility_name", columns="measure_id", values="top_box_pct")
h = h.reindex(columns=[c for c in QLABEL if c in h.columns]).dropna(how="all")
if "H_RECMND_DY" in h:
    h = h.loc[h["H_RECMND_DY"].sort_values(ascending=False, na_position="last").index]
fig3 = go.Figure(go.Heatmap(z=h.values, x=[QLABEL[c] for c in h.columns], y=[n.title() for n in h.index],
                            colorscale=[[i / (len(SEQ) - 1), c] for i, c in enumerate(SEQ)], zmin=40, zmax=95, xgap=2, ygap=2,
                            colorbar=dict(title=dict(text="Top-box %", font=dict(size=11, color=MUTED)), thickness=8, len=0.5, y=1, yanchor="top", tickfont=dict(size=10, color=MUTED), outlinewidth=0),
                            hovertemplate="%{y}<br>%{x}: %{z:.0f}% answered top-box<extra></extra>"))
lay = base_layout(max(440, 17 * len(h) + 130), "Patient experience, HCAHPS top-box answers", f"{len(h)} Houston-area hospitals · share of patients giving the best answer · darker is better")
lay["xaxis"].update(side="top", tickangle=-35, showgrid=False)
lay["yaxis"].update(autorange="reversed", tickfont=dict(size=10, color=INK2), showgrid=False)
lay["margin"].update(l=8, t=140)
fig3.update_layout(**lay)

# ================= Panel 4 — Texas vs national (single series, thin rounded bars, value at tip) =================
t = txn.sort_values("tx_share_beating_pct", ascending=True)
MLABEL = {"READM_30_PN": "Pneumonia readmission", "READM_30_HF": "Heart-failure readmission", "MORT_30_HF": "Heart-failure mortality", "MORT_30_PN": "Pneumonia mortality",
          "HAI_1_SIR": "Central-line infections", "HAI_2_SIR": "Catheter infections", "SEP_1": "Sepsis bundle", "OP_22": "Left ED without being seen",
          "H_RECMND_DY": "Would recommend", "H_HSP_RATING_9_10": "Rated 9–10", "H_STAR_RATING": "Patient-experience star rating"}
labels = [MLABEL.get(m, m) for m in t.measure_id]
fig4 = go.Figure(go.Bar(x=t.tx_share_beating_pct, y=labels, orientation="h", width=0.55,
                        marker=dict(color=BLUE, cornerradius=4),
                        text=[f"{v:.0f}%" for v in t.tx_share_beating_pct], textposition="outside", textfont=dict(size=11, color=INK2), cliponaxis=False,
                        customdata=list(zip(t.tx_avg, t.national_avg, t.tx_hospitals)),
                        hovertemplate="%{y}<br>%{x:.0f}% of Texas hospitals beat the national average<br>Texas %{customdata[0]} vs national %{customdata[1]} · n = %{customdata[2]}<extra></extra>"))
fig4.add_shape(type="line", x0=50, x1=50, y0=-0.5, y1=len(labels) - 0.5, line=dict(color=INK2, width=1))
fig4.add_annotation(x=50, y=len(labels) - 0.5, text="half of Texas hospitals", showarrow=False, yanchor="bottom", xanchor="left", xshift=4, font=dict(size=11, color=INK2))
lay = base_layout(420, "Share of Texas hospitals beating the national average", "by measure, latest CMS release · above half on 10 of 11 measures")
lay["xaxis"].update(range=[0, 100], ticksuffix="%", showgrid=True)
lay["yaxis"].update(showgrid=False, tickfont=dict(size=11, color=INK2))
lay["margin"].update(l=8, r=40)
lay["bargap"] = 0.45
fig4.update_layout(**lay)

# ================= assemble =================
cfg = dict(displayModeBar=False, responsive=True)
figs = {"fig2": fig2, "fig3": fig3, "fig4": fig4}
divs = {k: pio.to_html(f, full_html=False, include_plotlyjs=(k == "fig2"), config=cfg, div_id=k) for k, f in figs.items()}
(OUT / "figures.json").write_text(json.dumps({k: json.loads(f.to_json()) for k, f in figs.items()}), encoding="utf-8")

best_name = best.facility_name.title()
html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Houston Hospital Quality Explorer</title>
<style>
:root{{--surface:{SURFACE};--page:{PAGE};--ink:{INK};--ink2:{INK2};--muted:{MUTED};--grid:{GRID};--axis:{AXIS};--blue:{BLUE};--deemph:{DEEMPH};--border:rgba(11,11,11,.10)}}
*{{box-sizing:border-box}} html{{background:var(--page)}}
body{{margin:0;font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--page)}}
.wrap{{max-width:1080px;margin:0 auto;padding:40px 24px 56px}}
header{{border-bottom:1px solid var(--border);padding-bottom:22px;margin-bottom:28px}}
.kicker{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}}
h1{{font-size:34px;line-height:1.15;letter-spacing:-.01em;margin:0 0 10px;font-weight:650}}
.dek{{font-size:17px;color:var(--ink2);max-width:62ch;margin:0}}
.meta-row{{display:flex;flex-wrap:wrap;gap:18px;font-size:13px;color:var(--muted);margin-top:16px}} .meta-row a{{color:var(--ink2)}}
.hero{{display:grid;grid-template-columns:minmax(220px,1fr) 2fr;gap:28px;align-items:end;padding:26px 0;border-bottom:1px solid var(--border)}}
.hero .num{{font-size:64px;line-height:1;font-weight:650;letter-spacing:-.02em;color:var(--ink)}}
.hero .lbl{{font-size:14px;color:var(--ink2);margin-top:6px;max-width:34ch}}
.hero p{{margin:0;font-size:16px;color:var(--ink2);max-width:60ch}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border-bottom:1px solid var(--border)}}
.kpi{{padding:18px 18px 18px 0;border-right:1px solid var(--border)}} .kpi:last-child{{border-right:0}} .kpi+.kpi{{padding-left:18px}}
.kpi .v{{font-size:28px;font-weight:650;letter-spacing:-.01em;line-height:1.1}} .kpi .l{{font-size:13px;color:var(--ink2);margin-top:4px}}
section{{padding:34px 0 8px}} section+section{{border-top:1px solid var(--border)}}
h2{{font-size:20px;margin:0 0 4px;font-weight:650;letter-spacing:-.005em}} .sub{{margin:0 0 16px;color:var(--ink2);font-size:14px}}
.card{{background:var(--surface);border:1px solid var(--border);padding:14px 16px}}
.tablewrap{{overflow:auto;max-height:600px}}
table.scorecard{{width:100%;border-collapse:collapse;font-size:13px}}
.scorecard thead th{{position:sticky;top:0;background:var(--surface);text-align:left;font-weight:600;padding:8px 10px 8px 0;border-bottom:1px solid var(--axis);vertical-align:bottom;color:var(--ink)}}
.scorecard thead th .h{{display:block}} .scorecard thead th .dir{{display:block;font-weight:400;font-size:11px;color:var(--muted)}}
.scorecard tbody th{{text-align:left;font-weight:500;padding:9px 10px 9px 0;border-bottom:1px solid var(--grid);min-width:230px;color:var(--ink)}}
.scorecard tbody th .meta{{display:block;font-size:11.5px;color:var(--muted);font-weight:400}}
.scorecard td{{padding:9px 10px 9px 0;border-bottom:1px solid var(--grid);position:relative;min-width:120px;font-variant-numeric:tabular-nums;color:var(--ink2)}}
.scorecard td .bar{{position:absolute;left:0;top:14px;height:16px;border-radius:0 4px 4px 0;opacity:.9}}
.bar.emph{{background:var(--blue);opacity:.28}} .bar.ctx{{background:var(--deemph);opacity:.45}}
.scorecard td .v{{position:relative;padding-left:6px}} td.na{{color:var(--muted);text-align:center}}
.caption{{font-size:12px;color:var(--muted);margin:10px 0 0}} .key{{display:inline-block;width:14px;height:10px;vertical-align:middle;margin-right:4px}} .key.emph{{background:var(--blue);opacity:.35}} .key.ctx{{background:var(--deemph);opacity:.6}}
footer{{margin-top:36px;padding-top:16px;border-top:1px solid var(--border);font-size:13px;color:var(--ink2);max-width:80ch}}
footer h3{{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}}
@media (max-width:720px){{.hero{{grid-template-columns:1fr}} .kpis{{grid-template-columns:1fr}} .kpi{{border-right:0;border-bottom:1px solid var(--border);padding-left:0}} h1{{font-size:28px}}}}
</style></head><body><div class="wrap">
<header>
  <p class="kicker">CMS Care Compare · latest release (July 2026)</p>
  <h1>How Houston's hospitals measure up</h1>
  <p class="dek">Readmissions, mortality, infections and patient experience for the {n_hou} hospitals in the five-county Houston area, benchmarked against all {n_tx} Texas hospitals and the national distribution.</p>
  <div class="meta-row"><span>Six CMS datasets · 799,104 rows</span><span>PostgreSQL · SQL · Plotly</span><a href="https://github.com/JamesBelanger/hospital-quality-dashboard">Source and methods</a><a href="https://jamesbelanger.com/projects/hospital-quality/">Case study</a></div>
</header>

<div class="hero">
  <div><div class="num">0.4<span style="font-size:28px;font-weight:500;color:var(--ink2)">th</span></div><div class="lbl">national percentile: {best_name}'s heart-failure mortality rate (6.0%)</div></div>
  <p>Among roughly 3,000 U.S. hospitals reporting 30-day heart-failure mortality, {best_name} sits at the very bottom of the distribution — the best outcome in the Houston area, and among the best in the country.</p>
</div>

<div class="kpis">
  <div class="kpi"><div class="v">10 of 11</div><div class="l">key measures on which more than half of Texas hospitals beat the national average</div></div>
  <div class="kpi"><div class="v">66</div><div class="l">Texas hospitals beat the state on pneumonia readmission yet fall below it on “would recommend”</div></div>
  <div class="kpi"><div class="v">90 / 168</div><div class="l">measures missing for over half of Texas hospitals — coverage is the first caveat</div></div>
</div>

<section>
  <h2>The Houston scorecard</h2>
  <p class="sub">Six measures that anchor every hospital quality review, one row per hospital. Sorted by the share of patients who would definitely recommend the hospital.</p>
  <div class="card">{table_html}</div>
</section>

<section>
  <h2>Readmissions against the benchmarks</h2>
  <p class="sub">Every Texas hospital's pneumonia readmission rate on one axis. The benchmark lines are computed from the hospital-level data, not loaded from a separate table.</p>
  <div class="card">{divs['fig2']}</div>
</section>

<section>
  <h2>What patients said</h2>
  <p class="sub">Ten HCAHPS survey questions, Houston-area hospitals only. Each cell is the share of patients who gave the best possible answer.</p>
  <div class="card">{divs['fig3']}</div>
</section>

<section>
  <h2>Texas against the country</h2>
  <p class="sub">For each measure, the share of Texas hospitals doing better than the national average. The patient-experience star rating is the one measure where Texas trails.</p>
  <div class="card">{divs['fig4']}</div>
</section>

<footer>
  <h3>Method</h3>
  <p>Six CMS Care Compare datasets are pulled at run time through the data.cms.gov metastore and reduced to one tidy fact table in PostgreSQL (Supabase). State and national averages and percentiles are computed with SQL window functions from the hospital-level rows. Views feed CSV extracts, which drive this page and a Tableau Public workbook.</p>
  <h3>Limitations</h3>
  <p>This release carries one reporting period per measure, so there are no trends yet. CMS suppresses small-denominator scores, and 90 of 168 measures are missing for more than half of Texas hospitals. “Higher is better” is a documented per-measure heuristic. Built by James Belanger, August 2026.</p>
</footer>
</div></body></html>"""
(OUT / "index.html").write_text(html, encoding="utf-8")
print(f"wrote {OUT/'index.html'} ({(OUT/'index.html').stat().st_size/1e6:.1f} MB); Houston rows {n_hou}, heatmap rows {len(h)}")
