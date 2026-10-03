# vim: sw=4:ts=4:expandtab

"""
Aggregate freelance jobs from several feeds and normalize their budgets.

The feeds are odesk, guru, elance, and freelancer.

Examples:

    Run it::

        run-pipe kazeeki

"""

from __future__ import annotations

from functools import partial
from itertools import chain
from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline, async_chain, get_path
from riko.types.modules import (
    CurrencyFormatConf,
    CurrencyFormatRawConf,
    ExchangeRateConf,
    FetchDataConf,
    FindConfRule,
    ModuleOptions,
    RenameConf,
    RenameConfRule,
    SimpleMathRawConf,
    StrconcatConf,
    StrfindConf,
    StrReplaceConfRule,
    StrTransformConf,
    StrTransformConfRule,
    SubelementConf,
    Subkey,
)

if TYPE_CHECKING:
    from riko.types import AsyncStream, Item

BR = FindConfRule(find="<br>")
DEF_CUR_CODE = "USD"
Rules = FindConfRule | list[FindConfRule]

odesk_conf = FetchDataConf({"url": get_path("odesk.json"), "path": "items"})
guru_conf = FetchDataConf({"url": get_path("guru.json"), "path": "items"})
elance_conf = FetchDataConf({"url": get_path("elance.json"), "path": "items"})
freelancer_conf = FetchDataConf({"url": get_path("freelancer.json"), "path": "items"})


def make_simplemath(other: str, op: str) -> SimpleMathRawConf:
    return SimpleMathRawConf(
        {
            "other": {"subkey": other, "type": "float"},
            "op": {"value": op, "type": "text"},
        }
    )


def add_source(source: Pipeline) -> Pipeline:
    subelement_conf = SubelementConf({"path": "k:source.content.1", "token_key": None})
    urlparse_options = ModuleOptions(
        {"field": "link", "emit": False, "assign": "k:source"}
    )

    return source.urlparse(options=urlparse_options).subelement(
        conf=subelement_conf, options={"emit": False, "assign": "k:source"}
    )


def add_id(source: Pipeline, rule: Rules, field: str = "link") -> Pipeline:
    make_id_part = [
        {"subkey": "k:source", "type": "text"},
        "-",
        {"subkey": "id", "type": "text"},
    ]

    return source.strfind(
        conf={"rule": rule}, options={"field": field, "assign": "id"}
    ).strconcat(conf={"part": make_id_part}, options={"assign": "id"})


def add_posted(
    source: Pipeline, rule: Rules | None = None, field: str = "summary"
) -> Pipeline:
    if rule is None:
        rename_rule = RenameConfRule(field="updated", newval="k:posted")
        result = source.rename(conf={"rule": rename_rule})
    else:
        conf = StrfindConf({"rule": rule})
        result = source.strfind(
            conf=conf, options={"field": field, "assign": "k:posted"}
        )

    return result


def add_tags(
    source: Pipeline, rule: Rules, field: str = "summary", assign: str = "k:tags"
) -> Pipeline:
    tag_strreplace_rule = [
        StrReplaceConfRule(find="  ", replace=","),
        StrReplaceConfRule(find="&gt;", replace=","),
        StrReplaceConfRule(find="&amp;", replace="&"),
        StrReplaceConfRule(find="Other -", replace=""),
    ]

    transform_conf = StrTransformConf({"rule": StrTransformConfRule(transform="lower")})

    in_place = ModuleOptions({"field": assign, "assign": assign})

    return (
        source.strfind(conf={"rule": rule}, options={"field": field, "assign": assign})
        .strreplace(conf={"rule": tag_strreplace_rule}, options=in_place)
        .strtransform(conf=transform_conf, options=in_place)
        .tokenizer(
            conf={"dedupe": True, "sort": True},
            options={"field": assign, "emit": False, "assign": assign},
        )
    )


