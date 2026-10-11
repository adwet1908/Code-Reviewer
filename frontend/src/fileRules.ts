// Keep these in sync with backend/app/config.py. The server checks again.

export const CODE_MAX_BYTES = 200 * 1024;
export const CONTEXT_MAX_BYTES = 2 * 1024 * 1024;
export const ZIP_MAX_BYTES = 5 * 1024 * 1024;
export const MAX_UPLOADS = 20;

const CODE_EXTENSIONS = new Set([
  ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
  ".java", ".go", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh",
  ".cs", ".rb", ".php", ".rs", ".kt", ".kts", ".swift", ".scala",
  ".sql", ".sh", ".bash", ".html", ".css", ".scss", ".vue", ".svelte",
  ".json", ".yaml", ".yml", ".toml", ".xml",
]);

const CONTEXT_EXTENSIONS = new Set([".md", ".txt", ".pdf", ".docx"]);

export type FileKind = "code" | "context" | "zip";

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0) return "";
  return name.slice(dot).toLowerCase();
}

export function kindOf(name: string): FileKind | null {
  const extension = extensionOf(name);
  if (extension === ".zip") return "zip";
  if (CODE_EXTENSIONS.has(extension)) return "code";
  if (CONTEXT_EXTENSIONS.has(extension)) return "context";
  return null;
}

export function limitFor(kind: FileKind): number {
  if (kind === "code") return CODE_MAX_BYTES;
  if (kind === "context") return CONTEXT_MAX_BYTES;
  return ZIP_MAX_BYTES;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function addFiles(current: File[], incoming: File[]): { files: File[]; error: string | null } {
  const next = [...current];
  const errors: string[] = [];

  for (const file of incoming) {
    if (next.length >= MAX_UPLOADS) {
      errors.push(`You can select at most ${MAX_UPLOADS} files.`);
      break;
    }
    const kind = kindOf(file.name);
    if (!kind) {
      errors.push(
        `${file.name}: unsupported type. Use source code, a .zip, or a .md, .txt, .pdf, or .docx file.`,
      );
      continue;
    }
    const limit = limitFor(kind);
    if (file.size > limit) {
      errors.push(
        `${file.name} is ${formatBytes(file.size)}. The limit for this type is ${formatBytes(limit)}.`,
      );
      continue;
    }
    if (file.size === 0) {
      errors.push(`${file.name} is empty.`);
      continue;
    }
    const alreadySelected = next.some(
      (existing) =>
        existing.name === file.name &&
        existing.size === file.size &&
        existing.lastModified === file.lastModified,
    );
    if (!alreadySelected) next.push(file);
  }

  return { files: next, error: errors.length > 0 ? errors.join(" ") : null };
}
