# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_bd0834cfe6cdacb0bea5569505d330b8 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.definitions._inputs import resolve_inputs
from riko.modules.fetchdata import pipe as fetchdata
from riko.modules.input import pipe as _input
from riko.modules.urlbuilder import pipe as urlbuilder
from riko.runtime._workflow_pipes import workflow
from riko.types._enums import ExecutionMode
from riko.types.modules import FetchDataRawConf, InputRawConf, UrlBuilderRawConf

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {
    "gid": {"default": "1276", "description": "MP Guardian ID", "type": "string"}
}
DEPENDENCIES = ["fetchdata", "input", "urlbuilder"]


@workflow(subtype="transformer")
def pipe(item: Item | None = None, context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
        inputs = resolve_inputs(
            INPUT_SCHEMAS, None if context is None else context.inputs
        )
        sw_606 = _input(
            item,
            conf=InputRawConf({"input_key": {"type": "text", "value": "gid"}}),
            inputs=inputs,
            context=context,
        )
        sw_579 = urlbuilder(
            None,
            conf=UrlBuilderRawConf(
                {
                    "base": {"type": "text", "value": ""},
                    "param": [
                        {
                            "key": {"type": "text", "value": ""},
                            "value": {"type": "text", "value": ""},
                        }
                    ],
                    "path": [
                        {"terminal": "1_PATH", "type": "text"},
                        {"type": "text", "value": "json"},
                    ],
                }
            ),
            context=context,
            _1_PATH=sw_606,
        )
        sw_610 = fetchdata(
            None,
            conf=FetchDataRawConf(
                {
                    "url": {"terminal": "URL", "type": "url"},
                    "path": {"type": "text", "value": "person"},
                }
            ),
            context=context,
            URL=sw_579,
        )
        _OUTPUT = sw_610
    elif context.mode is ExecutionMode.DESCRIBE:
        _OUTPUT = iter([{"input_schemas": INPUT_SCHEMAS, "dependencies": DEPENDENCIES}])
    elif context.describe_input:
        _OUTPUT = iter([INPUT_SCHEMAS])
    else:
        _OUTPUT = iter(DEPENDENCIES)

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
