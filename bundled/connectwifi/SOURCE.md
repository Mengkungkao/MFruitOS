ConnectWifi runtime vendored from https://github.com/Mengkungkao/ConnectWifi
Commit: 0f1edf6d7223b455e189d832bba33135918b25a7, plus the uncommitted changes in
that checkout and, from 1.2.0 (2026-10-13), the network
chooser: started by mFruit OS (MFRUIT_HOME set), the app opens on the network
list behind Settings > Wi-Fi > Choose a network and Back returns there. Its tests
are in that repository (`python3 -m pytest tests`).
The installer adds the canonical mFruit SDK when packaging this component.
