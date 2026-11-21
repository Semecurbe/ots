// Monaco editor (web specification §9). The AMD build of Monaco is served by the
// application itself (no CDN) and loaded the first time an editor is opened.
// Events: "ready", "dirty" (bool), "save" (text), "run" (text), "run_selection" (text),
// "lint" (text, after a pause of typing in Python) and "request" ({id, kind, code, line,
// column}: completion, signature help and hover of Python, answered by the server with Jedi
// through resolveRequest).
let monacoLoading = null;
const EDITORS = new Map(); // model URI → editor component (the providers are global)

const KINDS = {
  function: "Function", class: "Class", module: "Module", instance: "Variable",
  statement: "Variable", param: "Variable", keyword: "Keyword", property: "Property",
  path: "File",
};

function registerPython(monaco) {
  if (window.otsPythonProviders) return;
  window.otsPythonProviders = true;
  const owner = (model) => EDITORS.get(model.uri.toString());
  const where = (model, position) => ({
    code: model.getValue(), line: position.lineNumber, column: position.column - 1,
  });
  monaco.languages.registerCompletionItemProvider("python", {
    triggerCharacters: ["."],
    provideCompletionItems: async (model, position) => {
      const editor = owner(model);
      if (!editor) return { suggestions: [] };
      const items = (await editor.request("complete", where(model, position))) || [];
      const word = model.getWordUntilPosition(position);
      const range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber,
        startColumn: word.startColumn, endColumn: word.endColumn };
      return {
        suggestions: items.map((item, i) => ({
          label: item.label,
          kind: monaco.languages.CompletionItemKind[KINDS[item.kind] || "Text"],
          detail: item.detail || item.kind,
          documentation: item.doc ? { value: item.doc } : undefined,
          insertText: item.label,
          sortText: String(i).padStart(4, "0"),
          range,
        })),
      };
    },
  });
  monaco.languages.registerSignatureHelpProvider("python", {
    signatureHelpTriggerCharacters: ["(", ","],
    provideSignatureHelp: async (model, position) => {
      const editor = owner(model);
      const sig = editor && (await editor.request("signature", where(model, position)));
      if (!sig) return null;
      return {
        value: {
          signatures: [{ label: sig.label, documentation: { value: sig.doc || "" },
            parameters: (sig.parameters || []).map((p) => ({ label: p })) }],
          activeSignature: 0,
          activeParameter: sig.active || 0,
        },
        dispose() {},
      };
    },
  });
  monaco.languages.registerHoverProvider("python", {
    provideHover: async (model, position) => {
      const editor = owner(model);
      const text = editor && (await editor.request("hover", where(model, position)));
      return text ? { contents: [{ value: text }] } : null;
    },
  });
}

function loadMonaco(base) {
  if (window.monaco && window.monaco.editor) return Promise.resolve(window.monaco);
  if (monacoLoading) return monacoLoading;
  monacoLoading = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = base + "/vs/editor/editor.main.css";
    document.head.appendChild(css);
    const script = document.createElement("script");
    script.src = base + "/vs/loader.js";
    script.onload = () => {
      window.require.config({ paths: { vs: base + "/vs" } });
      window.require(["vs/editor/editor.main"], () => resolve(window.monaco), reject);
    };
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return monacoLoading;
}

const CELL = /^\s*#\s*%%/;

export default {
  template: `<div class="ots-editor" style="width:100%;height:100%;min-height:200px"></div>`,
  props: {
    value: String,
    language: { type: String, default: "plaintext" },
    readOnly: { type: Boolean, default: false },
    baseUrl: String,
  },
  async mounted() {
    const monaco = await loadMonaco(this.baseUrl);
    this.editor = monaco.editor.create(this.$el, {
      value: this.value || "",
      language: this.language,
      readOnly: this.readOnly,
      automaticLayout: true,
      fontSize: 13,
      tabSize: 4,
      insertSpaces: true,
      scrollBeyondLastLine: false,
      minimap: { enabled: true },
      theme: document.body.classList.contains("body--dark") ? "vs-dark" : "vs",
    });
    this.markSaved();
    this.pending = new Map();
    this.requests = 0;
    this.uri = this.editor.getModel().uri.toString();
    EDITORS.set(this.uri, this);
    if (this.language === "python") registerPython(monaco);
    this.editor.onDidChangeModelContent(() => {
      const dirty = this.editor.getModel().getAlternativeVersionId() !== this.savedVersion;
      if (dirty !== this.dirty) {
        this.dirty = dirty;
        this.$emit("dirty", dirty);
      }
      if (this.language === "python") {
        clearTimeout(this.lintTimer); // ruff after a pause of typing
        this.lintTimer = setTimeout(() => this.$emit("lint", this.editor.getValue()), 1200);
      }
    });
    const { KeyMod, KeyCode } = monaco;
    this.editor.addCommand(KeyMod.CtrlCmd | KeyCode.KeyS, () => this.$emit("save", this.editor.getValue()));
    this.editor.addCommand(KeyCode.F5, () => this.$emit("run", this.editor.getValue()));
    this.editor.addCommand(KeyMod.Shift | KeyCode.Enter, () => this.$emit("run_selection", this.selectionOrCell()));
    this.$emit("ready");
  },
  unmounted() {
    EDITORS.delete(this.uri);
    clearTimeout(this.lintTimer);
    if (this.editor) this.editor.dispose();
  },
  methods: {
    getValue() {
      return this.editor ? this.editor.getValue() : this.value;
    },
    setValue(text) {
      if (!this.editor) return;
      this.editor.setValue(text);
      this.markSaved();
    },
    markSaved() {
      if (!this.editor) return;
      this.savedVersion = this.editor.getModel().getAlternativeVersionId();
      if (this.dirty) this.$emit("dirty", false);
      this.dirty = false;
    },
    setMarkers(markers, owner = "onthesignal") {
      if (!this.editor || !window.monaco) return;
      const level = { warning: "Warning", info: "Info" };
      window.monaco.editor.setModelMarkers(this.editor.getModel(), owner, (markers || []).map((m) => ({
        startLineNumber: m.line,
        startColumn: m.column || 1,
        endLineNumber: m.end_line || m.line,
        endColumn: m.end_column || 1000,
        message: m.message,
        source: m.source || undefined,
        severity: window.monaco.MarkerSeverity[level[m.severity] || "Error"],
      })));
    },
    request(kind, payload) {
      // Ask the server (Jedi); unanswered after 4 s, the request gives nothing.
      const id = ++this.requests;
      return new Promise((resolve) => {
        this.pending.set(id, resolve);
        this.$emit("request", { id, kind, ...payload });
        setTimeout(() => {
          if (this.pending.has(id)) {
            this.pending.delete(id);
            resolve(null);
          }
        }, 4000);
      });
    },
    resolveRequest(id, result) {
      const resolve = this.pending.get(id);
      if (resolve) {
        this.pending.delete(id);
        resolve(result);
      }
    },
    selectionOrCell() {
      const model = this.editor.getModel();
      const sel = this.editor.getSelection();
      if (sel && !sel.isEmpty()) return model.getValueInRange(sel);
      const lines = model.getLinesContent();
      const cur = this.editor.getPosition().lineNumber - 1;
      if (!lines.some((l) => CELL.test(l))) return lines[cur];
      let start = cur;
      while (start > 0 && !CELL.test(lines[start])) start--;
      if (CELL.test(lines[start])) start++;
      let end = cur + 1;
      while (end < lines.length && !CELL.test(lines[end])) end++;
      return lines.slice(start, end).join("\n");
    },
    focus() {
      if (this.editor) this.editor.focus();
    },
  },
};