def add_budget(
    source: Pipeline,
    fixed_text: str = "",
    hourly_text: str = "",
    double: bool | str = True,
) -> Pipeline:
    codes = "$£€₹"
    first_num_rule = FindConfRule(find=r"\d+", location="at")
    last_num_rule = FindConfRule(find=r"\d+", location="at", param="last")
    cur_rule = FindConfRule(find=r"\b[A-Z]{3}\b", location="at")
    sym_rule = FindConfRule(find=f"[{codes}]", location="at")

    invalid_budgets = [
        StrReplaceConfRule(find="Less than", replace="0-"),
        StrReplaceConfRule(find="Under", replace="0-"),
        StrReplaceConfRule(find="Upto", replace="0-"),
        StrReplaceConfRule(find="or less", replace="-0"),
        StrReplaceConfRule(find="k", replace="000"),
        StrReplaceConfRule(find="Not Sure", replace=""),
        StrReplaceConfRule(find="Not sure", replace=""),
        StrReplaceConfRule(find="(", replace=""),
        StrReplaceConfRule(find=")", replace=""),
        StrReplaceConfRule(find=".", replace=""),
        StrReplaceConfRule(find=",", replace=""),
        StrReplaceConfRule(find=" ", replace=""),
    ]

    cur_strreplace_rule = [
        StrReplaceConfRule(find="$", replace="USD"),
        StrReplaceConfRule(find="£", replace="GBP"),
        StrReplaceConfRule(find="€", replace="EUR"),
        StrReplaceConfRule(find="₹", replace="INR"),
    ]

    converted_budget_part: list[str | Subkey] = [
        Subkey({"subkey": "k:budget_w_sym", "type": "text"}),
        "(",
        Subkey({"subkey": "k:budget_converted_w_sym", "type": "text"}),
        ")",
    ]

    def_full_budget_part = Subkey({"subkey": "k:budget_w_sym", "type": "text"})
    hourly_budget_part: list[str | Subkey] = [
        {"subkey": "k:budget_full", "type": "text"},
        " / hr",
    ]
    exchangerate_conf = ExchangeRateConf({"url": get_path("quote.json")})
    native_currencyformat_conf = CurrencyFormatRawConf(
        {"currency": {"subkey": "k:cur_code", "type": "text"}}
    )
    def_currencyformat_conf = CurrencyFormatConf({"currency": DEF_CUR_CODE})
    ave_budget_conf = make_simplemath("k:budget_raw2_num", "mean")
    convert_budget_conf = make_simplemath("k:rate", "multiply")
    raw_budget = ModuleOptions({"field": "k:budget_raw", "assign": "k:budget_raw"})

    if fixed_text:
        result = source.strconcat(
            conf={"part": "fixed"}, options={"assign": "k:job_type"}
        )
    else:
        result = source

    if hourly_text:
        result = result.strconcat(
            conf={"part": "hourly"}, options={"assign": "k:job_type"}
        )

    result = result.refind(
        conf={"rule": cur_rule},
        options={"field": "k:budget_raw", "assign": "k:cur_code"},
    ).strreplace(conf={"rule": invalid_budgets}, options=raw_budget)

    if double:
        result = (
            result.refind(
                conf={"rule": first_num_rule},
                options={"field": "k:budget_raw", "assign": "k:budget_raw_num"},
            )
            .refind(
                conf={"rule": last_num_rule},
                options={"field": "k:budget_raw", "assign": "k:budget_raw2_num"},
            )
            .simplemath(
                conf=ave_budget_conf,
                options={"field": "k:budget_raw_num", "assign": "k:budget"},
            )
        )
    else:
        result = result.refind(
            conf={"rule": first_num_rule},
            options={"field": "k:budget_raw", "assign": "k:budget"},
        )

    result = (
        result.refind(
            conf={"rule": sym_rule},
            options={"field": "k:budget_raw", "assign": "k:budget_raw_sym"},
        )
        .strreplace(
            conf={"rule": cur_strreplace_rule},
            options={"field": "k:budget_raw_sym", "assign": "k:cur_code"},
        )
        .currencyformat(
            conf=native_currencyformat_conf,
            options={"field": "k:budget", "assign": "k:budget_w_sym"},
        )
        .exchangerate(
            conf=exchangerate_conf, options={"field": "k:cur_code", "assign": "k:rate"}
        )
        .simplemath(
            conf=convert_budget_conf,
            options={"field": "k:budget", "assign": "k:budget_converted"},
        )
        .currencyformat(
            conf=def_currencyformat_conf,
            options={
                "field": "k:budget_converted",
                "assign": "k:budget_converted_w_sym",
            },
        )
        .strconcat(
            conf=StrconcatConf({"part": converted_budget_part}),
            options={"assign": "k:budget_full"},
        )
        .strconcat(
            conf=StrconcatConf({"part": def_full_budget_part}),
            options={"assign": "k:budget_full"},
        )
    )

    if hourly_text:
        result = result.strconcat(
            conf={"part": hourly_budget_part}, options={"assign": "k:budget_full"}
        )

    return result


def clean_locations(source: Pipeline) -> Pipeline:
    rule = StrReplaceConfRule(find=", ", replace="")
    client = ModuleOptions(
        {"field": "k:client_location", "assign": "k:client_location"}
    )
    work = ModuleOptions({"field": "k:work_location", "assign": "k:work_location"})

    return source.strreplace(conf={"rule": rule}, options=client).strreplace(
        conf={"rule": rule}, options=work
    )


