Waveshare Sense HAT (B) Prometheus Exporter
===========================================

A simple Prometheus exporter for exporting values from the Waveshare Sense HAT (B).

Requirements
------------

* Raspberry Pi (5)
* [Waveshare Sense HAT (B)](https://www.waveshare.com/wiki/Sense_HAT_(B))

Installation
------------

    git clone https://github.com/epleterte/sensehat-b-exporter.git
    cd sensehat-exporter
    pip3 install -r requirements.txt
    sudo cp exporter.py /usr/local/bin/sensehat-b-exporter
    # start sensehat-b-exporter!
    sensehat-b-exporter

Usage
-----

    usage: sensehat-b-exporter.py [-h] [--port [PORT]] [--bind [BIND]]

    optional arguments:
      -h, --help     show this help message and exit
      --port [PORT]  The TCP port to listen on (default: 9111)
      --bind [BIND]  The interface/IP to bind to (default: 0.0.0.0)

Configuration
-------------

Currently there are no other configuration than options IP/port and no configuration file.

Prometheus Configuration
------------------------

In _/etc/prometheus/prometheus.yml_, Add a static scrape target under `scrape_configs`:

    scrape_configs:
      - job_name: 'sensehat-b'
        static_configs:
        - targets: ['<ip>:9111']


TODO
----

* Upload example Grafana dashboard
* Possibly make additional sensors configurable.

Demo
----

Here's a screenshot of the data being put to use in a Grafana dashboard:

![Grafana Sense HAT (B) dashboard screenshot](images/screenshot_2019-08-13.png)

License
-------

This software is licensed under the ISC license.

Inspiration
-----------

https://github.com/epleterte/sensehat-exporter
https://github.com/mhansen/sense_hat_exporter
https://github.com/tijmenvandenbrink/enviroplus_exporter
https://grafana.com/grafana/dashboards/1860-node-exporter-full/
https://makersportal.com/blog/2019/11/11/raspberry-pi-python-accelerometer-gyroscope-magnetometer
