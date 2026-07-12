import inspect
import typing as t


def _get_parsed_signature(method: t.Callable[..., t.Any]) -> inspect.Signature:
    """
    Get the signature of a method, with all parameters and return type
    being proper type instances, rather than strings.
    """

    parsed_annotations = t.get_type_hints(method)
    raw_signature = inspect.signature(method)

    # Replace all parameters with their parsed version
    parsed_parameters = []
    for param_name, param in raw_signature.parameters.items():
        try:
            param = param.replace(annotation=parsed_annotations[param_name])
        except KeyError:
            pass

        parsed_parameters.append(param)

    # Replace the return type
    return_type = parsed_annotations["return"]

    # Put it all together
    return raw_signature.replace(
        parameters=parsed_parameters,
        return_annotation=return_type,
    )
