#!/usr/bin/env bash
# What a fresh installation must have produced. Run inside the rehearsal
# container by tests/fresh_install/rehearse.sh (as the board user, after
# `bash scripts/install.sh --yes`). Exit status = number of failed checks.
set -u
cd "$(dirname "$0")/../.."
fails=0
expect() {
  local what="$1"
  shift
  if "$@" >/dev/null 2>&1; then echo "PASS  $what"; else echo "FAIL  $what"; fails=$((fails + 1)); fi
}
K="$(uname -r)"
CODECS="/lib/modules/$K/kernel/sound/soc/codecs"
# shellcheck source=../../drivers/whisplay/install.sh
source drivers/whisplay/install.sh  # package_installed, overlay_file, detect_platform, bundle_digest
set +e  # the sourced installer turns errexit on; every check here must run

echo "==> checks"
expect "no network in this container (offline)" bash -c '! getent hosts github.com'
expect "install log: packages came from the offline pack" grep -q "from the offline pack" ~/install.log
expect "install log: asks for the reboot" grep -q "reboot to finish the Whisplay driver" ~/install.log
for pkg in python3-pil python3-venv network-manager python3-spidev python3-libgpiod python3-numpy \
    python3-smbus alsa-utils i2c-tools device-tree-compiler libasound2-plugins sox make gcc \
    fonts-dejavu-core bluez python3-dbus python3-gi; do
  expect "package $pkg installed" package_installed "$pkg"
done
expect "Python imports PIL, spidev, gpiod, numpy, smbus" python3 -c "import PIL, spidev, gpiod, numpy, smbus"
expect "sound card module built for kernel $K" test -f "$CODECS/snd-soc-whisplay-soundcard.ko"
expect "  its vermagic is $K" bash -c "modinfo -F vermagic '$CODECS/snd-soc-whisplay-soundcard.ko' | grep -q '^$K '"
expect "WM8960 codec module built" test -f "$CODECS/snd-soc-wm8960.ko"
expect "module dependency index updated" grep -q whisplay "/lib/modules/$K/modules.dep"
expect "sound card overlay compiled" test -f "$(overlay_file "$(detect_platform)")"
case "$(detect_platform)" in
  orangepi_zero2w)
    expect "boot: I2C1 and SPI1 overlays" grep -qx "overlays=pi-i2c1 spi1-cs0-spidev" /boot/orangepiEnv.txt
    expect "boot: Whisplay sound card overlay" grep -qx "user_overlays=whisplay-soundcard-orangepi-zero2w" /boot/orangepiEnv.txt
    expect "modules loaded at boot" grep -qx snd-soc-whisplay-soundcard /etc/modules
    expect "GPIO/SPI udev rule" test -f /etc/udev/rules.d/60-whisplay-orangepi.rules
    expect "user in the gpio group (from the next login)" bash -c 'id -nG "$(id -un)" | grep -qw gpio' ;;
esac
expect "ALSA card name whisplaysound" grep -q whisplaysound /etc/asound.conf
expect "boot volume service" test -f /etc/systemd/system/whisplay-soundcard-warmup.service
expect "driver files at /usr/local/share/whisplay" test -f /usr/local/share/whisplay/daemon/whisplay_daemon.py
expect "  they match this MFruit OS" bash -c "grep -qx 'manifest_sha256=$(bundle_digest)' /usr/local/share/whisplay/MFRUIT_DRIVER"
expect "  compiled, read-only for the daemon user" bash -c \
  'test -d /usr/local/share/whisplay/daemon/__pycache__ && ! test -w /usr/local/share/whisplay/daemon'
expect "whisplay-daemon.service runs the driver" grep -q "^ExecStart=.*/usr/local/share/whisplay/daemon/whisplay_daemon.py" /etc/systemd/system/whisplay-daemon.service
expect "  through MFruit OS's wrapper" grep -q -- "--whisplay /usr/local/share/whisplay " /etc/systemd/system/whisplay-daemon.service.d/mfruit-os.conf
expect "whisplay-os.service" test -f /etc/systemd/system/whisplay-os.service
expect "sudoers files valid" sudo visudo -c
expect "Power page may reboot and power off" sudo test -f /etc/sudoers.d/whisplay-daemon-power
expect "daemon settings created" test -f ~/.whisplay-daemon/settings.json
expect "MFruit OS active version" test -f ~/.whisplay-os/system/current/mfruitos/__init__.py
expect "MFruit OS self-test" env PYTHONPATH="$HOME/.whisplay-os/system/current" python3 -m mfruitos --self-test
expect "Wi-Fi app provisioned" test -f ~/.whisplay-os/apps/connectwifi/current/manifest.json
expect "no build files left in the source tree" bash -c \
  '[ -z "$(find drivers/whisplay/audio -name "*.o" -o -name "*.ko" -o -name "*.dtbo" | head -1)" ]'

echo "==> drivers/whisplay/install.sh --check (no LCD, sound card or systemd in a container: those FAIL here)"
bash drivers/whisplay/install.sh --check | sed 's/^/    /'
echo "$fails check(s) failed"
exit "$fails"
