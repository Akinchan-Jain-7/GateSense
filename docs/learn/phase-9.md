# Phase 9 study guide: polish, docs, release

## What we built and why

Phase 9 adds no new features. It makes the project easy to judge and easy to explain.
A recruiter spends about a minute on a README, so it now opens with a picture of the
product, then says in one sentence what GateSense is, then gives the measured results.
The architecture document explains how the parts fit together with diagrams. The demo
script plans a 90-second video. The interview guide has the pitch, a whiteboard
walkthrough and answers to the hardest questions. The release notes say what v1.0.0
contains. The plate detector was also trained on real data in this period (on Kaggle), so
the README's results table now has a real accuracy number instead of "TBD".

## Key concepts, simply

**Recruiter-first README.** Put the things a busy reader looks for at the top: what it
is, what it looks like, whether it's live, and what the numbers are. How to install and
the folder layout come later, for the reader who is still interested.

**Honest results.** Every number in the README comes from a run we did and links to the
file that records it. Where something isn't measured yet, the README says "not measured
yet" and why. A made-up or vague number is easy to catch in an interview and costs more
trust than a gap.

**Known limitations.** Saying what doesn't work yet (no live demo, OCR not measured, a
small training set, Telegram tested with a fake bot) shows you understand your own
system. Interviewers often ask "what would you improve?" This section is the answer.

**Held-out test set.** The detector was tested on photos from a *different* dataset
(Gujarat plates) than the ones it trained on. Scores on photos that look like the training
photos are usually too optimistic. A separate source gives a fairer number. That's why the
test mAP (0.745) is lower than the validation mAP (0.848), and the test number is the one
we report.

**mAP@0.5.** For each predicted box, check whether it overlaps a real plate by at least
50% (IoU ≥ 0.5). Precision and recall at every confidence level give a curve; the area
under it is AP. With one class (plate), mAP = AP. mAP@0.5:0.95 averages over stricter
overlaps too, so it rewards tight boxes.

**Semantic versioning and tags.** `v1.0.0` means: major 1 (first stable version),
minor 0, patch 0. A git tag marks the exact commit; the GitHub release attaches notes
(and, for us, the model file) to it.

**Badges.** Small images at the top of the README. The CI badge updates by itself from
GitHub Actions. The coverage badge is fixed text, updated by hand when coverage changes,
because we don't send reports to a coverage service.

## Files to read, in order

1. `README.md`: the order of the sections, and how each result links to its source.
2. `docs/architecture.md`: the components, the path of one plate read, the visit state
   machine, the scheduled jobs.
3. `anpr/eval/results/detector_comparison.md`: the training data, the split, and why
   YOLOv8n won.
4. `docs/adr/0009-anpr-pipeline-and-model-choice.md`: the "Outcome" section. The rule for
   choosing a model was written *before* training.
5. `docs/learn/INTERVIEW_GUIDE.md`: practise the 2-minute pitch out loud.
6. `docs/demo-script.md`: what to show in 90 seconds.
7. `docs/release-notes-v1.0.0.md`: the whole project on one page.

## Decisions and the alternatives we rejected

- **Static coverage badge instead of Codecov.** Codecov would need an account and a
  token. The three coverage numbers are already enforced in CI, so a fixed badge is
  honest and has no moving parts.
- **"Not deployed yet" badge instead of hiding it.** Hiding the gap would look better for
  a day but worse in an interview. The badge changes when the host is set up.
- **Training on Kaggle instead of Colab.** Kaggle gives a free T4 GPU with a weekly quota,
  and its datasets attach directly as notebook inputs, so nothing needs an API key. The
  notebook still runs on Colab too.
- **Only datasets with a clear licence.** The biggest Indian plate dataset has no stated
  licence and mixes augmented copies of photos into its test split, so it was skipped, even though
  it would likely have given a higher (but less trustworthy) score.
- **Tag after review, not automatically.** A release is public and permanent, so the
  owner reviews before `v1.0.0` is tagged.

## Likely interview questions

1. **Walk me through your project in two minutes.** Use the pitch in the interview guide:
   the problem (guards writing plates in a register), the flow (camera → plate → resident,
   visitor or watchlist), what you measured, and one hard problem you solved.
2. **How accurate is your plate detector, and how do you know?** mAP@0.5 of 0.745 on 354
   photos from a dataset it never saw in training. Validation was 0.848, but validation
   photos come from the same sources as training.
3. **Why YOLOv8n and not the bigger YOLOv8s?** The rule was fixed in advance: take the
   small model unless the big one is clearly better. YOLOv8s was slightly better on
   mAP@0.5 but worse on mAP@0.5:0.95, and is 3.5× bigger and about 3× slower on CPU.
4. **What would you improve first?** Measure OCR on real local photos, then retrain the
   detector with the guard corrections the system already saves.
5. **What isn't finished?** Live deployment (waiting on a host), OCR accuracy, and a real
   Telegram test. Each one is listed with the reason.
6. **How do you keep the numbers in your README honest?** Each one links to a results file
   made by a script or notebook, with the date and machine. Unmeasured things say so.
7. **What does mAP@0.5:0.95 tell you that mAP@0.5 doesn't?** How tight the boxes are. A
   loose box still counts at IoU 0.5 but fails at 0.9.
8. **Why write ADRs?** So the reason for a decision survives. Months later, "why Celery
   and not cron?" has a written answer with the alternatives considered.
9. **How would you take this to a real society?** Run the ANPR worker on a small computer
   at the gate, host the API, collect a week of real plates, retrain, and set the
   thresholds from what the guards correct.
10. **What did you learn?** Pick one real thing: the state machine making bugs visible,
    the load test finding a bottleneck you didn't expect, or a test set from another
    source giving a lower but more honest number.

## Exercise

Open `anpr/eval/results/detector_comparison.json`. Find YOLOv8n's validation and test
mAP@0.5. Write two sentences explaining why they differ, then check your answer against
the "Held-out test set" section above.
