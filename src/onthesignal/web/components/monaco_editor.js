// Monaco editor (web specification §9). The AMD build of Monaco is served by the
// application itself (no CDN) and loaded the first time an editor is opened.
// Events: "ready", "dirty" (bool), "save" (text), "run" (text), "run_selection" (text).
let monacoLoading = null;

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
      theme: "vs",
    });
    this.markSaved();
    this.editor.onDidChangeModelContent(() => {
      const dirty = this.editor.getModel().getAlternativeVersionId() !== this.savedVersion;
      if (dirty !== this.dirty) {
        this.dirty = dirty;
        this.$emit("dirty", dirty);
      }
    });
    const { KeyMod, KeyCode } = monaco;
    this.editor.addCommand(KeyMod.CtrlCmd | KeyCode.KeyS, () => this.$emit("save", this.editor.getValue()));
    this.editor.addCommand(KeyCode.F5, () => this.$emit("run", this.editor.getValue()));
    this.editor.addCommand(KeyMod.Shift | KeyCode.Enter, () => this.$emit("run_selection", this.selectionOrCell()));
    this.$emit("ready");
  },
  unmounted() {
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
    setMarkers(markers) {
      if (!this.editor || !window.monaco) return;
      window.monaco.editor.setModelMarkers(this.editor.getModel(), "onthesignal", (markers || []).map((m) => ({
        startLineNumber: m.line,
        startColumn: m.column || 1,
        endLineNumber: m.line,
        endColumn: m.end_column || 1000,
        message: m.message,
        severity: m.severity === "warning" ? window.monaco.MarkerSeverity.Warning : window.monaco.MarkerSeverity.Error,
      })));
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
