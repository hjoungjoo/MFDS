"""Build a process-only integration without shipping native loader code.

Development sources stay intact. Replacements use AST spans and fail closed if
an expected definition changes. The resulting GPL Python source is distributed
verbatim in the commercial package, with the original surrounding comments.
"""

import ast


def replace_definitions(source, replacements):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    found = set()
    for node in reversed(tree.body):
        name = getattr(node, "name", None)
        if name in replacements:
            lines[node.lineno - 1 : node.end_lineno] = [replacements[name] + "\n"]
            found.add(name)
    if found != replacements.keys():
        raise ValueError(
            f"Commercial transformation missing: {replacements.keys() - found}"
        )
    return "".join(lines)


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Commercial transformation expected one occurrence: {old!r}")
    return source.replace(old, new)


def integration_source(name, data):
    source = data.decode()
    if name == "star_detect.py":
        source = replace_definitions(
            source,
            {
                "_native_library": "",
                "_detect_ctypes": "",
            },
        )
        source = replace_once(source, "import ctypes\n", "")
        source = replace_once(
            source,
            '    elif transport == "ctypes":\n        output, _ = _detect_ctypes(arr, saturation, binning, sigma, mode)\n',
            "",
        )
        source = source.replace(
            "must be process or ctypes", "must be process in MFNavis commercial builds"
        )
        source = source.replace(
            "MF_DETECT_TRANSPORT=ctypes selects the former in-process path for comparison.",
            "MFNavis commercial build: only the standalone process transport is included.",
        )
    elif name == "mf_star_only_preprocess.py":
        source = replace_definitions(
            source,
            {
                "_NativeTemporalReduction": 'class _NativeTemporalReduction:\n    def __init__(self):\n        raise ReductionUnavailable("Native linking excluded from MFNavis commercial build")',
                "_NativeGPU": 'class _NativeGPU:\n    def __init__(self):\n        raise GPUUnavailable("Native linking excluded from MFNavis commercial build")',
            },
        )
        for line in (
            "import ctypes\n",
            "from pathlib import Path\n",
            "import platform\n",
        ):
            source = replace_once(source, line, "")
        source = replace_once(
            source,
            'os.environ.get("MF_PREPROCESS_REDUCTION", "auto")',
            'os.environ.get("MF_PREPROCESS_REDUCTION", "numpy")',
        )
    elif name == "detector_profiles.py":
        source = source.replace('("process", "ctypes")', '("process",)')
        source = source.replace(
            "must be process or ctypes", "must be process in MFNavis commercial builds"
        )
    validate_python(source, name)
    return source.encode()


def validate_python(source, name):
    tree = ast.parse(source, filename=name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"ctypes", "cffi"}:
            raise ValueError(f"Native loader reference in commercial package: {name}")
        if isinstance(node, ast.Attribute) and node.attr in {
            "ctypes",
            "ctypeslib",
            "CDLL",
            "PyDLL",
            "LoadLibrary",
            "dlopen",
        }:
            raise ValueError(f"Native loader call in commercial package: {name}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
            if any(
                module.split(".")[0] in {"ctypes", "_ctypes", "cffi"}
                for module in modules
            ):
                raise ValueError(f"Native loader import in commercial package: {name}")


def validate_files(files):
    for name, data in files.items():
        if name.startswith("build/") and name != "build/mf_detect_star_server":
            raise ValueError(f"Unexpected commercial native artifact: {name}")
        if name.endswith((".so", ".dll", ".dylib", ".pyc")) or ".so." in name:
            raise ValueError(f"Native library/bytecode in commercial package: {name}")
        if name.endswith(".py"):
            validate_python(data.decode(), name)
