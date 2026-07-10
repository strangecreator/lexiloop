import re
import copy
import json
import uuid
import random
import base64
import hashlib
import pathlib
import datetime
import traceback
import contextlib
import typing as tp
from collections import deque
from collections.abc import Iterator


_TOKEN_RE = re.compile(r"\s+|\S+")
_HEX6 = re.compile(r"^#?[0-9a-fA-F]{6}$")
JSONType = dict[str, tp.Any] | list[tp.Any]


def default_for_none(value: tp.Any, default: tp.Any) -> tp.Any:
    return value if value is not None else default


def generate_json_preview(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def exclude_fields_from_dict(data: dict, fields: list[tp.Any], inplace: bool = False, deepcopy: bool = True) -> dict:
    if not inplace:
        data = copy.deepcopy(data) if deepcopy else copy.copy(data)

    for field in fields:
        data.pop(field, None)
    
    return data


def truncate_dict_to_fields(data: dict, fields: list[tp.Any], inplace: bool = False, deepcopy: bool = True) -> dict:
    keys = set(data.keys())

    if not inplace:
        return {
            field: (copy.deepcopy(data[field]) if deepcopy else data[field])
            for field in fields if (field in keys)
        }
    else:
        return exclude_fields_from_dict(data, list(keys - set(fields)), inplace=True, deepcopy=deepcopy)


def extend_dict(data: dict, new_data: dict, inplace: bool = False, override: bool = True, deepcopy: bool = True, deep: bool = False) -> dict:
    if not inplace:
        data = copy.deepcopy(data) if deepcopy else copy.copy(data)

    def _merge_into(dst: dict, src: dict) -> None:
        for key, value in src.items():
            if key in dst:
                if deep and isinstance(dst[key], dict) and isinstance(value, dict):
                    _merge_into(dst[key], value)
                else:
                    if override:
                        dst[key] = copy.deepcopy(value) if deepcopy else value
            else:
                dst[key] = copy.deepcopy(value) if deepcopy else value

    _merge_into(data, new_data)
    return data


def rename_fields_in_dict(data: dict, mapping: dict, inplace: bool = False, deepcopy: bool = True) -> dict:
    if not inplace:
        return {
            mapping.get(key, key): copy.deepcopy(value) if deepcopy else value
            for (key, value) in data.items()
        }

    renames: list[tuple[tp.Any, tp.Any]] = []

    for src, dst in mapping.items():
        if src == dst or src not in data:
            continue

        renames.append((src, dst))

    if not renames:
        return data

    tmp_keys: list[object] = []

    for src, _dst in renames:
        tmp = object()

        while tmp in data:
            tmp = object()

        tmp_keys.append(tmp)
        data[tmp] = data.pop(src)

    for (_src, dst), tmp in zip(renames, tmp_keys):
        data[dst] = data.pop(tmp)

    return data


def truncate_word_aware(
    string: str,
    max_len: int = 500,
    end: str = '...',
    save_spaces: bool = False,
) -> str:
    if max_len < 0:
        raise ValueError("`max_len` must be >= 0.")

    if max_len == 0:
        return ''

    base = string if save_spaces else " ".join(string.split())

    if len(base) <= max_len:
        return base

    suffix = end[:max_len]
    content_limit = max_len - len(suffix)

    if content_limit <= 0:
        return suffix

    if not save_spaces:
        words = base.split(" ")
        out_words = []
        used = 0

        for word in words:
            add = len(word) if not out_words else (1 + len(word))

            if used + add > content_limit:
                break

            out_words.append(word)
            used += add

        return " ".join(out_words) + suffix

    out_parts = []
    used = 0

    for match in _TOKEN_RE.finditer(base):
        token = match.group(0)

        if token.isspace():
            if used + len(token) > content_limit:
                break

            out_parts.append(token)
            used += len(token)
        else:
            if used + len(token) > content_limit:
                break

            out_parts.append(token)
            used += len(token)

    truncated = "".join(out_parts).rstrip()

    return truncated + suffix


def positive_filter(items: list[tp.Any]) -> list[tp.Any]:
    return [item for item in items if item]


def find_json_start(chunk: bytes) -> int | None:
    starts = {ord('{'), ord('[')}

    for i, byte in enumerate(chunk):
        if byte in starts:
            return i

    return None


def exception_to_string(e: BaseException, traceback_verbose: bool = False) -> str:
    if traceback_verbose:
        return ''.join(traceback.TracebackException.from_exception(e).format())

    string = str(e)

    if string:
        return f"{type(e).__name__}: {string}"

    if getattr(e, "args", ()):
        return f"{type(e).__name__}{e.args!r}"

    return f"{type(e).__name__}"


def repeat(value: tp.Any, size: int) -> list[tp.Any]:
    assert isinstance(size, int) and size >= 0
    return [copy.deepcopy(value) for _ in range(size)]


def generate_random_string_human_readable(length: int = 10) -> str:
    return base64.b32encode(uuid.uuid4().bytes).decode("ascii").rstrip('=')[:length]


def colorize(text: str, hex_color: str, *, background: bool = False, reset: bool = True) -> str:
    """
    Return `text` wrapped in ANSI truecolor escape codes.
    - hex_color: "#RRGGBB" or "RRGGBB"
    - background: if True, sets background color instead of foreground
    """

    if not _HEX6.match(hex_color):
        raise ValueError(f"Expected hex color like '#RRGGBB', got: {hex_color!r}.")

    h = hex_color[1:] if hex_color.startswith("#") else hex_color
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)

    # 38 = foreground, 48 = background and '2' means 24-bit RGB mode
    code = 48 if background else 38
    start = f"\x1b[{code};2;{r};{g};{b}m"
    end = "\x1b[0m" if reset else ''
    return f"{start}{text}{end}"


