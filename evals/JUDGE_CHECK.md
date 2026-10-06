# Judge check (about 10 minutes)

An AI judge decides whether each answer states each required point. This sheet checks the judge against a person.
For each item: read the ANSWER, read the POINT, and decide for yourself whether the answer states that point.
Then compare with the judge's verdict and write `agree` or `disagree` after **You:**. A vague or partial mention counts as NOT stated.

Source run: `evals/results/run_20261006T023824Z_luna-v6-a.json`. 12 items: 6 the judge marked stated, 6 not stated, shuffled.

## 1. `def-03`
**Question:** What does a negative hospital return days (EDAC) result mean, and in what units is it reported?

**Answer:** A negative hospital return days (EDAC) result means patients spent fewer days in acute care than expected compared with patients at an average-performing hospital with a similar case mix. It is reported in days per 100 discharges.

**Point:** An EDAC of zero means the hospital performs exactly as expected

**Judge:** NOT stated — The answer does not explain what an EDAC of zero means.

**You:** 

## 2. `def-14`
**Question:** What is a hybrid measure in the hospital-wide mortality methodology report, and what is the national observed mortality rate?

**Answer:** The Hybrid HWM Measure assesses hospital-wide, risk-standardized mortality within 30 days of admission for most conditions and procedures, combining administrative claims with clinical risk factors extracted from electronic health records. The national observed 30-day mortality rate was 8.17% for Medicare fee-for-service patients ages 65–94 from July 2016 through June 2017.

**Point:** National observed mortality rate is included hospitalizations with the outcome divided by all included hospitalizations

**Judge:** NOT stated — It gives the rate as 8.17% but does not define its numerator or denominator.

**You:** 

## 3. `def-21`
**Question:** Which indicators make up the CMS PSI 90 composite, and how are they combined?

**Answer:** The CMS PSI 90 composite includes PSI 03 pressure ulcer rate; PSI 06 iatrogenic pneumothorax rate; PSI 08 in-hospital fall with hip fracture rate; PSI 09 perioperative hemorrhage or hematoma rate; PSI 10 postoperative acute kidney injury requiring dialysis rate; PSI 11 postoperative respiratory failure rate; PSI 12 perioperative pulmonary embolism or deep vein thrombosis rate; PSI 13 postoperative sepsis rate; PSI 14 postoperative wound dehiscence rate; and PSI 15 unrecognized accidental puncture or laceration rate. It combines these indicators as a weighted average calculated at the hospital level; the excerpt does not give the individual weights. For physician group practices, the measure is calculated at the hospital level and then weighted by the practice’s clinical episode volume at each hospital.

**Point:** Components include PSI 03 pressure ulcer rate

**Judge:** STATED — The answer lists PSI 03 pressure ulcer rate.

**You:** 

## 4. `def-04`
**Question:** What do the 30-day death measures count, and is a lower rate better?

**Answer:** They estimate deaths from any cause within 30 days of the start of a hospital admission, for measures covering heart attack, heart failure, pneumonia, COPD, stroke, CABG surgery, and hospital-wide mortality. Lower death rates are better; however, the heart attack, heart failure, pneumonia, COPD, and CABG figures in the Hospital Value-Based Purchasing dataset are survival rates, not death rates.

**Point:** CMS chose 30-day death over inpatient death for a consistent time window

**Judge:** NOT stated — The answer does not mention why CMS chose a 30-day window instead of inpatient deaths.

**You:** 

## 5. `def-19`
**Question:** What does the SEP-1 sepsis measure calculate, and which patients are in its denominator?

**Answer:** SEP-1 calculates the proportion of Medicare beneficiaries with severe sepsis or septic shock who received all elements of the management bundle. Its denominator includes inpatients age 18 and over with a principal or other ICD-10-CM diagnosis of sepsis, severe sepsis, or septic shock; it is not limited to BPCI Advanced beneficiaries. The fact sheet lists exclusions including transfer from another acute-care facility; intravenous antibiotics for more than 24 hours before severe sepsis; comfort or palliative care directives or administrative contraindications within the specified presentation windows; discharge within six hours of presentation; a stay longer than 120 days; and inclusion in a clinical trial.

**Point:** It is the proportion of Medicare beneficiaries with severe sepsis or septic shock who received all elements of the bundle

**Judge:** STATED — The answer says SEP-1 calculates the proportion of Medicare beneficiaries with severe sepsis or septic shock who received all elements of the management bundle.

**You:** 

## 6. `def-15`
**Question:** What is the minimum number of completed HCAHPS surveys for a hospital's results to be reported, and for it to get HCAHPS star ratings?

**Answer:** A hospital needs at least 25 completed surveys in a four-quarter period for its HCAHPS results to be publicly reported. To receive HCAHPS star ratings, it needs at least 100 completed surveys over a four-quarter period and must be eligible for public reporting of HCAHPS measures.

**Point:** At least 25 completed surveys in a four-quarter period for results to be publicly reported

**Judge:** STATED — The answer states that at least 25 completed surveys in a four-quarter period are needed for public reporting.

**You:** 

