"""PiSugar battery boards (host implementation, layer E).

The drivers mFruit OS's power service uses for PiSugar 3, PiSugar 2
(IP5209, 4 or 2 LEDs) and PiSugar 2 Pro (IP5312), with the PiSugar 2
SD3078 clock. Written for mFruit OS from the boards' published register
interface; I2C uses the standard library (``i2c.py``).

    detect.open_board(bus_number, model)   -> (bus, chip) or NotFound
    base.Chip                               what the power service may call
    fake                                    register-level fakes for tests

Only ``mfruitos.power`` imports this package (docs/platform/HOST_API.md).
"""
