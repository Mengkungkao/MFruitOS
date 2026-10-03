"""Host implementations (layer E): code that drives specific hardware.

Generic platform code must not import from here directly except through a
documented boundary (docs/platform/HOST_API.md). Today this holds the LoRa
radio capability; the Whisplay display/input host still lives in
``mfruitos.daemon`` and ``mfruitos.launcher`` (see ADR 0005).
"""
