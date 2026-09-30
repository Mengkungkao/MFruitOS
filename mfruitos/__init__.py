"""MFruit OS — a tiny operating system for Whisplay applications.

MFruit OS runs on top of ``whisplay-daemon``. The daemon owns the hardware
(LCD, backlight, RGB LED, button) and the foreground-app lifecycle; MFruit OS
is a daemon foreground app that provides the launcher, settings, app manager,
updater and diagnostics.
"""

__version__ = "1.3.0"

OS_NAME = "MFruit OS"

# The app_id MFruit OS registers with whisplay-daemon. Manifests may not use it.
OS_APP_ID = "mfruit-os"
