"""Flask Application entrypoint."""
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
