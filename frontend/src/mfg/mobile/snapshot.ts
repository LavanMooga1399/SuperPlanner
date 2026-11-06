/**
 * The offline glance of the mobile home (M6 2): the last successfully loaded home data per user and workspace in
 * IndexedDB (`sp-mobile` / `snapshots`). No other API data is kept on the device. Failing storage is ignored.
 */
const DB = "sp-mobile";
const STORE = "snapshots";

function open(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

export interface Snapshot<T> {
  at: string;
  data: T;
}

export async function saveSnapshot<T>(key: string, data: T): Promise<void> {
  const db = await open();
  if (!db) return;
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put({ at: new Date().toISOString(), data } satisfies Snapshot<T>, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
  db.close();
}

export async function loadSnapshot<T>(key: string): Promise<Snapshot<T> | null> {
  const db = await open();
  if (!db) return null;
  const out = await new Promise<Snapshot<T> | null>((resolve) => {
    try {
      const req = db.transaction(STORE, "readonly").objectStore(STORE).get(key);
      req.onsuccess = () => resolve((req.result as Snapshot<T> | undefined) ?? null);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  db.close();
  return out;
}

/** Sign-out / plant removal: drop everything kept for the glance. */
export async function clearSnapshots(): Promise<void> {
  const db = await open();
  if (!db) return;
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    } catch {
      resolve();
    }
  });
  db.close();
}
