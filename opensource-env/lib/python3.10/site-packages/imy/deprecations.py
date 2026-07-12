import collections
import dataclasses
import functools
import inspect
import types
import typing as t
import warnings

import introspection

__all__ = [
    "configure",
    "deprecated",
    "parameter_renamed",
    "parameter_remapped",
    "warn",
    "warn_parameter_renamed",
]


C = t.TypeVar("C", bound=t.Callable)


@dataclasses.dataclass
class Deprecation:
    since_version: str
    message: str
    will_be_removed_in_version: str | None = None


# Global data structures containing information that's useful for
# `imy.docstrings`
deprecated_objects = collections.defaultdict[
    t.Callable | types.ModuleType | property, list[Deprecation]
](list)
deprecated_parameters = collections.defaultdict[
    t.Callable, collections.defaultdict[str, list[Deprecation]]
](lambda: collections.defaultdict(list))


# Configs. Each config is associated with a module. This allows different
# modules to customize how their deprecation warnings are displayed.
class Config:
    def __init__(
        self,
        project_name: str,
        modules_skipped_in_stacktrace: t.Container[str] | None = None,
        warning_class: type[Warning] = DeprecationWarning,
        name_for_object: t.Callable[[t.Callable], str] = lambda obj: obj.__name__,
    ):
        if modules_skipped_in_stacktrace is None:
            modules_skipped_in_stacktrace = {project_name}

        self.project_name = project_name
        self.modules_skipped_in_stacktrace = modules_skipped_in_stacktrace
        self.warning_class = warning_class
        self.name_for_object = name_for_object

    def make_parameter_deprecation_message(
        self,
        old_name: str,
        new_name: str,
        callable_: t.Callable | str | None = None,
    ) -> str:
        if callable_ is None:
            of_what = ""
        else:
            if not isinstance(callable_, str):
                callable_ = self.name_for_object(callable_)

            of_what = f" of `{callable_}`"

        return f"The `{old_name}` parameter{of_what} has been renamed. Use `{new_name}` instead."

    def add_versions(
        self,
        message: str,
        *,
        since: str | None = None,
        will_be_removed_in_version: str | None = None,
    ) -> str:
        if since is None:
            intro = ""
        else:
            intro = f"Deprecated since {self.project_name} version {since}"

        if will_be_removed_in_version is not None:
            if intro:
                intro += f"; to be removed in version {will_be_removed_in_version}"
            else:
                intro = f"To be removed in version {will_be_removed_in_version}"

        return f"{intro}: {message}"

    def warn(self, message: str) -> None:
        # Find the first stack frame outside of the module that's issuing the
        # warning. (Passing the stack level manually is error prone because
        # decorators like `@parameter_renamed` increase the call depth.)
        stacklevel = 0
        try:
            call_frame = introspection.CallFrame.up(1)
            stacklevel = 2

            while call_frame is not None:
                try:
                    module_name: str = call_frame.globals["__name__"]
                except KeyError:
                    # This can happen if the function is called via `eval` or
                    # `exec`.
                    break

                module_name, _, _ = module_name.partition(".")

                if (
                    module_name != "imy"
                    and module_name not in self.modules_skipped_in_stacktrace
                ):
                    break

                call_frame = call_frame.parent
                stacklevel += 1
        finally:
            call_frame = None  # Break the reference cycle

        warnings.warn(
            message,
            self.warning_class,
            stacklevel=stacklevel,
        )


DEFAULT_CONFIG = Config("imy")
module_name_to_config = dict[str, Config]()


def get_config_for_calling_module() -> Config:
    module_name = get_calling_module()
    return module_name_to_config.get(module_name, DEFAULT_CONFIG)


# I'm not a huge fan of inspecting the call stack, so this function exists as an
# alternatite to `get_config_for_calling_module()`. It obtains the module name
# via the `__module__` attribute of a class or function.
def get_config_for_defining_module(obj: t.Callable) -> Config:
    module_name, _, _ = obj.__module__.partition(".")
    return module_name_to_config.get(module_name, DEFAULT_CONFIG)


