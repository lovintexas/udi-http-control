#!/usr/bin/env python3
from pathlib import Path

import json
import operator
import time
import requests
import udi_interface
from http_control_web import start_web_server

LOGGER = udi_interface.LOGGER


class HttpTrigger(udi_interface.Node):
    id = "httptrigger"

    drivers = [
        {"driver": "ST", "value": 2, "uom": 25},
    ]

    OPERATORS = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
    }

    def __init__(self, polyglot, primary, address, name,
                 field_number, on_value, off_value,
                 on_operator="==", off_operator="=="):
        super().__init__(polyglot, primary, address, name)
        self.field_number = field_number
        self.on_value = float(on_value)
        self.off_value = float(off_value)
        self.on_operator = on_operator
        self.off_operator = off_operator
        self.current_state = None
        self.enabled = True

    def update_conditions(self, on_value, off_value,
                          on_operator, off_operator):
        on_value = float(on_value)
        off_value = float(off_value)

        if on_operator not in self.OPERATORS:
            raise ValueError("Invalid ON operator")
        if off_operator not in self.OPERATORS:
            raise ValueError("Invalid OFF operator")

        if (on_operator == off_operator == "=="
                and on_value == off_value):
            raise ValueError("ON and OFF values must differ")

        self.on_value = on_value
        self.off_value = off_value
        self.on_operator = on_operator
        self.off_operator = off_operator

    def start(self):
        # Explicitly initialize IoX status as Unknown.
        self.setDriver("ST", 2, report=True, force=True)

    def update_value(self, value):
        if not self.enabled:
            return

        value = float(value)

        on_match = self.OPERATORS[self.on_operator](value, self.on_value)
        off_match = self.OPERATORS[self.off_operator](value, self.off_value)

        if on_match and off_match:
            LOGGER.warning("%s: Both ON and OFF conditions match", self.name)
            return

        if on_match:
            new_state = 1
        elif off_match:
            new_state = 0
        else:
            return

        previous_state = self.current_state
        self.current_state = new_state
        self.setDriver("ST", new_state)

        if previous_state != new_state:
            command = "DON" if new_state else "DOF"
            LOGGER.info("%s: Reporting %s", self.name, command)
            self.reportCmd(command)

    def query(self, command=None):
        self.reportDrivers()

    commands = {"QUERY": query}


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

    def update_poll_interval(self, interval):
        interval = max(0, int(interval))
        method = str(self.config.get("method", "GET")).upper()
        self.poll_interval = interval if method == "GET" else 0
        self.config["interval"] = str(interval)

    def update_request_config(self, settings):
        for key in ("url", "method", "headers", "body"):
            self.config[key] = settings[key]

        fields = settings.get("fields", {})
        for i in range(1, 9):
            field = fields.get(str(i), fields.get(i, {}))
            new_path = field.get("path", "")
            self.config[f"field{i}"] = new_path

            # Always clear unconfigured response fields.
            if not new_path:
                self.setDriver(f"GV{i+2}", 0, report=True, force=True)

        self.update_poll_interval(settings["interval"])

        for i, trigger in getattr(self, "triggers", {}).items():
            field = fields.get(str(i), fields.get(i, {}))

            enabled = field.get("controller", False)
            if isinstance(enabled, str):
                enabled = enabled.strip().lower() in (
                    "true", "yes", "1", "on"
                )

            trigger.update_conditions(
                field.get("on", "1"),
                field.get("off", "0"),
                field.get("on_operator", "=="),
                field.get("off_operator", "==")
            )
            was_enabled = trigger.enabled
            trigger.enabled = bool(enabled)

            if not trigger.enabled:
                LOGGER.warning(
                    "Disabling scene controller %s; setting ST to Unknown",
                    trigger.address
                )
                trigger.current_state = None
                trigger.setDriver("ST", 2, report=True, force=True)

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

                    numeric_value = float(value)

                    self.setDriver(
                        f"GV{i+2}",
                        numeric_value
                    )

                    trigger = getattr(self, "triggers", {}).get(i)
                    if trigger is not None:
                        trigger.update_value(numeric_value)

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

    def turn_on(self, command=None):
        self.send(command)

    def turn_off(self, command=None):
        # Scene OFF does not trigger an HTTP request.
        pass

    commands = {
        "SEND": send,
        "DON": turn_on,
        "DOF": turn_off,
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

    def load_saved_config(self):
        path = Path(__file__).resolve().parent / "data/endpoints.json"
        if not path.exists():
            return

        try:
            configs = json.loads(path.read_text())
            if not isinstance(configs, list) or len(configs) != 16:
                raise ValueError("Expected 16 endpoint configurations")

            params = dict(self.params)
            for num, entry in enumerate(configs, 1):
                prefix = f"url{num}_"
                for key in ("name", "url", "method", "interval",
                            "headers", "body"):
                    params[prefix + key] = str(entry.get(key, ""))

                fields = entry.get("fields", {})
                for i in range(1, 9):
                    field = fields.get(str(i), {})
                    params[prefix + f"field{i}"] = str(field.get("path", ""))
                    for key in ("controller", "on", "off",
                                "on_operator", "off_operator"):
                        value = field.get(key, "")
                        if key == "controller":
                            value = "true" if value is True else "false"
                        params[prefix + f"field{i}_{key}"] = str(value)

            self.params = params
            LOGGER.info("Loaded saved HTTP Control configuration")
        except Exception:
            LOGGER.exception("Unable to load saved HTTP Control configuration")

    def start(self):
        self.load_saved_config()
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

            node.triggers = {}

            for i in range(1, 9):
                enabled = str(
                    self.params.get(
                        prefix + f"field{i}_controller", "false"
                    )
                ).strip().lower()

                enabled = enabled in ("true", "yes", "1", "on")

                if not config.get(f"field{i}"):
                    LOGGER.warning(
                        "%s: Field %d controller has no response path",
                        name, i
                    )
                    continue

                try:
                    on_value = float(
                        self.params.get(prefix + f"field{i}_on", "1")
                    )
                    off_value = float(
                        self.params.get(prefix + f"field{i}_off", "0")
                    )

                    on_operator = str(
                        self.params.get(
                            prefix + f"field{i}_on_operator", "=="
                        )
                    ).strip()

                    off_operator = str(
                        self.params.get(
                            prefix + f"field{i}_off_operator", "=="
                        )
                    ).strip()

                    if on_operator not in HttpTrigger.OPERATORS:
                        raise ValueError("Invalid ON comparison operator")

                    if off_operator not in HttpTrigger.OPERATORS:
                        raise ValueError("Invalid OFF comparison operator")

                    if (on_operator == off_operator == "=="
                            and on_value == off_value):
                        raise ValueError("ON and OFF values must differ")

                except (ValueError, TypeError) as ex:
                    LOGGER.error(
                        "%s: Invalid controller values for field %d: %s",
                        name, i, ex
                    )
                    continue

                trigger = HttpTrigger(
                    self.poly,
                    self.address,
                    f"url{num}f{i}",
                    f"{name} - Field {i}",
                    i,
                    on_value,
                    off_value,
                    on_operator,
                    off_operator
                )

                trigger.enabled = enabled
                self.poly.addNode(trigger)
                node.triggers[i] = trigger
                trigger.start()

                LOGGER.info(
                    "%s - Field %d: ON %s %s, OFF %s %s",
                    name, i,
                    on_operator, on_value,
                    off_operator, off_value
                )

    def apply_saved_config(self, configs):
        existing = {}
        for node in self.endpoints:
            try:
                num = int(node.address.removeprefix("url"))
                existing[num] = node
            except (ValueError, TypeError):
                LOGGER.warning("Skipping endpoint with unexpected address %s",
                               node.address)

        for num, settings in enumerate(configs, 1):
            name = str(settings.get("name", "")).strip()
            url = str(settings.get("url", "")).strip()

            # Empty endpoint slots do not create new nodes.
            if not name or not url:
                continue

            fields = settings.get("fields", {})
            node = existing.get(num)

            if node is None:
                config = {
                    "url": url,
                    "method": settings.get("method", "GET"),
                    "headers": settings.get("headers", "{}"),
                    "body": settings.get("body", ""),
                    "interval": settings.get("interval", "0"),
                }
                for i in range(1, 9):
                    field = fields.get(str(i), fields.get(i, {}))
                    config[f"field{i}"] = field.get("path", "")

                node = HttpEndpoint(
                    self.poly, self.address, f"url{num}", name, config
                )
                node.triggers = {}
                self.poly.addNode(node)
                self.endpoints.append(node)
                existing[num] = node
                LOGGER.info("Created endpoint %s (%s)", name, node.address)
            else:
                node.update_request_config(settings)

            for i in range(1, 9):
                field = fields.get(str(i), fields.get(i, {}))
                self.ensure_trigger(node, num, i, field)

    def ensure_trigger(self, node, num, i, field):
        enabled = field.get("controller", False)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in (
                "true", "yes", "1", "on"
            )
        if not enabled:
            return

        if not node.config.get(f"field{i}"):
            LOGGER.warning(
                "%s: Field %d controller has no response path",
                node.name, i
            )
            return

        triggers = getattr(node, "triggers", {})
        trigger = triggers.get(i)

        try:
            on_value = float(field.get("on", 1))
            off_value = float(field.get("off", 0))
            on_operator = field.get("on_operator", "==")
            off_operator = field.get("off_operator", "==")

            if trigger is None:
                trigger = HttpTrigger(
                    self.poly, self.address, f"url{num}f{i}",
                    f"{node.name} - Field {i}", i,
                    on_value, off_value, on_operator, off_operator
                )
                trigger.enabled = True
                self.poly.addNode(trigger)
                triggers[i] = trigger
                node.triggers = triggers
                trigger.start()
            else:
                trigger.update_conditions(
                    on_value, off_value, on_operator, off_operator
                )
                trigger.enabled = True

        except (ValueError, TypeError) as ex:
            LOGGER.error(
                "%s: Unable to configure Field %d controller: %s",
                node.name, i, ex
            )

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
        polyglot.start("1.5.0")

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

        try:
            controller.web_server = start_web_server(
                controller,
                logger=LOGGER,
                host="0.0.0.0",
                port=8766,
            )
            LOGGER.info(
                "HTTP Control web interface listening on HTTPS port 8766"
            )
        except Exception:
            LOGGER.exception("Unable to start HTTP Control web interface")

        polyglot.runForever()

    except (KeyboardInterrupt, SystemExit):
        pass

    except Exception:
        LOGGER.exception("Unhandled exception")
