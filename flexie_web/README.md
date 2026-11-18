# flexie_web

React 19 + TypeScript + Vite front end for Flexie's **provider settings and hand-gesture control** panel. It is separate from the other two web UIs: the dashboard served by the bridge at `http://localhost:8766/` (`interface/web_ui.html`) and the hand-gesture orb in `../vision/` (launched by saying "open vision mode").

## What is in it

- `src/App.tsx` - provider key/model form (Groq, OpenAI, DeepSeek, Gemini, Anthropic, Mistral, Ollama), the active-provider switch, and a gesture panel.
- `src/lib/handTracker.ts`, `gestureMapper.ts`, `useGestureControl.ts` - MediaPipe hand tracking (`@mediapipe/tasks-vision`), mapping gestures (swipe left/right/up/down, open palm, fist, wave, point) to Flexie commands with a 1.5 s cooldown.
- Settings are kept in the browser's `localStorage`; saving also sends `SET_API_KEY:<provider>:<key>` and `SET_MODEL:<provider>:<model>` over a WebSocket to `ws://localhost:8765`.

## Run it

```bash
cd flexie_web
npm install
npm run dev      # Vite dev server
npm run build    # type-check + production build into dist/
npm run lint
```

## Known gaps (verified against the code, not fixed here)

- **Backend link:** the WebSocket bridge (`interface/web_ui_bridge.py`) accepts browser connections only from its own dashboard origin (`http://localhost:8766` / `127.0.0.1:8766`) and requires `AUTH:<token>` as the first message. This app, served from the Vite dev server, sends neither, so it shows "offline" and settings are saved locally only unless the bridge's allowed origins are extended.
- **Stale model lists:** the provider catalogue in `App.tsx` lists default models such as `llama-3.1-8b-instant` (Groq) and `gemini-1.5-flash` that no longer match the backend defaults (`openai/gpt-oss-20b` for Groq, `gemini-flash-latest` for Gemini; see `utils/config.py` `SUPPORTED_PROVIDERS`).
- Gestures need camera permission in the browser and have not been tested live.

## Tooling

Created from the Vite React-TS template: ESLint flat config in `eslint.config.js`, `@vitejs/plugin-react`, TypeScript project references (`tsconfig.app.json`, `tsconfig.node.json`). To turn on type-aware lint rules, replace `tseslint.configs.recommended` with `recommendedTypeChecked` (or `strictTypeChecked`) in `eslint.config.js`.
