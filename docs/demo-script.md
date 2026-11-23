# 90-second demo video script

For a screen recording of the live demo (or the local stack with the simulator running).
Record at 1440×900, browser zoom 100%, light theme except the guard console. Speak the
narration; the "Show" column is what's on screen. Timings are targets, not limits.

**Before recording:** Admin → Settings → *Reset demo* (fresh data), make sure the simulator
is running, and open three browser windows side by side or as tabs: guard
(`guard@example.com`), resident (`resident@example.com`, phone-sized window) and admin
(`admin@example.com`). Password `GateSense@123`.

| Time | Show | Say |
|---|---|---|
| 0:00–0:08 | Landing page, then click *Try demo as Guard* | "This is GateSense: number-plate entry for housing societies. Residents drive in, visitors get approved by the flat, and overstays get followed up automatically." |
| 0:08–0:22 | Guard console (dark). Point at the live feed as a resident car arrives, the plate chip and snapshot | "This is the night guard's screen. Cameras read plates; a resident's car is logged by itself. Each read shows the photo and the plate the system understood." |
| 0:22–0:40 | A visitor arrives: unknown plate → *Register visitor* → name, phone, flat B-402 → submit | "An unknown car. The guard registers the visitor in two taps, and flat B-402 is asked to approve." |
| 0:40–0:52 | Resident window: the approval card appears live → *Approve*. Back to the guard: the card moves to approved | "The resident gets it instantly, here and on Telegram, and approves. If nobody answers in three minutes, the guard decides." |
| 0:52–1:02 | Guard: the watchlist alert (red) for HR26DK8337, then the escalation column with a "call the resident" task | "A watchlisted car raises a red alert. Visitors who stay too long are emailed, reminded, then turned into a call task for the guard." |
| 1:02–1:15 | Admin overview: busiest hours, overstay rate, vehicles inside; flick to the audit log | "The secretary sees the numbers: busiest hours, average stay, overstay rate, and every admin change in an audit log." |
| 1:15–1:25 | Switch the guard console to Hindi; show the phone-sized resident app | "Hindi for the guard, a phone app for residents, accessible in light and dark." |
| 1:25–1:30 | README results section or the architecture diagram | "Under the hood: FastAPI, PostgreSQL, Redis, Celery, React, and a YOLO plate detector at the gate. Code and results are on GitHub." |

## Tips

- Keep the mouse still while talking; move it only to the thing you're describing.
- If the simulator hasn't produced a visitor at the right moment, register one yourself
  (any plate like `MH12DE1433`); the flow is the same.
- Trim dead time in editing rather than rushing the narration.
- Export as MP4 for the video, and a 10–15 second GIF of 0:08–0:52 (guard → resident
  approval) for the top of the README. Keep the GIF under ~5 MB.
