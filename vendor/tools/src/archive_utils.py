from __future__ import annotations

import datetime
import os
import pathlib
import re
import stat
import zipfile


PathLike = str | pathlib.Path

_REGEX_PREFIXES = ("re:", "regex:")
_GLOB_MAGIC_CHARS = ("*", "?", "[")


__all__ = [
    "archive_selected",
    "resolve_selected_paths",
    "resolve_selected_dirs",
]


def archive_selected(
    dir: PathLike,
    selected: list[str],
    *,
    archive_path: PathLike | None = None,
    include_root: bool = True,
    overwrite: bool = True,
    strict_unmatched: bool = True,
    exclude_macos_metadata: bool = True,
    preserve_symlinks: bool = True,
    compression: int = zipfile.ZIP_DEFLATED,
    compresslevel: int | None = 6,
) -> pathlib.Path:
    """
    Archive selected files/folders from `dir`.

    `selected` items may be:
    - exact relative file/folder paths:
        "src"
        "README.md"
        "data/raw"
    - glob patterns, relative to `dir`:
        "*.toml"
        "tests/test_*.py"
        "data/**/images"
    - regex patterns, matched against POSIX-style relative paths:
        "re:^src/.*\\.py$"
        "regex:^experiments/run_[0-9]+$"

    By default, archive paths include the root folder name:

        tools_selected_2026-06-01_23-10-00.zip
        └── tools/
            ├── src/
            ├── README.md
            └── pyproject.toml
    """

    root = _normalize_root_dir(dir)

    selected_paths = resolve_selected_paths(
        root,
        selected,
        strict_unmatched=strict_unmatched,
    )

    if not selected_paths:
        raise ValueError("No files/directories selected.")

    output_path = _normalize_archive_path(root, archive_path)

    if output_path.exists():
        if output_path.is_dir():
            raise IsADirectoryError(f"Archive path points to a directory: {output_path}")
        if not overwrite:
            raise FileExistsError(f"Archive already exists: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path_resolved = output_path.resolve(strict=False)

    written: set[str] = set()

    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=compression,
        compresslevel=compresslevel,
        allowZip64=True,
    ) as zip_file:
        if include_root:
            _write_dir_entry(
                zip_file=zip_file,
                path=root,
                arcname=f"{root.name}/",
                written=written,
            )

        for selected_path in selected_paths:
            _write_selected_path(
                zip_file=zip_file,
                root=root,
                selected_path=selected_path,
                include_root=include_root,
                output_path=output_path_resolved,
                written=written,
                exclude_macos_metadata=exclude_macos_metadata,
                preserve_symlinks=preserve_symlinks,
                compression=compression,
                compresslevel=compresslevel,
            )

    return output_path


def resolve_selected_paths(
    dir: PathLike,
    selected: list[str],
    *,
    strict_unmatched: bool = True,
) -> list[pathlib.Path]:
    """
    Resolve selected exact paths / glob patterns / regex patterns
    to files and directories.

    Regex patterns must be prefixed with "re:" or "regex:".

    Regex matching is done against POSIX-style relative paths, for example:

        "src/archive_utils.py"
        "README.md"
        "tests/test_dict_utils.py"

    If a directory and its child are both selected, only the directory is kept,
    because archiving the directory already includes the child.
    """

    root = _normalize_root_dir(dir)

    if not isinstance(selected, list):
        raise TypeError(f"`selected` must be list[str], got {type(selected).__name__}.")

    if not selected:
        raise ValueError("`selected` must not be empty.")

    matched_paths: list[pathlib.Path] = []
    unmatched: list[str] = []

    for item in selected:
        if not isinstance(item, str):
            raise TypeError(f"Every item in `selected` must be str, got {type(item).__name__}.")

        pattern = item.strip()

        if not pattern:
            raise ValueError("Empty selected pattern.")

        if _is_regex_pattern(pattern):
            matches = _match_regex_paths(root, pattern)
        else:
            matches = _match_exact_or_glob_paths(root, pattern)

        if not matches:
            unmatched.append(item)
        else:
            matched_paths.extend(matches)

    if unmatched and strict_unmatched:
        joined = ", ".join(repr(item) for item in unmatched)
        raise FileNotFoundError(f"No files/directories matched selected pattern(s): {joined}")

    return _drop_duplicate_and_nested_paths(root, matched_paths)


