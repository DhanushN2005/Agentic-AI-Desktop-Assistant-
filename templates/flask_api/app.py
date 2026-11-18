"""Flask Application entrypoint."""
import os

from flask import Flask, jsonify, request

app = Flask(__name__)

items = []


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "flask_api"}), 200


@app.route("/api/items", methods=["GET"])
def get_items():
    return jsonify({"items": items}), 200


@app.route("/api/items", methods=["POST"])
def add_item():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "Missing item name"}), 400
    item = {"id": len(items) + 1, "name": name}
    items.append(item)
    return jsonify(item), 201


def _port() -> int:
    """Port to bind: the PORT environment variable when valid, otherwise 5000."""
    try:
        port = int(os.environ.get("PORT", "5000"))
    except ValueError:
        return 5000
    return port if 0 < port < 65536 else 5000


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=_port(),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )
