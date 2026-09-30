"""Updater screens. Network work runs through ``os.run_task`` / ``os.start_job``."""

from __future__ import annotations

import os as filesystem
import time

from mfruitos import OS_APP_ID, OS_NAME, __version__
from mfruitos.launcher.ui.components import Item, back_item
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import confirm
from mfruitos.updater.version import parse_version


def when(timestamp: float) -> str:
    if not timestamp:
        return "never"
    now = time.localtime()
    then = time.localtime(timestamp)
    clock = time.strftime("%H:%M", then)
    if then.tm_yday == now.tm_yday and then.tm_year == now.tm_year:
        return f"today {clock}"
    if time.time() - timestamp < 2 * 86400 and (now.tm_yday - then.tm_yday) in (1, -364, -365):
        return f"yesterday {clock}"
    return time.strftime("%d %b %H:%M", then)


class UpdaterScreen(ListScreen):
    title = "Updater"

    def on_show(self) -> None:
        up = self.os.updater
        if up.check_due() and not up.busy:
            self.os.check_updates(quiet=True)

    def items(self) -> list[Item]:
        os = self.os
        up = os.updater
        self.subtitle = "Checking…" if up.busy else f"Checked {when(up.last_check)}"
        if up.online is False and not up.busy:
            rows = [
                Item("Internet unavailable", kind="info", icon="warning", tone="warning",
                     subtitle="Installed apps remain available"),
                Item("Last check", kind="info", value=when(up.last_check)),
                Item("Retry", lambda: os.check_updates(), icon="refresh"),
            ]
        else:
            rows = []
        infos = up.infos()
        system = infos.get(OS_APP_ID)
        rows.append(self._row(OS_NAME, system, __version__, os.open_system_update))
        for app in os.registry.apps():
            info = infos.get(app.id)
            if app.kind in ("os", "daemon"):
                rows.append(self._row(app.name, info, app.version,
                                      lambda a=app.id: os.open_app_updates(a)))
        count = sum(1 for info in infos.values() if info.channel in ("release", "git")
                    and info.update_available and not info.error)
        if count > 1:
            rows.append(Item(f"Update all ({count})", os.update_all, icon="download", tone="accent"))
        rows += [
            Item("Install app", lambda: os.push(InstallAppScreen(os)), kind="nav", icon="package"),
            Item("Check now", lambda: os.check_updates(), icon="refresh", enabled=not up.busy,
                 subtitle="Checking…" if up.busy else f"Last check {when(up.last_check)}"),
            back_item(),
        ]
        return rows

    @staticmethod
    def _row(name: str, info, installed: str, action) -> Item:
        if info is None:
            return Item(name, action, kind="nav", icon="dot", value=installed or "—", tone="muted")
        if info.update_available:
            value = "new" if info.channel == "git" else f"→ {info.latest}"
            return Item(name, action, kind="nav", icon="up", tone="accent", value=value)
        if info.error and info.error != "offline":
            return Item(name, action, kind="nav", icon="warning", tone="warning",
                        value=installed or "—", subtitle=info.error[:40])
        return Item(name, action, kind="nav", icon="check", tone="success",
                    value=(info.installed.split(" @ ")[-1] if info.channel == "git" else info.installed)
                    or "—")