## 7. `def-14`
**Question:** What is a hybrid measure in the hospital-wide mortality methodology report, and what is the national observed mortality rate?

**Answer:** The Hybrid HWM Measure assesses hospital-wide, risk-standardized mortality within 30 days of admission for most conditions and procedures, combining administrative claims with clinical risk factors extracted from electronic health records. The national observed 30-day mortality rate was 8.17% for Medicare fee-for-service patients ages 65–94 from July 2016 through June 2017.

**Point:** Claims data give the cohort, outcome and comorbidities; EHR data add clinical data to risk adjustment

**Judge:** NOT stated — It mentions EHR-derived clinical risk factors but does not say claims determine the cohort, outcome, and comorbidities.

**You:** 

## 8. `def-18`
**Question:** How are the 1-to-5 star ratings assigned to each individual HCAHPS measure?

**Answer:** For each of the 10 publicly reported HCAHPS measures, CMS first turns survey responses into a 0–100 linear score by scoring, adjusting, rescaling, averaging across quarters, and rounding. CMS then uses relative distribution and a clustering algorithm to assign one of five whole-star ratings; partial stars are not used. The algorithm groups similar measure scores while separating groups as much as possible, and the star boundaries come from the score ranges in the clusters, whose star levels are ordered by their means.

**Point:** It is the same algorithm used for Medicare Part C and Part D star ratings

**Judge:** NOT stated — The answer does not mention Medicare Part C or Part D star ratings.

**You:** 

## 9. `def-09`
**Question:** What changed when Medicare Advantage admissions were added to the hospital-wide readmission measure?

**Answer:** The only measure change was adding Medicare Advantage admissions to the cohort; all other specifications stayed the same. In the July 1, 2018–June 30, 2019 test period, this added 127 hospitals and more than four million admissions, including 63 additional hospitals among those meeting the 25-admission public-reporting cutoff. Observed 30-day readmission was higher for MA-only than FFS-only admissions (15.72% versus 15.35%); the combined cohort’s mean risk-standardized rate was slightly higher than FFS-only (15.48% versus 15.35%) for hospitals with 25 or more admissions. Test-retest reliability increased from 0.725 to 0.780, while 67% of hospitals stayed in the same performance quintile and 95% stayed within one quintile. The testing used the claims-only version because EHR data were unavailable; the report says the impact on the Hybrid measure was expected to be comparable.

**Point:** Adding MA admissions added 127 hospitals and over four million admissions to the cohort

**Judge:** STATED — The answer says MA admissions added 127 hospitals and more than four million admissions.

**You:** 

## 10. `def-21`
**Question:** Which indicators make up the CMS PSI 90 composite, and how are they combined?

**Answer:** The CMS PSI 90 composite includes PSI 03 pressure ulcer rate; PSI 06 iatrogenic pneumothorax rate; PSI 08 in-hospital fall with hip fracture rate; PSI 09 perioperative hemorrhage or hematoma rate; PSI 10 postoperative acute kidney injury requiring dialysis rate; PSI 11 postoperative respiratory failure rate; PSI 12 perioperative pulmonary embolism or deep vein thrombosis rate; PSI 13 postoperative sepsis rate; PSI 14 postoperative wound dehiscence rate; and PSI 15 unrecognized accidental puncture or laceration rate. It combines these indicators as a weighted average calculated at the hospital level; the excerpt does not give the individual weights. For physician group practices, the measure is calculated at the hospital level and then weighted by the practice’s clinical episode volume at each hospital.

**Point:** It follows NQF #0531 specifications

**Judge:** NOT stated — The answer does not mention NQF #0531 specifications.

**You:** 

## 11. `def-04`
**Question:** What do the 30-day death measures count, and is a lower rate better?

**Answer:** They estimate deaths from any cause within 30 days of the start of a hospital admission, for measures covering heart attack, heart failure, pneumonia, COPD, stroke, CABG surgery, and hospital-wide mortality. Lower death rates are better; however, the heart attack, heart failure, pneumonia, COPD, and CABG figures in the Hospital Value-Based Purchasing dataset are survival rates, not death rates.

**Point:** Lower mortality rates are better

**Judge:** STATED — The answer explicitly says lower death rates are better.

**You:** 

## 12. `def-14`
**Question:** What is a hybrid measure in the hospital-wide mortality methodology report, and what is the national observed mortality rate?

**Answer:** The Hybrid HWM Measure assesses hospital-wide, risk-standardized mortality within 30 days of admission for most conditions and procedures, combining administrative claims with clinical risk factors extracted from electronic health records. The national observed 30-day mortality rate was 8.17% for Medicare fee-for-service patients ages 65–94 from July 2016 through June 2017.

**Point:** A hybrid measure uses two separate data sources

**Judge:** STATED — The answer says the measure combines administrative claims and electronic health record data.

**You:** 

## Tally
Agreed: __ of 12. Disagreements (item numbers and one line each):

When done, tell Claude the tally. 11 or 12 of 12 means the judge can be trusted at this level of detail; 
8 or fewer means the definition scores should be reported as rough, and the judge prompt needs work.
