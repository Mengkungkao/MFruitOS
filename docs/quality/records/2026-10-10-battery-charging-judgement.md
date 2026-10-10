# 2026-10-10 — Battery shown as charging with no charger connected

- **Revision:** `b473f0b` plus the uncommitted change described here
- **Platform:** dev machine (Jetson, Linux 6.8 tegra, Python 3.12); register-level fakes only
- **Device:** none. The Raspberry Pi Zero 2 W with the PiSugar 2 was not
  reachable over Wi-Fi during this work ("No route to host"), although its
  radio was still heard by the Orange Pi.

## Bug record

- **Problem:** the owner reported that RadioConnect sometimes shows the
  battery as charging when no charger is connected.
- **Expected behavior:** "charging" only while external power is connected.
- **Reproduction:** `tests.test_power.ChargingJudgementTests` feeds a PiSugar
  2 (four LEDs) fake a discharging battery: −3 mV a minute, ±4 mV of noise,
  and a 25 mV dip for 3 s every 45 s, like a radio transmitting.
- **Evidence:** RadioConnect shows what `get battery_charging` on
  `/tmp/pisugar-server.sock` answers (`app/utils/battery.py`). On the Pi Zero
  that socket is served by `mfruit-power.service`, which found a "PiSugar 2"
  there today. That model cannot sense external power, so
  `PowerService.charging()` used PiSugar's rule: the oldest of the last 30
  one-second samples below their mean and the newest above it
  (pisugar-power-manager-rs `ip5209.rs` `is_charging` does the same). The
  first device reading today (14:31, 3.851–3.854 V, "charging") came from
  this rule.
- **Root cause:** the rule compares single samples, so a few millivolts of
  noise, or the voltage recovering after a load, satisfy it on a battery
  that is discharging. In the reproduction it reported charging for 147 of
  900 seconds. A false "charging" also counts as external power for the
  low-battery shutdown: the countdown was cancelled and restarted many times
  and the power-off never ran.
- **Fix:** `mfruitos/power/charging.py` `ChargeJudge`, used by
  `PowerService` only for boards whose sample has no external-power reading.
  Charging is judged from a step of 0.1 V or more between the last whole
  minute's average and the last 10 samples (plugging in or out), or from
  three successive rising minute averages, 15 mV in all (starting on
  external power). It ends on a step down or when a minute's average is 8 mV
  below the recent highest. Changes are logged as "Battery charging (judged
  from the voltage: …)".
- **Regression test:** `ChargingJudgementTests` (5 tests). Negative control:
  with the old rule put back, 4 of 5 fail ("147 != 0" for the discharging
  board, and repeated `low_battery_cancelled` events with no power-off); with
  the fix all pass.
- **Hardware validation:** required on a PiSugar 2 with four LEDs, NOT
  PERFORMED (Pi Zero not reachable). The thresholds come from the physics
  (charge current times internal resistance), not from measured traces.
- **Compatibility:** boards that sense external power (PiSugar 3, PiSugar 2
  with two LEDs, PiSugar 2 Pro) are unchanged. On a four-LED PiSugar 2,
  "charging" now appears within about 10 s of plugging in. A board that
  starts already plugged in shows it after about four minutes, where the old
  rule flickered.

## Commands and results

| Check | Command | Result |
|---|---|---|
| New tests | `python3 -m unittest tests.test_power.ChargingJudgementTests` | AUTOMATED: 5 OK |
| Negative control | the same, with the old rule restored in `PowerService.charging()` | 4 FAIL, as expected |
| Power suite | `python3 -m unittest tests.test_power` | AUTOMATED: OK |
| Full check | `bash scripts/check.sh` | AUTOMATED: all checks passed, 655 tests OK |

## Not verified

- The judgement on a real PiSugar 2: plugging in, unplugging, starting
  plugged in, a full battery on the charger.
- The current's sign on battery (KI-13).