class AppUpdateScreen(ListScreen):
    def __init__(self, os, app_id: str):
        super().__init__(os)
        self.app_id = app_id

    def on_show(self) -> None:
        app = self.os.registry.get(self.app_id)
        if app is None:
            self.os.pop()
            return
        self.title = app.name

    def items(self) -> list[Item]:
        os = self.os
        app = os.registry.get(self.app_id)
        if app is None:
            return [back_item()]
        info = os.updater.info(app.id)
        if app.kind == "daemon":
            return self._git_items(app, info)
        rows = [Item("Installed", kind="info", value=app.version or "—")]
        if info and info.latest:
            rows.append(Item("Latest", kind="info", value=info.latest,
                             tone="accent" if info.update_available else "success"))
        if info and info.error and info.error != "offline":
            rows.append(Item("Problem", kind="info", subtitle=info.error, tone="warning",
                             icon="warning"))
        if info and info.update_available:
            rows.append(Item(f"Update to {info.latest}",
                             lambda: os.install_app_version(app.id, info.latest), icon="download",
                             tone="accent"))
        if app.repository:
            rows.append(Item("Versions", lambda: os.push(VersionListScreen(os, app.id)), kind="nav",
                             icon="list"))
            rows.append(Item("Reinstall", lambda: os.push(confirm(
                os, "Reinstall?", f"Download and reinstall {app.name} {app.version}.",
                "Reinstall", lambda: os.install_app_version(app.id, app.version), danger=False)),
                icon="refresh", enabled=bool(app.version)))
        if app.previous_version:
            rows.append(Item(f"Roll back to {app.previous_version}", lambda: os.push(confirm(
                os, "Roll back?", f"Switch {app.name} back to {app.previous_version}.",
                "Roll back", lambda: os.rollback_app(app.id), danger=False)), icon="rollback"))
        rows.append(back_item())
        return rows

    def _git_items(self, app, info) -> list[Item]:
        os = self.os
        if info is None or info.channel != "git":
            return [Item("Not managed", kind="info", icon="info",
                         subtitle="Not a git checkout or a package"),
                    Item("How to enable updates", lambda: os.show_message(
                        "Updates", "Give the app a manifest.json and publish GitHub releases, "
                        "or install it from a git clone. See APP_DEVELOPMENT.md."), kind="nav"),
                    Item("Check now", lambda: os.check_updates(), icon="refresh"),
                    back_item()]
        rows = [Item("Tracking", kind="info", value=info.installed),
                Item("Commit updates", kind="info", tone="muted",
                     subtitle="No versioned releases; follows the branch")]
        if info.latest:
            rows.append(Item("Remote", kind="info", value=info.latest,
                             tone="accent" if info.update_available else "success"))
        if info.error and info.error != "offline":
            rows.append(Item("Problem", kind="info", subtitle=info.error, tone="warning",
                             icon="warning"))
        if info.update_available and not info.error:
            rows.append(Item("Update now", lambda: os.git_update(app.id), icon="download",
                             tone="accent"))
        from mfruitos.updater.gittrack import previous_commit
        previous = previous_commit(os.paths.state_dir, app.id)
        rows.append(Item("Roll back", lambda: os.push(confirm(
            os, "Roll back?", "Reset to the commit before the last update.", "Roll back",
            lambda: os.git_rollback(app.id), danger=False)), icon="rollback",
            enabled=bool(previous), subtitle=None if previous else "No previous update saved"))
        rows.append(Item("Check now", lambda: os.check_updates(), icon="refresh"))
        rows.append(back_item())
        return rows


