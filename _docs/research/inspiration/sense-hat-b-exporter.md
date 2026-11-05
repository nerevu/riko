---
source: ../../../../sense-hat-b-exporter/README.md
---

Waveshare Sense HAT (B) Prometheus Exporter
===========================================

A simple Prometheus exporter for exporting values from the Waveshare Sense HAT (B).
It serves the board's current sensor readings as Prometheus gauges on `/metrics`.

Requirements
------------

* Raspberry Pi (5)
* [Waveshare Sense HAT (B)](https://www.waveshare.com/wiki/Sense_HAT_(B))
* Python 3 with the packages in `requirements.txt` (`prometheus-client`, `smbus`,
  `lgpio`, `gpiozero`, `RPi.GPIO`). `smbus` and `lgpio` are hard requirements:
  without them `exporter.py` logs
  `smbus or lgpio not available, please install the required libraries.` and
  exits with status 1 before it parses any options, so even `--help` fails.
* I2C enabled on the Pi, and a user in the `i2c` and `gpio` groups (the light
  sensor also watches a GPIO interrupt pin through `gpiozero`).

Installation
------------

    git clone https://github.com/nerevu/sense-hat-b-exporter.git
    cd sense-hat-b-exporter
    pip3 install -r requirements.txt
    # start the exporter from the checkout
    python3 exporter.py

Run `exporter.py` from the repository directory: it imports the `sensors`
package beside it.

Installing it as a `sensehat-b-exporter` command (intended; not implemented):

    sudo cp exporter.py /usr/local/bin/sensehat-b-exporter
    # start sensehat-b-exporter!
    sensehat-b-exporter

This does not work today: `exporter.py` has no shebang line, and the copied
file cannot import the `sensors` package it needs.

### Docker

The `Dockerfile` declares a multi-arch build. Build it on the Pi itself: the
builder stage runs on the build machine's platform and its installed packages
are copied into the final image, so a cross-built image carries packages for
the wrong architecture (see [Known issues](#known-issues)). The container runs
`python3 exporter.py --bind=0.0.0.0 --port=9111` as the user `sensehat`, which
belongs to the groups `gpio` (gid 993), `i2c` (gid 994), `spi` (gid 995) and
`dialout`. Pass the I2C and GPIO devices through and make sure the host's group
ids match these, for example (adjust the device names to your Pi):

    docker build -t sense-hat-b-exporter .
    docker run -d -p 9111:9111 \
      --device /dev/i2c-1 --device /dev/gpiochip0 \
      sense-hat-b-exporter

Usage
-----

    usage: exporter.py [-h] [--port [PORT]] [--bind [BIND]] [--bus BUS]

    options:
      -h, --help     show this help message and exit
      --port [PORT]  The TCP port to listen on (default: 9111)
      --bind [BIND]  The interface/IP to bind to (default: 0.0.0.0)
      --bus BUS      The I2C bus to read (default: 1)

The exporter logs `listening on http://<bind>:<port>/metrics` and serves until
it is stopped.

Configuration
-------------

Currently there are no other configuration than the command-line options
(IP, port and I2C bus) and no configuration file.

`--bus` applies only to the temperature/humidity sensor (SHTC3). The motion
(ICM20948), pressure (LPS22HB) and light (TCS34725) sensors always use I2C
bus 1.

Metrics
-------

The sensors are read live on every scrape of `/metrics`; there is no
background polling and no caching, so each scrape takes as long as the sensor
reads (the magnetometer read alone sleeps 0.1 s).

Metric | Type | Unit | Labels | Description
-------|------|------|--------|------------
`sense_hat_b_temperature_celsius` | gauge | °C | | temperature (SHTC3)
`sense_hat_b_pressure_h_pascals` | gauge | hPa | | air pressure (LPS22HB)
`sense_hat_b_humidity` | gauge | % | | relative humidity (SHTC3)
`sense_hat_b_lux` | gauge | lux | | light level (TCS34725)
`sense_hat_b_color_temp` | gauge | K | | colour temperature (TCS34725)
`sense_hat_b_tilt` | gauge | ° | | `sqrt(roll² + pitch²)` from the orientation
`sense_hat_b_total_magnetic_field` | gauge | μT | | magnitude of the x/y/z magnetic field (ICM20948)
`sense_hat_b_orientation` | gauge | ° | `axis` = `roll`, `pitch`, `yaw` | orientation (ICM20948)
`request_processing_seconds` | summary | s | | time spent collecting the sensor metrics

These metrics are defined but disabled (commented out in `exporter.py`):
`sense_hat_b_acceleration{axis}` (G), `sense_hat_b_gyroscope{axis}` (°/s),
`sense_hat_b_magnetic_field{axis}` (μT), `sense_hat_b_total_acceleration` (G)
and `sense_hat_b_angular_velocity` (°/s).

Prometheus Configuration
------------------------

In _/etc/prometheus/prometheus.yml_, Add a static scrape target under `scrape_configs`:

    scrape_configs:
      - job_name: 'sensehat-b'
        static_configs:
        - targets: ['<ip>:9111']

Grafana Dashboard
-----------------

`sensy.json` is a Grafana dashboard ("Environment") for these metrics. Five of
its panels query the disabled metrics (`sense_hat_b_acceleration`,
`sense_hat_b_angular_velocity`, `sense_hat_b_gyroscope`,
`sense_hat_b_magnetic_field` and `sense_hat_b_total_acceleration`), so they
stay empty. `1860_rev41.json` is the stock
[Node Exporter Full](https://grafana.com/grafana/dashboards/1860-node-exporter-full/)
dashboard for the Pi's system metrics.

TODO
----

* Possibly make additional sensors configurable.

Demo
----

Here's a screenshot of the data being put to use in a Grafana dashboard
(intended; the screenshot `images/screenshot_2019-08-13.png` is not in the
repository yet):

![Grafana Sense HAT (B) dashboard screenshot](images/screenshot_2019-08-13.png)

Known issues
------------

* `exporter.py` has no shebang and imports the sibling `sensors` package
  (`exporter.py:1,7`), so it cannot be installed as a standalone command.
* Without `smbus` or `lgpio` the script exits before parsing options, so
  `--help` fails too (`exporter.py:207-221`).
* `--bus` reaches only SHTC3 (`exporter.py:31`); the other sensors open
  `smbus.SMBus(1)` (`sensors/ICM20948.py:135`, `sensors/LPS22HB.py:48`,
  `sensors/TCS34725.py:138`).
* SHTC3 prints its bus settings to stdout when it starts
  (`sensors/SHTC3.py:27`).
* `sensors/SGM58031.py` is not used by the exporter.
* The Docker builder stage is pinned to `$BUILDPLATFORM` and its
  `site-packages` are copied into the target image (`Dockerfile:3,19`), so
  compiled packages such as `lgpio` are built for the build machine, not the
  target, when cross-building.

License
-------

This software is licensed under the ISC license (no `LICENSE` file is in the repository
today).

Inspiration
-----------

<https://github.com/epleterte/sensehat-exporter>
<https://github.com/mhansen/sense_hat_exporter>
<https://github.com/tijmenvandenbrink/enviroplus_exporter>
<https://grafana.com/grafana/dashboards/1860-node-exporter-full/>
<https://makersportal.com/blog/2019/11/11/raspberry-pi-python-accelerometer-gyroscope-magnetometer>
