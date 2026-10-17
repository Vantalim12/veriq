"""Create missing Appwrite resources; refuse to change existing configuration."""

import json
import os
from pathlib import Path

from veriq.appwrite_store import AppwriteAPI, AppwriteError
from veriq.ingestion import InputError


def ensure(api, collection, payload, identifier_key):
    path = collection + "/" + payload[identifier_key]
    try:
        existing = api.request("GET", path)
    except AppwriteError as exc:
        if exc.code != 404:
            raise
        return api.request("POST", collection, json=payload)
    for field in ("permissions", "fileSecurity", "rowSecurity", "enabled", "encryption", "maximumFileSize",
                  "execute", "events", "schedule", "entrypoint", "runtime", "timeout", "scopes", "logging",
                  "commands", "antivirus", "compression", "allowedFileExtensions"):
        actual = existing.get("$permissions" if field == "permissions" else field)
        if field in payload and actual != payload[field]:
            raise InputError(f"existing {path} has different {field}; review it before continuing")
    for group in ("columns", "indexes"):
        actual = {item["key"]: item for item in existing.get(group, [])}
        for item in payload.get(group, []):
            if item["key"] not in actual or any(actual[item["key"]].get(k) != v for k, v in item.items()):
                raise InputError(f"existing {path} has a different {group} definition")
    return existing


def provision(api, spec):
    ensure(api, "/storage/buckets", spec["bucket"], "bucketId")
    ensure(api, "/tablesdb", spec["database"], "databaseId")
    tables = "/tablesdb/" + spec["database"]["databaseId"] + "/tables"
    for table in spec["tables"]:
        ensure(api, tables, table, "tableId")
    for function in spec["functions"]:
        ensure(api, "/functions", function, "functionId")


if __name__ == "__main__":
    api = AppwriteAPI(os.environ["APPWRITE_FUNCTION_API_ENDPOINT"],
        os.environ["APPWRITE_FUNCTION_PROJECT_ID"], os.environ["VERIQ_APPWRITE_API_KEY"])
    try:
        provision(api, json.loads(Path(__file__).with_name("resources.json").read_text()))
        print("Private resources and function definitions are ready. Configure variables and deploy the code archive.")
    finally:
        api.close()
