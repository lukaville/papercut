// Minimal augmentations for the File System Access API bits that are not yet in
// the standard TS lib.dom (the permission helpers). The core handle types
// (FileSystemDirectoryHandle/FileSystemFileHandle) come from lib.dom; we access
// `showDirectoryPicker` and async iteration through small local casts.
export {};

declare global {
  type FileSystemPermissionMode = "read" | "readwrite";

  interface FileSystemHandlePermissionDescriptor {
    mode?: FileSystemPermissionMode;
  }

  interface FileSystemHandle {
    queryPermission?(
      descriptor?: FileSystemHandlePermissionDescriptor,
    ): Promise<PermissionState>;
    requestPermission?(
      descriptor?: FileSystemHandlePermissionDescriptor,
    ): Promise<PermissionState>;
  }
}
