"""KYB-Bench scoring service: POST /api/score, run as an AWS Lambda behind CloudFront.

Body: {"split": "test_fresh" | "test_historical", "system": {...}, "predictions": [prediction, ...]}
Header: X-KYB-Key: <submitter key>

Hidden labels and submitter keys come from Secrets Manager (the secrets named in KYB_LABELS_SECRET
and KYB_KEYS_SECRET), never from the deployment package. Only aggregate metrics are returned.
"""

import base64
import hmac
import json
import os

from kybbench import leaderboard

SPLITS = ("test_fresh", "test_historical")
MAX_BYTES = 6_000_000  # Lambda's request payload limit
_cache = {}


def _secret(name):
    if name not in _cache:
        import boto3  # available in the Lambda runtime
        _cache[name] = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=os.environ[name])["SecretString"])
    return _cache[name]


def _team(key, keys):
    return next((team for team, k in keys.items() if key and hmac.compare_digest(k, key)), None)


def score(key, raw, keys, labels):
    """(status, body) for one request; keys {team: key}, labels {split: packed labels}."""
    team = _team(key, keys)
    if not team:
        return 401, {"error": "unknown or missing submitter key (X-KYB-Key)"}
    if not 0 < len(raw) <= MAX_BYTES:
        return 413, {"error": f"body must be between 1 byte and {MAX_BYTES} bytes"}
    try:
        body = json.loads(raw)
        split = body["split"]
        blob = labels[split]
    except (ValueError, KeyError, TypeError):
        return 400, {"error": f"expected JSON with split in {list(SPLITS)} and predictions"}
    preds = {p["case_id"]: p for p in body.get("predictions") or [] if isinstance(p, dict) and "case_id" in p}
    result = leaderboard.score(leaderboard.unpack(blob), preds)
    # the logs keep a record of every submission, so probing for labels can be spotted
    print(json.dumps({"submission": team, "split": split, "n_predictions": len(preds), "system": body.get("system")}))
    return 200, {"team": team, "split": split, "system": body.get("system"), "metrics": result}


def handler(event, context):
    """Lambda function URL handler."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method != "POST":
        status, body = 200, {"service": "KYB-Bench scoring", "splits": list(SPLITS), "method": "POST /api/score"}
    else:
        raw = event.get("body") or ""
        raw = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        status, body = score(headers.get("x-kyb-key"), raw, _secret("KYB_KEYS_SECRET"), _secret("KYB_LABELS_SECRET"))
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}