def hex_color_from_string(string: str, *, lo: int = 40, hi: int = 215) -> str:
    """
    Deterministically map a string -> '#RRGGBB'.
    lo/hi clamp channels to avoid too-dark/too-bright colors for readability.
    """

    if lo < 0 or hi > 255 or lo > hi:
        raise ValueError("Expected 0 <= lo <= hi <= 255")

    # 3 bytes = RGB
    digest = hashlib.blake2s(string.encode("utf-8"), digest_size=3).digest()
    span = hi - lo + 1

    r = lo + (digest[0] % span)
    g = lo + (digest[1] % span)
    b = lo + (digest[2] % span)
    return f"#{r:02x}{g:02x}{b:02x}"


def read_line_by_index(path: str, index: int, encoding: str = "utf-8") -> str:
    if index < 0:
        raise ValueError("index0 must be >= 0")

    with open(path, "r", encoding=encoding, newline="") as file:
        for i, line in enumerate(file):
            if i == index:
                return line.rstrip("\n")

    raise IndexError(f"Line with index={index} was not found in the file.")


def shuffle(
    sequence: list,
    inplace: bool = False,
    deepcopy: bool = True,
) -> list:
    if inplace:
        random.shuffle(sequence)
        return sequence

    out = copy.deepcopy(sequence) if deepcopy else list(sequence)
    random.shuffle(out)
    return out


def join_strings(*strings, sep: str = '') -> str:
    assert all([(string is None or isinstance(string, str)) for string in strings])
    return sep.join([string for string in strings if string is not None])


def touch_file(file_path: str | pathlib.Path) -> None:
    file_path = pathlib.Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.touch(exist_ok=True)


def touch_dir(dir_path: str | pathlib.Path) -> None:
    dir_path = pathlib.Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)


def hash64(string: str) -> str:
    return hashlib.sha256(string.encode("utf-8")).hexdigest()


def hash128(string: str) -> str:
    return hashlib.sha512(string.encode("utf-8")).hexdigest()


