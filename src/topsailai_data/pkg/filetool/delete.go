package filetool

// DeleteFile removes one file.
//
// It removes a single regular file, never a folder, so a caller cannot
// accidentally remove a whole subtree. A missing file is reported as
// ErrFileNotFound, which lets a caller distinguish an absent file from a failed
// removal.
func DeleteFile(path string) error {
	return DeleteFileWithFS(path, nil)
}

// DeleteFileWithFS removes one file through the given file system. A nil file
// system uses the operating system file system.
func DeleteFileWithFS(path string, fs FS) error {
	if path == "" {
		return invalidParameter("file_path", path, "must be a non-empty string")
	}
	return resolveFS(fs).DeleteFile(path)
}
