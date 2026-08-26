# Daily card results (pre-computed by Claude on 2026-08-26 so James's daily run is confirm + tick)

For each card: the as-is row count, the tweaked row count, and what to notice. James still runs both in Supabase (that is the log); these are the answers to check against.

## day01  (day01.sql)
- tweak: `'READM_30_PN'` -> `'READM_30_HF'`
- as-is: **73 rows** - first: facility_name=ST LUKE'S PATIENTS MEDICAL C | county=HARRIS | hospital_ownership=Proprietary | star_rating=3
- tweaked: **73 rows** - first: facility_name=HOUSTON METHODIST HOSPITAL | county=HARRIS | hospital_ownership=Voluntary non-profit - Priva | star_rating=5

## day02  (day02.sql)
- tweak: `> 0.5` -> `> 0.25`
- as-is: **90 rows** - first: measure_id=EDV | domain=timely_effective | measure_name=Emergency department volume | hospitals_with_score=0
- tweaked: **168 rows** - first: measure_id=EDV | domain=timely_effective | measure_name=Emergency department volume | hospitals_with_score=0

## day03  (day03.sql)
- tweak: `>= 5` -> `>= 10`
- as-is: **9 rows** - first: hospital_ownership=Government - Local | hospitals=11 | avg_recommend_pct=79.0 | avg_star_rating=3.00
- tweaked: **7 rows** - first: hospital_ownership=Government - State | hospitals=15 | avg_recommend_pct=79.0 | avg_star_rating=3.67

## day04  (day04.sql)
- tweak: `'READM_30_HF'` -> `'MORT_30_HF'`
- as-is: **34 rows** - first: county=BRAZORIA | rank_in_county=1 | facility_name=CHI ST LUKE'S HEALTH BRAZOSP | readm_30_hf_pct=23.0
- tweaked: **32 rows** - first: county=BRAZORIA | rank_in_county=1 | facility_name=HCA HOUSTON HEALTHCARE PEARL | readm_30_hf_pct=11.1

## day05  (day05.sql)
- tweak: `'READM_30_PN'` -> `'SEP_1'`
- as-is: **258 rows** - first: facility_name=ST LUKE'S PATIENTS MEDICAL C | county=HARRIS | readm_30_pn_pct=14.7 | tx_avg=17.32
- tweaked: **233 rows** - first: facility_name=WHITE ROCK MEDICAL CENTER | county=DALLAS | readm_30_pn_pct=15.0 | tx_avg=66.54

## day06  (day06.sql)
- tweak: `'MORT_30_HF'` -> `'MORT_30_PN'`
- as-is: **32 rows** - first: facility_name=HOUSTON METHODIST HOSPITAL | county=HARRIS | mort_30_hf_pct=6.0 | national_percentile=0.004
- tweaked: **32 rows** - first: facility_name=HOUSTON METHODIST HOSPITAL | county=HARRIS | mort_30_hf_pct=8.0 | national_percentile=0.001

## day07  (day07.sql)
- tweak: `'H_HSP_RATING_9_10'` -> `'H_RECMND_DY'`
- as-is: **0 rows** - first: (no rows)
- tweaked: **0 rows** - first: (no rows)

## day08  (day08.sql)
- tweak: `'SEP_1'` -> `'OP_22'`
- as-is: **20 rows** - first: bucket=top | facility_name=METHODIST MIDLOTHIAN MEDICAL | county=ELLIS | z_readm=1.72
- tweaked: **20 rows** - first: bucket=top | facility_name=ENNIS REGIONAL MEDICAL CENTE | county=ELLIS | z_readm=0.12

## day09  (day09.sql)
- tweak: `r.readm < a.avg_readm AND p.recommend < a.avg_recommend` -> `r.readm > a.avg_readm AND p.recommend > a.avg_recommend`
- as-is: **66 rows** - first: facility_name=ST LUKE'S PATIENTS MEDICAL C | county=HARRIS | readm=14.7 | tx_avg_readm=17.32
- tweaked: **32 rows** - first: facility_name=LAMB HEALTHCARE CENTER | county=LAMB | readm=17.4 | tx_avg_readm=17.32

## day10  (day10.sql)
- tweak: `>= 3` -> `>= 5`
- as-is: **20 rows** - first: county=MONTGOMERY | hospitals=8 | with_score=3 | mean_readm=17.00
- tweaked: **11 rows** - first: county=BEXAR | hospitals=20 | with_score=8 | mean_readm=17.28

## day11  (day11.sql)
- tweak: `ORDER BY recommend_pct DESC NULLS LAST` -> `ORDER BY readm_pn ASC NULLS LAST`
- as-is: **53 rows** - first: facility_name=MEMORIAL HERMANN HOUSTON PHY | county=HARRIS | readm_pn=None | mort_hf=None
- tweaked: **53 rows** - first: facility_name=ST LUKE'S PATIENTS MEDICAL C | county=HARRIS | readm_pn=14.7 | mort_hf=10.8

## day12  (day12.sql)
- tweak: `'H_STAR_RATING')` -> `'H_STAR_RATING','OP_22')`
- as-is: **6 rows** - first: measure_id=HAI_1_SIR | higher_is_better=False | national_avg=0.58 | tx_hospitals=151
- tweaked: **7 rows** - first: measure_id=OP_22 | higher_is_better=False | national_avg=1.69 | tx_hospitals=298
