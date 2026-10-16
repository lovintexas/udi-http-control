# HTTP Control — PG3x Node Server

HTTP Control allows Universal Devices IoX to send HTTP requests and display numeric response values as node drivers.

Designed for eisy and PG3x.

## Features

- Up to 16 configurable HTTP endpoints
- GET, POST, PUT, and DELETE methods
- JSON request bodies
- Custom HTTP headers
- Eight numeric response fields per endpoint
- Nested JSON response parsing
- Plain-text numeric response parsing
- Optional automatic GET polling
- HTTP status and response time reporting
- Success status displayed as True or False
- Previous measurements retained when requests fail

## Configuration

Configure endpoints through PG3x Custom Parameters.

Each endpoint uses a numbered prefix, such as `url1_`, `url2_`, etc.

| Parameter | Description |
|---|---|
| url1_name | IoX node name |
| url1_url | HTTP or HTTPS URL |
| url1_method | GET, POST, PUT, or DELETE |
| url1_headers | Optional JSON object containing HTTP headers |
| url1_body | Optional request body |
| url1_interval | Automatic polling interval in seconds; 0 disables polling |
| url1_field1 through url1_field8 | Response fields to extract |

Both `urlN_name` and `urlN_url` are required to create an endpoint.

Save changes and restart the node server after changing configuration.

## Example: JSON Response

URL:

    https://httpbin.org/anything?temperature=35&humidity=62

Configuration:

    url1_name = Temperature Monitor
    url1_method = GET
    url1_field1 = args.temperature
    url1_field2 = args.humidity
    url1_interval = 60

Results:

    Field 1 = 35
    Field 2 = 62

Nested JSON properties can be selected using dot notation.

For JSON arrays, use numeric indices, such as:

    sensors.0.temperature

## Example: Plain-Text Response

URL:

    https://httpbin.org/base64/NzIuNQ==

Configuration:

    url1_method = GET
    url1_field1 = text

Result:

    Field 1 = 72.5

The text response must be convertible to a number.

## Example: POST Request

Configuration:

    url1_method = POST
    url1_url = https://httpbin.org/anything
    url1_body = {"temperature":47,"humidity":81}
    url1_field1 = json.temperature
    url1_field2 = json.humidity

Use the IoX Send Request command to execute the POST.

## Automatic Polling

Set `urlN_interval` to the desired polling interval in seconds.

    url1_interval = 60

Polling is supported only for GET requests.

POST, PUT, and DELETE are command-only to prevent unintended repeated actions.

Polling is checked on PG3x Short Poll events. Actual intervals are therefore limited by the configured Short Poll cadence.

Setting the interval to 0 disables automatic polling.

## IoX Commands

**Send Request** — Executes the configured HTTP request.

**Query** — Reports stored values without executing the HTTP request.

## IoX Status Fields

| Field | Meaning |
|---|---|
| Last Request Successful | True for HTTP 200–299; otherwise False |
| HTTP Status Code | Most recent HTTP response status |
| Response Time (ms) | Duration of the most recent HTTP response |
| Field 1–8 | Numeric values extracted from the response |

Missing or invalid response fields retain their previous values.

HTTP errors do not overwrite previous measurements.

## Security

Custom headers can contain API credentials.

Keep sensitive credentials in PG3x Custom Parameters rather than hardcoding them into source files.

Use HTTPS where supported.

HTTP requests have a five-second timeout and do not automatically follow redirects.

## Requirements

- Universal Devices eisy with PG3x
- Python 3
- udi_interface
- requests

## Version

1.5.0

## HTTP Scene Controllers (v1.5.0)

Each HTTP endpoint supports up to eight optional scene-controller nodes,
one for each numeric response field.

Example configuration:

    url1_field1 = temperature
    url1_field1_controller = true
    url1_field1_on = 75
    url1_field1_on_operator = >=
    url1_field1_off = 70
    url1_field1_off_operator = <=

Add the resulting Field 1 node to an IoX scene as a Controller.

Supported comparison operators: ==, !=, >, >=, <, <=

Operators default to ==. ON and OFF thresholds default to 1 and 0.

The first matching reading after startup sends an ON or OFF event.
Subsequent events occur only when the controller state changes.

Values between the thresholds retain the previous state (hysteresis).
Before either condition matches, the controller displays Unknown.

If both ON and OFF conditions match, neither event is sent.

Failed HTTP requests and invalid response fields do not trigger scenes.

Save Custom Parameters and restart the node server after configuration changes.