def remove_cruft(source: Pipeline) -> Pipeline:
    remove_rule = [
        RenameConfRule(field="author"),
        RenameConfRule(field="content"),
        RenameConfRule(field="dc:creator"),
        RenameConfRule(field="links"),
        RenameConfRule(field="pubDate"),
        RenameConfRule(field="summary"),
        RenameConfRule(field="updated"),
        RenameConfRule(field="updated_parsed"),
        RenameConfRule(field="y:id"),
        RenameConfRule(field="y:title"),
        RenameConfRule(field="y:published"),
        RenameConfRule(field="k:budget_raw"),
        RenameConfRule(field="k:budget_raw2_num"),
        RenameConfRule(field="k:budget_raw_num"),
        RenameConfRule(field="k:budget_raw_sym"),
    ]

    return source.rename(conf=RenameConf({"rule": remove_rule}))


def parse_odesk(source: Pipeline) -> Pipeline:
    budget_text = "Budget</b>:"
    raw_budget_rule = [FindConfRule(find=budget_text, location="after"), BR]
    title_rule = FindConfRule(find="- oDesk")
    find_id_rule = [FindConfRule(find="ID</b>:", location="after"), BR]
    categ_rule = [FindConfRule(find="Category</b>:", location="after"), BR]
    skills_rule = [FindConfRule(find="Skills</b>:", location="after"), BR]
    client_loc_rule = [FindConfRule(find="Country</b>:", location="after"), BR]
    posted_rule = [FindConfRule(find="Posted On</b>:", location="after"), BR]
    desc_rule = [
        FindConfRule(find="<p>", location="after"),
        FindConfRule(find="<br><br><b>"),
    ]

    result = (
        source.strfind(
            conf={"rule": title_rule}, options={"field": "title", "assign": "title"}
        )
        .strfind(
            conf={"rule": client_loc_rule},
            options={"field": "summary", "assign": "k:client_location"},
        )
        .strfind(
            conf={"rule": desc_rule},
            options={"field": "summary", "assign": "description"},
        )
        .strfind(
            conf={"rule": raw_budget_rule},
            options={"field": "summary", "assign": "k:budget_raw"},
        )
    )

    result = add_source(result)
    result = add_posted(result, posted_rule)
    result = add_id(result, find_id_rule, field="summary")
    result = add_budget(result, double=False)
    result = add_tags(result, skills_rule)
    result = add_tags(result, categ_rule, assign="k:categories")
    result = clean_locations(result)
    return remove_cruft(result)


def parse_guru(source: Pipeline) -> Pipeline:
    budget_text = "budget:</b>"
    fixed_text = "Fixed Price budget:</b>"
    hourly_text = "Hourly budget:</b>"

    raw_budget_rule = [FindConfRule(find=budget_text, location="after"), BR]
    after_hourly = StrfindConf({"rule": FindConfRule(find="Rate:", location="after")})
    find_id_rule = FindConfRule(find="/", location="after", param="last")
    categ_rule = [FindConfRule(find="Category:</b>", location="after"), BR]
    skills_rule = [FindConfRule(find="Required skills:</b>", location="after"), BR]

    job_loc_conf = StrfindConf(
        {"rule": [FindConfRule(find="Freelancer Location:</b>", location="after"), BR]}
    )

    desc_conf = StrfindConf(
        {"rule": [FindConfRule(find="Description:</b>", location="after"), BR]}
    )

    result = (
        source.strfind(
            conf=job_loc_conf, options={"field": "summary", "assign": "k:work_location"}
        )
        .strfind(conf=desc_conf, options={"field": "summary", "assign": "description"})
        .strfind(
            conf={"rule": raw_budget_rule},
            options={"field": "summary", "assign": "k:budget_raw"},
        )
        .strfind(
            conf=after_hourly,
            options={"field": "k:budget_raw", "assign": "k:budget_raw"},
        )
    )

    kwargs = {"fixed_text": fixed_text, "hourly_text": hourly_text}
    result = add_source(result)
    result = add_posted(result)
    result = add_id(result, find_id_rule)
    result = add_budget(result, **kwargs)
    result = add_tags(result, skills_rule)
    result = add_tags(result, categ_rule, assign="k:categories")
    result = clean_locations(result)
    return remove_cruft(result)