def bytesize_to_string(bytes_count: int, decimals: int = 1) -> str:
    if not isinstance(bytes_count, int):
        raise TypeError("`bytes_count` must be an int.")
    if bytes_count < 0:
        raise ValueError("`bytes_count` must be >= 0.")
    if decimals < 0:
        raise ValueError("`decimals` must be >= 0.")

    step = 1024
    units = ['B', "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]

    value = float(bytes_count)
    unit_i = 0
    while value >= step and unit_i < len(units) - 1:
        value /= step
        unit_i += 1

    if unit_i == 0:
        return f"{int(value)} {units[unit_i]}"

    rounded = round(value, decimals)
    if rounded.is_integer():
        return f"{int(rounded)} {units[unit_i]}"

    return f"{rounded:.{decimals}f} {units[unit_i]}"


def datetime_now_pretty(
    *,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    tz: tp.Literal["local", "utc"] = "local",
    timespec: tp.Literal["seconds", "milliseconds", "microseconds"] = "seconds",
    iso: bool = False,
) -> str:
    if tz == "utc":
        now = datetime.datetime.now(datetime.timezone.utc)
    elif tz == "local":
        now = datetime.datetime.now().astimezone()
    else:
        raise ValueError("tz must be 'local' or 'utc'.")

    if iso:
        return now.isoformat(timespec=timespec)

    if timespec == "seconds":
        return now.strftime(fmt)
    if timespec == "milliseconds":
        if "%f" in fmt:
            return now.strftime(fmt)[:-3]
        return now.strftime(fmt) + "." + f"{now.microsecond // 1000:03d}"
    if timespec == "microseconds":
        if "%f" in fmt:
            return now.strftime(fmt)
        return now.strftime(fmt) + "." + f"{now.microsecond:06d}"

    raise ValueError("timespec must be 'seconds', 'milliseconds', or 'microseconds'.")


def datetime_pretty_to_datetime(
    text: str,
    *,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    tz: tp.Literal["local", "utc"] = "local",
    timespec: tp.Literal["seconds", "milliseconds", "microseconds"] = "seconds",
    iso: bool = False,
) -> datetime.datetime:
    if not isinstance(text, str):
        raise TypeError(f"`text` must be str, got {type(text).__name__}.")
    s = text.strip()
    if not s:
        raise ValueError("Empty datetime string.")

    local_tzinfo = datetime.datetime.now().astimezone().tzinfo
    if local_tzinfo is None:
        raise RuntimeError("Could not determine local timezone.")

    def attach_tz_if_naive(dt: datetime.datetime) -> datetime.datetime:
        if dt.tzinfo is not None:
            return dt
        if tz == "utc":
            return dt.replace(tzinfo=datetime.timezone.utc)
        if tz == "local":
            return dt.replace(tzinfo=local_tzinfo)
        raise ValueError("tz must be 'local' or 'utc'.")

    if iso:
        # Accept trailing Z for UTC
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        return attach_tz_if_naive(dt)

    # Non-ISO path mirrors your datetime_now_pretty behavior.

    if "%f" in fmt:
        # Handles 1..6 fractional digits if present in the string.
        dt = datetime.datetime.strptime(s, fmt)
        return attach_tz_if_naive(dt)

    # fmt has no %f: you may have appended .mmm or .uuuuuu
    if "." in s:
        base, frac = s.rsplit(".", 1)
        if not frac.isdigit():
            raise ValueError(f"Invalid fractional part in datetime: {text!r}")

        dt = datetime.datetime.strptime(base, fmt)

        # Normalize fraction to microseconds:
        # "123" -> 123000, "123456" -> 123456, "1" -> 100000, etc.
        microsecond = int(frac[:6].ljust(6, "0"))
        dt = dt.replace(microsecond=microsecond)

        return attach_tz_if_naive(dt)

    dt = datetime.datetime.strptime(s, fmt)
    return attach_tz_if_naive(dt)


class InvalidJSONError(Exception):
    def __init__(self, body_text: str, max_len: int = 3000) -> None:
        self.body_text = body_text
        self.body_text_truncated = truncate_word_aware(
            body_text,
            end="... (truncated)",
            max_len=max_len,
            save_spaces=True,
        )

        super().__init__(f"Invalid JSON:\n{self.body_text_truncated}")


def parse_json_from_string(text: str) -> JSONType:
    if not isinstance(text, str):
        raise TypeError(f"`text` must be str, got {type(text).__name__}.")

    if not text.strip():
        raise InvalidJSONError("Empty input (no JSON to parse).")

    normalized_text = text.lstrip("\ufeff").strip()

    decoder = json.JSONDecoder()

    def try_decode_at(source: str, start_index: int) -> tuple[tp.Any, int] | None:
        try:
            value, end_index = decoder.raw_decode(source, idx=start_index)
        except json.JSONDecodeError:
            return None
        return value, end_index

    def find_fenced_blocks(source: str) -> list[str]:
        fence_pattern = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```", re.DOTALL)
        return [match.group(1) for match in fence_pattern.finditer(source)]

    def iter_json_starts(source: str) -> tp.Iterable[int]:
        for match in re.finditer(r"[\{\[]", source):
            yield match.start()

    def parse_first_container(source: str) -> JSONType | None:
        for start_index in iter_json_starts(source):
            decoded = try_decode_at(source, start_index)
            if decoded is None:
                continue

            value, end_index = decoded

            remainder = source[end_index:].strip()
            if remainder and not re.fullmatch(r"[,;.\s]*", remainder):
                pass

            if isinstance(value, (dict, list)):
                return tp.cast(JSONType, value)

        return None

    fenced_blocks = find_fenced_blocks(normalized_text)
    for block in fenced_blocks:
        parsed = parse_first_container(block.strip())
        if parsed is not None:
            return parsed

    parsed = parse_first_container(normalized_text)
    if parsed is not None:
        return parsed

    preview = text if len(text) <= 1500 else (text[:1500] + "\n...<truncated>...")
    raise InvalidJSONError(f"Could not find a valid JSON object/array in the provided text. Preview:\n{preview}")


@tp.overload
def read_jsonl(path: str | pathlib.Path, load: tp.Literal[False] = False) -> Iterator[str]: ...
@tp.overload
def read_jsonl(path: str | pathlib.Path, load: tp.Literal[True]) -> Iterator[dict | list]: ...

def read_jsonl(path: str | pathlib.Path, load: bool = False) -> Iterator[str | dict | list]:
    file_path = pathlib.Path(path)

    with file_path.open("rt", encoding="utf-8") as file:
        if load:
            for line in file:
                stripped = line.strip()

                if not stripped:
                    continue

                value = json.loads(stripped)

                if isinstance(value, (dict, list)):
                    yield value
                else:
                    raise TypeError(f"JSONL line is {type(value).__name__}, expected dict or list.")
        else:
            for line in file:
                raw = line.rstrip('\n')

                if raw == '':
                    continue

                yield raw


def read_jsonl_indexed(path: str | pathlib.Path) -> tp.Iterator[tuple[int, int, dict | list]]:
    file_path = pathlib.Path(path)

    with file_path.open("rb") as file:
        local_index = 0

        while True:
            offset = file.tell()
            raw = file.readline()

            if not raw:
                break

            stripped = raw.strip()

            if not stripped:
                continue

            value = json.loads(stripped)

            if not isinstance(value, (dict, list)):
                raise TypeError(f"JSONL line is {type(value).__name__}, expected dict or list.")

            yield local_index, offset, value
            local_index += 1


def read_jsonl_at(file: tp.BinaryIO, offset: int) -> dict | list:
    file.seek(offset)
    raw = file.readline().strip()

    if not raw:
        raise ValueError("JSONL offset points to an empty line.")

    value = json.loads(raw)

    if not isinstance(value, (dict, list)):
        raise TypeError(f"JSONL line is {type(value).__name__}, expected dict or list.")

    return value


def concat_jsonl_sequence(
    filepaths: list[str | pathlib.Path],
    names: list[str],
    skip_on_error: bool = False,
    verbose: bool = True,
) -> tp.Iterator[dict]:
    filepaths = [pathlib.Path(path) for path in filepaths]

    if len(filepaths) == 0:
        raise ValueError("`filepaths` must not be empty.")

    if len(filepaths) != len(names):
        raise ValueError("`filepaths` and `names` must have the same length.")

    root_offsets: dict[int, int] = {}
    previous_local_to_root: dict[int, int] = {}

    for local_index, offset, _ in read_jsonl_indexed(filepaths[0]):
        root_offsets[local_index] = offset
        previous_local_to_root[local_index] = local_index

    root_length = len(root_offsets)
    root_to_offsets_by_file: list[dict[int, int]] = [root_offsets]

    for level, filepath in enumerate(filepaths[1:], start=1):
        current_local_to_root: dict[int, int] = {}
        current_root_offsets: dict[int, int] = {}

        for local_index, offset, value in read_jsonl_indexed(filepath):
            if not isinstance(value, dict):
                raise TypeError(f"JSONL line {local_index} in file {level} is {type(value).__name__}, expected dict with `index`.")
            if "index" not in value:
                raise KeyError(f"JSONL line {local_index} in file {level} has no `index` field.")
            if not isinstance(value["index"], int) or isinstance(value["index"], bool):
                raise TypeError(f"JSONL line {local_index} in file {level} has invalid `index`, expected int.")

            parent_local_index = value["index"]

            if parent_local_index not in previous_local_to_root:
                if skip_on_error:
                    if verbose:
                        print(f"Warning: file {level}, line {local_index} has `index` out of bounds for the previous level. Skipped.")
                    continue
                raise ValueError(f"File {level}, line {local_index} has `index` out of bounds for the previous level.")

            root_index = previous_local_to_root[parent_local_index]

            if root_index in current_root_offsets:
                raise ValueError(f"File {level} has multiple rows attached to root index {root_index}; dict output cannot represent that unambiguously.")

            current_local_to_root[local_index] = root_index
            current_root_offsets[root_index] = offset

        previous_local_to_root = current_local_to_root
        root_to_offsets_by_file.append(current_root_offsets)

    with contextlib.ExitStack() as stack:
        files = [stack.enter_context(path.open("rb")) for path in filepaths]

        for root_index in range(root_length):
            item = {name: None for name in names}

            for file_index, name in enumerate(names):
                offset = root_to_offsets_by_file[file_index].get(root_index)

                if offset is not None:
                    item[name] = read_jsonl_at(files[file_index], offset)

            yield item


def concat_jsonl_graph(
    filepaths: list[str | pathlib.Path],
    names: list[str],
    edges: list[tuple[int, int]],
) -> tp.Iterator[dict]:
    filepaths = [pathlib.Path(path) for path in filepaths]
    vertex_count = len(filepaths)

    if vertex_count == 0:
        raise ValueError("`filepaths` must not be empty.")
    if vertex_count != len(names):
        raise ValueError("`filepaths` and `names` must have the same length.")
    if len(edges) != vertex_count - 1:
        raise ValueError("Graph is not a tree: a tree with n vertices must have exactly n - 1 edges.")

    children: list[list[int]] = [[] for _ in range(vertex_count)]
    parent_of = [-1] * vertex_count
    seen_edges: set[tuple[int, int]] = set()

    for parent, child in edges:
        if not isinstance(parent, int) or not isinstance(child, int) or isinstance(parent, bool) or isinstance(child, bool):
            raise TypeError("Every edge must be a tuple of integer vertices.")
        if parent < 0 or parent >= vertex_count or child < 0 or child >= vertex_count:
            raise ValueError("Every edge vertex must be inside the range [0, len(filepaths)).")
        if parent == child:
            raise ValueError("Graph is not a tree: self-loops are not allowed.")
        if (parent, child) in seen_edges:
            raise ValueError("Graph is not a tree: duplicate edges are not allowed.")
        if child == 0:
            raise ValueError("Graph is not rooted at vertex 0: vertex 0 cannot have a parent.")
        if parent_of[child] != -1:
            raise ValueError(f"Graph is not a tree: vertex {child} has more than one parent.")

        seen_edges.add((parent, child))
        parent_of[child] = parent
        children[parent].append(child)

    for vertex in range(1, vertex_count):
        if parent_of[vertex] == -1:
            raise ValueError(f"Graph is not connected to root vertex 0: vertex {vertex} has no parent.")

    order: list[int] = []
    queue = deque([0])

    while queue:
        vertex = queue.popleft()
        order.append(vertex)
        queue.extend(children[vertex])

    if len(order) != vertex_count:
        raise ValueError("Graph is not connected to root vertex 0.")

    root_offsets: dict[int, int] = {}
    local_to_root_by_file: list[dict[int, int]] = [{} for _ in range(vertex_count)]
    root_to_offsets_by_file: list[dict[int, int]] = [{} for _ in range(vertex_count)]

    for local_index, offset, _ in read_jsonl_indexed(filepaths[0]):
        root_offsets[local_index] = offset
        local_to_root_by_file[0][local_index] = local_index

    root_length = len(root_offsets)
    root_to_offsets_by_file[0] = root_offsets

    for vertex in order[1:]:
        parent = parent_of[vertex]
        parent_local_to_root = local_to_root_by_file[parent]
        current_local_to_root: dict[int, int] = {}
        current_root_offsets: dict[int, int] = {}

        for local_index, offset, value in read_jsonl_indexed(filepaths[vertex]):
            if not isinstance(value, dict):
                raise TypeError(f"JSONL line {local_index} in file {vertex} is {type(value).__name__}, expected dict with `index`.")
            if "index" not in value:
                raise KeyError(f"JSONL line {local_index} in file {vertex} has no `index` field.")
            if not isinstance(value["index"], int) or isinstance(value["index"], bool):
                raise TypeError(f"JSONL line {local_index} in file {vertex} has invalid `index`, expected int.")

            parent_local_index = value["index"]

            if parent_local_index not in parent_local_to_root:
                raise ValueError(f"File {vertex}, line {local_index} has `index` out of bounds for parent file {parent}.")

            root_index = parent_local_to_root[parent_local_index]

            if root_index in current_root_offsets:
                raise ValueError(f"File {vertex} has multiple rows attached to root index {root_index}; dict output cannot represent that unambiguously.")

            current_local_to_root[local_index] = root_index
            current_root_offsets[root_index] = offset

        local_to_root_by_file[vertex] = current_local_to_root
        root_to_offsets_by_file[vertex] = current_root_offsets

    with contextlib.ExitStack() as stack:
        files = [stack.enter_context(path.open("rb")) for path in filepaths]

        for root_index in range(root_length):
            item = {name: None for name in names}

            for file_index, name in enumerate(names):
                offset = root_to_offsets_by_file[file_index].get(root_index)

                if offset is not None:
                    item[name] = read_jsonl_at(files[file_index], offset)

            yield item

def extract_json_object(text: str) -> str:
    """Extract the first balanced JSON-like object, respecting quoted strings."""
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    start = text.find('{')
    if start < 0:
        raise ValueError("No '{' found in input.")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start:index + 1].strip()
    raise ValueError('Unbalanced braces in input.')