class VersionListScreen(ListScreen):
    """Available releases for an app (or the OS); select to install that version."""

    def __init__(self, os, app_id: str):
        super().__init__(os)
        self.app_id = app_id
        self.releases = None
        self.error = ""
        self.title = "Versions"

    def on_show(self) -> None:
        if self.releases is not None:
            return
        repository = self._repository()
        self.subtitle = "Loading…"

        def done(releases):
            self.releases = releases
            self.subtitle = f"{len(releases)} available"
            self.redraw()

        def failed(exc):
            self.releases = []
            self.error = str(exc)[:80]
            self.subtitle = ""
            self.redraw()
        self.os.run_task("releases", lambda: self.os.updater.releases_for(repository), done, failed)

    def _repository(self) -> str:
        if self.app_id == OS_APP_ID:
            return self.os.settings.get("system.repository")
        app = self.os.registry.get(self.app_id)
        return app.repository if app else ""

    def _installed(self) -> str:
        if self.app_id == OS_APP_ID:
            return __version__
        app = self.os.registry.get(self.app_id)
        return app.version if app else ""

    def items(self) -> list[Item]:
        if self.releases is None:
            return [Item("Loading releases…", kind="info", icon="refresh"), back_item()]
        if self.error:
            return [Item("Could not load versions", kind="info", icon="warning", tone="warning",
                         subtitle=self.error),
                    Item("Retry", self._retry, icon="refresh"), back_item()]
        if not self.releases:
            return [Item("No published versions", kind="info", icon="info",
                         subtitle="Publish a version tag or release"),
                    Item("Retry", self._retry, icon="refresh"), back_item()]
        installed = parse_version(self._installed())
        rows = []
        for index, release in enumerate(self.releases):
            version = parse_version(release.version)
            tag = "installed" if version == installed else ("latest" if index == 0 else "")
            rows.append(Item(release.version, lambda r=release: self._pick(r), icon="package",
                             value=tag, tone="success" if tag == "installed" else "accent",
                             subtitle=(release.published_at[:10] or release.source)))
        rows.append(back_item())
        return rows

    def _retry(self) -> None:
        self.releases = None
        self.error = ""
        self.on_show()
        self.redraw()

    def _pick(self, release) -> None:
        os = self.os
        installed = parse_version(self._installed())
        target = parse_version(release.version)
        verb = "Reinstall" if target == installed else (
            "Downgrade to" if installed and target < installed else "Update to")
        if self.app_id == OS_APP_ID:
            action = lambda: os.update_system(release.version)
        else:
            action = lambda: os.install_app_version(self.app_id, release.version)
        os.push(confirm(os, f"{verb} {release.version}?",
                        "The current version is kept and restored if anything fails.",
                        verb.split()[0], action, danger=False))


class InstallAppScreen(ListScreen):
    title = "Install app"

    def items(self) -> list[Item]:
        os = self.os
        return [
            Item("Discover apps", lambda: os.push(DiscoverScreen(os)), kind="nav", icon="search",
                 subtitle="GitHub topic & your sources"),
            Item("Local packages", lambda: os.push(LocalPackagesScreen(os)), kind="nav",
                 icon="package", subtitle="Install a downloaded package"),
            Item("From a terminal", lambda: os.show_message(
                "Install from GitHub",
                "On the device run:\n  mfruitctl install github.com/user/repo\n"
                "The repository must contain a manifest.json (see APP_DEVELOPMENT.md)."),
                kind="nav", icon="developer"),
            back_item(),
        ]


class LocalPackagesScreen(ListScreen):
    title = "Packages"

    def __init__(self, os):
        super().__init__(os)
        self.packages = None
        self.error = ""

    def on_show(self) -> None:
        directory = filesystem.path.join(self.os.paths.home, "inbox")

        def read():
            if not filesystem.path.isdir(directory):
                return []
            with filesystem.scandir(directory) as entries:
                return sorted((e.name, e.path) for e in entries if
                              (e.is_file() and e.name.endswith((".tar.gz", ".tgz", ".tar", ".zip")))
                              or (e.is_dir() and filesystem.path.isfile(
                                  filesystem.path.join(e.path, "manifest.json"))))

        def done(packages):
            self.packages = packages
            self.error = ""
            self.redraw()

        def failed(exc):
            self.packages = []
            self.error = str(exc)
            self.redraw()
        self.os.run_task("local-packages", read, done, failed)

    def items(self) -> list[Item]:
        if self.packages is None:
            return [Item("Loading packages…", kind="info"), back_item()]
        rows = [Item(name, lambda p=path, n=name: self.os.push(confirm(
            self.os, "Install package?", f"{n}\nInstall this version, replacing any newer version. "
            "Only install packages you trust.", "Install", lambda: self.os.sideload(p),
            danger=False)), icon="package") for name, path in self.packages]
        if not rows:
            rows.append(Item("No local packages", kind="info", subtitle=self.error or
                             "Add a package to the inbox"))
        rows.append(Item("How to add packages", lambda: self.os.show_message(
            "Package inbox", "Copy an app archive or package folder to:\n"
            "~/.whisplay-os/\ninbox/\nThen choose Refresh."), kind="nav", icon="info"))
        rows += [Item("Refresh", self.on_show, icon="refresh"), back_item()]
        return rows


