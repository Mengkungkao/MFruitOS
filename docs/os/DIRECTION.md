# Project direction and goals

MFruit OS makes small Linux devices useful through one predictable launcher,
consistent controls and independently installable applications. The product
name is **MFruit OS**. Whisplay identifies today's hardware integration, not
the identity of the platform.

## Goals

| Goal | What success looks like |
|---|---|
| Easy to use | Users can see the selected item, open it once, leave it reliably and recover from failure using one button or a keyboard. |
| Easy to develop | Each responsibility has a clear owner; offline tests and previews give fast feedback; contributors can find one authoritative guide for each contract. |
| Feasible to integrate | A new app can start from the template, validate a manifest, package its dependencies and data, install, launch, stop and update without changes to the launcher. |
| Reliable on small boards | Work fits the Raspberry Pi Zero 2 W resource budget; idle input and rendering do not busy-loop; heavy jobs do not freeze navigation. |
| Portable over time | Core lifecycle, registry and package logic remain separate from the hardware host; adapters replace the current Whisplay coupling incrementally. |

MFruit OS is an application operating environment, not a new Linux distribution,
kernel or board-driver installer. Application features belong in applications;
shared navigation, lifecycle and package behavior belong in the platform.

## Current capability and target

This table describes the current 1.4.0 source. A capability existing in code
does not mean every device path has been verified. Use
[known issues](../quality/KNOWN_ISSUES.md) for the current evidence boundary.

| Area | Implemented now | Intended direction |
|---|---|---|
| Launcher and settings | Pillow UI, screen stack, button gestures, keyboard hub, settings and diagnostics on Whisplay | Preserve the same user model across hosts. |
| Application lifecycle | Hardware-independent `ApplicationManager`, one active session, session IDs; Whisplay `FocusController` performs the handoff | Extract process and host responsibilities behind tested interfaces without changing launch semantics. |
| Processes | Daemon starts apps through `mfruit-run`; `AppLifecycle` manages tickets, registration, run records and cleanup | A dedicated `ProcessManager` or equivalent host service, justified by concrete adapter needs. This class does not exist yet. |
| Packages and updates | Manifest/registry, GitHub releases, catalogue recipes, local sideloading, version directories, rollback and system boot guard | Keep GUI and CLI on the same services; make dependency/platform compatibility explicit as new hosts are introduced. |
| Hardware independence | Lifecycle/manifest/package logic can be tested offline; `--preview` and `--self-test` render without a daemon | Generic display, input, LED, audio and power adapters; a runnable mock/terminal host. Full launcher independence is unfinished. |
| Whisplay integration | Daemon sockets and framebuffer, background UI wrapper, direct display fallback using `WhisplayBoard` | Move platform-specific code behind adapters; keep Whisplay functioning throughout. |
| App API | Vendored Python SDK for input, status, UI and daemon access | Evolve a host-independent API without breaking installed apps; current SDK daemon access is still Whisplay-specific. |
| Diagnostics/recovery | `mfruitctl status`, logs, diagnostic screens, fallback display, retained versions and boot guard | A documented safe mode and offline diagnostic entrypoint after their implementation and tests exist. |
| Permissions | Package validation and file containment; apps run as the device user | Explicit capabilities and enforcement are future work. There is no general app sandbox today. |

The existing CLI is `python3 -m mfruitos` and `mfruitctl`. Commands such as
`mf-os --headless`, `mf-os --safe-mode` and `mf-os doctor` in earlier planning
notes were proposals, not supported commands. Use the actual commands in
[Development](DEVELOPMENT.md#local-development) and
[Installation](../../INSTALL.md).

## Target architecture

```text
Launcher UI / CLI / independent apps
                |
       Shared platform services
  navigation, lifecycle, registry, packages,
  settings, diagnostics, update orchestration
                |
      Host and hardware interfaces
       /           |            \
   Whisplay     mock/terminal    future hardware
                |
               Linux
```

This is a target boundary, not a map of completed modules. The current source
map and ownership are in [Architecture](../ARCHITECTURE.md). Reuse working code;
move one responsibility at a time. Do not replace the implementation wholesale
to match the diagram.

## Phased roadmap

Phases are ordered by dependency, with acceptance criteria instead of promised
dates. A phase is complete only when its evidence is recorded. Small maintenance
and app fixes may proceed independently; major ecosystem expansion waits for
the launch lifecycle baseline.

| Phase | Work | Acceptance criteria |
|---|---|---|
| 1. Establish a reliable baseline | Resolve the outstanding daemon-page launch-window test using observed state; preserve input ownership, single-flight launching and app cleanup. | The regression fails with the relevant guard removed; timing-sensitive tests pass repeatedly; the complete suite passes on the intended Linux revision with skips disclosed; the board input checklist is recorded separately. |
| 2. Make the integration path repeatable | Use the template and one app contract; validate release packages; document dependencies, SDK version, logs and data; validate install/update/rollback with disposable data. | A clean checkout becomes an installable app without launcher edits; install, launch, exit, reinstall, update and rollback have recorded results; SDK sync check passes for the apps being released. |
| 3. Extract host boundaries | Start from `ApplicationManager.Host`; isolate `focus.py`, daemon transport and `system/hardware.py`; keep the wrapper and direct fallback in the Whisplay implementation. Introduce process ownership interfaces only where needed. | Existing Whisplay regressions remain intact; core contract tests run without the Whisplay checkout; two hosts satisfy the same lifecycle/input contracts; all temporary coupling is documented. |
| 4. Deliver a usable offline host | Add a mock or terminal runtime, then documented recovery/diagnostic commands using the existing services. | Developers can navigate, launch a fake app, stop it, inspect failure, change settings and exercise disposable package operations without a daemon or HAT; invalid configuration and broken apps remain recoverable. |
| 5. Broaden hardware and app capabilities | Validate another adapter; define optional permissions, notifications and richer app services only when an app needs them. | A second adapter passes shared contract tests and its own physical checklist; capability failures are visible; any permission claim has enforcement tests and migration guidance. |

The latest handoff reports installation completed on the Raspberry Pi, but
`test_press_during_launch_window_page_is_closed` still needs investigation and
a complete passing suite rerun remains pending. Installation success and screen
rendering do not complete phase 1. See [known issues](../quality/KNOWN_ISSUES.md)
and [the current handoff](../../CONTINUE.md) before changing that status.

## Decision rules

1. Fix lifecycle, navigation and input correctness before adding major features.
2. Prefer an existing service, SDK component or standard-library facility over
   a parallel implementation or heavy dependency.
3. Keep application-specific behavior in the app. Add a shared service only
   when its ownership, callers and failure behavior are clear.
4. Separate required behavior from implemented behavior and tested behavior in
   every design note. Proposed commands or manifest fields must say **planned**.
5. Record a meaningful architecture change with its reason, alternatives,
   compatibility impact and verification; update the relevant canonical guide.

[OS development](README.md) · [App integration](../apps/README.md) · [Quality](../quality/README.md)
