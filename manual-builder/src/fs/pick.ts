/**
 * Directory picking + permission helpers for the File System Access API.
 *
 * The user may pick either a single project directory (one that contains a
 * `manual/` folder or `project.yaml`) or the `projects/` root, in which case we
 * enumerate the project subdirectories so they can choose one.
 */

interface DirectoryPickerOptions {
  id?: string;
  mode?: FileSystemPermissionMode;
  startIn?: FileSystemHandle | string;
}

type ShowDirectoryPicker = (options?: DirectoryPickerOptions) => Promise<FileSystemDirectoryHandle>;

export function isFileSystemAccessSupported(): boolean {
  return typeof (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker ===
    "function";
}

/** Open the OS directory picker. Returns null if the user cancels. */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle | null> {
  const show = (window as unknown as { showDirectoryPicker?: ShowDirectoryPicker })
    .showDirectoryPicker;
  if (!show) {
    throw new Error(
      "This browser lacks the File System Access API. Use Chrome or Edge.",
    );
  }
  try {
    return await show({ id: "papercut-manual", mode: "readwrite" });
  } catch (err) {
    if ((err as DOMException)?.name === "AbortError") return null;
    throw err;
  }
}

async function hasDir(handle: FileSystemDirectoryHandle, name: string): Promise<boolean> {
  try {
    await handle.getDirectoryHandle(name);
    return true;
  } catch {
    return false;
  }
}

async function hasFile(handle: FileSystemDirectoryHandle, name: string): Promise<boolean> {
  try {
    await handle.getFileHandle(name);
    return true;
  } catch {
    return false;
  }
}

/** A directory is a project if it has a `manual/` folder or a `project.yaml`. */
export async function isProjectDir(handle: FileSystemDirectoryHandle): Promise<boolean> {
  return (await hasDir(handle, "manual")) || (await hasFile(handle, "project.yaml"));
}

/** Names of immediate child directories that look like projects. */
export async function listProjectSubdirs(handle: FileSystemDirectoryHandle): Promise<string[]> {
  const names: string[] = [];
  const iterable = handle as unknown as AsyncIterable<[string, FileSystemHandle]>;
  for await (const [name, child] of iterable) {
    if (child.kind !== "directory" || name.startsWith(".")) continue;
    if (await isProjectDir(child as FileSystemDirectoryHandle)) names.push(name);
  }
  names.sort((a, b) => a.localeCompare(b));
  return names;
}

/** Ensure read/write permission, prompting only when a gesture allows it. */
export async function ensurePermission(
  handle: FileSystemHandle,
  interactive: boolean,
): Promise<PermissionState> {
  const opts: FileSystemHandlePermissionDescriptor = { mode: "readwrite" };
  const current = (await handle.queryPermission?.(opts)) ?? "granted";
  if (current === "granted") return current;
  if (!interactive) return current;
  return (await handle.requestPermission?.(opts)) ?? "denied";
}
