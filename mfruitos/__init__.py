"""mFruit OS — a compact application platform for Linux devices.

mFruit OS runs on top of ``whisplay-daemon``. The daemon owns the hardware
(LCD, backlight, RGB LED, button) and the foreground-app lifecycle; mFruit OS
is a daemon foreground app that provides the launcher, settings, app manager,
updater and diagnostics.
"""

__version__ = "1.4.0"

OS_NAME = "mFruit OS"

# The app_id mFruit OS registers with whisplay-daemon. Manifests may not use it.
OS_APP_ID = "mfruit-os"
