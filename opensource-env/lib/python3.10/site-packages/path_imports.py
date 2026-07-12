from __future__ import annotations


__version__ = "1.1.2"


import importlib.machinery
import importlib.util
import os
import sys
import types
import typing as t
from pathlib import Path

try:
    from importlib.machinery import NamespaceLoader
except ImportError:
    from importlib._bootstrap_external import _NamespaceLoader as NamespaceLoader


__all__ = [
    "import_from_path",
    "import_from_directory",
    "find_module_location",
    "create_namespace_package",
]


def find_module_location(
    module_name: str,
    *,
    directory: str | os.PathLike | None = None,
) -> Path | None:
    """
    Finds the path of the given module, or `None` if it can't be found.

    :param module_name: The name of the module to find
    :param directory: Optionally, a specific directory that should be searched. If omitted, all
        directories in `sys.path` are searched.
    :return: The path of the module, or `None` if it can't be found.
    """
    *packages, module_name = module_name.split(".")

    if directory is None:
        directories = sys.path
    else:
        directories = [directory]

    for candidate_directory in directories:
        parent_directory = Path(candidate_directory).joinpath(*packages)

        # First, check for a directory with an __init__.py
        module_location = parent_directory / module_name / "__init__.py"
        if module_location.is_file():
            return module_location.parent

        # Then check for importable files
        for file_path in parent_directory.glob(f"{module_name}.*"):
            spec = importlib.util.spec_from_file_location(module_name, file_path)

            if spec is not None:
                return file_path

        # Finally, check for a directory with no __init__.py
        module_location = parent_directory / module_name
        if module_location.is_dir():
            return module_location

    return None


def import_from_directory(
    module_name: str,
    directory: str | os.PathLike,
    *,
    force_reimport: bool = False,
    add_directory_to_sys_path: bool = False,
) -> types.ModuleType:
    """
    Imports a module or package from the given directory. The imported module is added to
    `sys.modules`.

    The directory is searched for a matching package or module in this order:
        1. a package (i.e. a directory named "module_name" with an __init__.py)
        2. a .py file (i.e. a file named "module_name.py")

    :param module_name: The module or package name to import.
    :param directory: The path of the directory where the module or package resides.
    :param force_reimport: Whether to re-import the module in case it's already present in
        `sys.modules`.
    :param add_directory_to_sys_path: Whether to temporarily add the directory to `sys.path`. This
        lets the module import other files from that directory.
    :raises ModuleNotFoundError: If the module can't be found in the given directory.
    :raises ImportError:
        - If an exception is raised during the execution of the module's code
        - If `force_reimport` is `False` and a module with this name already exists
        - If an error occurs in the internals of the importlib machinery
    :return: The imported module instance.
    """
    module_path = find_module_location(module_name, directory=directory)
    if module_path is None:
        raise ModuleNotFoundError(f"Module {module_name!r} could not be found in {directory!r}")

    return import_from_path(
        module_path,
        module_name,
        force_reimport=force_reimport,
        add_parent_directory_to_sys_path=add_directory_to_sys_path,
        import_parent_modules=True,
    )


def import_from_path(
    path: str | os.PathLike,
    module_name: str | None = None,
    *,
    force_reimport: bool = False,
    import_parent_modules: bool = True,
    add_parent_directory_to_sys_path: bool = False,
) -> types.ModuleType:
    """
    Imports the module or package at the given path. The imported module is added to `sys.modules`.

    :param path: Direct path to the module or package.
    :param module_name: Optional module name. If not given, the file/folder name is used.
    :param force_reimport: Whether to re-import the module in case it's already present in
        `sys.modules`.
    :param import_parent_modules: Whether parent modules should also be imported in case the module
        name contains dots.
    :param add_parent_directory_to_sys_path: Whether to temporarily add the parent directory of the
        (root) module to `sys.path`. This lets the module import other files from that directory.
    :raises ImportError:
        - If an exception is raised during the execution of the module's code
        - If `force_reimport` is `False` and a module with this name already exists
        - If an error occurs in the internals of the importlib machinery
    :return: The imported module instance.
    """
    path = Path(path)

    if module_name is None:
        module_name = path.stem

    if add_parent_directory_to_sys_path:
        parent_dir = str(path.parents[module_name.count(".")])
        sys.path.insert(0, parent_dir)

    try:
        # If we don't have to import the parent modules, then it's easy - just check if it's a file
        # or folder and call the appropriate function.
        if not import_parent_modules:
            if force_reimport:
                sys.modules.pop(module_name, None)

            return _import_file_or_folder(path, module_name)

        # If we do have to import the parent modules as well, then we have to start at the root
        # module
        if force_reimport:
            mod_name = module_name
            while mod_name:
                sys.modules.pop(mod_name, None)
                mod_name, _, _ = mod_name.rpartition(".")

        *package_names, _ = module_name.split(".")

        # I want this to work even if the folder names don't match the package names. Since the user
        # told us to import this as "foo.bar", that's what we're gonna do. So start at the given
        # module path, and go up the file system until we hit the root module.
        package_dirs = dict[str, Path]()
        package_path = path
        for package_name in reversed(package_names):
            package_path = package_path.parent
            package_dirs[package_name] = package_path

        for i, package_name in enumerate(package_names, 1):
            full_name = ".".join(package_names[:i])
            package_path = package_dirs[package_name]

            _import_folder(package_path, full_name)

        return _import_file_or_folder(path, module_name)
    finally:
        if add_parent_directory_to_sys_path:
            assert parent_dir  # type: ignore
            sys.path.remove(parent_dir)


def _import_file_or_folder(path: Path, name: str) -> types.ModuleType:
    if path.is_file():
        return _import_file(path, name)
    else:
        return _import_folder(path, name)


def _import_file(path: Path, name: str) -> types.ModuleType:
    try:
        module = sys.modules[name]
    except KeyError:
        pass
    else:
        if module.__file__ == str(path.absolute()):
            return module

        raise ImportError(
            f"The file {path} cannot be imported because a module named"
            f" {name!r} already exists."
        )

    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None:
        raise ImportError(
            "The module could not be loaded for an unknown reason."
            " (`importlib.util.spec_from_file_location` returned `None`.)"
        )

    return _module_from_spec(spec)


def _import_folder(path: Path, name: str) -> types.ModuleType:
    init_py_path = path / "__init__.py"

    if init_py_path.is_file():
        return _import_file(init_py_path, name)

    # If there's no __init__.py, create a namespace package
    return create_namespace_package(name, [path])


def _module_from_spec(spec: importlib.machinery.ModuleSpec) -> types.ModuleType:
    if spec.loader is None:
        raise ImportError(
            "The module could not be loaded for an unknown reason."
            " (`importlib.util.spec_from_file_location` returned a module spec"
            " without a loader.)"
        )

    module = importlib.util.module_from_spec(spec)

    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        del sys.modules[spec.name]

        raise ImportError(
            f"An exception was raised during execution of the module code: {type(error)} {error}"
        ) from error

    return module


def create_namespace_package(
    module_name: str, directories: t.Iterable[str | os.PathLike]
) -> types.ModuleType:
    submodule_search_locations = [os.fspath(directory) for directory in directories]

    path_finder = importlib.machinery.PathFinder._get_spec  # type: ignore
    loader = NamespaceLoader(module_name, submodule_search_locations, path_finder)

    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None

    spec.submodule_search_locations = submodule_search_locations

    package = _module_from_spec(spec)
    package.__file__ = None

    return package
