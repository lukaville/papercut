/**
 * Persists the opened project's directory handle in IndexedDB so the app can
 * reconnect to the same folder across page refreshes. File System Access
 * handles are structured-cloneable, so they round-trip through IndexedDB.
 */

const DB_NAME = "papercut-manual-builder";
const STORE = "handles";
const KEY = "project-dir";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(STORE, mode);
        const request = run(transaction.objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => db.close();
      }),
  );
}

export function saveProjectHandle(handle: FileSystemDirectoryHandle): Promise<void> {
  return tx("readwrite", (store) => store.put(handle, KEY)).then(() => undefined);
}

export function loadProjectHandle(): Promise<FileSystemDirectoryHandle | null> {
  return tx<FileSystemDirectoryHandle | undefined>("readonly", (store) => store.get(KEY))
    .then((h) => h ?? null)
    .catch(() => null);
}

export function clearProjectHandle(): Promise<void> {
  return tx("readwrite", (store) => store.delete(KEY)).then(() => undefined);
}
