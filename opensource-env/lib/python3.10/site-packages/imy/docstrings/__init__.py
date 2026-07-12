"""
Functionality for standardized docstring parsing.

Docstrings are expected to have the following form:

```
# An optional heading-1 in the first line is stripped

The first line is the summary.

The summary is followed by a blank line and then the description. The
description may be arbitrarily long. It may span multiple lines, paragraphs,
contain code blocks, whatever.

## Parameters

`param_`: Parameters are stored in key sections. Values may span multiple
    lines, as long as followup lines are indented

param_2: The backticks around the name are optional, and only so the name shows
    up as code when viewing the docstring directly inside a code editor

## Raises

`ValueError`: This section works the same as parameters

## Attributes

`attr_1`: As does this

## Metadata

`public`: Whether this object is meant for anyone outside of the packages itself

`experimental`: This marks code whose API may still change

## Other Sections

Any sections other than the ones listed above are considered to be part of the
description. They are not parsed in any way.
```
"""

from .data_models import *
from .utilities import *
