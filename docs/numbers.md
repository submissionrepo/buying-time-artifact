# Every number in the text

One row per macro of `research_ideas/bridge_limits_paper/tex/numbers.tex`, in the order `make_numbers.py` writes them: the value, where the paper uses it, the section of `make_numbers.py` that computes it (its `# --- ... ---` comment) and the files that section reads. A value computed from data read in an earlier section lists no files; see the section named there. The second table names the script that writes each file (level 2 unless stated).

| Macro | Value | Used in | make_numbers.py section | Files read there |
|---|---|---|---|---|
| `\nRecords` | 69 | Sec. 3.3, App. B | events (bridge set of the event table) | `results/incidents.csv` |
| `\nExcluded` | 12 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\nEvents` | 57 | Abstract, Sec. 1, Sec. 3.3, Sec. 7, Sec. 8.3, Sec. 9, Sec. 13, App. B | events (bridge set of the event table) | `results/incidents.csv` |
| `\valueEventsB` | 3.7 | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\valueEventsM` | 3,711 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\eventsFirstYear` | 2021 | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\eventsLastYear` | 2026 | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\medOutflowMin` | 8 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\medOutflowWords` | eight | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\medRespH` | 3 | Sec. 1, Sec. 4 | events (bridge set of the event table) | `results/incidents.csv` |
| `\medRespM` | 42 | Sec. 1, Sec. 4 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nTimedEvents` | 48 | Sec. 1, Sec. 6.1, Sec. 9 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nUntimedEvents` | 9 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\shareTenMinPct` | 68 | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nShareTenMin` | 38 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\nPaused` | 19 | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nPausedAfterLast` | 17 | Sec. 1 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nRespAck` | 30 | Sec. 9 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nRespPause` | 18 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateOneEventsPct` | 83 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateOneValuePct` | 91 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateSixEventsPct` | 35 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateSixValuePct` | 23 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateDayEventsPct` | 10 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateDayValuePct` | 19 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateTwoDaysEventsPct` | 8 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\lateTwoDaysValuePct` | 19 | not in the text | events (bridge set of the event table) | `results/incidents.csv` |
| `\classVPct` | 32 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nClassV` | 21 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\classDPct` | 57 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nClassD` | 25 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\classSPct` | 11 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nClassS` | 6 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\classOPct` | 0.3 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\nClassO` | 5 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\sideEscrowPct` | 63 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\sideMintPct` | 19 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\sideBothPct` | 18 | Sec. 3.3 | events (bridge set of the event table) | `results/incidents.csv` |
| `\valueTimedB` | 3.7 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\valueTimedM` | 3,672 | Sec. 6.1 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\valueUntimedM` | 39 | Sec. 3.3 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\rampOneMPct` | 87.2 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\rampPointOneMPct` | 97.3 | Sec. 6.2 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\rampTenMPct` | 59.3 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\rampThirtyMPct` | 35.0 | Sec. 6.2 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\cliffDayPct` | 80.7 | Sec. 6.2 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\cliffOneHPct` | 8.9 | Sec. 6.2 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\cliffSixHPct` | 76.4 | Sec. 6.2 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\cliffThreeDPct` | 84.8 | Sec. 6.2 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\freezeOneMPct` | 97.4 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\freezeTenMPct` | 90.1 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\freezeHundredMPct` | 48.6 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\verifierMaxPct` | 27.0 | Sec. 1, Sec. 6.1 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\verifierCeilNoTopThreePct` | 51.2 | Sec. 6.1 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\verifierRampThirtyMPct` | 10.5 | not in the text | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\valueClassSTimedM` | 406 | Sec. 6.1 | event replay (Theorems on shape and placement) | `results/incidents.csv` |
| `\matchSmallTwelvePct` | 85.4 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchFullTwelvePct` | 75.3 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchSmallTwentyFourPct` | 58.6 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchFullTwentyFourPct` | 32.1 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchEnvFourHM` | 10.7 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchEnvFourHTwentyFourM` | 46.0 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robRampTimesTwoPct` | 80.3 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robRampPlusSixPct` | 83.3 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robRampPausesPct` | 89.7 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robPausesN` | 18 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robRampEventPct` | 32 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robRampNoLargestPct` | 85.0 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robLargestSharePct` | 17 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robCliffEventPct` | 79 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robMatchEventPct` | 25 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robMatchFullEventPct` | 19 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchEnvFourHFullM` | 30.9 | App. B | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\matchEnvFourHFullTwentyFourM` | 120 | App. B | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robVerifierMaxPct` | 36.7 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\robVerifierTopThreePct` | 48.5 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\stakeFlowMedianM` | 30.9 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\stakeFlowMeanM` | 49.8 | Sec. 10 | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\stakeFlowReviewMeanM` | 29.2 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketWormThreeH` | 1.14 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketWormSixH` | 1.07 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketWormDay` | 1.00 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketCcipOneMed` | 1.13 | Sec. 8 | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketCcipOneMax` | 2.38 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketCcipOneMedPct` | 13 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketCcipSixMed` | 1.05 | Sec. 8 | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketCcipSixMax` | 1.57 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\oneBucketCcipSixMedPct` | 5 | not in the text | traffic-matched replay, robustness, price of a single bucket (replay_matched.py) | `results/replay_matched.json` |
| `\plRampSepPct` | 87.2 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plRampGovPct` | 80.6 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plRampPessPct` | 75.8 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plRampVerPct` | 25.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plRampContractPct` | 82.8 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampTwoPct` | 80.3 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampFivePct` | 68.4 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampTenPct` | 62.8 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampOutflowPct` | 62.8 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampNoPausePct` | 80.6 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampAlertPct` | 87.9 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampAlarmPct` | 97.2 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampAlarmHourPct` | 96.1 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtRampAllPct` | 86.3 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\wtRampEventPct` | 32 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\wtRampNetPct` | 79.2 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plHoldSepPct` | 80.7 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plHoldGovPct` | 73.7 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plHoldPessPct` | 68.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plHoldVerPct` | 26.7 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plHoldContractPct` | 76.9 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldTwoPct` | 79.8 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldFivePct` | 71.8 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldTenPct` | 25.4 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldOutflowPct` | 64.9 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldNoPausePct` | 73.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldAlertPct` | 80.7 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldAlarmPct` | 99.7 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldAlarmHourPct` | 99.7 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtHoldAllPct` | 79.9 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\wtHoldEventPct` | 79 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\wtHoldNetPct` | 67.6 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plMatchSepPct` | 75.3 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plMatchGovPct` | 71.1 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plMatchPessPct` | 68.2 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plMatchVerPct` | 20.7 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\plMatchContractPct` | 72.0 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchTwoPct` | 71.7 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchFivePct` | 63.9 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchTenPct` | 56.9 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchOutflowPct` | 53.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchNoPausePct` | 71.1 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchAlertPct` | 75.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchAlarmPct` | 79.1 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchAlarmHourPct` | 79.1 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\rtMatchAllPct` | 74.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\wtMatchEventPct` | 19 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\wtMatchNetPct` | 67.0 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\vKeysCtrlN` | 12 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\vN` | 21 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\vKeysCtrlValuePct` | 10.9 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\dFlawReachN` | 2 | Sec. 6.1 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\dN` | 25 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\noPauseValuePct` | 11 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\outflowDetectedN` | 20 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\outflowDetectedValuePct` | 31 | Sec. 9 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\breakevenRamp` | 22.5 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\breakevenMatch` | 23.75 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\meanRespH` | 50 | Sec. 8 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\bestOneBDStarH` | 13 | Sec. 8 | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\bestOneBGainPct` | 2 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\bestTwoBDStarH` | 50 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\bestTwoBGainPct` | 13 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\kBucketsHullPct` | 6 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\kBucketsEnvPct` | 19 | not in the text | placement with control, response times as a variable, weightings, best bucket, K buckets | `results/replay_variants.json` |
| `\detThirdParty` | 21 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\detOperator` | 10 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\detUnknown` | 23 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\detShortfall` | 2 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\pauseIndependent` | 39 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\pauseNone` | 9 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\pauseControlled` | 4 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\pauseUnknown` | 5 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\classAgree` | 53 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\nRecovered` | 20 | Sec. 3.3 | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\recoveredM` | 1,744 | not in the text | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\recoveredPct` | 47 | Sec. 3.3 | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\nSingleChain` | 36 | Sec. 8.3 | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\nBorderline` | 37 | App. B | failure coding (results/incident_coding.csv) | `results/incident_coding.csv` |
| `\ccipInTodayDelayedPct` | 19.3 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipInTodayMeanDelayH` | 0.53 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipInTodayWaitPFifty` | 1.3 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevDelayedPct` | 0.8 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevMeanDelayH` | 0.014 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevPerMonth` | 2.4 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevValuePct` | 24 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevCapOne` | 0.62 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevCapSix` | 0.52 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevBreakevenH` | 2.2 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevAtOneH` | 0.25 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevVariants` | six | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevLowerBoth` | Five | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevBreakevenMinH` | 1.6 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipRevBreakevenMaxH` | 2.5 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\roninReviewN` | five | Sec. 8.1 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\roninReleasesAll` | 74,282 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\roninReviewMinH` | 15 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\roninReviewMedH` | 62 | Sec. 8.1 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\roninReviewMaxD` | 7.8 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipEthLagPOneMin` | 14 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipEthLagMedMin` | 17 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipNoRevDelayedPct` | 8.3 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipNoRevMeanDelayH` | 10.8 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipNoRevWaitPFifty` | 27 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipNoRevCapSix` | 0.60 | not in the text | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipLanesDisabledHalf` | 5 | Sec. 8.2 | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipInLanes` | 16 | Sec. 8.2, App. C | CCIP inbound buckets, review path, historical configurations | `data/ccip/derived/review_policy.json`, `data/ccip/derived/rolling_v2.json`, `results/review_latency_ronin.json`, `data/ccip/derived/lags.json` |
| `\ccipEntries` | 2,992 | Sec. 3.2 | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipEnabled` | 2,021 | Sec. 3.2 | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipActive` | 1,682 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipNearZero` | 331 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipRefillOneH` | 450 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipRefillDay` | 586 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipMedRefillH` | 6.0 | Sec. 3.2 | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipMedCapK` | 623 | Sec. 3.2 | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipCapQOneK` | 108 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipCapQThreeM` | 2.55 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipMedRateK` | 108 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipTokens` | 168 | not in the text | CCIP: census of outbound buckets (lanes.json) | `data/ccip/derived/limits_distribution.json` |
| `\ccipSelLanes` | 18 | Sec. 8.2, App. C | CCIP: the studied lanes (selection rule in ccip/selection.json) | `ccip/selection.json` |
| `\ccipSelSharePct` | 53.9 | Sec. 8.2 | CCIP: the studied lanes (selection rule in ccip/selection.json) | `ccip/selection.json` |
| `\ccipFitLanes` | 18 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipFitLanesBucket` | 17 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipLooseOne` | 7 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipTightOne` | 10 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipRatioMinOne` | 0.17 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipRatioMaxOne` | 7.69 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipInSampleDelayedOne` | 0 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipLooseSix` | 9 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipTightSix` | 8 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipRatioMinSix` | 0.31 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipRatioMaxSix` | 13.38 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipInSampleDelayedSix` | 0 | not in the text | CCIP: the deployed bucket against the zero-delay minimum at D (static, in sample) | `data/ccip/derived/recommended_buckets.json` |
| `\ccipOosLanes` | 18 | Sec. 8.2 | CCIP: static fit, first half against second half | `data/ccip/derived/out_of_sample.json` |
| `\ccipOosZero` | 8 | Sec. 8.2 | CCIP: static fit, first half against second half | `data/ccip/derived/out_of_sample.json` |
| `\ccipOosMaxPct` | 88 | Sec. 8.2 | CCIP: static fit, first half against second half | `data/ccip/derived/out_of_sample.json` |
| `\ccipOosOverHalf` | 3 | not in the text | CCIP: static fit, first half against second half | `data/ccip/derived/out_of_sample.json` |
| `\ccipLanes` | 17 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipLanesBucket` | 16 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipCurrentDelayedPct` | 21.2 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipSixDelayedPct` | 8.3 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipSixRatio` | 0.66 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipSixTwoDelayedPct` | 4.5 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipSixTwoRatio` | 0.88 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipOneTwoDelayedPct` | 5.8 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\ccipOneTwoRatio` | 1.71 | not in the text | CCIP: rolling recalibration of buckets matched to the response time | `data/ccip/derived/rolling_policy.json` |
| `\poolLow` | 2.6 | Sec. 8.3 | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\poolHigh` | 2.7 | Sec. 8.3 | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\poolRatioLowPct` | 37 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\poolRatioHighPct` | 39 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormChains` | 9 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormChainsWords` | nine | Sec. 8.3 | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormEnvOneHFullM` | 30.0 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormEnvOneHSmallM` | 8.7 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormEnvRatio` | 3.4 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormEnvDayFullM` | 42.8 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormEnvDaySmallM` | 29.6 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormBigN` | 397 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormBigValuePct` | 8.2 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormBigTwelveN` | 53 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\wormBigTwelveValuePct` | 5.8 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\govSuiHours` | 415 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\govSuiPct` | 2.4 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\govEthHours` | 13 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\govOtherMaxHours` | 75 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\govChains` | 9 | not in the text | Wormhole: envelopes, pooling, large transfers, Governor usage | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv` |
| `\stakeMaxRatio` | 0.16 | Sec. 10 | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeLargeMinM` | 16 | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeLargeMaxM` | 529 | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeLargeN` | three | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeLargeCoverWords` | Two | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeLargeCoverLow` | two | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeLinkM` | 529 | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakePolygonM` | 342 | Sec. 10 | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeAxelarM` | 16 | Sec. 10 | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeSlashableMaxM` | 1.3 | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeEmptyVaults` | 4 | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeEmptyVaultsWords` | four | not in the text | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeBlock` | 26,201,369 | App. C | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\stakeAxelarHeight` | 36,297,293 | App. C | stake against value held | `data/stake/onchain/valuation_20261016T000856Z.json`, `data/stake/api/axelar_reads_20261016T000617Z.json`, `results/replay_matched.json` |
| `\nRules` | 22 | Sec. 1, Sec. 3.2 | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesBounded` | 4 | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesBoundedWords` | four | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesBoundedControlled` | 3 | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesBoundedControlledWords` | three | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesVerifierSide` | 4 | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesVerifierSideWords` | four | Sec. 3.2 | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesAutoRelease` | 7 | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesAutoReleaseWords` | seven | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesNet` | 6 | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesNetWords` | six | Sec. 6.2 | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesNetSameToken` | 4 | not in the text | deployed rules (Table of rules) | `tex/rules.csv` |
| `\nRulesNetSameTokenWords` | four | Sec. 6.2 | deployed rules (Table of rules) | `tex/rules.csv` |
| `\gasPlain` | 38,135 | Sec. 12 | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasWindow` | 71,473 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasWindowExtra` | 33,338 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasQueue` | 100,716 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasExecute` | 62,824 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasExecuteMint` | 62,404 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasLimiter` | 163,540 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasLimiterExtra` | 125,405 | Sec. 12 | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasCancel` | 30,032 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasPause` | 29,662 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\gasHashSaving` | 44,200 | not in the text | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\nTests` | 48 | Sec. 12 | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\invRuns` | 256 | Sec. 12 | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\invDepth` | 100 | Sec. 12 | prototype gas (one escrow release; snapshot written by the harness) | `prototype/snapshots/GasBench.json`, `prototype/snapshots/test_summary.txt`, `prototype/foundry.toml` |
| `\nRulesReleaseOutside` | 13 | not in the text | rules by placement and control (rules.csv) |  |
| `\nRulesReleaseOutsideWords` | thirteen | Sec. 3.2 | rules by placement and control (rules.csv) |  |
| `\nRulesReleasePartlyWords` | three | Sec. 3.2 | rules by placement and control (rules.csv) |  |
| `\nRulesSendOnlyWords` | one | Sec. 3.2 | rules by placement and control (rules.csv) |  |
| `\nRulesNoPauseWords` | Five | Sec. 3.2 | rules by placement and control (rules.csv) |  |
| `\ccipGriefDayM` | 3.2 | Sec. 11 | rules by placement and control (rules.csv) |  |
| `\ccipMisLanes` | 17 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInLooseOne` | 7 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInTightOne` | 10 | not in the text | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInRatioMinOne` | 0.17 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInRatioMaxOne` | 8.09 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInLooseSix` | 9 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInTightSix` | 8 | not in the text | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInRatioMinSix` | 0.34 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInRatioMaxSix` | 13.94 | Sec. 8.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInEnabled` | 1,986 | Sec. 3.2 | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipInOutSharePct` | 98 | not in the text | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\ccipNoRefill` | 8 | not in the text | CCIP inbound buckets against each lane's traffic (ccip/inbound_mismatch.py) | `data/ccip/derived/inbound_mismatch.json` |
| `\classKappa` | 0.92 | not in the text | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\nSecondDisagreeWords` | three | App. B | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\classSExactPct` | 11.1 | App. B | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\classSRecodedPct` | 11.1 | App. B | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\ceilHighPct` | 27.4 | Sec. 6.1 | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\ceilLowPct` | 18.2 | Sec. 6.1 | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\verifierVisiblePct` | 27 | not in the text | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\nRedeemedLegs` | three | Sec. 6.1 | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\nVerifierChecksWords` | five | Sec. 6.1 | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\nSPossible` | 5 | App. B | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\nSDoubt` | 2 | App. B | coding agreement and the verifier-side ceiling under borderline readings |  |
| `\nValidation` | 13 | not in the text | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\nValidationWords` | thirteen | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoQuota` | 1,000 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoUsed` | 999 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninEthLock` | 4,000 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninEthDaily` | 4,500 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninEthUsed` | 103 | not in the text | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninUsdcLockM` | 2 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninUsdcDailyM` | 2.5 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninUsdcUsed` | 16,200 | not in the text | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoRate` | 41.7 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoRead` | 128.22 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoBound` | 297 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoOut` | 278 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoPct` | 94 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valTaikoMaxPct` | 99 | not in the text | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninEthBound` | 4,397 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninEthOut` | 3,996 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninEthPct` | 91 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninUsdcBoundM` | 2.48 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninUsdcOutM` | 2.00 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\valRoninUsdcPct` | 80 | Sec. 7 | failures that met a limit in force (validation.csv) | `tex/validation.csv`, `results/validation_bounds.json` |
| `\respBothN` | 18 | Sec. 9 | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respPauseFirstN` | 16 | Sec. 9 | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respAckAfterPauseH` | 2.2 | Sec. 9 | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respPauseOnchainN` | 13 | Sec. 9 | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respWeekendMedH` | 3.5 | not in the text | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respWeekdayMedH` | 3.7 | not in the text | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respWeekendP` | 0.75 | Sec. 9 | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respHourP` | 0.40 | Sec. 9 | how the first response was timed (response_protocol.py) | `results/response_protocol.json` |
| `\respIndepMedH` | 3.1 | not in the text | response times by pause holder and by period |  |
| `\respIndepN` | 33 | not in the text | response times by pause holder and by period |  |
| `\respEarlyMedH` | 3.1 | Sec. 9 | response times by pause holder and by period |  |
| `\respEarlyN` | 19 | Sec. 9 | response times by pause holder and by period |  |
| `\respLateMedH` | 5.0 | Sec. 9 | response times by pause holder and by period |  |
| `\respLateN` | 29 | Sec. 9 | response times by pause holder and by period |  |
| `\pbN` | 20 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbNAllWords` | twenty | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbNWords` | sixteen | Abstract, Sec. 1, Sec. 8.1, Sec. 14 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbValueSharePct` | 89 | Sec. 1, Sec. 8.1, Sec. 14 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbValueB` | 3.3 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFirstHistoryDays` | 40 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbSelectionText` | every failure with a recorded response of at least \$20 million except Mixin, whose custody sat in hot wallets on many chains that we could not enumerate, and seven smaller ones whose release point we could read. | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbApartText` | four more are shown apart: the 2024 Ronin failure met a deployed limit (Section~\ref{sec:validation}), and Anyswap's routers, QBridge and the AFX bridge went into service 40, 59 and 71 days before their failures, too late for the fit below. | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorPct` | 71.4 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorEventPct` | 78 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorLoPct` | 49 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorHiPct` | 90 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorNetPct` | 57 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbLargestLossShare` | 57 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbLargestLossDays` | 6 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbLargestLegitDayM` | 24 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbOthersN` | fifteen | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbOthersFloorPct` | 85.4 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketPct` | 72.2 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketEventPct` | 76 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketGovPct` | 69.2 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketFivePct` | 67.2 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketOutflowPct` | 61.0 | Sec. 9 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketDelayedPct` | 17 | Sec. 1, Sec. 8.1, Sec. 14 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketDelayedTwoPct` | 48 | Sec. 1, Sec. 8.1, Sec. 14 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketDelayedMaxPct` | 98 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketWaitMedH` | 14 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketHoursPerDollar` | 4.7 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketHoursPerDollarTwo` | 41 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewPct` | 77.7 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewEventPct` | 82 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewLoPct` | 53 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewHiPct` | 96 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewGovPct` | 73.4 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewOutflowPct` | 65.8 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewFivePct` | 69.9 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewDelayedPct` | 2.4 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewDelayedTwoPct` | 1.0 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewSharePct` | 38 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewShareTwoPct` | 48 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewTotalPct` | 40 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewTotalTwoPct` | 49 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewPerMonth` | 14 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewPerMonthTwo` | 15 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitOneH` | 0.4 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitOneHTwo` | 0.5 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitSixH` | 2.3 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitSixHTwo` | 3.0 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitDayH` | 9.1 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitDayHTwo` | 11.7 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewWaitOneMin` | 26 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbTestTransfers` | 115,811 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbTestTransfersTwo` | 141,544 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmHourPct` | 94.5 | Sec. 9 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmHourEventPct` | 92 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmHourLoPct` | 92 | Sec. 9 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmHourHiPct` | 97 | Sec. 9 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketAlarmHourPct` | 73.0 | Sec. 9 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorAlarmHourPct` | 76.9 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbAlarmOnlyHourPct` | 14 | Sec. 9 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmTenPct` | 95.4 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmTenEventPct` | 93 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmTenLoPct` | 93 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbReviewAlarmTenHiPct` | 97 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketAlarmTenPct` | 73.4 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbFloorAlarmTenPct` | 78.5 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbAlarmOnlyTenPct` | 32 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbHundredPct` | 85.1 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbHundredEventPct` | 85 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbHundredSharePct` | 66 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbHundredPerMonth` | 92 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbHundredAlarmHourPct` | 97.0 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbVarFloorPct` | 78.9 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbVarReviewPct` | 77.7 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbVarDroppedN` | three | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbPolyUnpricedPct` | 43 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbPolyTwoUnpricedPct` | 31 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbWinReviewPct` | 77 to 78 | not in the text | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketOnePct` | 72.7 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketOneDelayedPct` | 16 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketDayPct` | 69.5 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketDayDelayedPct` | 18 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketFiftyPct` | 67.7 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbBucketFiftyDelayedPct` | 20 | Sec. 8.1 | per-bridge counterfactual on each failed bridge's own traffic (replay_perbridge.py) | `results/replay_perbridge.json` |
| `\pbGateMin` | 10 | Abstract, Sec. 1, Sec. 5, Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbFloorPctR` | 71 | Abstract, Sec. 1, Sec. 5, Sec. 14 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketPctR` | 72 | Abstract, Sec. 1, Sec. 5, Sec. 9, Sec. 11, Sec. 14 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewPctR` | 78 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateWorksPctR` | 100 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewSparePct` | 99.8 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateHoursPerDollar` | 0.17 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateWorksPct` | 100.0 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateFailsPct` | 72.2 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateWorksMatchPct` | 99.9 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateAloneFailsPct` | 0 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateAloneWorksPct` | 100 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\checkSeesPct` | 99.7 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\checkMatchSeesPct` | 89 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\checkKeysHeldVPct` | 8 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateBuiltPct` | 96 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewCheckFailsPct` | 8 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewAlarmCheckFailsPct` | 8 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLoosePct` | 63.9 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseGateWorksPct` | 100.0 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseDelayedPct` | 7 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseDelayedTwoPct` | 35 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseHoursPerDollar` | 1.4 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseHoursPerDollarTwo` | 9.7 | Sec. 9 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketCountPct` | 0.8 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketCountTwoPct` | 12.7 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewCountPct` | 0.4 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewCountTwoPct` | 0.3 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseCountPct` | 0.1 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbLooseCountTwoPct` | 2.8 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketWaitNinetyNineTwoH` | 219 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewPerMonthMed` | 1 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewPerMonthMax` | 148 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketKeysHeldPct` | 69.2 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewKeysHeldPct` | 74.5 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbPauseFirstN` | ten | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbPauseFirstFloorPct` | 65 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbPauseFirstBucketPct` | 67 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbPauseFirstReviewPct` | 71 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketNetPct` | 57 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewNetPct` | 63 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateWorksNetPct` | 100 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbFloorLooLoPct` | 66 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbFloorLooHiPct` | 85 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewLooLoPct` | 73 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbReviewLooHiPct` | 93 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketLoPct` | 49 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbBucketHiPct` | 90 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbGateWorksLoPct` | 100 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbRoninEnvM` | 855 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbRoninOutsizedM` | 722 | Sec. 1, Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbRoninEnvTrimM` | 342 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbRoninFloorTrimPct` | 37 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\pbRoninTakenM` | 540 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\dbLowerPct` | 8 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\dbLowerTwoPct` | 23 | Sec. 8.1 | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\coverEntries` | 92 | App. B | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\coverMatched` | 43 | App. B | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\coverLeftOut` | 9 | App. B | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\coverSmall` | 32 | App. B | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\coverNotBridge` | seven | App. B | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\coverAfter` | 33 | App. B | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\fpPausedTimePct` | 1.8 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\fpWaitPerDollar` | 0.009 | not in the text | the check that a deposit backs each release, used as a gate (a hold on every withdrawal while it runs, the bucket behind), as the review of the largest transfers, or as an alarm; what each design keeps when the check works and when it fails (replay_perbridge.py, check_sees), its cost in counts and tails, and the subsets and weightings | `results/delay_budget.json`, `results/coverage.json` |
| `\gasPriceGwei` | 0.20 | Sec. 12 | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasPriceNinetyGwei` | 0.61 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\ethUsd` | 2,441 | Sec. 12 | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasExtraUsd` | 0.06 | Sec. 12 | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasExtraNinetyUsd` | 0.19 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasExtraThirtyUsd` | 9 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasTunedOne` | 79,161 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasTunedFour` | 95,981 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasTunedPerBucket` | 5,606 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasTunedTotal` | 207,384 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasTunedExtra` | 169,249 | Sec. 12 | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\gasTunedExtraUsd` | 0.08 | Sec. 12 | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\nTestsTuned` | 12 | not in the text | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\nFuzzRuns` | 1,000 | Sec. 12 | the prototype's overhead in dollars (prototype/snapshots/gas_price.json) | `prototype/snapshots/gas_price.json`, `prototype/snapshots/TunedGasBench.json`, `prototype/snapshots/test_suites.txt` |
| `\blindN` | 57 | not in the text | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\blindAgree` | 55 | Sec. 3.3, Sec. 13, App. B | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\blindKappa` | 0.95 | Sec. 3.3, App. B | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\blindDisValuePct` | 0.4 | Sec. 3.3 | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\blindVerifierPct` | 27 | Sec. 6.1, App. B | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\blindPauseAgree` | 54 | App. B | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\blindPauseN` | 57 | not in the text | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\keysHeldPct` | 17 | Sec. 6.1 | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\keysHeldN` | 8 | Sec. 6.1, App. B | blind recoding by an independent coder (coding/agreement.py -> results/blind_agreement.json) | `results/blind_agreement.json` |
| `\tbForgedN` | 12 | Sec. 12 | forged deposits (prototype/testbed/run_forged.py, summarize_forged.py -> results/testbed_forged.json): a monitor matching requests to recorded deposits against one that also requires the value to have moved | `results/testbed_forged.json` |
| `\tbForgedDetectMaxS` | 12 | not in the text | forged deposits (prototype/testbed/run_forged.py, summarize_forged.py -> results/testbed_forged.json): a monitor matching requests to recorded deposits against one that also requires the value to have moved | `results/testbed_forged.json` |
| `\tbForgedPauseMaxS` | 12 | Sec. 12 | forged deposits (prototype/testbed/run_forged.py, summarize_forged.py -> results/testbed_forged.json): a monitor matching requests to recorded deposits against one that also requires the value to have moved | `results/testbed_forged.json` |
| `\tbForgedRecordReleasedM` | 2.9 | Sec. 12 | forged deposits (prototype/testbed/run_forged.py, summarize_forged.py -> results/testbed_forged.json): a monitor matching requests to recorded deposits against one that also requires the value to have moved | `results/testbed_forged.json` |
| `\tbForgedPoints` | ten | not in the text | forged deposits (prototype/testbed/run_forged.py, summarize_forged.py -> results/testbed_forged.json): a monitor matching requests to recorded deposits against one that also requires the value to have moved | `results/testbed_forged.json` |
| `\tbReleasesOrbit` | 4,152 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbReleasesNomad` | 14,532 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbLegitRequests` | 56,052 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbNomadDelayedPct` | 14 | not in the text | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbBurstOrbitM` | 2.6 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbBurstNomadM` | 13.1 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbFalseAlarms` | 0 | not in the text | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbEpisodes` | 636 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbRuns` | four | not in the text | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbPauseMaxS` | 60 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbHoldReleased` | 0 | not in the text | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbFinalityGapMinM` | 10 | not in the text | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbFinalityGapMaxM` | 12 | not in the text | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbReorgTargets` | 119 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbReorgOnceMax` | 19 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbReorgRecheckMaxS` | 48 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbRtPauseMinS` | 2 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbRtPauseMaxS` | 60 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\tbRtEpisodes` | 36 | Sec. 12 | end-to-end testbed (prototype/testbed/summarize.py -> results/testbed.json) | `results/testbed.json` |
| `\shRel` | 13,261 | Sec. 1, Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shUsdM` | 29.5 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shUnmatched` | thirteen | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shFeeTokens` | three | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shNotFinal` | three | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shNotFinalAgeMin` | three | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shNotFinalWaitMin` | 14 | not in the text | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveStart` | 16 October | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveDays` | 15.6 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveAll` | 5,673 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveUpPct` | 49 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveN` | 2,904 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveCaughtN` | 2,846 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveWaitedN` | 58 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveWaitedOver` | 30 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveMedS` | 36 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveNinetyNineS` | 164 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveMaxS` | 351 | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shLiveAlarmText` | raised 22 alarms: a re-check cleared the 21 read errors from a public node, and the other was one more release paid in parts | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shTwinN` | 8,701 | not in the text | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\shTwinText` | flagged all 8,701 test copies we made of live releases | Sec. 9 | the check in shadow beside two live bridges between Ethereum and BSC | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` |
| `\exHeldM` | 100 | Sec. 1, Sec. 4 | the running example of the introduction |  |
| `\exRateM` | 2 | Sec. 1, Sec. 4 | the running example of the introduction |  |
| `\exLossM` | 9.4 | Sec. 1, Sec. 4 | the running example of the introduction |  |

## Files and the scripts that write them

| File | Written by |
|---|---|
| `tex/rules.csv` | compiled by hand (results/limiter_code_facts.md Section 3, deploy_controls.md, rules_controls.csv) |
| `tex/validation.csv` | compiled by hand (checked against results/validation_bounds.json) |
| `ccip/selection.json` | selection rule applied to the CCIP crawl (level 3) |
| `data/ccip/derived/inbound_mismatch.json` | ccip/inbound_mismatch.py |
| `data/ccip/derived/lags.json` | ccip/lags.py |
| `data/ccip/derived/limits_distribution.json` | ccip/limits_distribution.py |
| `data/ccip/derived/out_of_sample.json` | ccip/out_of_sample.py |
| `data/ccip/derived/recommended_buckets.json` | ccip/recommend_buckets.py |
| `data/ccip/derived/review_policy.json` | ccip/review_policy.py |
| `data/ccip/derived/rolling_policy.json` | ccip/rolling_policy.py |
| `data/ccip/derived/rolling_v2.json` | ccip/rolling_v2.py |
| `data/stake/api/axelar_reads_20261016T000617Z.json` | stake/axelar_reads.py (level 3), extract |
| `data/stake/onchain/valuation_20261016T000856Z.json` | stake/value_calc.py (level 3), extract |
| `data/wormhole/derived/pooling_clean.json` | wormhole/pooling_clean.py |
| `data/wormhole/flows/summary.json` | wormhole/analyze_series.py |
| `data/wormhole/flows/usage.csv` | wormhole/analyze_series.py |
| `prototype/foundry.toml` | prototype configuration |
| `prototype/snapshots/GasBench.json` | forge test (prototype) |
| `prototype/snapshots/TunedGasBench.json` | forge test (prototype) |
| `prototype/snapshots/gas_price.json` | prototype/gas_price.py (level 3) |
| `prototype/snapshots/test_suites.txt` | forge test console output (prototype) |
| `prototype/snapshots/test_summary.txt` | forge test console output (prototype) |
| `results/blind_agreement.json` | coding/agreement.py |
| `results/coverage.json` | coverage/counts.py |
| `results/delay_budget.json` | delay_budget.py |
| `results/incident_coding.csv` | coded by hand (rules in results/incident_coding.md) |
| `results/incidents.csv` | incidents/05_build_dataset.py |
| `results/replay_matched.json` | replay_matched.py |
| `results/replay_perbridge.json` | replay_perbridge.py |
| `results/replay_variants.json` | replay_variants.py |
| `results/response_protocol.json` | response_protocol.py |
| `results/review_latency_ronin.json` | data/review_latency/ronin_public.py (level 3) |
| `results/shadow_fee_tokens.json` | shadow/fee_token_check.py (level 3: reads the collector's receipt cache) |
| `results/shadow_live.json` | shadow/live_monitor.py summary (from the live records in shadow/live/) |
| `results/shadow_run.json` | shadow/simulate.py |
| `results/testbed.json` | prototype/testbed/summarize.py |
| `results/testbed_forged.json` | prototype/testbed/summarize_forged.py |
| `results/validation_bounds.json` | validation_bounds.py |