def resolve_selected_dirs(
    dir: PathLike,
    selected: list[str],
    *,
    strict_unmatched: bool = True,
) -> list[pathlib.Path]:
    """
    Compatibility helper.

    For archiving, use resolve_selected_paths(...), because selected items
    may be files too.
    """

    return [
        path
        for path in resolve_selected_paths(
            dir,
            selected,
            strict_unmatched=strict_unmatched,
        )
        if path.is_dir() and not path.is_symlink()
    ]


def _write_selected_path(
    *,
    zip_file: zipfile.ZipFile,
    root: pathlib.Path,
    selected_path: pathlib.Path,
    include_root: bool,
    output_path: pathlib.Path,
    written: set[str],
    exclude_macos_metadata: bool,
    preserve_symlinks: bool,
    compression: int,
    compresslevel: int | None,
) -> None:
    if _same_path(selected_path, output_path):
        return

    _write_ancestor_dir_entries(
        zip_file=zip_file,
        root=root,
        selected_path=selected_path,
        include_root=include_root,
        written=written,
    )

    if selected_path.is_symlink():
        if preserve_symlinks:
            _write_symlink_entry(
                zip_file=zip_file,
                path=selected_path,
                arcname=_archive_name(root, selected_path, include_root),
                written=written,
                compression=compression,
                compresslevel=compresslevel,
            )
        return

    if selected_path.is_dir():
        _write_tree(
            zip_file=zip_file,
            root=root,
            selected_dir=selected_path,
            include_root=include_root,
            output_path=output_path,
            written=written,
            exclude_macos_metadata=exclude_macos_metadata,
            preserve_symlinks=preserve_symlinks,
            compression=compression,
            compresslevel=compresslevel,
        )
        return

    if selected_path.is_file():
        _write_file_entry(
            zip_file=zip_file,
            path=selected_path,
            arcname=_archive_name(root, selected_path, include_root),
            written=written,
            compression=compression,
            compresslevel=compresslevel,
        )
        return

    raise FileNotFoundError(f"Selected path disappeared or has unsupported type: {selected_path}")


def _normalize_root_dir(path: PathLike) -> pathlib.Path:
    root = pathlib.Path(path).expanduser().resolve(strict=False)

    if not root.exists():
        raise FileNotFoundError(f"Directory does not exist: {root}")

    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    return root


def _normalize_archive_path(
    root: pathlib.Path,
    archive_path: PathLike | None,
) -> pathlib.Path:
    if archive_path is None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return root.parent / f"{root.name}_selected_{timestamp}.zip"

    path = pathlib.Path(archive_path).expanduser()

    if not path.is_absolute():
        path = pathlib.Path.cwd() / path

    return path.resolve(strict=False)


def _is_regex_pattern(pattern: str) -> bool:
    return pattern.startswith(_REGEX_PREFIXES)


def _strip_regex_prefix(pattern: str) -> str:
    for prefix in _REGEX_PREFIXES:
        if pattern.startswith(prefix):
            regex = pattern[len(prefix):]

            if not regex:
                raise ValueError(f"Empty regex pattern: {pattern!r}")

            return regex

    raise ValueError(f"Not a regex pattern: {pattern!r}")


def _match_regex_paths(root: pathlib.Path, pattern: str) -> list[pathlib.Path]:
    regex_text = _strip_regex_prefix(pattern)

    try:
        regex = re.compile(regex_text)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern {pattern!r}: {e}") from e

    matches: list[pathlib.Path] = []

    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        rel = path.relative_to(root).as_posix()

        if regex.search(rel):
            matches.append(_absolute_no_symlink_resolution(path))

    return matches


