#!/usr/bin/env python3

import json
import time
import requests
import udi_interface

LOGGER = udi_interface.LOGGER


class HttpEndpoint(udi_interface.Node):
    id = "httpendpoint"

    drivers = [
        {"driver": "ST", "value": 0, "uom": 25},
        {"driver": "GV1", "value": 0, "uom": 56},
        {"driver": "GV2", "value": 0, "uom": 56},
        {"driver": "GV3", "value": 0, "uom": 56},
        {"driver": "GV4", "value": 0, "uom": 56},
        {"driver": "GV5", "value": 0, "uom": 56},
        {"driver": "GV6", "value": 0, "uom": 56},
        {"driver": "GV7", "value": 0, "uom": 56},
        {"driver": "GV8", "value": 0, "uom": 56},
        {"driver": "GV9", "value": 0, "uom": 56},
        {"driver": "GV10", "value": 0, "uom": 56},
    ]

    def __init__(self, polyglot, primary, address, name, config):
        super().__init__(polyglot, primary, address, name)
        self.config = config
        self.last_request = 0.0
        self.poll_interval = 0

        try:
            self.poll_interval = max(
                0, int(config.get("interval", 0))
            )
        except (ValueError, TypeError):
            LOGGER.warning(
                "%s: Invalid polling interval; disabled",
                name
            )

        method = str(
            config.get("method", "GET")
        ).strip().upper()

        if method != "GET" and self.poll_interval:
            LOGGER.warning(
                "%s: Automatic polling disabled for %s",
                name, method
            )
            self.poll_interval = 0

    def send(self, command=None):
        self.last_request = time.monotonic()
        url = self.config["url"]
        method = str(self.config.get("method", "GET")).strip().upper()

        if method not in ("GET", "POST", "PUT", "DELETE"):
            LOGGER.error("%s: Unsupported method %s", self.name, method)
            self.setDriver("ST", 0)
            return

        try:
            headers = self.config.get("headers") or {}
            body = self.config.get("body")

            if isinstance(headers, str):
                headers = json.loads(headers)

            if not isinstance(headers, dict):
                raise ValueError("Headers must be a JSON object")

            kwargs = {
                "headers": headers,
                "timeout": 5,
                "allow_redirects": False,
            }

            if body:
                try:
                    kwargs["json"] = json.loads(body)
                except (ValueError, TypeError):
                    kwargs["data"] = body

            start = time.monotonic()

            response = requests.request(
                method,
                url,
                **kwargs
            )

            elapsed_ms = int(
                (time.monotonic() - start) * 1000
            )

            self.setDriver("GV1", response.status_code)
            self.setDriver("GV2", elapsed_ms)

            success = 200 <= response.status_code < 300
            self.setDriver("ST", int(success))

            if not success:
                LOGGER.warning(
                    "%s: HTTP %s returned status %s",
                    self.name,
                    method,
                    response.status_code
                )
                return

            try:
                data = response.json()
            except ValueError:
                data = {}

            for i in range(1, 9):
                key = self.config.get(f"field{i}")
                if not key:
                    continue

                try:
                    if key.strip().lower() == "text":
                        value = response.text.strip()
                    else:
                        value = data

                        for part in key.split("."):
                            if isinstance(value, list):
                                value = value[int(part)]
                            else:
                                value = value[part]

                    if isinstance(value, bool):
                        value = int(value)

                    self.setDriver(
                        f"GV{i+2}",
                        float(value)
                    )

                except (
                    KeyError,
                    IndexError,
                    TypeError,
                    ValueError
                ):
                    LOGGER.warning(
                        "%s: Could not parse field %s",
                        self.name,
                        key
                    )

            LOGGER.info(
                "%s: %s HTTP %s in %d ms",
                self.name,
                method,
                response.status_code,
                elapsed_ms
            )

        except (
            requests.RequestException,
            ValueError,
            TypeError
        ) as ex:
            self.setDriver("ST", 0)
            LOGGER.error(
                "%s: HTTP request failed: %s",
                self.name,
                ex
            )

    def query(self, command=None):
        self.reportDrivers()

    commands = {
        "SEND": send,
        "QUERY": query,
    }


class Controller(udi_interface.Node):
    id = "httpctrl"

    drivers = [
        {"driver": "ST", "value": 1, "uom": 25},
    ]

    def __init__(self, polyglot):
        super().__init__(
            polyglot, "controller", "controller", "HTTP Control"
        )
        self.poly = polyglot
        self.params = {}
        self.endpoints = []

    def configure(self, params):
        self.params = dict(params)
        LOGGER.info("Configuration updated; restart required")

    def start(self):
        for num in range(1, 17):
            prefix = f"url{num}_"

            name = self.params.get(prefix + "name")
            url = self.params.get(prefix + "url")

            if not name or not url:
                continue

            config = {
                "url": url,
                "method": self.params.get(
                    prefix + "method", "GET"
                ),
                "headers": self.params.get(
                    prefix + "headers", "{}"
                ),
                "body": self.params.get(
                    prefix + "body", ""
                ),
                "interval": self.params.get(
                    prefix + "interval", "0"
                ),
            }

            for i in range(1, 9):
                config[f"field{i}"] = self.params.get(
                    prefix + f"field{i}"
                )

            node = HttpEndpoint(
                self.poly,
                self.address,
                f"url{num}",
                name,
                config
            )
            self.poly.addNode(node)
            self.endpoints.append(node)

    def poll(self):
        now = time.monotonic()

        for node in self.endpoints:

            if node.poll_interval <= 0:
                continue

            if now - node.last_request >= node.poll_interval:
                node.send()

    def query(self, command=None):
        self.reportDrivers()

    commands = {"QUERY": query}


controller = None
pending_params = {}


def custom_params_handler(params):
    global pending_params
    pending_params = dict(params)
    LOGGER.info("HTTP Control custom parameters received")

    if controller is not None:
        controller.configure(pending_params)


def poll_handler(poll_type):
    if poll_type != "shortPoll":
        return

    if controller is not None:
        controller.poll()


def stop_handler():
    LOGGER.info("HTTP Control stopping")
    polyglot.stop()


if __name__ == "__main__":
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start("1.4.0")

        polyglot.subscribe(
            polyglot.CUSTOMPARAMS,
            custom_params_handler
        )

        polyglot.subscribe(
            polyglot.STOP,
            stop_handler
        )

        polyglot.subscribe(
            polyglot.POLL,
            poll_handler
        )

        polyglot.ready()
        polyglot.updateProfile()

        controller = Controller(polyglot)
        controller.configure(pending_params)
        polyglot.addNode(controller)

        time.sleep(1)
        controller.start()

        polyglot.runForever()

    except (KeyboardInterrupt, SystemExit):
        pass

    except Exception:
        LOGGER.exception("Unhandled exception")
