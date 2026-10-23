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

When using the web editor, click Save Configuration to apply endpoint, response-field, and scene-controller changes immediately. Changes made through PG3x Custom Parameters require restarting the node server.

## Web Editor Password Management

Open the HTTPS configuration editor at:

`https://EISY_IP:8766/editor`

Replace `EISY_IP` with your eisy's IP address.

On first installation, create an administrator password of at
least 12 characters. The editor uses HTTP Basic Authentication
with username `admin`.

The locally generated HTTPS certificate is self-signed, so your
browser may initially display a certificate warning.

### Change Password

Open the configuration editor and click **Change Password**
next to **Save Configuration**.

Alternatively, open:

`https://EISY_IP:8766/auth`

Enter your current password and choose a new password.

### Forgotten Password

Connect to the eisy using SSH and run:

    cd ~/http-control
    python3 http_control_auth.py reset

The command generates a temporary recovery code.

Open `https://EISY_IP:8766/auth`, select password recovery,
and enter the code and your new password.

Recovery codes expire after 15 minutes, allow five incorrect
attempts, and can only be used once. Generating a code does
not invalidate the existing password.

Keep recovery codes private. Browser-cached credentials may
require opening a new private browsing window after a change.

The web editor password is separate from credentials used
for outgoing HTTP requests.

## HTTPS & Authentication

HTTP Control accepts HTTP and HTTPS URLs. For HTTPS, use `https://` in `urlN_url`. The server must present a certificate trusted by the eisy, with a hostname matching the URL.

### Username and password (HTTP Basic Authentication)

If the API uses **HTTP Basic Authentication**, encode `username:password` as Base64. On the eisy, run:

```bash
printf '%s' 'admin:mypassword' | base64 | tr -d '\n'
```

The example produces `YWRtaW46bXlwYXNzd29yZA==`. Replace the sample credentials with your own. Configure **each line as a separate PG3x Custom Parameter** (the `=` signs below are separators, not part of the names):

```text
url1_name = Secure Device
url1_url = https://device.example.com/api/status
url1_method = GET
url1_headers = {"Authorization":"Basic YWRtaW46bXlwYXNzd29yZA=="}
url1_interval = 0
```

For your own account, use `{"Authorization":"Basic YOUR_BASE64_VALUE"}` as the **value** of `url1_headers`. Enter it as ordinary JSON, without extra escaping or enclosing quotes. Use the matching `urlN_` prefix for other endpoints. Set response-field mappings only if you need numeric values from the reply.

### Other API authentication headers

- Bearer token: `{"Authorization":"Bearer YOUR_TOKEN"}`
- API key (if specified by the API): `{"X-API-Key":"YOUR_API_KEY"}`
- No authentication: `{}`

These are header-based examples, **not** automatic Digest authentication or web-form/session login. Check the target API documentation for its required authentication scheme.

### Certificates, errors, and security

HTTPS certificate verification is normally enabled. Self-signed, expired, untrusted, or hostname-mismatched certificates may cause SSL verification errors; the documented configuration has no per-endpoint certificate-verification switch. Prefer installing/trusting the appropriate certificate or using a valid certificate rather than disabling verification.

An HTTP **401** generally means missing/invalid credentials; **403** means access is forbidden. A TLS certificate error happens before an HTTP status is received; check PG3x logs. Base64 is **encoding, not encryption**. HTTPS encrypts credentials in transit, but credentials in PG3x Custom Parameters may be visible to administrators. Never publish actual credentials or Authorization headers.

Save the Custom Parameters and restart the node server after changing endpoint configuration.

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

1.5.2

## Release Notes — 1.5.2

- First-time administrator password setup through HTTPS.
- Change Password button in the web configuration editor.
- Password recovery using a code generated through SSH.
- Recovery codes expire after 15 minutes.
- Five incorrect attempts invalidate a recovery code.
- Recovery codes are single-use.

## Release Notes — 1.5.1

- Add a web-based configuration editor with authenticated HTTPS access.
- Save and load endpoint configuration persistently.
- Apply endpoint settings, response-field paths, and scene-controller
  thresholds and operators without restarting the node server.
- Create newly configured endpoint and scene-controller nodes live.
- Disabled scene controllers display Unknown and retain their existing
  IoX node addresses.
- Clear unconfigured response-field values when saving.

## HTTP Scene Controllers (v1.5.1)

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
