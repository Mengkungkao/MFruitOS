# ADR 0006 — Settings provider apps instead of a hard-coded Wi-Fi app

Status: **Proposed** 2026-10-02 — needs the project owner's decision before
implementation (it adds a manifest field, [Part I §9](../DEVELOPMENT_RULES.md#9-app-integration-contract)).

## Context

The platform special-cases the app ID `connectwifi` (KI-2 in
[known issues](../../quality/KNOWN_ISSUES.md)):

| Where | Special case |
|---|---|
| `launcher/services.py` `launch_app` | no "Opening <App>" screen; Settings stays visible until the app draws |
| `apps/registry.py` `SETTINGS_APPS` | excluded from Home entries |
| `launcher/ui/screens/settings.py` | *Settings → Wi-Fi* launches it when installed |
| `launcher/ui/screens/updater.py` `InstallAppScreen` | excluded from the restorable-app list (with two daemon IDs) |
| `provision.py` | bundled install, hidden on Home, part of the curated menu |

This violates [Part I §33](../DEVELOPMENT_RULES.md#33-do-not) ("hard-code
applications in launcher logic"): another Wi-Fi app cannot take its place, and
the platform knows an application's identity.

## Proposed decision

Add an optional manifest field naming the Settings page an app provides:

```json
{ "settings_provider": "wifi" }
```

- **Values:** a closed set owned by the platform; initially only `wifi`.
- **Validation:** unknown values are rejected by `validate_manifest`.
- **Behavior:** the registry exposes `settings_provider(page)`; an app with
  the field is not listed on Home, launches without an Opening screen
  (Settings stays until its first frame), and *Settings → <page>* opens it. If
  several apps provide a page, the user's choice in Settings wins, else the
  most recently installed.
- **Owner:** registry (lookup) and Settings screen (entry point);
  `ApplicationManager` is unchanged.
- **Old mFruit OS versions:** ignore the unknown field; the bundled ConnectWifi
  keeps working there through today's special case.
- **Migration:** ConnectWifi's bundled manifest gains the field. Installed
  copies without it are recognized through a single, documented compatibility
  alias (`connectwifi` → `wifi`) in the registry, removed after one release in
  which provisioning refreshes the bundled package.
- Provisioning keeps installing the bundled Wi-Fi app, identified through the
  bundle's manifest rather than a literal ID.

## Alternatives

- **Keep the hard-coded ID** — rejected long-term (§33), acceptable until
  decided.
- **A settings key naming the Wi-Fi app** — moves the coupling into
  configuration without letting the app declare what it provides.
- **Generic "hidden from Home" field** — covers one of the five special cases
  only.

## Consequences

The platform stops knowing application IDs; another Wi-Fi app can be
installed. One compatibility alias remains for one release.

## Compatibility

No change for installed apps without the field. Apps declaring it require
the mFruit OS version that introduces it (`min_os_version`).

## Validation

Manifest tests for the field; registry tests for lookup, alias and multiple
providers; screen tests for Settings → Wi-Fi and Home filtering; the existing
installer navigation tests; a device check that Settings → Wi-Fi still opens
without an Opening screen and returns to Settings.
