import fs from "fs";
import { JSDOM } from "jsdom";
const html = `<!doctype html><body><div class="status-chips"></div><span id="mailUnreadBadge" style="display:none">0</span></body>`;
const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
const sent = [], toasts = [];
w.sendRaw = (m) => { sent.push(m); return true; };
w.toast = (t, m, ty) => toasts.push([t, m, ty]);
w.eval(fs.readFileSync(process.argv[2], "utf8"));
await new Promise((r) => setTimeout(r, 100));   // let DOMContentLoaded fire (the real page loads the script at the end of <body>)
const P = w.FlexiePanels;
const ok = (c, msg) => { console.log((c ? "PASS " : "FAIL ") + msg); if (!c) process.exitCode = 1; };

// keys button injected
ok(!!w.document.getElementById("fxKeysBtn"), "Keys button added to the status chips");

// approval: plain (controller) then JSON (permission system) -> ONE modal, adopts id
ok(P.handle("APPROVAL_REQUEST", "delete file notes.txt") === true, "APPROVAL_REQUEST handled");
P.handle("APPROVAL_REQUEST", JSON.stringify({ id: "req-1", action: "delete file notes.txt", level: "USER_CONFIRMATION" }));
ok(w.document.querySelectorAll(".fx-approval").length === 1, "duplicate announcement keeps a single modal");
w.document.querySelectorAll(".fx-btn")[1].click(); // Approve
ok(sent.at(-1) === "APPROVE:req-1", "Approve sends APPROVE:<id> (got " + sent.at(-1) + ")");
ok(w.document.querySelectorAll(".fx-approval").length === 0, "modal closes after answering");

// reject without id, and Esc = reject
P.handle("APPROVAL_REQUEST", "format drive");
w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
ok(sent.at(-1) === "CANCEL", "Esc with no id sends CANCEL (got " + sent.at(-1) + ")");

// reject with id
P.handle("APPROVAL_REQUEST", JSON.stringify({ id: "req-2", action: "send email", level: "SENSITIVE" }));
w.document.querySelectorAll(".fx-btn")[0].click();
ok(sent.at(-1) === "REJECT:req-2", "Reject sends REJECT:<id>");

// resolved closes
P.handle("APPROVAL_REQUEST", "x");
P.handle("APPROVAL_RESOLVED", "approved");
ok(w.document.querySelectorAll(".fx-approval").length === 0, "APPROVAL_RESOLVED closes the modal");

// XSS: server text is shown as text only
P.handle("APPROVAL_REQUEST", '<img src=x onerror="window.__pwned=1"><b>hi</b>');
ok(w.document.querySelector(".fx-action img") === null && !w.__pwned, "action text is not parsed as HTML");
ok(w.document.querySelector(".fx-action").textContent.includes("<img"), "action text shown literally");
P.handle("APPROVAL_RESOLVED", "rejected");

// not connected: stays open and says so
w.sendRaw = () => false;
P.handle("APPROVAL_REQUEST", "danger");
w.document.querySelectorAll(".fx-btn")[1].click();
ok(w.document.querySelectorAll(".fx-approval").length === 1 && /Not connected/.test(w.document.querySelector(".fx-status").textContent), "send failure keeps the modal open with a message");
w.sendRaw = (m) => { sent.push(m); return true; };
P.handle("APPROVAL_RESOLVED", "rejected");

// settings
w.document.getElementById("fxKeysBtn").click();
ok(sent.at(-1) === "GET_SETTINGS", "Keys button requests GET_SETTINGS");
const snap = { active: "auto", active_choices: ["auto", "groq", "gemini"], ollama: { url: "http://localhost:11434/api/generate", model: "tinyllama:latest" },
  providers: [{ id: "groq", label: "Groq", env: "GROQ_API_KEY", help: "console.groq.com/keys", placeholder: "gsk_...", has_key: true, hint: "gsk_••••abcd", model: "openai/gpt-oss-20b", models: ["openai/gpt-oss-20b"] },
              { id: "gemini", label: "Gemini", env: "GEMINI_API_KEY", help: "", placeholder: "AIza...", has_key: false, hint: "", model: "gemini-flash-latest", models: [] }] };
P.handle("SETTINGS", JSON.stringify(snap));
const pw = [...w.document.querySelectorAll("input[type=password]")];
ok(pw.length === 2 && pw.every(i => i.value === ""), "two password inputs, empty (saved keys are never shown)");
ok(/gsk_••••abcd \(saved\)/.test(pw[0].placeholder), "masked hint shown in the placeholder only");
pw[1].value = "AIzaSyTESTKEY12345678";
const saveBtn = [...w.document.querySelectorAll(".fx-btn")].find(b => b.textContent === "Save");
saveBtn.click();
const m = sent.at(-1);
ok(m.startsWith("SAVE_SETTINGS:"), "Save sends SAVE_SETTINGS");
const payload = JSON.parse(m.slice("SAVE_SETTINGS:".length));
ok(payload.keys.gemini === "AIzaSyTESTKEY12345678" && !("groq" in payload.keys), "only the typed key is sent");
ok(pw[1].value === "", "key input cleared right after sending");
ok(payload.models.groq === "openai/gpt-oss-20b" && payload.active === "auto", "models and active provider included");
P.handle("SETTINGS_SAVED", JSON.stringify({ changed: 1, problems: [] }));
ok(/Saved 1 setting/.test(w.document.querySelector(".fx-settings .fx-status").textContent), "SETTINGS_SAVED shows the result");
ok(sent.at(-1) === "GET_SETTINGS", "settings refreshed after a save");

// mail + quit
P.handle("MAIL_COUNT", "7");
ok(w.document.getElementById("mailUnreadBadge").textContent === "7" && w.document.getElementById("mailUnreadBadge").style.display !== "none", "MAIL_COUNT updates the badge");
P.handle("MAIL_COUNT", "0");
ok(w.document.getElementById("mailUnreadBadge").style.display === "none", "badge hidden at zero");
P.handle("MAIL_INBOX", "[{\"id\":1},{\"id\":2}]");
ok(w.document.getElementById("mailUnreadBadge").textContent === "2", "MAIL_INBOX (JSON list) counts items");
ok(P.handle("QUIT", "") === true && toasts.at(-1)[0] === "Flexie", "QUIT shows a notice");
ok(P.handle("STATE", "IDLE") === false, "unknown tags fall through (returns false)");
