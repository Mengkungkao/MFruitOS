"""The LoRa radio capability: Waveshare SX126X (E22-900T22S) HATs.

mFruit OS owns setting the radio up -- provisioning the module and
checking that it is ready -- because every radio app shares one module,
one frequency and one identity (docs/platform/ADR/0007-shared-radio-capability.md).
The apps keep their own transport for sending and receiving.

    python3 -m mfruitos.hosts.lora status       readiness, as JSON
    sudo python3 -m mfruitos.hosts.lora check   read the module's registers
    sudo python3 -m mfruitos.hosts.lora provision --band au915
"""