class DiscoverScreen(ListScreen):
    title = "Discover"

    def __init__(self, os):
        super().__init__(os)
        self.results = None
        self.error = ""

    def on_show(self) -> None:
        if self.results is not None:
            return

        def done(results):
            self.results = results
            self.redraw()

        def failed(exc):
            self.results = []
            self.error = str(exc)[:80]
            self.redraw()
        self.os.run_task("discover", self.os.updater.discover, done, failed)

    def items(self) -> list[Item]:
        if self.results is None:
            return [Item("Searching GitHub…", kind="info", icon="search"), back_item()]
        if self.error:
            return [Item("Search failed", kind="info", icon="warning", tone="warning",
                         subtitle=self.error), back_item()]
        if not self.results:
            return [Item("No apps found", kind="info", icon="info",
                         subtitle=f"topic: {self.os.settings.get('updater.discovery_topic')}"),
                    back_item()]
        installed = {a.repository.lower() for a in self.os.registry.apps() if a.repository}
        rows = []
        for item in self.results:
            url = f"https://github.com/{item['full_name']}"
            done = url.lower() in installed
            rows.append(Item(item["full_name"].split("/")[-1],
                             lambda u=url, n=item["full_name"]: self._install(u, n),
                             icon="package", value="installed" if done else (
                                 f"★{item['stars']}" if item.get("stars") is not None else ""),
                             tone="success" if done else "muted",
                             subtitle=item.get("description") or item["full_name"]))
        rows.append(back_item())
        return rows

    def _install(self, url: str, name: str) -> None:
        os = self.os
        os.push(confirm(os, "Install app?", f"{name}\nThe latest compatible release will be "
                                           f"downloaded, verified and installed.",
                        "Install", lambda: os.install_from_repository(url), danger=False))


class SystemUpdateScreen(ListScreen):
    title = "System update"

    def items(self) -> list[Item]:
        os = self.os
        info = os.updater.info(OS_APP_ID)
        rows = [Item("Current", kind="info", value=__version__)]
        if info and info.latest:
            rows.append(Item("Latest", kind="info", value=info.latest,
                             tone="accent" if info.update_available else "success"))
        if info and info.error:
            rows.append(Item("Problem", kind="info", icon="warning", tone="warning",
                             subtitle=info.error.replace("offline:", "Offline: ")[:60]))
        if info and info.notes:
            rows.append(Item("Changes", lambda: os.show_message(f"{OS_NAME} {info.latest}",
                                                                info.notes), kind="nav",
                             icon="list"))
        if info and info.update_available:
            rows.append(Item("Update now", lambda: os.push(confirm(
                os, f"Update to {info.latest}?",
                "MFruit OS restarts after the update. If the new version fails to start it is "
                "rolled back automatically.", "Update", lambda: os.update_system(info.latest),
                danger=False)), icon="download", tone="accent"))
        if os.settings.get("system.repository"):
            rows.append(Item("Versions", lambda: os.push(VersionListScreen(os, OS_APP_ID)),
                             kind="nav", icon="list"))
        record = os.installer.read_record(os.paths.system_dir)
        if record.get("previous_dir"):
            version = record.get("previous_version") or "previous build"
            rows.append(Item(f"Roll back to {version}", lambda: os.push(confirm(
                os, "Roll back system?", "Restore the saved build and restart MFruit OS.",
                "Roll back", os.rollback_system, danger=False)), icon="rollback"))
        rows += [Item("Check now", lambda: os.check_updates(), icon="refresh"), back_item()]
        return rows