def configure(
    module: str | None = None,
    *,
    project_name: str | None = None,
    modules_skipped_in_stacktrace: t.Container[str] | None = None,
    warning_class: type[Warning] = DeprecationWarning,
    name_for_object: t.Callable[[t.Callable], str] = lambda obj: obj.__name__,
) -> None:
    """
    Configures how deprecation warnings are displayed for your module.

    ## Parameters

    `module`: The module to which this configuration should apply. This
        parameter is optional; if omitted, it will apply to the module that is
        calling this function.

    `project_name`: The name of your project, as it should apper in deprecation
        warnings.

    `modules_skipped_in_stacktrace`: Names of modules that should be omitted
        from the stacktrace of a deprecation warning.

    `warning_class`: The type of warning that is emitted at runtime.

        Note: Per default, python only displays `DeprecationWarning`s that
        originate from the `__main__` module. Keeping this in mind, you may want
        to choose a different `Warning` class or reconfigure the warnings
        filter.

    `name_for_object`: A function that takes a deprecated object as input and
        returns its name, as it should appear in deprecation warnings.
    """
    if module is None:
        module_name = get_calling_module()
    else:
        module_name, _, _ = module.partition(".")

    if project_name is None:
        project_name = module_name

    module_name_to_config[module_name] = Config(
        project_name=project_name,
        modules_skipped_in_stacktrace=modules_skipped_in_stacktrace,
        warning_class=warning_class,
        name_for_object=name_for_object,
    )


def get_calling_module() -> str:
    try:
        call_frame = introspection.CallFrame.up(1)

        while call_frame is not None:
            root_module, _, _ = call_frame.globals["__name__"].partition(".")

            if root_module != "imy":
                return root_module

            call_frame = call_frame.parent

        assert False, "All frames on the call stack are from `imy`?!"
    finally:
        call_frame = None  # Break the reference cycle


def function_or_class_decorator(
    decorator: t.Callable[[Config, C, t.Callable, t.Callable], C],
) -> t.Callable[[C], C]:
    """
    Many decorators in this module can be applied to both functions and classes,
    but classes need special handling - the decorator has to modify the class's
    `__init__` method instead.

    This function helps with the implementation of such decorators. It's hard to
    explain how it works, so here's an example instead:

    ```
    @function_or_class_decorator
    def my_decorator(
        config: Config,
        decorated_callable: C,
        undecorated_callable: t.Callable,
        function_to_wrap: t.Callable,
    ) -> C:
        ...
    ```

    The arguments passed to the decorator are:

    1. The relevant `Config`.
    2. The object that was decorated.
    3. The object that was decorated, but with all decorators removed. This is
       the "original" callable, for which the deprecation should be registered.
    4. The function that needs to be wrapped. (If the input was a class, this
       will be the relevant `__init__` method.)

    Your decorator doesn't need to use `@functools.wraps`. The metadata will be
    updated automatically.
    """

    def actual_decorator(decorated_callable: C) -> C:
        config = get_config_for_defining_module(decorated_callable)

        # Decorators often return a *new* callable, which is a problem for us.
        # We want to register all our Deprecations with the original,
        # undecorated, callable.
        undecorated_callable = inspect.unwrap(decorated_callable)

        # Easy case: It's a function. Just apply the decorator as usual.
        if not isinstance(decorated_callable, type):
            result = decorator(
                config,
                decorated_callable,
                undecorated_callable,
                decorated_callable,
            )
            functools.update_wrapper(result, decorated_callable)
            return result

        # Harder case: It's a class. We must decorate its `__init__` instead.
        original_init = decorated_callable.__init__
        new_init = decorator(
            config,
            decorated_callable,  # type: ignore (ugh)
            undecorated_callable,
            original_init,
        )

        new_init.__name__ = "__init__"
        new_init.__qualname__ = decorated_callable.__qualname__ + ".__init__"
        new_init.__module__ = decorated_callable.__module__
        new_init.__wrapped__ = original_init  # type: ignore

        decorated_callable.__init__ = new_init

        # Return the class, not the `__init__`
        return decorated_callable  # type: ignore (ugh)

    return actual_decorator


@t.overload
def deprecated(
    *,
    since: str,
    replacement: t.Callable | str,
    will_be_removed_in_version: str | None = None,
) -> t.Callable[[C], C]: ...


@t.overload
def deprecated(
    *,
    since: str,
    description: str,
    will_be_removed_in_version: str | None = None,
) -> t.Callable[[C], C]: ...