def _match_exact_or_glob_paths(root: pathlib.Path, pattern: str) -> list[pathlib.Path]:
    pattern = _normalize_relative_pattern(pattern)

    matches: list[pathlib.Path] = []

    exact_path = _absolute_no_symlink_resolution(root / pattern)

    if exact_path.exists() or exact_path.is_symlink():
        matches.append(exact_path)

    if _has_glob_magic(pattern):
        for path in sorted(root.glob(pattern), key=lambda item: item.as_posix()):
            if path == root:
                continue

            if path.exists() or path.is_symlink():
                matches.append(_absolute_no_symlink_resolution(path))

    return _unique_paths(matches)


def _normalize_relative_pattern(pattern: str) -> str:
    pattern = pattern.strip().replace("\\", "/").strip("/")

    if not pattern:
        raise ValueError("Selected path/glob must not be empty.")

    pure = pathlib.PurePosixPath(pattern)

    if pure.is_absolute():
        raise ValueError(f"Selected path/glob must be relative, got absolute path: {pattern!r}")

    parts = pure.parts

    if any(part == ".." for part in parts):
        raise ValueError(f"Selected path/glob must not contain '..': {pattern!r}")

    if pattern == ".":
        raise ValueError("Selecting the root directory itself is not allowed; select files/subfolders instead.")

    return pattern


def _has_glob_magic(pattern: str) -> bool:
    return any(char in pattern for char in _GLOB_MAGIC_CHARS)


def _drop_duplicate_and_nested_paths(
    root: pathlib.Path,
    paths: list[pathlib.Path],
) -> list[pathlib.Path]:
    unique = _unique_paths(paths)

    sorted_paths = sorted(
        unique,
        key=lambda path: (
            path.relative_to(root).parts,
            0 if path.is_dir() and not path.is_symlink() else 1,
        ),
    )

    result: list[pathlib.Path] = []
    selected_dirs: list[pathlib.Path] = []

    for path in sorted_paths:
        if any(_is_relative_to(path, directory) for directory in selected_dirs):
            continue

        result.append(path)

        if path.is_dir() and not path.is_symlink():
            selected_dirs.append(path)

    return result


def _unique_paths(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    seen: set[pathlib.Path] = set()
    result: list[pathlib.Path] = []

    for path in paths:
        absolute = _absolute_no_symlink_resolution(path)

        if absolute in seen:
            continue

        seen.add(absolute)
        result.append(absolute)

    return result


def _absolute_no_symlink_resolution(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(os.fspath(path)))


def _write_tree(
    *,
    zip_file: zipfile.ZipFile,
    root: pathlib.Path,
    selected_dir: pathlib.Path,
    include_root: bool,
    output_path: pathlib.Path,
    written: set[str],
    exclude_macos_metadata: bool,
    preserve_symlinks: bool,
    compression: int,
    compresslevel: int | None,
) -> None:
    for current_str, dirnames, filenames in os.walk(selected_dir, topdown=True, followlinks=False):
        current = pathlib.Path(current_str)

        dirnames[:] = sorted(dirnames)
        filenames = sorted(filenames)

        if exclude_macos_metadata:
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname != "__MACOSX"
            ]

            filenames = [
                filename
                for filename in filenames
                if filename != ".DS_Store"
            ]

        current_arcname = _archive_name(root, current, include_root)

        _write_dir_entry(
            zip_file=zip_file,
            path=current,
            arcname=current_arcname + "/",
            written=written,
        )

        normal_dirnames: list[str] = []
        symlink_dirnames: list[str] = []

        for dirname in dirnames:
            path = current / dirname

            if path.is_symlink():
                symlink_dirnames.append(dirname)
            else:
                normal_dirnames.append(dirname)

        dirnames[:] = normal_dirnames

        for dirname in symlink_dirnames:
            path = current / dirname

            if preserve_symlinks:
                _write_symlink_entry(
                    zip_file=zip_file,
                    path=path,
                    arcname=_archive_name(root, path, include_root),
                    written=written,
                    compression=compression,
                    compresslevel=compresslevel,
                )

        for filename in filenames:
            path = current / filename

            if _same_path(path, output_path):
                continue

            arcname = _archive_name(root, path, include_root)

            if path.is_symlink():
                if preserve_symlinks:
                    _write_symlink_entry(
                        zip_file=zip_file,
                        path=path,
                        arcname=arcname,
                        written=written,
                        compression=compression,
                        compresslevel=compresslevel,
                    )

                continue

            if path.is_file():
                _write_file_entry(
                    zip_file=zip_file,
                    path=path,
                    arcname=arcname,
                    written=written,
                    compression=compression,
                    compresslevel=compresslevel,
                )