def parse_elance(source: Pipeline) -> Pipeline:
    budget_text = "Budget:</b>"
    fixed_text = "Budget:</b> Fixed Price"
    hourly_text = "Budget:</b> Hourly"

    raw_budget_rule = [FindConfRule(find=budget_text, location="after"), BR]
    after_hourly = StrfindConf({"rule": FindConfRule(find="Hourly", location="after")})
    after_fixed = StrfindConf(
        {"rule": FindConfRule(find="Fixed Price", location="after")}
    )
    title_conf = StrfindConf({"rule": FindConfRule(find="| Elance Job")})

    find_id_rule = [
        FindConfRule(find="/", param="last"),
        FindConfRule(find="/", location="after", param="last"),
    ]

    categ_rule = [FindConfRule(find="Category:</b>", location="after"), BR]
    skills_rule = [FindConfRule(find="Desired Skills:</b>", location="after"), BR]

    job_loc_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Preferred Job Location:</b>", location="after"),
                BR,
            ]
        }
    )

    client_loc_conf = StrfindConf(
        {"rule": [FindConfRule(find="Client Location:</b>", location="after"), BR]}
    )

    desc_rule = [
        FindConfRule(find="<p>", location="after"),
        FindConfRule(find="...\n    <br>"),
    ]

    proposals_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Proposals:</b>", location="after"),
                FindConfRule(find="("),
            ]
        }
    )

    jobs_posted_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Client:</b> Client (", location="after"),
                FindConfRule(find="jobs posted"),
            ]
        }
    )

    jobs_awarded_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="jobs posted,", location="after"),
                FindConfRule(find="awarded"),
            ]
        }
    )

    purchased_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="total purchased"),
                FindConfRule(find=",", location="after", param="last"),
            ]
        }
    )

    ends_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Time Left:</b>", location="after"),
                FindConfRule(find=") <br>"),
                FindConfRule(find="h (Ends", location="after"),
            ]
        }
    )

    result = (
        source.strfind(conf=title_conf, options={"field": "title", "assign": "title"})
        .strfind(
            conf=proposals_conf, options={"field": "summary", "assign": "k:submissions"}
        )
        .strfind(
            conf=jobs_posted_conf, options={"field": "summary", "assign": "k:num_jobs"}
        )
        .strfind(
            conf=jobs_awarded_conf,
            options={"field": "summary", "assign": "k:per_awarded"},
        )
        .strfind(
            conf=purchased_conf,
            options={"field": "summary", "assign": "k:tot_purchased"},
        )
        .strfind(conf=ends_conf, options={"field": "summary", "assign": "k:due"})
        .strfind(
            conf=job_loc_conf, options={"field": "summary", "assign": "k:work_location"}
        )
        .strfind(
            conf=client_loc_conf,
            options={"field": "summary", "assign": "k:client_location"},
        )
        .strfind(
            conf={"rule": desc_rule},
            options={"field": "summary", "assign": "description"},
        )
        .strfind(
            conf={"rule": raw_budget_rule},
            options={"field": "summary", "assign": "k:budget_raw"},
        )
        .strfind(
            conf=after_hourly,
            options={"field": "k:budget_raw", "assign": "k:budget_raw"},
        )
        .strfind(
            conf=after_fixed,
            options={"field": "k:budget_raw", "assign": "k:budget_raw"},
        )
    )

    kwargs = {"fixed_text": fixed_text, "hourly_text": hourly_text}
    result = add_source(result)
    result = add_posted(result)
    result = add_id(result, find_id_rule)
    result = add_budget(result, **kwargs)
    result = add_tags(result, skills_rule)
    result = add_tags(result, categ_rule, assign="k:categories")
    return clean_locations(result)


def parse_freelancer(source: Pipeline) -> Pipeline:
    budget_text = "(Budget:"
    raw_budget_rule = [
        FindConfRule(find=budget_text, location="after"),
        FindConfRule(find=","),
    ]

    title_rule = FindConfRule(find=" by ")
    skills_rule = [
        FindConfRule(find=", Jobs:", location="after"),
        FindConfRule(find=")</p>"),
    ]
    desc_rule = [
        FindConfRule(find="<p>", location="after"),
        FindConfRule(find="(Budget:"),
    ]

    result = (
        source.strfind(
            conf={"rule": title_rule}, options={"field": "title", "assign": "title"}
        )
        .strfind(
            conf={"rule": desc_rule},
            options={"field": "summary", "assign": "description"},
        )
        .strfind(
            conf={"rule": raw_budget_rule},
            options={"field": "summary", "assign": "k:budget_raw"},
        )
    )

    result = add_source(result)
    result = add_posted(result)
    result = add_budget(result)
    result = add_tags(result, skills_rule)
    result = clean_locations(result)
    return remove_cruft(result)


def build_flows() -> list[Pipeline]:
    source = partial(Pipeline.from_module, "fetchdata")
    return [
        parse_odesk(source(conf=odesk_conf)),
        parse_guru(source(conf=guru_conf)),
        parse_freelancer(source(conf=freelancer_conf)),
        parse_elance(source(conf=elance_conf)),
    ]


def pipe(
    test: bool = False, parallel: bool = False, threads: bool = False
) -> list[Item]:
    flows = build_flows()

    if parallel:
        executor = "thread" if threads else "process"
        flows = [flow.with_execution(executor=executor) for flow in flows]

    return list(chain.from_iterable(flows))


def async_pipe(test: bool | None = None) -> AsyncStream:
    return async_chain(*build_flows())


def print_results(result: list[Item]) -> None:
    pprint(result[-1])


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