def deprecated(
    *,
    since: str,
    will_be_removed_in_version: str | None = None,
    description: str | None = None,
    replacement: t.Callable | str | None = None,
) -> t.Callable[[C], C]:
    """
    This is a class/function decorator that marks the decorated object as
    deprecated. Calling the deprecated object will emit a runtime warning.
    """

    @function_or_class_decorator
    def decorator(
        config: Config,
        decorated_callable: C,
        undecorated_callable: t.Callable,
        function_to_wrap: t.Callable,
    ) -> C:
        if description is None:
            warning_message = (
                f"`{config.name_for_object(decorated_callable)}` is deprecated"
            )
        else:
            warning_message = description

        if replacement is not None and not isinstance(replacement, str):
            replacement_name = config.name_for_object(replacement)
        else:
            replacement_name = replacement

        if replacement_name is not None:
            warning_message += f". Use `{replacement_name}` instead."

        deprecated_objects[undecorated_callable].append(
            Deprecation(
                since_version=since,
                message=warning_message,
                will_be_removed_in_version=will_be_removed_in_version,
            )
        )

        warning_message = config.add_versions(
            warning_message,
            since=since,
            will_be_removed_in_version=will_be_removed_in_version,
        )

        def wrapper(*args, **kwargs):
            config.warn(warning_message)
            return function_to_wrap(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


def parameter_renamed(
    *,
    since: str,
    old_name: str,
    new_name: str,
    will_be_removed_in_version: str | None = None,
) -> t.Callable[[C], C]:
    """
    This decorator helps with renaming a parameter. Works on functions and
    classes.

    The old parameter should be removed from the signature. Example:

    ```
    @parameter_renamed(old_name='foo', new_name='bar', since='1.0')
    def my_function(bar: int):
        ...
    ```

    Note: In case of a class, only the `__init__` method will be modified.
    `__new__` methods are not affected.
    """

    @function_or_class_decorator
    def decorator(
        config: Config,
        decorated_callable: C,
        undecorated_callable: t.Callable,
        function_to_wrap: t.Callable,
    ) -> C:
        warning_message = config.make_parameter_deprecation_message(
            old_name=old_name,
            new_name=new_name,
            callable_=decorated_callable,
        )

        deprecated_parameters[undecorated_callable][old_name].append(
            Deprecation(
                since_version=since,
                message=warning_message,
                will_be_removed_in_version=will_be_removed_in_version,
            )
        )

        warning_message = config.add_versions(
            warning_message,
            since=since,
            will_be_removed_in_version=will_be_removed_in_version,
        )

        def new_function(*args, **kwargs):
            # Remap the old parameter to the new one
            try:
                kwargs[new_name] = kwargs.pop(old_name)
            except KeyError:
                pass
            else:
                config.warn(warning_message)

            # Delegate to the original function
            return function_to_wrap(*args, **kwargs)

        return new_function  # type: ignore

    return decorator


def parameter_remapped(
    *,
    since: str,
    old_name: str,
    new_name: str,
    remap: t.Callable[[t.Any], t.Any],
    will_be_removed_in_version: str | None = None,
):
    """
    This is a function decorator that's quite similar to `parameter_renamed`,
    but it allows you to change the type and value of the parameter as well
    as the name.

    Example: `Theme.from_colors` used to have a `light: bool = True` parameter
    which was changed to `mode: t.Literal['light', 'dark'] = 'light'`.

        class Theme:
            @parameter_remapped(
                since='0.9',
                old_name='light',
                new_name='mode'
                remap=lambda light: "light" if light else "dark",
            )
            def from_colors(..., mode: t.Literal['light', 'dark'] = 'light'):
                ...

        Theme.from_colors(light=False)  # Equivalent to `mode='dark'`

    WARNING: The remapping only takes effect if the argument is passed as a
    keyword argument.
    """

    @function_or_class_decorator
    def decorator(
        config: Config,
        decorated_callable: C,
        undecorated_callable: t.Callable,
        function_to_wrap: t.Callable,
    ) -> C:
        warning_message = config.make_parameter_deprecation_message(
            old_name=old_name,
            new_name=new_name,
            callable_=decorated_callable,
        )

        deprecated_parameters[undecorated_callable][old_name].append(
            Deprecation(
                since_version=since,
                message=warning_message,
                will_be_removed_in_version=will_be_removed_in_version,
            )
        )

        warning_message = config.add_versions(
            warning_message,
            since=since,
            will_be_removed_in_version=will_be_removed_in_version,
        )

        def wrapper(*args, **kwargs):
            try:
                old_value = kwargs.pop(old_name)
            except KeyError:
                pass
            else:
                config.warn(warning_message)
                kwargs[new_name] = remap(old_value)

            return function_to_wrap(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


def warn(message: str, *, since: str | None = None):
    """
    Emits a runtime warning.

    This function is part of the "low-level API". Please use the provided
    decorators instead whenever possible.
    """
    config = get_config_for_calling_module()

    if since is not None:
        message = config.add_versions(message, since=since)

    config.warn(message)


def warn_parameter_renamed(
    *,
    old_name: str,
    new_name: str,
    function: t.Callable | str | None = None,
    since: str | None = None,
    will_be_removed_in_version: str | None = None,
):
    """
    Emits a runtime warning about a parameter being renamed.

    This function is part of the "low-level API". Please use the provided
    decorators instead whenever possible.
    """
    config = get_config_for_calling_module()

    message = config.make_parameter_deprecation_message(
        old_name=old_name, new_name=new_name, callable_=function
    )

    message = config.add_versions(
        message,
        since=since,
        will_be_removed_in_version=will_be_removed_in_version,
    )

    config.warn(message)