def _write_ancestor_dir_entries(
    *,
    zip_file: zipfile.ZipFile,
    root: pathlib.Path,
    selected_path: pathlib.Path,
    include_root: bool,
    written: set[str],
) -> None:
    if include_root:
        _write_dir_entry(
            zip_file=zip_file,
            path=root,
            arcname=f"{root.name}/",
            written=written,
        )

    rel_parts = selected_path.relative_to(root).parts

    if selected_path.is_dir() and not selected_path.is_symlink():
        parent_parts = rel_parts[:-1]
    else:
        parent_parts = rel_parts

    current = root

    for part in parent_parts[:-1]:
        current = current / part

        _write_dir_entry(
            zip_file=zip_file,
            path=current,
            arcname=_archive_name(root, current, include_root) + "/",
            written=written,
        )


def _write_dir_entry(
    *,
    zip_file: zipfile.ZipFile,
    path: pathlib.Path,
    arcname: str,
    written: set[str],
) -> None:
    arcname = arcname.rstrip("/") + "/"

    if not arcname or arcname in written:
        return

    info = zipfile.ZipInfo(
        filename=arcname,
        date_time=_zip_datetime(path),
    )

    info.create_system = 3
    info.external_attr = (stat.S_IFDIR | _permission_bits(path, default=0o755)) << 16

    zip_file.writestr(info, b"")
    written.add(arcname)


def _write_file_entry(
    *,
    zip_file: zipfile.ZipFile,
    path: pathlib.Path,
    arcname: str,
    written: set[str],
    compression: int,
    compresslevel: int | None,
) -> None:
    arcname = arcname.rstrip("/")

    if not arcname or arcname in written:
        return

    zip_file.write(
        filename=path,
        arcname=arcname,
        compress_type=compression,
        compresslevel=compresslevel,
    )

    written.add(arcname)


def _write_symlink_entry(
    *,
    zip_file: zipfile.ZipFile,
    path: pathlib.Path,
    arcname: str,
    written: set[str],
    compression: int,
    compresslevel: int | None,
) -> None:
    arcname = arcname.rstrip("/")

    if not arcname or arcname in written:
        return

    target = os.readlink(path)

    info = zipfile.ZipInfo(
        filename=arcname,
        date_time=_zip_datetime(path),
    )

    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16

    zip_file.writestr(
        zinfo_or_arcname=info,
        data=target.encode("utf-8"),
        compress_type=compression,
        compresslevel=compresslevel,
    )

    written.add(arcname)


def _archive_name(
    root: pathlib.Path,
    path: pathlib.Path,
    include_root: bool,
) -> str:
    path = _absolute_no_symlink_resolution(path)

    if path == root:
        return root.name if include_root else ""

    rel = path.relative_to(root).as_posix()

    if include_root:
        return f"{root.name}/{rel}"

    return rel


def _zip_datetime(path: pathlib.Path) -> tuple[int, int, int, int, int, int]:
    try:
        timestamp = path.lstat().st_mtime
    except OSError:
        return 1980, 1, 1, 0, 0, 0

    dt = datetime.datetime.fromtimestamp(timestamp)

    if dt.year < 1980:
        return 1980, 1, 1, 0, 0, 0

    return dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second


def _permission_bits(path: pathlib.Path, *, default: int) -> int:
    try:
        mode = stat.S_IMODE(path.lstat().st_mode)
    except OSError:
        return default

    return mode or default


def _is_relative_to(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False

    return True


def _same_path(left: pathlib.Path, right: pathlib.Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return False